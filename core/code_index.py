"""
core/code_index.py — B-036 (ADR-025): a thin code index built on tree-sitter.

Given {path: source text} it extracts symbols, call edges with receiver-aware resolution, HTTP/main entry
points and sinks for Python, Java, C# and TypeScript/JavaScript. It reads nothing but the text it is given
(no file system, no network), so it works on a stored scan snapshot and on hostile code alike.

Call resolution: the receiver's type is inferred from constructor calls, field/local/parameter declarations
and imports of classes defined in the scanned code. A call on a receiver of a known repo class resolves to
that class's method; a call on a receiver of a type that is not in the scanned code (a framework or driver
object) is external and creates no edge; a bare identifier of unknown type resolves by name only if the name
is defined exactly once. Everything else stays unresolved. Languages with no grammar are listed in
`unsupported` and have no structure (callers fall back to text search).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

import tree_sitter as ts

_EXT = {".py": "python", ".java": "java", ".cs": "csharp", ".ts": "typescript", ".tsx": "typescript",
        ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript", ".cjs": "typescript"}
_PARSERS: dict[str, ts.Parser] = {}


def _parser(lang: str) -> ts.Parser:
    if lang not in _PARSERS:
        if lang == "python":
            import tree_sitter_python as g
            language = g.language()
        elif lang == "java":
            import tree_sitter_java as g
            language = g.language()
        elif lang == "csharp":
            import tree_sitter_c_sharp as g
            language = g.language()
        else:
            import tree_sitter_typescript as g
            language = g.language_typescript()
        _PARSERS[lang] = ts.Parser(ts.Language(language))
    return _PARSERS[lang]


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Symbol:
    file: str
    name: str
    kind: str                 # function | method | class
    line: int
    cls: str = ""             # enclosing class for methods


@dataclass(frozen=True)
class Call:
    caller_file: str
    caller: str               # enclosing function or method name, "<module>" at top level
    callee: str
    line: int
    resolution: str           # type | name | external | unresolved
    callee_file: str = ""
    callee_class: str = ""


@dataclass(frozen=True)
class EntryPoint:
    file: str
    kind: str                 # http | main
    symbol: str
    route: str = ""
    line: int = 0


@dataclass(frozen=True)
class Sink:
    file: str
    kind: str                 # sql | file | command
    line: int
    call: str = ""


@dataclass
class CodeIndex:
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def edges(self) -> list[Call]:
        """Resolved call edges only."""
        return [c for c in self.calls if c.resolution in ("type", "name")]

    def find_definition(self, name: str) -> list[Symbol]:
        return [s for s in self.symbols if s.name == name or f"{s.cls}.{s.name}" == name]

    def find_callers(self, name: str, file: str = "") -> list[Call]:
        return [c for c in self.edges() if c.callee == name and (not file or c.callee_file == file)]

    def find_callees(self, name: str, file: str = "") -> list[Call]:
        return [c for c in self.edges() if c.caller == name and (not file or c.caller_file == file)]

    def list_entry_points(self) -> list[EntryPoint]:
        return list(self.entry_points)

    def list_sinks(self, kind: str = "") -> list[Sink]:
        return [s for s in self.sinks if not kind or s.kind == kind]

    def as_dict(self) -> dict:
        return {k: [asdict(x) for x in v] if k != "unsupported" else v
                for k, v in (("symbols", self.symbols), ("calls", self.calls), ("entry_points", self.entry_points),
                             ("sinks", self.sinks), ("unsupported", self.unsupported))}


# ── Language tables ───────────────────────────────────────────────────────────

FUNCTION_NODES = {"python": {"function_definition"}, "java": {"method_declaration", "constructor_declaration"},
                  "csharp": {"method_declaration", "constructor_declaration"},
                  "typescript": {"function_declaration", "method_definition"}}
CLASS_NODES = {"python": {"class_definition"}, "java": {"class_declaration", "interface_declaration"},
               "csharp": {"class_declaration"}, "typescript": {"class_declaration"}}
CALL_NODES = {"python": {"call"}, "java": {"method_invocation", "object_creation_expression"},
              "csharp": {"invocation_expression", "object_creation_expression"},
              "typescript": {"call_expression", "new_expression"}}
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "route", "api_route", "all"}
JAVA_MAPPINGS = {"GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping", "RequestMapping"}
CS_MAPPINGS = {"HttpGet", "HttpPost", "HttpPut", "HttpDelete", "HttpPatch", "Route"}
SQL_NAMES = {"execute", "executemany", "executescript", "executeQuery", "executeUpdate", "ExecuteReader",
             "ExecuteNonQuery", "ExecuteScalar", "query"}
FILE_NAMES = {"write_text", "write_bytes", "writeFileSync", "writeFile", "appendFileSync", "appendFile", "readFileSync",
              "readFile", "unlink", "unlinkSync", "createWriteStream", "createReadStream"}
COMMAND_NAMES = {"execSync", "spawn", "spawnSync", "execFile", "execFileSync"}
_THIS = {"self", "this"}


def _text(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _simple_type(text: str) -> str:
    """`Foo<Bar>`, `ns.Foo`, `Foo[]`, `Foo?` -> `Foo`."""
    t = text.strip().lstrip(":").strip()
    for cut in ("<", "[", "?", "("):
        t = t.split(cut)[0]
    return t.split(".")[-1].strip()


def _first_string(node) -> str:
    stack = [node]
    while stack:
        n = stack.pop(0)
        if "string" in n.type and n.type not in ("string_content", "interpolated_string_expression"):
            return _text(n).strip("\"'`@$")
        stack = list(n.children) + stack
    return ""


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def call_info(lang: str, node):
    """(callee name, receiver node or None, kind) for a call or constructor node; kind is call|new."""
    t = node.type
    if lang == "python":
        fn = node.child_by_field_name("function")
        if fn is not None and fn.type == "attribute":
            return _text(fn.child_by_field_name("attribute")), fn.child_by_field_name("object"), "call"
        return _text(fn), None, "call"
    if lang == "java":
        if t == "object_creation_expression":
            return _simple_type(_text(node.child_by_field_name("type"))), None, "new"
        return _text(node.child_by_field_name("name")), node.child_by_field_name("object"), "call"
    if lang == "csharp":
        if t == "object_creation_expression":
            return _simple_type(_text(node.child_by_field_name("type"))), None, "new"
        fn = node.child_by_field_name("function")
        if fn is not None and fn.type == "member_access_expression":
            return _text(fn.child_by_field_name("name")), fn.child_by_field_name("expression"), "call"
        return _text(fn), None, "call"
    if t == "new_expression":
        return _simple_type(_text(node.child_by_field_name("constructor"))), None, "new"
    fn = node.child_by_field_name("function")
    if fn is not None and fn.type == "member_expression":
        return _text(fn.child_by_field_name("property")), fn.child_by_field_name("object"), "call"
    return _text(fn), None, "call"


def sink_kind(lang: str, name: str, receiver_text: str, kind: str) -> str | None:
    q = "new" if kind == "new" else receiver_text.replace(" ", "")
    if name in SQL_NAMES:
        return "sql"
    if lang == "typescript" and name in {"all", "get", "run", "iterate"} and "prepare(" in q:
        return "sql"
    if name in FILE_NAMES or (lang == "python" and name == "open" and not q):
        return "file"
    if lang == "java" and q == "new" and name in {"FileWriter", "FileOutputStream", "FileReader", "FileInputStream"}:
        return "file"
    if lang == "csharp" and q == "File" and name in {"WriteAllText", "WriteAllBytes", "AppendAllText", "ReadAllText", "Delete"}:
        return "file"
    if name in COMMAND_NAMES or (lang == "typescript" and name == "exec"):
        return "command"
    if lang == "python" and (q == "subprocess" or (name in {"system", "popen"} and q == "os")):
        return "command"
    if lang == "java" and ((name == "exec" and "Runtime" in q) or (q == "new" and name == "ProcessBuilder")):
        return "command"
    if lang == "csharp" and q == "Process" and name == "Start":
        return "command"
    return None


# ── Declarations: classes, fields and variable types ─────────────────────────

def _initialiser_type(lang: str, node) -> str:
    """Class name of `new T()` / `T()` initialisers; empty if not a constructor-like expression."""
    if node is None:
        return ""
    if node.type in ("object_creation_expression", "new_expression"):
        return call_info(lang, node)[0]
    if lang == "python" and node.type == "call":
        fn = node.child_by_field_name("function")
        return _simple_type(_text(fn)) if fn is not None else ""
    if node.type in CALL_NODES[lang]:                  # `express()`, `require("x")`: a plain function call
        name, receiver, kind = call_info(lang, node)
        if kind == "call" and receiver is None and name:
            return f"@call:{name.split('.')[-1]}"
    return ""


def declarations(lang: str, node):
    """Yield (name, type_name, is_field_access) for declarations directly represented by `node`.

    `type_name` is the declared type, else the initialiser's class; empty when unknown."""
    t = node.type
    if lang == "python":
        if t == "assignment":
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            declared = _simple_type(_text(node.child_by_field_name("type")))
            typ = declared or _initialiser_type(lang, right)
            if left is not None and left.type == "identifier":
                yield _text(left), typ, False
            elif left is not None and left.type == "attribute" and _text(left.child_by_field_name("object")) == "self":
                yield _text(left.child_by_field_name("attribute")), typ, True
        elif t in ("typed_parameter", "typed_default_parameter"):
            ident = next((c for c in node.children if c.type == "identifier"), None)
            if ident is not None:
                yield _text(ident), _simple_type(_text(node.child_by_field_name("type"))), False
    elif lang == "java":
        if t in ("field_declaration", "local_variable_declaration"):
            declared = _simple_type(_text(node.child_by_field_name("type")))
            for d in (c for c in node.children if c.type == "variable_declarator"):
                init = _initialiser_type(lang, d.child_by_field_name("value"))
                yield _text(d.child_by_field_name("name")), (init if declared in ("var", "") else declared) or init, t == "field_declaration"
        elif t == "formal_parameter":
            yield _text(node.child_by_field_name("name")), _simple_type(_text(node.child_by_field_name("type"))), False
    elif lang == "csharp":
        if t in ("field_declaration", "local_declaration_statement"):
            for v in (c for c in node.children if c.type == "variable_declaration"):
                declared = _simple_type(_text(v.child_by_field_name("type")))
                for d in (c for c in v.children if c.type == "variable_declarator"):
                    init = next((_initialiser_type(lang, c) for c in d.children if c.type == "object_creation_expression"), "")
                    yield _text(d.child_by_field_name("name")), (init if declared in ("var", "", "implicit_type") else declared) or init, t == "field_declaration"
        elif t == "parameter":
            yield _text(node.child_by_field_name("name")), _simple_type(_text(node.child_by_field_name("type"))), False
    else:
        if t == "public_field_definition":
            declared = _simple_type(_text(node.child_by_field_name("type")))
            yield _text(node.child_by_field_name("name")), declared or _initialiser_type(lang, node.child_by_field_name("value")), True
        elif t == "variable_declarator":
            declared = _simple_type(_text(node.child_by_field_name("type")))
            yield _text(node.child_by_field_name("name")), declared or _initialiser_type(lang, node.child_by_field_name("value")), False
        elif t in ("required_parameter", "optional_parameter"):
            pattern = node.child_by_field_name("pattern")
            is_property = any(c.type in ("accessibility_modifier", "readonly") for c in node.children)
            if pattern is not None and pattern.type == "identifier":
                yield _text(pattern), _simple_type(_text(node.child_by_field_name("type"))), is_property


