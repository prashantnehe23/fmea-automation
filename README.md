# FMEA Automation Platform

**A risk register written from your code.** The platform reads a GitHub repository, asks a language model to find realistic failure modes and attack chains, scores each one by business impact (Failure Mode and Effects Analysis, FMEA), and keeps those scores stable, explained and open to human override.

> **Status: working prototype.** The scan engine is the mature part. It is not yet ready to run on a team's private code. See [Known limits](#known-limits) before you try it.

---

## What it does today

1. **Scans a public GitHub repository.** The README is read for business context, and the code files in scope are sent to the model. Test files, vendored code and secrets are excluded or reported by name only. A code index (tree-sitter: Python, Java, C#, TypeScript and JavaScript) gives the chat and the validator call-graph navigation.
2. **Finds failure modes** with an attack chain, code evidence and file and line references (agent `saboteur`).
3. **Scores each one** as Severity × Occurrence × Detection = RPN (agent `actuary`), calibrated to the project's business tier and user type. A catastrophic-severity floor stops high-impact items being ranked low.
4. **Validates the scores** with a second model pass (`validator`) and records evaluation history.
5. **Keeps results deterministic.** Scores are locked per scenario. A rescan returns the same scenarios and scores, and renamed duplicates are caught by embedding similarity.
6. **Accepts expert overrides.** A security engineer can adjust S/O/D with a justification. The adjustment is stored, listed in an audit trail, and used as the baseline on the next scan.
7. **Proposes fixes.** The remediator produces a unified diff and a test stub, applies it in memory, rescans, and shows the before and after RPN. Nothing is written back to the repository.
8. **Answers questions about the results** in a chat panel with read-only code tools. The model's proposed changes are applied only when the user accepts them.
9. **Tracks cost and health.** Cost per scan and per agent, latency, cache hits and evaluation trend.

### Model providers

| Provider | Models in the registry |
|---|---|
| OpenAI | GPT-6 Astra, GPT-5.6 Sol, GPT-5.6 Luna, GPT-5.1, GPT-4o, GPT-4o mini |
| Mistral AI | Mistral Large 4, Mistral Medium, Mistral Small |
| Anthropic | Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku 5.5 (through Anthropic's OpenAI-compatibility endpoint; no built-in price) |
| Azure OpenAI | your own deployment names, on your resource's `/openai/v1/` URL |
| Local endpoint | any OpenAI-compatible server (Ollama, vLLM, LM Studio): your URL, your model names, no key needed |

Pick the model, reasoning level and key in the app's settings panel. `OPENAI_API_KEY`, `MISTRAL_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY` (with `AZURE_OPENAI_ENDPOINT`) and `LOCAL_LLM_BASE_URL` are used as a fallback. The Anthropic, Azure and local connections are checked with fake clients only so far ([ADR-030](docs/decisions/ADR-030-more-model-providers.md)); AWS Bedrock is not supported yet. Adding another provider that speaks the OpenAI chat protocol takes registry entries only ([ADR-011](docs/decisions/ADR-011-multi-provider-llm.md)). Model identifiers and prices are best effort. Check them against the provider's documentation.

---

## Architecture

```
React + Vite + Tailwind frontend (frontend/)
        │  HTTP and server-sent events (the Vite dev server proxies /api to :8000)
FastAPI (api/)  — scan, github, workspace, scoring, remediation, chat, settings, telemetry, eval
        │
Pipeline (workflows/fmea_pipeline.py)
  saboteur → actuary → controls assessor → SRE → validator → registry → evaluator   (agents/)
  remediator (diffs, in-memory apply, rescan)       code index and scope (core/)
        │
SQLite (memory/fmea.db) + JSON caches (memory/)  — created on first run, not committed
```

Decisions are recorded as ADRs in [docs/decisions](docs/decisions/README.md). The index lists each ADR with its status. Several are still Draft.

---

## How to run

Requires Python 3.11+, Node 18+ and a key for one provider.

```bash
pip install -r requirements.txt
uvicorn api.main:app --port 8000      # API on http://localhost:8000 (set FMEA_API_DOCS=1 to serve /docs; off by default because it is not behind sign-in)
```

```bash
cd frontend
npm install
npm run dev                           # app on http://localhost:5173
```

Open the app. The first time, it asks you to create the administrator (or set `FMEA_ADMIN_USER` and `FMEA_ADMIN_PASSWORD` before starting). Then enter your provider key in the settings panel, create a portfolio and project, paste a GitHub repository URL (for a private one, add an access token in Settings first), and run a scan.

The SQLite database (`memory/fmea.db`) and the scan caches are created automatically on first run. They are listed in `.gitignore` and never committed.

Production build of the frontend: `cd frontend && npm run build` (output in `frontend/dist/`).

### Container (single-tenant install, ADR-026)

```bash
python -m core.secrets          # prints a new FMEA_SECRET_KEY; keep it, stored keys cannot be read without it
docker compose up --build       # then open http://localhost:8000
```

Set `FMEA_SECRET_KEY` and `OPENAI_API_KEY` and/or `MISTRAL_API_KEY` in the environment or a `.env` file. All runtime data lives in one volume (`FMEA_DATA_DIR`, `/data` in the container). `FMEA_SOURCE_RETENTION_DAYS` (default 30, `0` keeps no scanned code) controls how long scanned source is stored; findings are kept. `GET /api/health` reports the version and database status. Optional: `FMEA_ADMIN_USER` / `FMEA_ADMIN_PASSWORD` (first administrator), `FMEA_SETUP_TOKEN`, `FMEA_COOKIE_SECURE=0` (plain-http development only), `FMEA_DEMO_MODE=1` (shows the persona switcher), and single sign-on with `FMEA_OIDC_ISSUER`, `FMEA_OIDC_CLIENT_ID`, `FMEA_OIDC_CLIENT_SECRET`, `FMEA_OIDC_REDIRECT_URI`, `FMEA_OIDC_ROLE_MAP` (JSON, group to role), `FMEA_OIDC_GROUPS_CLAIM`, `FMEA_OIDC_DEFAULT_ROLE`. The compose file binds to localhost only. **The container build has not yet been run on a clean machine.**

### Tests

```bash
python -m pytest tests/ -v            # 867 passing on 2026-11-22
cd frontend && npm test               # 23 passing on 2026-11-22 (Vitest, Testing Library, jsdom: ADR-031)
```

`make test`, `make test-ui`, `make build`, `make bench` and `make bench-report` wrap the common commands (see `Makefile`). `make bench` scans the benchmark repositories in `benchmarks/repos/` and **spends real provider credit**. See [ADR-023](docs/decisions/ADR-023-benchmark-methodology.md).

`dashboard.py` is the original Streamlit prototype. The React app is the supported interface.

---

## Scoring

```
RPN = Severity × Occurrence × Detection      (each 1–10, maximum 1000)

Severity    business impact if the failure happens
Occurrence  likelihood that it happens
Detection   how hard it is to notice before harm is done
```

Priority also depends on severity, so a catastrophic item cannot be hidden by a low RPN ([ADR-020](docs/decisions/ADR-020-severity-aware-prioritisation.md)).

---

## Known limits

Read these before a pilot.

- **GitHub only.** Private repositories work with an access token per GitHub owner (administrators add it in Settings; read-only Contents access is enough; the scan role can then scan anything that token reaches). Not verified against a real private repository yet. There is no GitLab or Bitbucket.
- **Sign-in is new and has had one independent review only.** Every API route needs a session (password sign-in, or OpenID Connect single sign-on when configured) and a role: admin, security engineer, risk manager, developer, viewer. The user-management screen does not exist yet (use `GET/POST/PATCH /api/users`). Serve it over HTTPS (the session cookie is `Secure` by default; set `FMEA_COOKIE_SECURE=0` only for plain-http local development on a browser that needs it). Set `FMEA_SETUP_TOKEN` so that only someone holding it can create the first administrator on a new install. All users of an install see all projects; there is no per-project membership.
- **Results come from the server for the latest scan of a project.** The browser keeps a cache; older scan history stays per browser.
- **Keys are encrypted at rest only when `FMEA_SECRET_KEY` is set** (always in the container); otherwise they are plain text in `core/settings.json`. Scanned code is stored in SQLite until the retention period ends, and a copy of each finished scan is kept in the API process's memory until restart.
- **Large repositories take several passes** (up to five by default, 300 KB each, highest-risk files first); files beyond that are listed as not examined. Findings are no longer capped, but remediation plans stop at 30 per scan. The scan page shows a cost estimate before a multi-pass scan. Recall, precision and cost on the benchmark have not been re-measured since this change.
- **The container is untested on a clean machine**, and there is no licence file yet.
- **Not yet measured on real code.** The benchmark is six small repositories with in-house labels. The false-positive rate is unknown.
- **Provider guardrails can block scans.** In testing, about half of Mistral Large 4 scans were refused by the provider. Every prompt now states its defensive purpose and a block is shown plainly with a way to choose another model ([ADR-024](docs/decisions/ADR-024-defensive-framing-and-provider-blocks.md), [provider policies](docs/provider-policies.md)); the block rate after this change has not been measured yet.
- **Pull-request check (new, not yet run against a real repository):** a GitHub Actions workflow (`docs/ci/fmea-pr-check.yml`) asks the install for a verdict on each pull request; it fails on a new or regressed finding at or above the project's severity (default 9), within a USD budget per check. The project must have been scanned once on its default branch. API only for tokens and settings.
- **No ticketing, SARIF or report export.** Fixes are never opened as pull requests.
- **No compliance mapping.** The platform produces code-level evidence. It does not map findings to any compliance framework, and it does not replace a formal risk register or a penetration test.

The prioritised plan, with acceptance criteria for each item, is in [docs/BACKLOG.md](docs/BACKLOG.md). The review behind the current order is in [docs/DISCOVERY-2026-11.md](docs/DISCOVERY-2026-11.md).
