# ADR-021: Scan Scope Transparency, Infrastructure Files and Secret Handling

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-10-24  **Backlog:** B-033

## Context
`core/github_fetcher.py` decides what the agents can see, silently:
- **Extension allowlist.** Only code, config and doc extensions are fetched. `Dockerfile`, `.env` (the suffix of a dotfile is empty), Terraform (`.tf`, `.hcl`), `Makefile` and web templates (`.html`, `.vue`, `.svelte`, `.ejs`, `.j2`) are never fetched, although infrastructure, CI and templates are where many catastrophic scenarios live (public bucket, privileged container, injected CI step, template XSS).
- **Noise directories.** `.github/` (CI workflows), lockfiles and, by default, tests are skipped.
- **Size cap.** Beyond 300 KB of concatenated text the remaining files are dropped, with only a marker inside the code text; the user is not told.

The coverage ledger of ADR-015 can only cover what was fetched, so these exclusions are invisible holes under any "nothing missed" claim. Secret-bearing files such as `.env` carry real credentials, which must not be sent to a model provider.

## Decision
1. **A scope manifest for every scan**: each repository path is recorded as included or excluded with a reason (extension, noise directory, test file, size budget, user rule), stored with the snapshot and shown to the user ("N files examined, M not examined"). Files that are in scope but cannot be examined (size budget) are `unexamined`, and become `unresolved` cells in the coverage ledger.
2. **Widen the scope** to infrastructure and delivery files: Dockerfiles, compose files, Terraform and other IaC, Makefiles, `.github/workflows`, Kubernetes/Helm manifests, web templates, and dependency manifests. Lockfiles are parsed into a **dependency inventory** (names and versions) rather than dumped as text.
3. **No silent truncation.** When the budget is exceeded, files are prioritised (entry points, auth, data access, infrastructure first) and the remainder is listed as unexamined; agents read files through the code tools (ADR-014/ADR-015) instead of one concatenated blob.
4. **Secrets never reach a model.** Values in `.env`-style files and recognised credential patterns are redacted before any file text is sent to a provider; the key names stay. A committed secrets file is reported by a **deterministic check** (pattern and entropy), independent of model behaviour, and is a hypothesis source for the hunters.
5. **User control**: include/exclude patterns per project, persisted, with the file-selection panel (B-005) as the interface.

## Alternatives considered
- Keep the allowlist and only document it: honest, but leaves catastrophic classes unreachable.
- Send everything: maximum coverage, but sends secrets to a third party and blows the budget.
- Rely on the model to ignore secrets: not a control.

## Consequences
- Scans see more files, so cost and time rise somewhat; the budget and prioritisation keep this bounded.
- Redaction can hide a problem that depends on a secret's value (e.g. a weak password); the deterministic checks cover the common cases.
- The scope manifest becomes part of the evidence for any "not found" claim.
