# ADR-021: Scan Scope Transparency, Infrastructure Files and Secret Handling

**Status:** Accepted (approved by engineer 2026-11-09)  **Date:** 2026-10-24  **Backlog:** B-033

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

## Implementation notes (phases 1 and 2, 2026-11-09)
- `core/scan_scope.py` holds the scope rule (`classify_path`), the manifest and the priority/budget logic; `core/github_fetcher.py` classifies the GitHub tree through it (`list_repo`), and the benchmark runner and pasted-code paths use the same `build_scan_input`, so every entry point shares one rule.
- In scope now: Dockerfiles, compose files, Terraform/HCL/Bicep, Makefiles, Jenkinsfiles, `.github/workflows` and `.github/actions`, `.env` files (`.env`, `.env.*`, `*.env`), web templates (`.html`, `.vue`, `.svelte`, `.ejs`, `.j2`, `.cshtml`, `.razor`, `.jsp` and similar), dependency manifests (`pom.xml`, `build.gradle`, `go.mod`, `*.csproj`, `requirements*.txt`, ...). Other `.github/` content, lockfiles, binaries and (by default) tests stay out, each with a stated reason.
- Under the 300 KB budget files are taken in priority order: infrastructure and CI, env files and security-relevant code (auth, session, database, API, config names), other code, templates, config and manifests, documentation. The tree's file sizes are used to choose before downloading, so only the chosen files are fetched. Everything else appears in the manifest as `unexamined` with a reason; the old silent "remaining files skipped" marker is gone.
- Redaction happens inside `build_scan_input`, before any file text leaves it, so the cache, the chat's stored sources and every prompt only ever hold redacted text. `core/secret_scan.py` redacts `.env` values, quoted secret-named assignments, unquoted assignments with a digit in shell/docs/Dockerfile/compose/yaml/ini files, known token formats and PEM private-key blocks; placeholders, environment lookups and prose are left alone. Findings carry names, lines and kinds, never values; key and certificate files are reported by name. Placeholder detection and the digit rule are heuristics and can miss weak secrets without digits (documented limit); there is no entropy check yet.
- Not done yet (phase 3): lockfile parsing into a dependency inventory, persisted per-project include/exclude patterns, and treating unexamined files as `unresolved` ledger cells (needs B-028).
