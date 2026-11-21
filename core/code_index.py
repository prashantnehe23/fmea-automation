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

from dataclasses import asdict, dataclass, field, replace
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
JAXRS_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
CS_MINIMAL = {"MapGet", "MapPost", "MapPut", "MapDelete", "MapPatch", "MapMethods"}
DJANGO_ROUTES = {"path", "re_path", "url"}
ROUTER_FACTORIES = {"APIRouter", "Router", "Blueprint"}
MOUNT_CALLS = {"include_router", "register_blueprint"}
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
            return _text(n).lstrip("rRbBuUfF@$").strip("\"'`")           # drop string prefixes (r"", @"") and quotes
        stack = list(n.children) + stack
    return ""


def join_route(prefix: str, route: str) -> str:
    """Join a mount or class prefix and a route with exactly one slash between them."""
    if not prefix:
        return route
    if not route.strip("/"):
        return prefix                                   # "/" under a prefix is the prefix itself
    return prefix.rstrip("/") + "/" + route.lstrip("/")


def _kwarg_string(call, names: tuple[str, ...]) -> str:
    """The string value of a keyword argument such as prefix="/v1" (Python)."""
    args = call.child_by_field_name("arguments")
    for arg in (args.children if args is not None else []):
        if arg.type == "keyword_argument" and _text(arg.child_by_field_name("name")) in names:
            return _first_string(arg.child_by_field_name("value"))
    return ""