# ── Indexing ──────────────────────────────────────────────────────────────────

class _FileScan:
    """Pass 1 over one file: its symbols, classes, field types and file-level variable types."""

    def __init__(self, lang: str, rel: str, root):
        self.lang, self.rel = lang, rel
        self.symbols: list[Symbol] = []
        self.fields: dict[str, dict[str, str]] = {}      # class -> field -> type
        self.file_vars: dict[str, str] = {}              # module-level variable -> type
        self._scan(root, [])

    def _scan(self, node, classes: list[str]) -> None:
        t = node.type
        if t in CLASS_NODES[self.lang]:
            name = _text(node.child_by_field_name("name"))
            self.symbols.append(Symbol(self.rel, name, "class", node.start_point[0] + 1))
            self.fields.setdefault(name, {})
            classes = classes + [name]
        elif t in FUNCTION_NODES[self.lang]:
            name = _text(node.child_by_field_name("name"))
            self.symbols.append(Symbol(self.rel, name, "method" if classes else "function",
                                       node.start_point[0] + 1, classes[-1] if classes else ""))
        for decl_name, typ, is_field in declarations(self.lang, node):
            if not typ:
                continue
            if classes and is_field:
                self.fields[classes[-1]][decl_name] = typ
            elif not classes and not self._inside_function(node):
                self.file_vars[decl_name] = typ
        for child in node.children:
            self._scan(child, classes)

    def _inside_function(self, node) -> bool:
        p = node.parent
        while p is not None:
            if p.type in FUNCTION_NODES[self.lang]:
                return True
            p = p.parent
        return False


