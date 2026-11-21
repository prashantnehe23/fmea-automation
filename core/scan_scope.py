"""
core/scan_scope.py — B-033 (ADR-021): what the agents are shown, and a record of what they were not.

Every repository path gets a scope entry: examined, excluded (with a reason) or unexamined
(in scope but over the size budget). The manifest travels with the scan result, so
"nothing found" can be told apart from "not looked at". Files are chosen under the byte budget
by priority (infrastructure and delivery, then security-relevant code), never by alphabet and
never silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from core.secret_scan import SecretFinding, finding_dicts, redact

MAX_BYTES = 300_000      # soft byte budget for the code the agents receive in one pass (one batch)
DEFAULT_MAX_BATCHES = 5  # B-028 phase 0: passes over a large repository before the rest is listed as not examined

CODE_EXTS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rb", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".rs", ".php", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash",
    ".zsh", ".r", ".sql", ".graphql", ".proto", ".lua",
    ".vb", ".fs", ".dart", ".ex", ".exs", ".groovy", ".gradle", ".ps1", ".psm1",
})
CONFIG_EXTS = frozenset({
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".properties", ".conf", ".xml", ".env",
})
DOC_EXTS = frozenset({".md", ".rst", ".txt", ".adoc"})
INFRA_EXTS = frozenset({".tf", ".tfvars", ".hcl", ".bicep", ".nomad"})
TEMPLATE_EXTS = frozenset({
    ".html", ".htm", ".vue", ".svelte", ".ejs", ".hbs", ".handlebars", ".j2", ".jinja", ".jinja2",
    ".twig", ".erb", ".cshtml", ".razor", ".jsp", ".tpl", ".njk", ".pug",
})
MANIFEST_EXTS = frozenset({".csproj", ".props", ".targets"})
INFRA_NAMES = frozenset({"makefile", "gnumakefile", "jenkinsfile", "procfile", "vagrantfile"})
MANIFEST_NAMES = frozenset({"go.mod", "gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "cargo.toml"})

NOISE_DIRS = (
    "node_modules/", ".git/", ".github/", "vendor/", "dist/", "build/",
    "__pycache__/", ".venv/", "venv/", ".tox/", ".eggs/",
    ".coverage", "coverage/", ".nyc_output/", "site-packages/",
)
CI_DIRS = (".github/workflows/", ".github/actions/")       # exceptions inside .github/
NOISE_SUFFIXES = (".pyc", ".pyo", ".class", ".min.js", ".min.css", ".DS_Store")
LOCKFILE_NAMES = frozenset({"package-lock.json", "yarn.lock", "poetry.lock", "pipfile.lock", "gemfile.lock",
                            "pnpm-lock.yaml", "composer.lock", "cargo.lock", "go.sum"})
TEST_PATTERNS = (
    "test_", "_test.", "/tests/", "/test/",
    "/spec/", ".spec.", ".test.", "__tests__/",
)

_SECURITY_NAMES = re.compile(
    r"auth|login|session|token|jwt|oauth|passw|secret|crypto|admin|payment|billing|checkout|"
    r"db|database|sql|query|model|repo|dao|route|view|controller|handler|api|server|app|main|index|"
    r"setting|config|middleware|permission|acl|webhook|upload|export|import", re.IGNORECASE)
_README = re.compile(r"^README(\.\w+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class ScopeEntry:
    path: str
    included: bool
    reason: str            # why it is in or out
    category: str          # code | infra | ci | template | config | manifest | doc | env | other
    size: int | None = None


def _is_env_file(name: str) -> bool:
    lower = name.lower()
    return lower == ".env" or lower.startswith(".env.") or lower.endswith(".env")


def _category(path: str) -> str | None:
    p = PurePosixPath(path)
    name, lower, ext = p.name, p.name.lower(), p.suffix.lower()
    if any(path.startswith(d) or f"/{d}" in path for d in CI_DIRS):
        return "ci"
    if _is_env_file(name):
        return "env"
    if lower == "dockerfile" or lower.startswith("dockerfile.") or ext == ".dockerfile" or lower in INFRA_NAMES \
            or ext in INFRA_EXTS or lower.startswith("docker-compose"):
        return "infra"
    if lower in MANIFEST_NAMES or ext in MANIFEST_EXTS or re.match(r"^requirements.*\.txt$", lower):
        return "manifest"
    if ext in TEMPLATE_EXTS:
        return "template"
    if ext in CODE_EXTS:
        return "code"
    if ext in CONFIG_EXTS:
        return "config"
    if ext in DOC_EXTS:
        return "doc"
    return None


def classify_path(path: str, skip_tests: bool = True, size: int | None = None) -> ScopeEntry:
    """The scope rule for one repository path."""
    path = path.replace("\\", "/")
    name = PurePosixPath(path).name
    category = _category(path)
    if category == "ci":
        return ScopeEntry(path, True, "CI/CD definition", "ci", size)
    if any(nd in path for nd in NOISE_DIRS):
        return ScopeEntry(path, False, "noise directory", category or "other", size)
    if name.lower() in LOCKFILE_NAMES or path.endswith(".lock"):
        return ScopeEntry(path, False, "lockfile (dependency inventory)", "other", size)
    if any(path.endswith(s) for s in NOISE_SUFFIXES):
        return ScopeEntry(path, False, "binary or generated", "other", size)
    if skip_tests and any(pat in path for pat in TEST_PATTERNS):
        return ScopeEntry(path, False, "test file", category or "other", size)
    if category is None:
        return ScopeEntry(path, False, "file type not scanned", "other", size)
    return ScopeEntry(path, True, f"{category} file", category, size)


def classify_tree(items: list[tuple[str, int | None]], skip_tests: bool = True) -> list[ScopeEntry]:
    return [classify_path(path, skip_tests, size) for path, size in items]


def readme_path(paths: list[str]) -> str | None:
    """The root README, if any."""
    return next((p for p in paths if "/" not in p and _README.match(p)), None)


# ── Priority and budget ───────────────────────────────────────────────────────

def priority(entry: ScopeEntry) -> tuple[int, str]:
    """Lower sorts first: infrastructure and delivery, then security-relevant code, then the rest."""
    name = PurePosixPath(entry.path).stem
    if entry.category in ("infra", "ci"):
        tier = 0
    elif entry.category == "env":
        tier = 1
    elif entry.category == "code":
        tier = 1 if _SECURITY_NAMES.search(name) else 2
    elif entry.category == "template":
        tier = 3
    elif entry.category in ("config", "manifest"):
        tier = 4
    else:
        tier = 5
    return tier, entry.path


def choose_within_budget(entries: list[ScopeEntry], budget: int = MAX_BYTES) -> tuple[list[ScopeEntry], list[ScopeEntry]]:
    """Split the included entries into (examined, over budget) by priority; unknown sizes count as 0."""
    chosen: list[ScopeEntry] = []
    over: list[ScopeEntry] = []
    used = 0
    for e in sorted((e for e in entries if e.included), key=priority):
        size = e.size or 0
        if used + size <= budget or not chosen:
            chosen.append(e)
            used += size
        else:
            over.append(e)
    return sorted(chosen, key=lambda e: e.path), sorted(over, key=lambda e: e.path)


def plan_batches(entries: list[ScopeEntry], budget: int = MAX_BYTES,
                 max_batches: int = DEFAULT_MAX_BATCHES, boost: set[str] | frozenset = frozenset()) -> tuple[list[list[ScopeEntry]], list[ScopeEntry]]:
    """
    Split the included entries into batches of at most `budget` bytes, highest priority first (B-028 phase 0).

    Files go into the first batch with room; a new batch is opened while fewer than `max_batches` exist; a file
    bigger than the budget gets a batch of its own. Whatever does not fit is returned as `over` and is listed as
    not examined. Unknown sizes count as 0. Paths in `boost` (the files a pull request changed) go first.
    """
    batches: list[list[ScopeEntry]] = []
    used: list[int] = []
    over: list[ScopeEntry] = []
    for e in sorted((e for e in entries if e.included), key=lambda e: (e.path not in boost, priority(e))):
        size = e.size or 0
        slot = next((i for i, u in enumerate(used) if u + size <= budget), None)
        if slot is None and len(batches) < max_batches:
            batches.append([])
            used.append(0)
            slot = len(batches) - 1
        if slot is None:
            over.append(e)
            continue
        batches[slot].append(e)
        used[slot] += size
    return [sorted(b, key=lambda e: e.path) for b in batches], sorted(over, key=lambda e: e.path)


# ── Manifest ──────────────────────────────────────────────────────────────────

def make_manifest(entries: list[ScopeEntry], unexamined: set[str] = frozenset(),
                  not_selected: set[str] = frozenset()) -> list[dict]:
    """Plain, JSON-ready scope manifest. Status: examined | excluded | unexamined."""
    out = []
    for e in sorted(entries, key=lambda e: e.path):
        if not e.included:
            status, reason = "excluded", e.reason
        elif e.path in not_selected:
            status, reason = "excluded", "not selected by the user"
        elif e.path in unexamined:
            status, reason = "unexamined", "over the size budget"
        else:
            status, reason = "examined", e.reason
        out.append({"path": e.path, "status": status, "reason": reason, "category": e.category, "size": e.size})
    return out


def summarise_manifest(manifest: list[dict]) -> dict:
    """Counts for display: 'N files examined, M not examined'."""
    examined = [m for m in manifest if m["status"] == "examined"]
    unexamined = [m for m in manifest if m["status"] == "unexamined"]
    excluded = [m for m in manifest if m["status"] == "excluded"]
    by_reason: dict[str, int] = {}
    for m in unexamined + excluded:
        by_reason[m["reason"]] = by_reason.get(m["reason"], 0) + 1
    return {"examined": len(examined), "unexamined": len(unexamined), "excluded": len(excluded),
            "not_examined": len(unexamined) + len(excluded), "by_reason": by_reason}


# ── Building what the agents receive ─────────────────────────────────────────

@dataclass
class ScanInput:
    code: str                  # concatenated, headered file blocks (what the agents are shown)
    readme_text: str           # root README text for business context ("" if none)
    manifest: list[dict]       # scope manifest, see make_manifest
    examined: list[str]        # paths whose content is in `code`
    secret_findings: list[dict]  # deterministic secret findings (names and lines, never values)
    batch_codes: list[str] | None = None   # `code` split into the batches the agents see one at a time (B-028 phase 0)


def build_scan_input(contents: dict[str, str], entries: list[ScopeEntry] | None = None,
                     skip_tests: bool = True, budget: int = MAX_BYTES,
                     not_selected: set[str] = frozenset(), max_batches: int = 1,
                     boost: set[str] | frozenset = frozenset()) -> ScanInput:
    """
    Turn fetched file contents into the code the agents see plus a scope manifest.

    `entries` is the classified repository tree (including excluded paths); when None it is
    derived from `contents` alone (pasted code, benchmark repositories). Included files are
    taken in priority order into batches of the byte budget, up to `max_batches` of them (1 = a single pass, as
    before); the rest are listed as unexamined.
    """
    from core.github_fetcher import file_block

    if entries is None:
        entries = classify_tree([(p, len(c.encode("utf-8"))) for p, c in contents.items()], skip_tests)
    else:
        # real sizes beat the tree's, and a path whose download failed cannot be examined
        entries = [ScopeEntry(e.path, e.included, e.reason, e.category,
                              len(contents[e.path].encode("utf-8")) if e.path in contents else e.size)
                   for e in entries]
    candidates = [e for e in entries if e.included and e.path not in not_selected]
    planned, over = plan_batches(candidates, budget, max_batches, boost)
    chosen = [e for b in planned for e in b]
    missing = {e.path for e in chosen if e.path not in contents}
    examined = sorted(e.path for e in chosen if e.path not in missing)
    unexamined = {e.path for e in over} | missing
    manifest = make_manifest(entries, unexamined, not_selected)
    for m in manifest:
        if m["path"] in missing:
            m["reason"] = "could not be downloaded"
    # Secret values never go further than this function: redact before anything is sent to a model (ADR-021)
    secrets: list[SecretFinding] = []
    safe: dict[str, str] = {}
    for p in examined:
        safe[p], found = redact(p, contents[p])
        secrets.extend(found)
    batch_codes = [c for c in ("\n\n".join(file_block(e.path, safe[e.path]) for e in b if e.path in safe) for b in planned) if c]
    code = "\n\n".join(file_block(p, safe[p]) for p in examined)       # path order, whatever the batching (stable cache key)
    readme = readme_path([e.path for e in entries])
    readme_text = redact(readme, contents[readme])[0] if readme in contents else ""
    findings = finding_dicts(secrets) + _secret_file_findings([e.path for e in entries])
    return ScanInput(code, readme_text, manifest, examined, findings, batch_codes or [code])


_SECRET_FILE = re.compile(r"(?:^|/)(?:id_rsa|id_dsa|id_ecdsa|id_ed25519)$|\.(?:pem|p12|pfx|key|jks|keystore)$",
                          re.IGNORECASE)


def _secret_file_findings(paths: list[str]) -> list[dict]:
    """Key and certificate files committed to the repository, reported by name (their content is never fetched)."""
    return [{"path": p, "line": 0, "kind": "secret-file", "name": ""} for p in sorted(paths) if _SECRET_FILE.search(p)]
