"""
In-house code index prototype for the B-036 spike: tree-sitter parse -> symbols, name-based call edges,
entry points and sinks, for Python, Java, C#, and TypeScript/JavaScript.

Uses the official per-language tree-sitter wheels (static grammars, no download at run time).
This is the candidate that would become core/code_index.py if the spike supports it.
"""

from __future__ import annotations

import re
from pathlib import Path

import tree_sitter as ts

_EXT = {".py": "python", ".java": "java", ".cs": "csharp", ".ts": "typescript", ".tsx": "typescript",
        ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript"}
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


FUNCTION_NODES = {"python": {"function_definition"}, "java": {"method_declaration", "constructor_declaration"},
                  "csharp": {"method_declaration", "constructor_declaration"},
                  "typescript": {"function_declaration", "method_definition"}}
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


def _text(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _first_string(node) -> str:
    """The first string literal under `node`, without quotes."""
    stack = [node]
    while stack:
        n = stack.pop(0)
        if "string" in n.type and n.type not in ("string_content",) and n.type != "interpolated_string_expression":
            return _text(n).strip("\"'`@$")
        stack = list(n.children) + stack
    return ""


def call_info(lang: str, node) -> tuple[str, str]:
    """(callee name, qualifier text) for a call or constructor node."""
    t = node.type
    if lang == "python":
        fn = node.child_by_field_name("function")
        if fn is not None and fn.type == "attribute":
            return _text(fn.child_by_field_name("attribute")), _text(fn.child_by_field_name("object"))
        return _text(fn), ""
    if lang == "java":
        if t == "object_creation_expression":
            return _text(node.child_by_field_name("type")).split(".")[-1], "new"
        return _text(node.child_by_field_name("name")), _text(node.child_by_field_name("object"))
    if lang == "csharp":
        if t == "object_creation_expression":
            return _text(node.child_by_field_name("type")).split(".")[-1], "new"
        fn = node.child_by_field_name("function")
        if fn is not None and fn.type == "member_access_expression":
            return _text(fn.child_by_field_name("name")), _text(fn.child_by_field_name("expression"))
        return _text(fn), ""
    if t == "new_expression":
        return _text(node.child_by_field_name("constructor")), "new"
    fn = node.child_by_field_name("function")
    if fn is not None and fn.type == "member_expression":
        return _text(fn.child_by_field_name("property")), _text(fn.child_by_field_name("object"))
    return _text(fn), ""


def sink_kind(lang: str, name: str, qualifier: str) -> str | None:
    q = qualifier.replace(" ", "")
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
    if lang == "python" and q == "subprocess" or (lang == "python" and name in {"system", "popen"} and q == "os"):
        return "command"
    if lang == "java" and ((name == "exec" and "Runtime" in q) or (q == "new" and name == "ProcessBuilder")):
        return "command"
    if lang == "csharp" and q == "Process" and name == "Start":
        return "command"
    return None


class _Extractor:
    def __init__(self, lang: str, rel: str, source: bytes):
        self.lang, self.rel, self.source = lang, rel, source
        self.scope: list[str] = []
        self.symbols: list[dict] = []
        self.calls: list[dict] = []
        self.entries: list[dict] = []
        self.sinks: list[dict] = []

    def run(self, root) -> None:
        self.visit(root)

    # entry points ------------------------------------------------------------
    def _entry(self, kind: str, symbol: str, route: str = "") -> None:
        self.entries.append({"file": self.rel, "kind": kind, "symbol": symbol, "route": route})

    def _python_decorators(self, node) -> None:
        definition = node.child_by_field_name("definition")
        name = _text(definition.child_by_field_name("name")) if definition is not None else ""
        for dec in (c for c in node.children if c.type == "decorator"):
            expr = next((c for c in dec.children if c.type not in ("@",)), None)
            if expr is not None and expr.type == "call":
                fn = expr.child_by_field_name("function")
                if fn is not None and fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) in HTTP_VERBS:
                    self._entry("http", name, _first_string(expr.child_by_field_name("arguments")))

    def _annotated_entry(self, node, names: set[str]) -> None:
        name = _text(node.child_by_field_name("name"))
        attrs = [c for c in node.children if c.type in ("modifiers", "attribute_list")]
        for group in attrs:
            for a in self._walk(group):
                if a.type in ("annotation", "marker_annotation", "attribute"):
                    label = _text(a.child_by_field_name("name")).split(".")[-1]
                    if label in names:
                        self._entry("http", name, _first_string(a))
                        return

    def _walk(self, node):
        stack = [node]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def _main_check(self, node) -> None:
        if self.lang == "python" and node.type == "if_statement":
            cond = _text(node.child_by_field_name("condition"))
            if "__name__" in cond and "__main__" in cond:
                self._entry("main", "__main__")
        elif self.lang == "typescript" and node.type == "if_statement":
            if "require.main" in _text(node.child_by_field_name("condition")):
                self._entry("main", "<main>")
        elif self.lang in ("java", "csharp") and node.type == "method_declaration":
            if _text(node.child_by_field_name("name")) in ("main", "Main") and "static" in _text(node)[:80]:
                self._entry("main", _text(node.child_by_field_name("name")))

    def _ts_route(self, node, name: str) -> None:
        if name not in HTTP_VERBS - {"route", "api_route", "head", "options"}:
            return
        args = node.child_by_field_name("arguments")
        if args is None:
            return
        named = [c for c in args.children if c.is_named]
        if len(named) >= 2 and named[0].type in ("string", "template_string") and _text(named[0]).strip("\"'`").startswith("/"):
            handler = named[-1]
            symbol = _text(handler) if handler.type == "identifier" else "<anonymous>"
            self._entry("http", symbol, _text(named[0]).strip("\"'`"))

    # traversal ---------------------------------------------------------------
    def visit(self, node) -> None:
        t = node.type
        self._main_check(node)
        if self.lang == "python" and t == "decorated_definition":
            self._python_decorators(node)
        if self.lang == "java" and t == "method_declaration":
            self._annotated_entry(node, JAVA_MAPPINGS)
        if self.lang == "csharp" and t == "method_declaration":
            self._annotated_entry(node, CS_MAPPINGS)

        if t in FUNCTION_NODES[self.lang]:
            name = _text(node.child_by_field_name("name"))
            self.symbols.append({"file": self.rel, "name": name, "line": node.start_point[0] + 1})
            self.scope.append(name)
            for child in node.children:
                self.visit(child)
            self.scope.pop()
            return

        if t in CALL_NODES[self.lang]:
            name, qualifier = call_info(self.lang, node)
            self.calls.append({"caller_file": self.rel, "caller": self.scope[-1] if self.scope else "<module>",
                               "callee": name.split(".")[-1], "line": node.start_point[0] + 1})
            kind = sink_kind(self.lang, name.split(".")[-1], qualifier)
            if kind:
                self.sinks.append({"file": self.rel, "kind": kind, "line": node.start_point[0] + 1})
            if self.lang == "typescript" and t == "call_expression":
                self._ts_route(node, name)
        for child in node.children:
            self.visit(child)


def index_repo(repo: Path) -> dict:
    """Index every supported file under `repo`. Returns the common shape used by score_index."""
    out = {"symbols": [], "calls": [], "entry_points": [], "sinks": []}
    for path in sorted(Path(repo).rglob("*")):
        lang = _EXT.get(path.suffix.lower())
        if not lang or not path.is_file():
            continue
        source = path.read_bytes()
        ex = _Extractor(lang, path.relative_to(repo).as_posix(), source)
        ex.run(_parser(lang).parse(source).root_node)
        out["symbols"] += ex.symbols
        out["calls"] += ex.calls
        out["entry_points"] += ex.entries
        out["sinks"] += ex.sinks
    return out
