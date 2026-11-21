# B-012 report

Design: [ADR-029](../../decisions/ADR-029-pull-request-check.md). Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **652 passed** (35 new in `tests/test_pr_check.py`).
- No browser check: the item has no UI (API, workflow template and settings only).

## Acceptance criteria
Met with scripted agents: no new or regressed findings passes with an empty comment; unchanged findings are not reported again; the budget stops the check with a notice; a catastrophic new finding fails with file, line and a link.
**Unverified:** the recorded run of a catastrophic finding on a real test repository with a real model (no key, no test repository).

## Review
Fresh-subagent security review. No critical findings; no bearer-token bypass found. Important findings and their resolution:
1. The budget stop was swallowed by agents that catch Exception: **fixed** (`BudgetReached` is a BaseException; tests through the validator, judge and linkage).
2. False "new" findings could block merges: **mitigated** (matching also against the baseline snapshot by code quote or same file and similar name; heuristic, recorded as a limit).
3. Silent passes: **fixed** (no baseline and unexamined changed files now appear as notes in the comment; a disabled project stays silent by design).
4. Budget and token scope: **fixed** (a request can only lower the project's budget; tokens can be limited to one repository; at most two checks per project at once). No rate limit across projects; the worker is not cancelled when a client disconnects.
5. Markdown injection from model text: **fixed** (mentions defused, links, HTML and markdown removed, length bounded).
6. The workflow commented "null" on an error: **fixed** (HTTP status checked; no comment without a verdict).
Minor fixed: cancel-in-progress and a job timeout in the template, notes on forks and enforcement. Minor left: the tree's `truncated` flag is ignored; several projects on one repository (first match wins); embeddings are not priced; telemetry rows still written; tokens have no expiry.

## Release notes
- **Migration:** automatic; adds `api_tokens` and `pr_check_config` tables.
- **Rollout:** create a token (`POST /api/tokens`), add `FMEA_URL` and `FMEA_TOKEN` secrets, copy the workflow, scan the default branch once, make the job a required check.
- **Rollback:** revert the merge; remove the workflow.
- **Monitor:** `audit_events` (`pr_check`, `token_created`), failed or budget-reached checks, cost per check.
