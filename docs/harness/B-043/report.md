# B-043 report

Design: [ADR-027](../../decisions/ADR-027-authentication-roles-and-repository-access.md) (amended). Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **563 passed** (27 new in `tests/test_repo_access.py`).
- `npm run build`: built.
- Browser, against real GitHub on a temp data directory: a scan of a repository that does not exist publicly showed the plain not-found message with an Open Settings button; saving a fake token was rejected by GitHub ("GitHub rejected this token"), nothing stored.

## Acceptance criteria
Met as listed in the B-043 entry of `docs/BACKLOG.md`. **Unverified:** a scan of a real private repository with a real token (no repository or token available); the test uses a fake GitHub.

## Review
Security review by me plus a fresh-subagent review. No critical findings. Important findings and their resolution:
1. A malformed stored token (line break) could leak into an error shown to scanners: **fixed** (token shape validated on save; non-HTTP failures replaced by a generic message; test).
2. Confused deputy: anyone with the scan role can read what the token reaches, and `*` applies to every owner: **mitigated** (catch-all must be explicit with a warning, scans using a token audited, admin-only management, documented in the ADR; allowed-repository list not built).
3. Token-backed scans not audited: **fixed** (`scan_with_stored_token`).
4. Leak test too narrow: **fixed** (error paths, malformed token, delete response); redirect test now covers scheme downgrade and a module-local opener.
Minor fixed: URL owner/repo/branch validation, branch quoting, global opener replaced by a local one, repository tokens encrypted when a secret key appears later and reported when unreadable, lock around credential edits. Minor left: 403 wording cannot distinguish a missing permission from a file over 1 MB; public files of an owner with a token use the contents API.

## Release notes
- **Migration:** none; credentials live in `settings.json` under `repo_credentials`.
- **Rollout:** an administrator adds a token per owner in Settings; scans of that owner's repositories then work.
- **Rollback:** revert the merge; stored tokens stay in `settings.json` and are ignored.
- **Monitor:** `audit_events` for `scan_with_stored_token`, `repo_credential_set`, `repo_credential_removed`; `/api/health` `undecryptable_keys` (now includes `github:<owner>`).
