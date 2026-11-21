# ADR-027: Authentication, Roles, Server-Side Results and Repository Credentials

**Status:** Accepted (engineer, 2026-11-21) with the proposed options: Authlib for OIDC, standard-library scrypt for local passwords, fine-grained token first for repository access (GitHub App when B-012 starts)  **Date:** 2026-11-21  **Backlog:** B-015 (also covers the credential part of B-043)

## Context
Every API route is open, including those that set provider keys and delete scenarios. The "personas" are a dropdown (Developer, Risk Manager, SRE, Security Engineer, Executive). Scan results live in browser `localStorage` (the server keeps `scan_snapshots`, but the UI reads the browser copy), so a teammate sees "No scan data" for a project that has scans. Adjustments record `source` (manual or chat) but not the person. Only public GitHub repositories can be scanned (`core/github_fetcher.py`). ADR-026 proposes one organisation per install, which shapes the choices below.

## Proposed decision
1. **Sign-in.** OpenID Connect single sign-on (authorisation code flow with PKCE) against the customer's identity provider, plus one **local administrator account** created on first start so an install works before SSO is configured and can recover from a broken SSO setup. **DECIDE:** library for the OIDC client: `Authlib` (maintained, handles discovery, JWKS and token validation; a new dependency, recommended) or a small hand-written client on `httpx` (no dependency, but we would own token and signature validation, which is easy to get wrong).
2. **Local password storage.** `hashlib.scrypt` from the standard library, with a per-user salt and constant-time comparison; no new dependency. Alternative: `argon2-cffi` (a stronger default, one more dependency). **DECIDE** if you prefer argon2.
3. **Sessions.** Server-side session records in SQLite referenced by a random identifier in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. Benefits over bearer tokens held by the browser: revocable, nothing readable by page scripts, works with the SSE streams. Trade-off: state in the database. State-changing requests also need a custom header (CSRF defence for a same-origin single-page app).
4. **Roles.** `admin`, `security_engineer`, `risk_manager`, `developer`, `viewer`. Mapping from today's personas: Executive to `viewer`, SRE to `developer`. Rules enforced on the server by a route dependency: settings and keys: admin; score changes and chat proposals applied: security_engineer; scans and fixes: developer and above; reading: every role. Roles come from an identity-provider group claim mapped in configuration, or are set by an admin. The persona switcher is removed outside demo mode (an environment flag).
5. **Every route needs a session** except health and the sign-in endpoints. A test enumerates `app.routes` and fails when a new route lacks the dependency, so the rule cannot silently erode.
6. **Server-side results.** The UI reads scan results and history from the API (`scan_snapshots`); `localStorage` becomes a cache only. A workspace has members; one organisation per install (ADR-026) means workspace membership is a table of user to workspace.
7. **Audit.** Adjustments, chat proposals and key changes record the signed-in user id. Existing rows keep their `source` and get no user.
8. **Migration.** Existing projects, scans and adjustments are attributed to a default workspace owned by the first administrator. Tested on a copy of a real database (B-015 criterion 6).
9. **Repository credential (B-043).** **DECIDE:** (a) a fine-grained personal access token per workspace, read-only on selected repositories, stored encrypted (ADR-026): works for a self-hosted install behind a firewall because nothing needs to reach it from outside; or (b) a GitHub App installation: short-lived tokens and finer permissions, but the pull-request check (B-012) wants webhooks, which a firewalled install cannot receive. Proposed: start with (a), add (b) when B-012 starts. The token is never sent to a model, never logged and never returned by the API after saving.

## Consequences
- Every page and route changes at once, which is why B-048 phase 1 (findings-first interface) is built together with this work.
- The first-run flow gains a step: create the administrator, then optionally configure SSO.
- Without a configured identity provider the install is protected by the local account only; that is stated in the security statement.

## Acceptance mapping (B-015)
All routes return 401 without a session (enumerating test); a developer cannot apply a score change or set a key (tests); a scan from one browser appears in a second browser for another user of the workspace (browser check); adjustments and chat proposals record the user (test); existing data loads after migration (test on a database copy).

## Alternatives not chosen
A hosted identity service as the only option (adds a third party for self-hosted installs); JWTs in `localStorage` (readable by page scripts and not revocable); per-route role checks written by hand without the enumerating test (drifts).
