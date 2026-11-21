# ADR-026: Deployment Model — Single-Tenant Self-Hosted Container with the Customer's Own Model Key

**Status:** Accepted (engineer, 2026-11-21) with the proposed options: SQLite for v1, `cryptography` for key encryption, 30-day default retention. The licence (point 8) was not chosen; it must be chosen before an image is given to anyone outside the company and does not block implementation  **Date:** 2026-11-21  **Backlog:** B-042 (blocks B-015, B-043)

## Context
There is no way to install the product for a customer: no container, no licence, SQLite as the only store, per-scan counters held in module globals (`core/llm.py`: `_call_count`, `_prompt_tokens`, `_completion_tokens`, reset at the start of each scan in `workflows/fmea_pipeline.py`) so two scans in one process corrupt each other's counts and costs, customer code stored unencrypted (`scan_sources`), provider keys stored unencrypted (`core/settings.json`), and no retention or deletion controls. The deployment model decides how much of that the product must solve itself (discovery report A4, A5, A7). Customer source code is the most sensitive thing the product handles.

## Options
| | A. Single-tenant, self-hosted container, customer's own model key | B. Hosted multi-tenant SaaS | C. Hosted single-tenant per customer, run by us |
|---|---|---|---|
| Where customer code goes | Their environment, then only to the model provider they chose | Our infrastructure as well | Our infrastructure, isolated per customer |
| What we must build first | Image, config, retention, key encryption, per-scan state | All of A, plus tenancy isolation, billing, a DPA and security attestations, on-call | All of A, plus provisioning and operating many installs |
| Fit with the current design | Direct: bring-your-own-key and one SQLite file already exist | Poor: SQLite, global state and open endpoints all have to change | Medium |
| Buyer acceptability (regulated, security teams) | High: code does not reach a new third party | Low until certified (SOC 2 or ISO 27001 report, which does not exist) | Medium |
| Our cost to operate | Low; support burden per install | High | High |
| Revenue path | Fixed-fee pilots, then subscription | Self-serve, later | Premium tier |

## Proposed decision
**Option A first; hosted SaaS later as a separate decision.** Benefits: the discovery report found that it sidesteps most of A5 and A7 and suits the buyers named as first target; it needs the least new code; every later item (B-015 sign-in, B-043 private repositories) is simpler when one install serves one organisation. Trade-offs: we ship upgrades to many installs and cannot see their usage unless they report it; no self-serve trial; SQLite limits concurrency (see 2).

Sub-decisions:

1. **Packaging.** One multi-stage image: build the frontend with Node, then a Python slim image running the API with the built frontend served as static files by the same process (no separate web server). Runs as a non-root user. `docker compose` file with one service and one named volume. Configuration by environment variables only (provider keys, secret key, retention, port).
2. **Database.** Keep SQLite on the mounted volume for the first releases (WAL mode already on, one container replica). Revisit Postgres when a customer needs more than one API replica, or when B-015 shows write contention with several users. All access already goes through `memory/db.py`, which contains the migration. **DECIDE:** accept SQLite for v1 (recommended) or require Postgres from the start (adds a service to every install and a migration framework now).
3. **Secrets at rest.** Provider keys (and later the B-043 repository credential and B-016 tracker tokens) are encrypted with a key supplied in an environment variable (`FMEA_SECRET_KEY`), using authenticated encryption. Keys given only as environment variables are never written to disk. Needs the `cryptography` package, a new dependency. **DECIDE:** accept `cryptography` (recommended: maintained, standard) or rely on volume-level encryption and environment-only keys (no new dependency, but the UI could no longer store a key).
4. **Retention of scanned code.** `scan_sources` is deleted after a configurable number of days, and on request per project. **DECIDE:** default retention (proposed 30 days; 0 would mean "do not keep").
5. **Concurrency.** Per-scan state (call count, tokens, cost) moves from module globals to a per-scan context object (`contextvars`), so two scans run at once with separate counts. Required by B-042 criterion 5.
6. **Health.** `GET /api/health` returns version and database status, no authentication (used by orchestrators).
7. **Telemetry.** Nothing leaves the install. Any usage reporting is a later, opt-in decision.
8. **Licence.** **DECIDE** (legal, not technical): proprietary EULA, source-available, or open-core. Choose before the first image is given to anyone outside the company; a `LICENSE` file is part of B-042. I do not give legal advice; the choice should be reviewed by whoever advises the company.

## Consequences
- B-015 and B-043 can assume one organisation per install, which simplifies workspace membership and credential storage.
- The security statement to prospects can say exactly where code and keys go (model provider chosen by the customer; nothing else).
- Moving to hosted SaaS later needs a new ADR: tenancy isolation, Postgres, billing, certifications. Nothing here blocks it, and nothing here builds it.
- Risk: an install exposed to the internet before B-015 lands has no authentication. The README states this today; the compose file binds to localhost by default until B-015 is done.

## Acceptance mapping (B-042)
ADR accepted (this document); compose up serves the app and runs a scan on a benchmark repository (recorded); keys not readable on disk (test: stored value differs from the plain key and decrypts only with the secret key); retention deletes sources after N days and on request (tests); two concurrent scans keep separate counts (test); `/api/health` reports version and database status (test).

## Alternatives not chosen
Option B now (too much new surface before a first pilot); Option C (operating cost without the self-serve benefit); Kubernetes manifests (a Helm chart can follow when a customer asks; compose is enough for pilots).