def _handler_name(node) -> str:
    """A route handler argument: `view`, `views.view`, `ViewClass.as_view()`, or an inline function."""
    if node is None:
        return "<anonymous>"
    if node.type == "identifier":
        return _text(node)
    if node.type in ("attribute", "member_expression", "member_access_expression"):
        return _text(node).split(".")[-1]
    if node.type in ("call", "call_expression", "invocation_expression"):
        fn = node.child_by_field_name("function")
        text = _text(fn)
        return text.split(".")[-2] if text.endswith(".as_view") and "." in text else _text(fn).split(".")[-1]
    return "<anonymous>"


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
        self._owners: list[str] = []                    # router/group variable of each entry, for prefixes
        self.prefixes: dict[str, str] = {}              # router/group variable -> its own prefix
        self.mounts: list[tuple[str, str, str]] = []    # (router variable, prefix, variable it is mounted on)
        self.class_routes: list[str] = []

    def finish(self) -> None:
        """Apply router prefixes and mounts to the entry routes (they can be declared after the routes)."""
        def full(var: str, seen: tuple[str, ...] = ()) -> str:
            own = self.prefixes.get(var, "")
            mount = next(((m, parent) for child, m, parent in self.mounts if child == var and parent not in seen + (var,)), None)
            if mount is None:
                return own
            return join_route(full(mount[1], seen + (var,)), join_route(mount[0], own))     # first mount wins

        self.entries = [replace(e, route=join_route(full(owner), e.route)) if owner else e
                        for e, owner in zip(self.entries, self._owners)]

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
    def _entry(self, kind: str, symbol: str, route: str, line: int, owner: str = "") -> None:
        self.entries.append(EntryPoint(self.rel, kind, symbol, route, line))
        self._owners.append(owner)

    @staticmethod
    def _annotations(node) -> dict[str, object]:
        """label -> annotation/attribute node for the modifiers or attribute lists of a class or method."""
        found: dict[str, object] = {}
        for group in (c for c in node.children if c.type in ("modifiers", "attribute_list")):
            for a in _walk(group):
                if a.type in ("annotation", "marker_annotation", "attribute"):
                    found.setdefault(_text(a.child_by_field_name("name")).split(".")[-1], a)
        return found

    def _class_route(self, node) -> str:
        """Class-level route prefix: Spring @RequestMapping, JAX-RS @Path, ASP.NET [Route] with [controller]."""
        annotations = self._annotations(node)
        label = next((l for l in ("RequestMapping", "Path", "Route") if l in annotations), "")
        if not label:
            return ""
        route = _first_string(annotations[label])
        if self.lang == "csharp":
            name = _text(node.child_by_field_name("name"))
            route = route.replace("[controller]", name[:-len("Controller")] if name.endswith("Controller") else name)
        return route

    def _method_entry(self, node) -> None:
        """HTTP entry from method annotations (Spring, JAX-RS) or attributes (ASP.NET), with the class prefix."""
        annotations = self._annotations(node)
        name, line = _text(node.child_by_field_name("name")), node.start_point[0] + 1
        prefix = self.class_routes[-1] if self.class_routes else ""
        if self.lang == "java":
            spring = next((a for l, a in annotations.items() if l in JAVA_MAPPINGS), None)
            if spring is not None:
                self._entry("http", name, join_route(prefix, _first_string(spring)), line)
            elif JAXRS_VERBS & set(annotations):
                own = _first_string(annotations["Path"]) if "Path" in annotations else ""
                self._entry("http", name, join_route(prefix, own), line)
        else:
            attr = next((a for l, a in annotations.items() if l in CS_MAPPINGS), None)
            if attr is not None:
                route = _first_string(attr)
                self._entry("http", name, route if route.startswith("/") else join_route(prefix, route), line)

    def _csharp_minimal(self, node, name: str, receiver) -> None:
        """app.MapGet("/x", handler) and routes on a MapGroup variable."""
        args = node.child_by_field_name("arguments")
        named = [a.children[0] if a.type == "argument" and a.children else a for a in (args.children if args is not None else []) if a.is_named]
        if not named:
            return
        owner = _text(receiver) if receiver is not None and receiver.type == "identifier" else ""
        self._entry("http", _handler_name(named[-1]) if len(named) > 1 else "<anonymous>", _first_string(named[0]),
                    node.start_point[0] + 1, owner)

    def _csharp_group(self, node) -> None:
        """var api = app.MapGroup("/api"): remember the prefix of `api`."""
        inv = next((c for c in node.children if c.type == "invocation_expression"), None)
        if inv is None:
            return
        name, receiver, _ = call_info("csharp", inv)
        if name == "MapGroup":
            parent = self.prefixes.get(_text(receiver), "") if receiver is not None else ""
            self.prefixes[_text(node.child_by_field_name("name"))] = join_route(parent, _first_string(inv))

    def _python_assign(self, node) -> None:
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None or left.type != "identifier" or right.type not in ("list", "call"):
            return
        var = _text(left)
        if right.type == "call":
            fn = _text(right.child_by_field_name("function")).split(".")[-1]
            if fn in ROUTER_FACTORIES:
                self.prefixes[var] = _kwarg_string(right, ("prefix", "url_prefix"))
        elif var == "urlpatterns":
            for call in (n for n in _walk(right) if n.type == "call"):
                fn = _text(call.child_by_field_name("function"))
                args = call.child_by_field_name("arguments")
                named = [a for a in (args.children if args is not None else []) if a.is_named and a.type != "keyword_argument"]
                if fn in DJANGO_ROUTES and len(named) >= 2 and "string" in named[0].type:
                    if _handler_name(named[1]) != "include":
                        self._entry("http", _handler_name(named[1]), _first_string(named[0]), call.start_point[0] + 1)

    def _python_decorators(self, node) -> None:
        definition = node.child_by_field_name("definition")
        name = _text(definition.child_by_field_name("name")) if definition is not None else ""
        for dec in (c for c in node.children if c.type == "decorator"):
            expr = next((c for c in dec.children if c.type != "@"), None)
            if expr is not None and expr.type == "call":
                fn = expr.child_by_field_name("function")
                if fn is not None and fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) in HTTP_VERBS:
                    obj = fn.child_by_field_name("object")
                    self._entry("http", name, _first_string(expr.child_by_field_name("arguments")), node.start_point[0] + 1,
                                _text(obj) if obj is not None and obj.type == "identifier" else "")

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

    def _ts_route(self, node, name: str, receiver=None) -> None:
        args = node.child_by_field_name("arguments")
        named = [c for c in args.children if c.is_named] if args is not None else []
        if name == "use" and len(named) >= 2 and named[0].type in ("string", "template_string") and named[-1].type == "identifier":
            parent = _text(receiver) if receiver is not None and receiver.type == "identifier" else ""
            self.mounts.append((_text(named[-1]), _text(named[0]).strip("\"'`"), parent))     # app.use("/api", router)
            return
        if name not in HTTP_VERBS - {"route", "api_route", "head", "options"}:
            return
        if len(named) >= 2 and named[0].type in ("string", "template_string") and _text(named[0]).strip("\"'`").startswith("/"):
            handler = named[-1]
            owner = _text(receiver) if receiver is not None and receiver.type == "identifier" else ""
            self._entry("http", _text(handler) if handler.type == "identifier" else "<anonymous>",
                        _text(named[0]).strip("\"'`"), node.start_point[0] + 1, owner)

    # traversal -------------------------------------------------------------------
    def visit(self, node) -> None:
        t, lang = node.type, self.lang
        self._main(node)
        if lang == "python" and t == "decorated_definition":
            self._python_decorators(node)
        if lang == "python" and t == "assignment":
            self._python_assign(node)
        if lang in ("java", "csharp") and t == "method_declaration":
            self._method_entry(node)
        if lang == "csharp" and t == "variable_declarator":
            self._csharp_group(node)

        if t in CLASS_NODES[lang]:
            self.classes.append(_text(node.child_by_field_name("name")))
            self.class_routes.append(self._class_route(node) if lang in ("java", "csharp") else "")
            for child in node.children:
                self.visit(child)
            self.class_routes.pop()
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
                self._ts_route(node, name, receiver)
            if lang == "csharp" and name in CS_MINIMAL:
                self._csharp_minimal(node, name, receiver)
            if lang == "python" and name in MOUNT_CALLS:
                self._python_mount(node, receiver)
        for child in node.children:
            self.visit(child)

    def _python_mount(self, node, receiver) -> None:
        """app.include_router(router, prefix="/x") / app.register_blueprint(bp, url_prefix="/x")."""
        args = node.child_by_field_name("arguments")
        first = next((a for a in (args.children if args is not None else []) if a.is_named and a.type != "keyword_argument"), None)
        if first is not None and first.type == "identifier":
            parent = _text(receiver) if receiver is not None and receiver.type == "identifier" else ""
            prefix = _kwarg_string(node, ("prefix", "url_prefix"))
            if prefix and _text(node.child_by_field_name("function")).endswith("register_blueprint"):
                self.prefixes[_text(first)] = ""                # Flask: the registration prefix replaces the blueprint's own
            self.mounts.append((_text(first), prefix, parent))

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
        resolver.finish()
        index.calls.extend(resolver.calls)
        index.entry_points.extend(resolver.entries)
        index.sinks.extend(resolver.sinks)
    return index
