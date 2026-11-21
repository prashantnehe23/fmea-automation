# B-015 report

Design: [ADR-027](../../decisions/ADR-027-authentication-roles-and-repository-access.md). Plan: [plan.md](plan.md). Date: 2026-11-21.

## Verification evidence
- `python -m pytest tests -q`: **536 passed** (47 new in `tests/test_auth.py` and `tests/test_oidc.py`).
- `npm run build`: built.
- Browser, on a copy of the real database in a temp data directory: first-run setup through the UI, sign-in persisted across a reload (cookie is `Secure` by default and works on http://localhost), existing portfolios and projects loaded; with the browser cache cleared the project showed a stored scan from the server; a second user (viewer) read the same scan over the API and got 403 on creating a portfolio.

## Acceptance criteria
All six met; see the B-015 entry in `docs/BACKLOG.md` for the evidence and the two caveats (the browser check used an inserted demo scan; migration was tested on a hand-built old schema plus a manual run on a copy of the real database).

## Review
Security review by me plus a fresh-subagent review. No critical findings. Important findings and their resolution:
1. Throttle bypass by padding or case: **fixed** (normalise once; counted per client and username; bounded table).
2. Setup takeover and SSO users closing setup: **fixed** (no active admin; optional `FMEA_SETUP_TOKEN`).
3. OIDC callback not bound to the browser: **fixed** (state cookie).
4. API docs and schema reachable without sign-in: **fixed** (off unless `FMEA_API_DOCS=1`; test that no route exists outside the policy).
5. State-changing GET (`pricing/refresh`): **fixed** (POST).
6. Cookie not `Secure` behind a TLS proxy: **fixed** (Secure by default, `FMEA_COOKIE_SECURE=0` to relax).
7. Lockout abuse and table growth: **fixed** (per client, bounded).
8. Audit stores names not ids and missed key changes: key, model, reasoning, user changes and sign-ins now audited; names kept, recorded in the ADR amendment.
9. SSO roles overwritten and password patched onto SSO users: **fixed** (identity provider is authoritative).
10. Criteria evidence and ADR deviations: browser check done; deviations recorded in the ADR amendment and backlog.
11. Cache kept after session expiry: **fixed**.
Minor fixed: unknown role gave a 500; SSO-only timing difference; leaked connection; issuer mismatch and non-https issuer refused; sign-in error removed from the address bar. Minor left: `aud` list and `azp` not checked, JWKS not cached, authorisation code in access logs, no idle timeout, no 403 message in the UI, naive local timestamps.

## Release notes
- **Migration:** automatic; adds `users`, `sessions`, `oidc_logins`, `audit_events` and two attribution columns. Existing rows keep a null user.
- **Rollout:** first start shows the setup page (or set `FMEA_ADMIN_USER` and `FMEA_ADMIN_PASSWORD`; set `FMEA_SETUP_TOKEN` on any reachable install). Existing browsers must sign in. The container compose file passes the new variables.
- **Behaviour changes:** every API call needs a session; `/docs` is off by default; `pricing/refresh` is POST; the persona switcher needs `FMEA_DEMO_MODE=1`.
- **Rollback:** revert the merge; new tables and columns are ignored by older code.
- **Monitor:** failed sign-ins (401/429), `audit_events`.