class _Resolver:
    def __init__(self, lang: str, rel: str, source_index: "_Project"):
        self.lang, self.rel, self.project = lang, rel, source_index
        self.scope: list[str] = []
        self.classes: list[str] = []
        self.locals: list[dict[str, str]] = []
        self.calls: list[Call] = []
        self.entries: list[EntryPoint] = []
        self.sinks: list[Sink] = []

    # type of a receiver expression -> (category, class name)
    def receiver_type(self, node) -> tuple[str, str]:
        if node is None:
            return "none", ""
        t = node.type
        if t in CALL_NODES[self.lang]:
            name, recv, kind = call_info(self.lang, node)
            name = name.split(".")[-1]
            if kind == "new" or (recv is None and name in self.project.classes):
                return self._category(name)             # `new T()` / `T()`
            if recv is not None and self.receiver_type(recv)[0] == "external":
                return "external", ""                   # a chain on a framework or driver object
            return "unknown", ""
        if t == "identifier":
            name = _text(node)
            if name in _THIS:
                return ("repo", self.classes[-1]) if self.classes else ("unknown", "")
            for frame in reversed(self.locals):
                if name in frame:
                    return self._category(frame[name])
            if self.classes and name in self.project.fields.get(self.classes[-1], {}):
                return self._category(self.project.fields[self.classes[-1]][name])
            if name in self.project.file_vars.get(self.rel, {}):
                return self._category(self.project.file_vars[self.rel][name])
            if name in self.project.classes:
                return "repo", name                    # static access: ClassName.method()
            return "unknown", ""
        attr = None
        if t == "attribute":
            obj, attr = node.child_by_field_name("object"), _text(node.child_by_field_name("attribute"))
        elif t == "member_expression":
            obj, attr = node.child_by_field_name("object"), _text(node.child_by_field_name("property"))
        elif t in ("member_access_expression", "field_access"):
            obj = node.child_by_field_name("expression") or node.child_by_field_name("object")
            attr = _text(node.child_by_field_name("name") or node.child_by_field_name("field"))
        else:
            return "unknown", ""
        if obj is not None and (_text(obj) in _THIS or obj.type == "this") and self.classes:
            typ = self.project.fields.get(self.classes[-1], {}).get(attr)
            return self._category(typ) if typ else ("unknown", "")
        base = self.receiver_type(obj)
        if base[0] == "external":
            return "external", ""
        return "unknown", ""

    def _category(self, typ: str) -> tuple[str, str]:
        if typ.startswith("@call:"):                    # initialised from a plain function call
            typ = typ[len("@call:"):]
            return ("repo", typ) if typ in self.project.classes else ("external", typ)
        return ("repo", typ) if typ in self.project.classes else ("external", typ)

    def resolve(self, name: str, receiver) -> Call | None:
        """Resolution for one call; None when it is not a call to repo code and not worth recording."""
        caller = self.scope[-1] if self.scope else "<module>"
        base = dict(caller_file=self.rel, caller=caller, callee=name)
        if receiver is None:
            cls = self.classes[-1] if self.classes else ""
            target = self.project.methods.get((cls, name)) if cls else None
            if target is None:
                target = self.project.functions.get(name)
            if target is not None:
                return Call(**base, line=0, resolution="type", callee_file=target.file, callee_class=target.cls)
            if name in self.project.classes:
                return Call(**base, line=0, resolution="type", callee_file=self.project.classes[name].file, callee_class=name)
            return Call(**base, line=0, resolution="external")
        category, typ = self.receiver_type(receiver)
        if category == "repo":
            target = self.project.methods.get((typ, name))
            if target is not None:
                return Call(**base, line=0, resolution="type", callee_file=target.file, callee_class=typ)
            return Call(**base, line=0, resolution="unresolved", callee_class=typ)
        if category == "external":
            return Call(**base, line=0, resolution="external")
        if receiver.type == "identifier":              # bare identifier of unknown type: unique-name fallback
            defs = self.project.defs_by_name.get(name, [])
            if len(defs) == 1:
                return Call(**base, line=0, resolution="name", callee_file=defs[0].file, callee_class=defs[0].cls)
        return Call(**base, line=0, resolution="unresolved")

    # entry points ----------------------------------------------------------------
    def _entry(self, kind: str, symbol: str, route: str, line: int) -> None:
        self.entries.append(EntryPoint(self.rel, kind, symbol, route, line))

    def _annotated(self, node, names: set[str]) -> None:
        name = _text(node.child_by_field_name("name"))
        for group in (c for c in node.children if c.type in ("modifiers", "attribute_list")):
            for a in _walk(group):
                if a.type in ("annotation", "marker_annotation", "attribute"):
                    if _text(a.child_by_field_name("name")).split(".")[-1] in names:
                        self._entry("http", name, _first_string(a), node.start_point[0] + 1)
                        return

    def _python_decorators(self, node) -> None:
        definition = node.child_by_field_name("definition")
        name = _text(definition.child_by_field_name("name")) if definition is not None else ""
        for dec in (c for c in node.children if c.type == "decorator"):
            expr = next((c for c in dec.children if c.type != "@"), None)
            if expr is not None and expr.type == "call":
                fn = expr.child_by_field_name("function")
                if fn is not None and fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) in HTTP_VERBS:
                    self._entry("http", name, _first_string(expr.child_by_field_name("arguments")), node.start_point[0] + 1)

    def _main(self, node) -> None:
        t, line = node.type, node.start_point[0] + 1
        if self.lang == "python" and t == "if_statement":
            cond = _text(node.child_by_field_name("condition"))
            if "__name__" in cond and "__main__" in cond:
                self._entry("main", "__main__", "", line)
        elif self.lang == "typescript" and t == "if_statement":
            if "require.main" in _text(node.child_by_field_name("condition")):
                self._entry("main", "<main>", "", line)
        elif self.lang in ("java", "csharp") and t == "method_declaration":
            if _text(node.child_by_field_name("name")) in ("main", "Main") and "static" in _text(node)[:80]:
                self._entry("main", _text(node.child_by_field_name("name")), "", line)

    def _ts_route(self, node, name: str) -> None:
        if name not in HTTP_VERBS - {"route", "api_route", "head", "options"}:
            return
        args = node.child_by_field_name("arguments")
        named = [c for c in args.children if c.is_named] if args is not None else []
        if len(named) >= 2 and named[0].type in ("string", "template_string") and _text(named[0]).strip("\"'`").startswith("/"):
            handler = named[-1]
            self._entry("http", _text(handler) if handler.type == "identifier" else "<anonymous>",
                        _text(named[0]).strip("\"'`"), node.start_point[0] + 1)

    # traversal -------------------------------------------------------------------
    def visit(self, node) -> None:
        t, lang = node.type, self.lang
        self._main(node)
        if lang == "python" and t == "decorated_definition":
            self._python_decorators(node)
        if lang == "java" and t == "method_declaration":
            self._annotated(node, JAVA_MAPPINGS)
        if lang == "csharp" and t == "method_declaration":
            self._annotated(node, CS_MAPPINGS)

        if t in CLASS_NODES[lang]:
            self.classes.append(_text(node.child_by_field_name("name")))
            for child in node.children:
                self.visit(child)
            self.classes.pop()
            return
        if t in FUNCTION_NODES[lang]:
            self.scope.append(_text(node.child_by_field_name("name")))
            self.locals.append({n: ty for n, ty, _ in self._frame_declarations(node) if ty})
            for child in node.children:
                self.visit(child)
            self.locals.pop()
            self.scope.pop()
            return
        if t in CALL_NODES[lang]:
            name, receiver, kind = call_info(lang, node)
            name = name.split(".")[-1]
            line = node.start_point[0] + 1
            call = self.resolve(name, receiver) if kind == "call" else self._instantiation(name)
            self.calls.append(Call(call.caller_file, call.caller, call.callee, line, call.resolution,
                                   call.callee_file, call.callee_class))
            sink = sink_kind(lang, name, _text(receiver) if receiver is not None else "", kind)
            if sink:
                self.sinks.append(Sink(self.rel, sink, line, name))
            if lang == "typescript" and t == "call_expression":
                self._ts_route(node, name)
        for child in node.children:
            self.visit(child)

    def _instantiation(self, name: str) -> Call:
        caller = self.scope[-1] if self.scope else "<module>"
        cls = self.project.classes.get(name)
        return Call(self.rel, caller, name, 0, "type" if cls else "external", cls.file if cls else "", name if cls else "")

    def _frame_declarations(self, function_node):
        """Declarations in a function (parameters and locals), not descending into nested functions or classes."""
        stack = list(function_node.children)
        while stack:
            n = stack.pop()
            yield from declarations(self.lang, n)
            if n.type in FUNCTION_NODES[self.lang] or n.type in CLASS_NODES[self.lang]:
                continue
            stack.extend(n.children)


