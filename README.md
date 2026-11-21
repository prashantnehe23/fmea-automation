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

Pick the model, reasoning level and key in the app's settings panel. `OPENAI_API_KEY` and `MISTRAL_API_KEY` are used as a fallback. Adding another provider that speaks the OpenAI chat protocol takes registry entries only ([ADR-011](docs/decisions/ADR-011-multi-provider-llm.md)). Model identifiers and prices are best effort. Check them against the provider's documentation.

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
uvicorn api.main:app --port 8000      # API on http://localhost:8000, docs at /docs
```

```bash
cd frontend
npm install
npm run dev                           # app on http://localhost:5173
```

Open the app, enter your provider key in the settings panel, create a portfolio and project, paste a public GitHub repository URL, and run a scan.

The SQLite database (`memory/fmea.db`) and the scan caches are created automatically on first run. They are listed in `.gitignore` and never committed.

Production build of the frontend: `cd frontend && npm run build` (output in `frontend/dist/`).

### Tests

```bash
python -m pytest tests/ -v            # 439 passing on 2026-11-21
```

`make test`, `make build`, `make bench` and `make bench-report` wrap the common commands (see `Makefile`). `make bench` scans the benchmark repositories in `benchmarks/repos/` and **spends real provider credit**. See [ADR-023](docs/decisions/ADR-023-benchmark-methodology.md).

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

- **Public GitHub repositories only.** There is no private-repository access, GitLab or Bitbucket.
- **No sign-in or access control.** Every API route is open, including the one that sets provider keys. The five "personas" in the UI are a role-play switch, not security roles. Do not expose the API to a network you do not control.
- **Results are held in the browser.** A second browser or user does not see a project's scan results.
- **Keys and scanned code are stored unencrypted** on the machine that runs the API (`core/settings.json`, SQLite).
- **At most seven findings per scan**, and repositories above about 300 KB of code are sampled rather than read in full.
- **No deployment package.** There is no container image, and scans run one at a time per process.
- **Not yet measured on real code.** The benchmark is six small repositories with in-house labels. The false-positive rate is unknown.
- **Provider guardrails can block scans.** In testing, about half of Mistral Large 4 scans were refused by the provider ([ADR-024](docs/decisions/ADR-024-defensive-framing-and-provider-blocks.md), Draft).
- **No pull-request check, ticketing, SARIF or report export.** Fixes are never opened as pull requests.
- **No compliance mapping.** The platform produces code-level evidence. It does not map findings to any compliance framework, and it does not replace a formal risk register or a penetration test.

The prioritised plan, with acceptance criteria for each item, is in [docs/BACKLOG.md](docs/BACKLOG.md). The review behind the current order is in [docs/DISCOVERY-2026-11.md](docs/DISCOVERY-2026-11.md).
