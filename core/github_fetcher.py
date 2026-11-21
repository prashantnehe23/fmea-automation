"""
Fetch source code from a GitHub repository. Public repositories need no token; a private one is read with the
access token stored for its owner (core/repo_credentials.py, B-043).

Scans ALL non-binary file types relevant to code analysis:
  code (.py, .js, .ts, .java, .go, .rb, .cs, .cpp, .rs, …)
  config (.yaml, .yml, .json, .toml, .ini, .xml, …)
  docs (.md, .rst, .txt) including README files

API endpoints used:
  api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1
  raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}                 (no token)
  api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}          (with a token)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

from core.repo_credentials import token_for
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


_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


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
    if not (_NAME.match(owner) and _NAME.match(repo) and _NAME.match(branch)) or ".." in (owner, repo, branch):
        raise ValueError(f"Cannot parse GitHub URL: {url!r}")
    return RepoRef(owner=owner, repo=repo, branch=branch)


# ── HTTP helpers ─────────────────────────────────────────────────────────────────

class RepoAccessError(Exception):
    """GitHub refused or could not find a repository. `message` says in plain words what to do (B-043)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class _KeepTokenOnTheSameHost(urllib.request.HTTPRedirectHandler):
    """urllib forwards request headers on a redirect; never forward the token to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            to, here = urllib.parse.urlparse(newurl), urllib.parse.urlparse(req.full_url)
            if (to.scheme, to.netloc) != (here.scheme, here.netloc):
                new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_KeepTokenOnTheSameHost)      # local: nothing else in the process is affected


def _urlopen(req, timeout=20):
    return _OPENER.open(req, timeout=timeout)


def _explain(exc: urllib.error.HTTPError, owner: str, repo: str, token_used: bool) -> Exception:
    """Turn a GitHub HTTP error into a RepoAccessError; other errors pass through unchanged."""
    name = f"{owner}/{repo}"
    if exc.code == 401:
        return RepoAccessError("token_rejected", f"GitHub rejected the access token for '{owner}'. It may have expired "
                                                 "or been revoked. Add a new token in Settings.")
    if exc.code == 403:
        headers = exc.headers or {}
        if str(headers.get("X-RateLimit-Remaining", "")) == "0":
            try:
                when = time.strftime(" until %H:%M UTC", time.gmtime(int(headers.get("X-RateLimit-Reset"))))
            except (TypeError, ValueError):
                when = ""
            advice = ("Wait and try again." if token_used
                      else "Adding an access token in Settings raises the limit.")
            return RepoAccessError("rate_limited", f"GitHub's rate limit was reached{when}. {advice}")
        if token_used:
            return RepoAccessError("forbidden", f"GitHub refused access to {name}. The access token for '{owner}' may lack "
                                                "read-only 'Contents' permission, or the organisation restricts tokens. "
                                                "Check it in Settings.")
        return RepoAccessError("forbidden", f"GitHub refused access to {name}. If it is private, add an access token for "
                                            f"'{owner}' in Settings.")
    if exc.code == 404:
        if token_used:
            return RepoAccessError("no_access", f"The access token for '{owner}' cannot see {name}. Check that the token is "
                                                "allowed to use this repository and has read-only 'Contents' permission, "
                                                "then update it in Settings.")
        return RepoAccessError("not_found", f"Repository {name} was not found. If it is private, add an access token for "
                                            f"'{owner}' in Settings (read-only 'Contents' access is enough).")
    return exc


def _open(url: str, owner: str, repo: str, accept: str) -> bytes:
    """One GET to GitHub, carrying the owner's token when there is one."""
    # The token goes to api.github.com only, never to raw.githubusercontent.com or anywhere else
    token = token_for(owner) if url.startswith("https://api.github.com/") else None
    headers = {"Accept": accept, "User-Agent": "fmea-automation/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with _urlopen(urllib.request.Request(url, headers=headers), timeout=20) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise _explain(exc, owner, repo, bool(token)) from None
    except (ValueError, UnicodeError):
        # http.client puts the whole header value, token included, in its message: never pass that on
        raise RepoAccessError("token_invalid", f"The stored access token for '{owner}' is not valid. "
                                               "Replace it in Settings.") from None


def _get_json(url: str, owner: str, repo: str) -> object:
    return json.loads(_open(url, owner, repo, "application/vnd.github+json"))


def _try_branches(owner: str, repo: str) -> tuple[str, object]:
    """Try 'main' then 'master', return (branch, tree_data)."""
    last: RepoAccessError | None = None
    for branch in ("main", "master"):
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
            "?recursive=1"
        )
        try:
            data = _get_json(url, owner, repo)
            if isinstance(data, dict) and "tree" in data:
                return branch, data
        except RepoAccessError as exc:
            if exc.code not in ("not_found", "no_access"):
                raise
            last = exc
        except urllib.error.HTTPError:
            continue
    hint = " If the repository exists, its default branch may not be 'main' or 'master': add the branch to the URL, e.g. .../tree/develop."
    if last is not None:
        raise RepoAccessError(last.code, last.message + hint)
    raise ValueError(f"Could not find tree on 'main' or 'master' for {owner}/{repo}." + hint)


# ── Repo scanning ─────────────────────────────────────────────────────────────────

def list_repo(
    url: str,
    skip_tests: bool = True,
) -> tuple[RepoRef, list[ScopeEntry], str | None]:
    """
    List a public GitHub repo's tree and classify every path against the scan scope (B-033).

    Returns (ref, entries, readme_path_or_None); each entry says whether the path is in scope and why.
    Does NOT download any file content — only fetches the tree JSON. Uses the owner's stored token, if any.
    Falls back from 'main' to 'master' automatically.
    """
    ref = parse_github_url(url)

    if ref.branch in ("main", "master"):
        branch, data = _try_branches(ref.owner, ref.repo)
        ref = RepoRef(owner=ref.owner, repo=ref.repo, branch=branch)
    else:
        url_api = (
            f"https://api.github.com/repos/{ref.owner}/{ref.repo}/git/trees/{urllib.parse.quote(ref.branch, safe='')}"
            "?recursive=1"
        )
        data = _get_json(url_api, ref.owner, ref.repo)

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
    if token_for(owner):      # private repositories are not served by raw.githubusercontent.com to every token type
        url = (f"https://api.github.com/repos/{owner}/{repo}/contents/{urllib.parse.quote(path, safe='/')}"
               f"?ref={urllib.parse.quote(branch, safe='')}")
        return _open(url, owner, repo, "application/vnd.github.raw+json").decode("utf-8", errors="replace")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return _open(url, owner, repo, "*/*").decode("utf-8", errors="replace")


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
