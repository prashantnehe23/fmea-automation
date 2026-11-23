# ADR-033: Fix Proposals from Stored Scans, Targeted Context, Server-Built Diffs

**Status:** Accepted (engineer, 2026-11-23: "Accept ADR-033, start B-056"), as written  **Date:** 2026-11-23  **Backlog:** B-056 (builds on B-053; prepares B-049)  **Builds on:** [ADR-018](ADR-018-remediation-actions.md) (actions), [ADR-027](ADR-027-authentication-roles-and-repository-access.md) (server-side results and roles), B-042 (stored sources and their retention)

## Context
B-053 added a **Remediate** button on each corrective and preventive action. In use it failed on the first real try ("This scan is no longer available on the server"), for three reasons:

1. **Where the code comes from.** The route looks up the scan in a Python dictionary in server memory, keyed by a counter that restarts at 1. A server restart empties it, while the Fixes page shows findings saved in the browser and the database. After a restart the counter can also match a different, newer scan, which would produce a fix for the wrong code.
2. **What the model is shown.** `generate_fix` picks 60 lines by guessing from words in the evidence, even when the finding already cites exact files and lines (the exploit path, or the evidence field).
3. **What is returned.** The model writes a diff by hand. Hand-written diffs are often wrong (wrong line counts, wrong context), cannot be trusted to apply, and the download cannot be used with `git apply`. A cross-component finding usually needs changes in more than one file, which a single snippet cannot express.

The database already stores each scan's full result and its source files (`scan_snapshots`, `scan_sources`, kept for `FMEA_SOURCE_RETENTION_DAYS`, 30 by default, set to 0 to store none), written for the chat feature (B-025, B-042).

## Decision
1. **The stored snapshot is the source of truth for a fix.** The request names the project and the saved scan (`workspace_id`, `db_scan_id`), both already in every scan result. The server loads that snapshot (findings, fix plans, source files). The in-memory store stays only for the older `/api/remediate` route. A snapshot is matched on both ids exactly; if it is missing the answer is a plain 404, never a "closest" scan.
2. **Retention is respected, not bypassed.** If the sources of that scan are not stored (retention 0, or purged), the route answers 409 with a plain message that says why and how to get a fix (run the scan again, or keep source code for longer). Nothing is fetched from the repository at that point.
3. **The model is shown the code the finding cites.** The files named by the exploit path steps, else by the evidence field, up to 3 files and a fixed size limit each, shown with line numbers; the action chosen by the person leads the prompt. If a finding cites nothing, the existing keyword heuristic is the fallback and the panel says the context was a guess.
4. **The model returns edits, not a diff.** A list of `{file, start_line, end_line, replacement}` (1-based, inclusive line ranges of the original file) plus a test and a one-sentence reason. One or more files per proposal, up to 3.
5. **The server validates, applies and builds the diff.** Every edit must name a file that was shown, stay inside that file, and not overlap another edit; a bad edit is dropped with a reason shown, never guessed. The server applies the edits to the original text and builds a standard unified diff (`a/` and `b/` paths) with `difflib`, so the result applies with `git apply`. Python files that are changed must still parse (`ast.parse`); if not, the proposal is returned flagged as "does not parse" rather than hidden.
6. **A person's edit is checked the same way.** The decision route receives the final replacements, rebuilds the diff on the server, and records in the audit trail the files touched and a SHA-256 of the final diff. The code itself is not stored; that waits for the pull-request work (B-049), which needs proposals to be stored anyway.
7. **Nothing is written to any repository.** This ADR changes how proposals are made and checked; it does not apply them.

## Alternatives considered
- **Keep scans in memory, make users rescan after a restart:** simplest, but breaks the moment a server restarts, and the wrong-scan risk remains.
- **Store scans in a new table keyed by the memory counter:** duplicates `scan_snapshots`.
- **Fetch the code again from the repository when it is not stored:** works for public repositories, but needs a repository credential at that moment, may fetch a different version than was scanned, and sends code the retention setting says should be gone. Left for later and explicit consent.
- **Keep the model-written diff and "fix" it afterwards:** brittle; computing the diff from real text is simple and correct.
- **Ask the model for whole files:** easier to apply, but costs far more tokens, truncates on large files, and invites changes nobody asked for.

## Consequences
- Fixes work after a restart, a reload or a new browser, for any scan whose sources are still stored. Projects with retention 0 cannot get proposals, and the interface says so.
- Better targeted context should give better fixes; this is not yet measured, and B-056 only claims what its tests show.
- The download can become a real patch. Applying it is still the person's act (or B-049's, later).
- The audit trail will say which files and which exact diff a person accepted (by hash), which the earlier version could not.
- **Not solved here:** access is still by role, not per project. Any signed-in user who may scan can request a fix for a snapshot of any project whose ids they supply. This is how the other project routes work today (ADR-027); per-project access needs its own decision.
- Python is the only language with a syntax check; the prompt's language wording is a separate small item (B-057).
- Source code goes to the model provider when a fix is requested, as it does for scans.

## Decided
Accepted with all seven points as written, including no re-fetch when sources are gone, a flagged (not refused) proposal that does not parse, and the 3-file limit.
