# ADR-029: Pull-Request Check Invoked from CI

**Status:** Accepted (engineer, 2026-11-21: "CI invoked design for now is okay"); the webhook option stays open for later  **Date:** 2026-11-21  **Backlog:** B-012 (depends on ADR-027 for tokens and ADR-019 for finding identity)

## Context
Risk is only seen when someone opens the app. Teams want it on the pull request, before merge. The backlog assumed a GitHub App delivering webhooks. ADR-026 makes the install single-tenant and self-hosted, often behind a firewall, and ADR-027 chose a repository token first because it needs no inbound connection. The check needs a trigger, a place for the verdict and a way to bound its cost.

## Options
| | A. Invoked from CI (chosen) | B. GitHub App with webhooks | C. The install polls for pull requests |
|---|---|---|---|
| Trigger | A workflow in the customer's repository calls `POST /api/pr-check` | GitHub sends events to the install | A scheduler on the install lists open pull requests |
| Inbound network path | The CI runner must reach the install (a self-hosted runner inside the network works) | GitHub must reach the install | None: outbound only |
| Credentials we store | None for writing; the workflow uses its own `GITHUB_TOKEN`; an API token (hash only) for the call | An App private key and installation tokens with write access | A token with write access to checks or statuses |
| Verdict shown as | The workflow job's status (a required check) and a comment the workflow posts | A native check run | A commit status or check run |
| New moving parts | Token auth, one endpoint, a workflow template | App registration, webhook receiver and signature checks, retries | A scheduler, state per pull request, rate limits |
| Weakness | The customer must add and maintain a workflow; a pull request can edit it unless a required workflow or ruleset enforces it | Cannot serve firewalled installs | Latency, and write credentials stored |

## Decision
Option A first. Benefits: it works with the credentials already built, needs no inbound webhook and stores no GitHub write access. Trade-offs: the install must be reachable from the runner, and enforcement depends on branch protection or a required workflow. Option B can be added later without changing the verdict logic: only the trigger differs.

Details:
1. **API tokens for CI.** An administrator creates a token (optionally limited to one repository); it is shown once and stored as a hash. A token may call `POST /api/pr-check` and nothing else, and needs no cookie or CSRF header.
2. **The scan does not touch the project's record.** `run_fmea(persist=False)` leaves the registry, lifecycle history, scan log, caches, learning memory and eval history as the default branch left them. Telemetry spans are still written (they inflate the project's cost view; to be separated later).
3. **Verdict against the baseline.** The project (found by its repository URL) must have been scanned on its default branch; its registry and last snapshot are the baseline. A head finding is unchanged if its name, code quote or file and similar name match the baseline; otherwise new. A finding marked `fixed` that returns is regressed. The check fails on a new or regressed finding at or above the project's failure severity (default 9, the catastrophic threshold of ADR-020). Without a baseline, or when disabled, it passes and says why.
4. **Quick depth.** One pass over at most 300 KB, files changed by the pull request first, no finding cap.
5. **Budget.** Each project has a USD budget per check (default 1.00, at most 50); a request may lower it, never raise it. Spend is tracked per model call; the call that crosses the limit stops the work (`BudgetReached` is a `BaseException` so agents that fall back on errors cannot swallow it), so the limit is exceeded by at most the one call in flight. The check then passes with a "budget reached" notice. At most two checks per project run at once.
6. **Comment.** Built by the platform from model text made safe: no mentions, links, images, HTML or markdown, bounded length. Findings link to the exact line at the pull request's commit. An empty comment means nothing to say.

## Consequences
- A pull request can steer the model with text in its code (prompt injection); the comment is sanitised and the verdict depends on severities the model assigns, so a determined author could try to lower them. The check is a safety net for honest mistakes, not a gate against a hostile contributor.
- Fork pull requests have no secrets and fail; trusted branches only.
- Findings the baseline does not know that are really renamed old ones can block a merge when severity is 9 or more; the matching reduces but cannot remove this. A live run (2026-11-22, real model) showed a docstring-only pull request failing on such findings, so a finding is reported only when it sits on a line the pull request changed (within 3 lines); findings elsewhere are counted in the summary but not posted. The flip side: a genuinely new weakness of a kind the baseline already has, in the same file, can be treated as the known one and missed.