class _Project:
    """Pass 1 over all files: what is defined where (needed to resolve calls across files)."""

    def __init__(self) -> None:
        self.classes: dict[str, Symbol] = {}
        self.methods: dict[tuple[str, str], Symbol] = {}
        self.functions: dict[str, Symbol] = {}
        self.defs_by_name: dict[str, list[Symbol]] = {}
        self.fields: dict[str, dict[str, str]] = {}
        self.file_vars: dict[str, dict[str, str]] = {}

    def add(self, scan: _FileScan) -> None:
        for s in scan.symbols:
            if s.kind == "class":
                self.classes.setdefault(s.name, s)
            elif s.kind == "method":
                self.methods.setdefault((s.cls, s.name), s)
                self.defs_by_name.setdefault(s.name, []).append(s)
            else:
                self.functions.setdefault(s.name, s)
                self.defs_by_name.setdefault(s.name, []).append(s)
        for cls, fields in scan.fields.items():
            self.fields.setdefault(cls, {}).update(fields)
        self.file_vars[scan.rel] = scan.file_vars


def build_index(files: dict[str, str]) -> CodeIndex:
    """Index {path: text}. Unsupported extensions are listed in `unsupported` and otherwise ignored."""
    index = CodeIndex()
    parsed = []
    project = _Project()
    for path in sorted(files):
        lang = _EXT.get(PurePosixPath(path).suffix.lower())
        if lang is None:
            index.unsupported.append(path)
            continue
        root = _parser(lang).parse(files[path].encode("utf-8", "replace")).root_node
        scan = _FileScan(lang, path, root)
        project.add(scan)
        index.symbols.extend(scan.symbols)
        parsed.append((lang, path, root))
    for lang, path, root in parsed:
        resolver = _Resolver(lang, path, project)
        resolver.visit(root)
        index.calls.extend(resolver.calls)
        index.entry_points.extend(resolver.entries)
        index.sinks.extend(resolver.sinks)
    return index
