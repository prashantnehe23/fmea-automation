"""
Fetch source code from a public GitHub repository — no auth token required.

Scans ALL non-binary file types relevant to code analysis:
  code (.py, .js, .ts, .java, .go, .rb, .cs, .cpp, .rs, …)
  config (.yaml, .yml, .json, .toml, .ini, .xml, …)
  docs (.md, .rst, .txt) including README files

Public API endpoints used:
  api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1
  raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

# ── File classification ────────────────────────────────────────────────────────

_CODE_EXTS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rb", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".rs", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".zsh", ".r", ".sql", ".graphql", ".proto", ".lua",
})
_CONFIG_EXTS = frozenset({
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".properties", ".conf", ".xml", ".env",
})
_DOC_EXTS = frozenset({".md", ".rst", ".txt", ".adoc"})

# Directories and suffixes to always skip
_NOISE_DIRS = (
    "node_modules/", ".git/", ".github/", "vendor/", "dist/", "build/",
    "__pycache__/", ".venv/", "venv/", ".tox/", ".eggs/",
    ".coverage", "coverage/", ".nyc_output/", "site-packages/",
)
_NOISE_SUFFIXES = (
    ".pyc", ".pyo", ".class", ".min.js", ".min.css",
    ".DS_Store", ".lock",
)
_NOISE_NAMES = (
    "package-lock.json", "yarn.lock", "poetry.lock",
    "Pipfile.lock", "Gemfile.lock",
)
_TEST_PATTERNS = (
    "test_", "_test.", "/tests/", "/test/",
    "/spec/", ".spec.", ".test.", "__tests__/",
)

_MAX_BYTES = 300_000   # soft byte cap for concatenated output


def get_category(path: str) -> str:
    """Return 'readme' | 'code' | 'config' | 'doc' | 'other'."""
    name = Path(path).name.lower()
    ext = Path(path).suffix.lower()
    if re.match(r"^readme(\.\w+)?$", name):
        return "readme"
    if ext in _CODE_EXTS:
        return "code"
    if ext in _CONFIG_EXTS:
        return "config"
    if ext in _DOC_EXTS:
        return "doc"
    return "other"


class RepoRef(NamedTuple):
    owner: str
    repo: str
    branch: str


# ── URL parsing ──────────────────────────────────────────────────────────────────

def parse_github_url(url: str) -> RepoRef:
    """
    Extract (owner, repo, branch) from a GitHub URL.

    Handles:
      https://github.com/owner/repo
      https://github.com/owner/repo/tree/main
      https://github.com/owner/repo/blob/main/path/to/file.py
    """
    url = url.strip().rstrip("/")
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/([^/]+))?",
        url,
    )
    if not m:
        raise ValueError(f"Cannot parse GitHub URL: {url!r}")
    owner, repo, branch = m.group(1), m.group(2), m.group(3) or "main"
    repo = repo.removesuffix(".git")
    return RepoRef(owner=owner, repo=repo, branch=branch)


# ── HTTP helpers ─────────────────────────────────────────────────────────────────

def _get_json(url: str) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "fmea-automation/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        import json
        return json.loads(resp.read())


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "fmea-automation/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _try_branches(owner: str, repo: str) -> tuple[str, object]:
    """Try 'main' then 'master', return (branch, tree_data)."""
    for branch in ("main", "master"):
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
            "?recursive=1"
        )
        try:
            data = _get_json(url)
            if isinstance(data, dict) and "tree" in data:
                return branch, data
        except urllib.error.HTTPError:
            continue
    raise ValueError(
        f"Could not find tree on 'main' or 'master' for {owner}/{repo}. "
        "Try specifying the branch in the URL, e.g. .../tree/develop"
    )


# ── Repo scanning ─────────────────────────────────────────────────────────────────

def scan_repo(
    url: str,
    skip_tests: bool = True,
) -> tuple[RepoRef, list[str], str | None]:
    """
    Scan a public GitHub repo and return:
      (ref, file_paths, readme_path_or_None)

    file_paths: all non-binary, non-noise paths (code + config + docs).
    readme_path: path to the root README (any extension) if present, else None.

    Does NOT download any file content — only fetches the tree JSON.
    Falls back from 'main' to 'master' automatically.
    """
    ref = parse_github_url(url)

    if ref.branch in ("main", "master"):
        branch, data = _try_branches(ref.owner, ref.repo)
        ref = RepoRef(owner=ref.owner, repo=ref.repo, branch=branch)
    else:
        url_api = (
            f"https://api.github.com/repos/{ref.owner}/{ref.repo}/git/trees/{ref.branch}"
            "?recursive=1"
        )
        data = _get_json(url_api)

    tree = data.get("tree", []) if isinstance(data, dict) else []
    blobs = [item.get("path", "") for item in tree
             if isinstance(item, dict) and item.get("type") == "blob"]
    files, readme_path = select_paths(blobs, skip_tests)
    return ref, files, readme_path


def select_paths(paths: list[str], skip_tests: bool = True) -> tuple[list[str], str | None]:
    """
    The scan scope rule: which of a repository's file paths are shown to the agents.
    Returns (sorted paths, root README path or None). Shared with the benchmark runner so
    benchmark scans see exactly what real scans see.
    """
    files: list[str] = []
    readme_path: str | None = None

    for path in paths:
        # Skip noise directories
        if any(nd in path for nd in _NOISE_DIRS):
            continue

        # Skip noise file suffixes / exact names
        name = Path(path).name
        if any(path.endswith(s) for s in _NOISE_SUFFIXES):
            continue
        if name in _NOISE_NAMES:
            continue

        # Skip test files if requested
        if skip_tests and any(pat in path for pat in _TEST_PATTERNS):
            continue

        # Detect root README (any extension)
        if re.match(r"^README(\.\w+)?$", name, re.IGNORECASE) and "/" not in path:
            readme_path = path

        # Include if it's a known text-based extension
        ext = Path(path).suffix.lower()
        if ext in (_CODE_EXTS | _CONFIG_EXTS | _DOC_EXTS):
            files.append(path)

    return sorted(files), readme_path


# ── File content fetch ───────────────────────────────────────────────────────────

def fetch_file_content(owner: str, repo: str, branch: str, path: str) -> str:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return _get_text(url)


def fetch_readme(ref: RepoRef, readme_path: str) -> str:
    """Fetch and return README plain text."""
    return fetch_file_content(ref.owner, ref.repo, ref.branch, readme_path)


def file_block(path: str, content: str) -> str:
    """One file as it appears in the concatenated code the agents receive."""
    return f"# ── {path} {'─' * max(0, 60 - len(path))}\n" + content


def fetch_selected_files(
    ref: RepoRef,
    paths: list[str],
    max_bytes: int = _MAX_BYTES,
) -> tuple[str, list[str]]:
    """
    Fetch and concatenate the given file paths into a single string.

    Returns (concatenated_code, successfully_fetched_paths).
    Stops appending when max_bytes is reached and notes the truncation.
    """
    parts: list[str] = []
    fetched: list[str] = []
    total = 0

    for path in paths:
        try:
            content = fetch_file_content(ref.owner, ref.repo, ref.branch, path)
            parts.append(file_block(path, content))
            fetched.append(path)
            total += len(content)
            if total >= max_bytes:
                parts.append(
                    f"\n# [remaining files skipped — {max_bytes:,}-byte soft limit reached]\n"
                )
                break
        except Exception as exc:
            parts.append(f"# [could not fetch {path}: {exc}]\n")

    return "\n\n".join(parts), fetched
