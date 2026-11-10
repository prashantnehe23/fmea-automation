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

from core.scan_scope import ScopeEntry, classify_tree, readme_path

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

def list_repo(
    url: str,
    skip_tests: bool = True,
) -> tuple[RepoRef, list[ScopeEntry], str | None]:
    """
    List a public GitHub repo's tree and classify every path against the scan scope (B-033).

    Returns (ref, entries, readme_path_or_None); each entry says whether the path is in scope and why.
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
    items = [(item.get("path", ""), item.get("size")) for item in tree
             if isinstance(item, dict) and item.get("type") == "blob"]
    entries = classify_tree(items, skip_tests)
    return ref, entries, readme_path([e.path for e in entries])


def scan_repo(
    url: str,
    skip_tests: bool = True,
) -> tuple[RepoRef, list[str], str | None]:
    """
    Scan a public GitHub repo and return:
      (ref, file_paths, readme_path_or_None)

    file_paths: the paths in scan scope (see core/scan_scope.py).
    readme_path: path to the root README (any extension) if present, else None.
    """
    ref, entries, readme = list_repo(url, skip_tests)
    return ref, sorted(e.path for e in entries if e.included), readme


def select_paths(paths: list[str], skip_tests: bool = True) -> tuple[list[str], str | None]:
    """
    The scan scope rule applied to bare paths: (sorted in-scope paths, root README path or None).
    """
    entries = classify_tree([(p, None) for p in paths], skip_tests)
    return sorted(e.path for e in entries if e.included), readme_path(paths)


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


def fetch_contents(ref: RepoRef, paths: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Download the given paths. Returns ({path: text}, {path: error}); a failed file never aborts the rest."""
    contents: dict[str, str] = {}
    errors: dict[str, str] = {}
    for path in paths:
        try:
            contents[path] = fetch_file_content(ref.owner, ref.repo, ref.branch, path)
        except Exception as exc:
            errors[path] = str(exc)
    return contents, errors


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
