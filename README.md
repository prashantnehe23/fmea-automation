# FMEA Automation Platform

**AI-native, continuous Failure Mode & Effects Analysis for software development teams.**

---

## The Problem

Software teams do risk assessments wrong — or not at all.

Traditional FMEA is a manual, infrequent process: a spreadsheet filled in by a risk manager
once a quarter, based on what engineers remember, not what the code actually does. By the time
the spreadsheet is complete, the codebase has changed. By the time a vulnerability is
exploited, no one remembers why it was rated Low.

The result: teams ship code with known-but-unquantified risks, regulators penalise for
undocumented risk decisions, and post-incident reviews uncover "we knew about this six months ago."

---

## What This Platform Does

This system treats FMEA as a **continuous, code-driven, adversarial process** rather than a
periodic documentation exercise.

Given a Python codebase (a function, a service, a repository), it:

1. **Simulates failure** — an adversarial AI agent (`saboteur`) generates realistic attack
   chains: concurrency bugs, malicious inputs, secrets exposure, control bypass, partial outages.
   Not generic CVEs — specific failure modes derived from reading the actual code.

2. **Scores business impact** — an actuarial agent converts each failure mode into an RPN
   (Risk Priority Number) using `Severity × Occurrence × Detection`, calibrated to the
   business context (customer-facing tier, compliance regime, user type).

3. **Validates the scores** — an LLM-as-judge validator checks whether the scores are
   reasonable, consistent, and reflect the stated controls. Human security engineers can
   propose score adjustments with justifications that go to an immutable audit trail.

4. **Locks results for determinism** — the first scan's failure modes and scores are stored in
   a scenario registry. Every subsequent scan of the same code returns the same scenarios and
   RPNs. If the LLM tries to rename a scenario, semantic deduplication (cosine similarity on
   embeddings) catches the rename and restores the canonical name and score.

5. **Generates code fixes** — an auto-remediation agent produces exact unified code diffs,
   pytest test stubs, and plain-English explanations. It applies the fix in memory, rescans
   the patched code, and shows before/after RPN deltas.

6. **Shows risk across the organisation** — a five-persona, six-step React UI presents the
   right view to the right person: executives see portfolio-level KPIs and board escalation
   flags; developers see their fix queue; security engineers adjust scores; risk managers track
   the remediation pipeline.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  React Frontend  (Vite + Tailwind)  ·  frontend/                    │
│  5 personas · 6 FMEA steps · scope-aware (Org/Portfolio/Project/    │
│  Component) · client-side state machine                             │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  HTTP / SSE  (planned — ADR-008)
┌───────────────────────────▼─────────────────────────────────────────┐
│  FastAPI  (planned)  ·  api/                                        │
│  POST /api/scan  ·  POST /api/remediate  ·  GET /api/workspace/…   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  Python function call
┌───────────────────────────▼─────────────────────────────────────────┐
│  Pipeline Orchestrator  ·  workflows/fmea_pipeline.py               │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Saboteur    │  │  Actuary     │  │  Validator (LLM-judge)   │  │
│  │  generates   │→ │  scores      │→ │  checks consistency      │  │
│  │  attack      │  │  S×O×D = RPN │  │  human override allowed  │  │
│  │  chains      │  │  (locked     │  │  locked scenarios exempt │  │
│  │  (locked     │  │  short-      │  │                          │  │
│  │  names first)│  │  circuits)   │  │                          │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐    │
│  │  SRE Agent               │  │  Remediator                  │    │
│  │  generates remediation   │  │  generates code diffs        │    │
│  │  plans (90-day roadmap)  │  │  applies in-memory, rescans  │    │
│  └──────────────────────────┘  └──────────────────────────────┘    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│  Memory Layer                                                       │
│                                                                     │
│  memory/db.py          — SQLite  (memory/fmea.db)                  │
│    workspaces · scans · scenarios (+ embeddings) · eval_history    │
│                                                                     │
│  memory/scenario_registry.py  — semantic deduplication             │
│    text-embedding-3-small · cosine sim ≥ 0.85 → same scenario     │
│                                                                     │
│  memory/workspace_store.py    — file-based result cache (L1)       │
│    SHA256 fingerprint → JSON cache · learning memory update        │
└─────────────────────────────────────────────────────────────────────┘
```

### Key data flows

**First scan of a codebase**
```
code → saboteur → [new failure modes] → actuary → [RPN scores]
     → validator → [adjusted scores] → register_new_scenarios()
     → save_scan() → React UI (via API)
```

**Subsequent scan of the same code**
```
code → fingerprint matches cache? → return cached result (0 LLM calls)
     if force_rerun:
       → saboteur (locked_names constraint → LLM reproduces exact names)
       → actuary (exact-name match → 0 LLM calls for locked scenarios)
       → validator (locked scenarios exempt from adjustment)
       → semantic dedup (catches any LLM renames)
       → results identical to first scan
```

**Auto-remediation**
```
risks sorted by RPN desc → for each:
  generate_fix() → {code_diff, test_code, patched_snippet}
  apply patch in memory → cumulative patched_code
rescan(patched_code) → before/after RPN delta per scenario
```

---

## Project Structure

```
fmea-automation/
│
├── agents/                  # AI agents
│   ├── saboteur.py          # adversarial failure mode generation
│   ├── actuary.py           # RPN scoring (S × O × D)
│   ├── validator.py         # LLM-as-judge quality check
│   ├── sre_agent.py         # remediation plan generation
│   └── remediator.py        # code diff + auto-apply + rescan
│
├── core/                    # shared models and utilities
│   ├── models.py            # FailureMode, RiskScore, RemediationPlan, RemediationResult
│   └── ast_extractor.py     # (planned) interface-aware change detection
│
├── workflows/
│   └── fmea_pipeline.py     # full pipeline orchestrator
│
├── memory/                  # persistence and memory
│   ├── db.py                # SQLite CRUD (fmea.db)
│   ├── scenario_registry.py # embedding-based semantic deduplication
│   └── workspace_store.py   # file-based result cache + learning memory
│
├── api/                     # (planned) FastAPI layer — see ADR-008
│
├── frontend/                # React + Vite + Tailwind UI
│   ├── src/
│   │   ├── data.js          # mock constants (to be replaced by API calls)
│   │   ├── helpers.js       # filterRisks, aggregateBy, colour maps
│   │   ├── App.jsx          # persona/scope/step state machine
│   │   ├── components/      # Sidebar, Header, HierarchyTree, RiskTable, …
│   │   └── pages/           # ScanPage, ScenariosPage, ScoringPage, …
│   └── dist/                # production build output
│
├── tests/
│   ├── test_db.py           # 11 tests — SQLite CRUD
│   ├── test_scenario_registry.py  # 14 tests — dedup + actuary short-circuit
│   └── test_remediator.py   # 9 tests — patch apply + fix generation
│
├── docs/
│   ├── BACKLOG.md           # prioritised product backlog
│   └── decisions/           # Architecture Decision Records (ADR-001 – ADR-008)
│
├── dashboard.py             # 7-page Streamlit operator dashboard
└── requirements.txt
```

---

## The Five Personas

| Persona | Default scope | Primary steps | What they do |
|---|---|---|---|
| **Risk Manager** | Project | Scenarios, Scoring, Dashboard | Reviews and signs off on risk posture |
| **Security Engineer** | Component | Scoring, Mitigations | Adjusts RPN scores; owns the fix queue |
| **Developer / SRE** | Component | Mitigations, Remediation | Applies fixes; marks items done |
| **Executive** | Organisation | Dashboard | Board-level KPIs and escalation flags |
| **Platform Engineer** | Portfolio | Scan, Dashboard | Runs analyses; manages workspace config |

---

## The Six FMEA Steps

```
1. Scan          — submit code, configure workspace, trigger analysis
2. Scenarios     — review AI-generated failure modes and attack chains
3. Scoring       — inspect / adjust RPN scores (S × O × D)
4. Mitigations   — assign owners, track fix status (Open → In Progress → Mitigated)
5. Remediation   — AI-generated code diffs with before/after RPN validation
6. Dashboard     — portfolio KPIs, top risks, remediation progress, eval health
```

---

## RPN Scoring

```
RPN = Severity × Occurrence × Detection    (each 1–10, max 1000)

Severity  — business impact if exploited (data breach, outage, regulatory fine)
Occurrence — likelihood of exploitation (known CVE, exposed endpoint, weak auth)
Detection — how hard to catch before harm (no monitoring, no tests, no alerting)

Critical  RPN ≥ 300   → board escalation required
High      RPN 200–299 → sprint-priority fix
Medium    RPN 100–199 → backlog with owner
Low       RPN < 100   → accepted risk / monitor
```

---

## How to Run

### Python pipeline + Streamlit dashboard

```bash
# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key
export OPENAI_API_KEY=sk-...

# Run the Streamlit operator dashboard
streamlit run dashboard.py
```

The SQLite database is created automatically at `memory/fmea.db` on first run.

### React frontend (development)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

The frontend currently uses mock data from `src/data.js`.  
Full API connectivity requires the FastAPI layer (see [B-001 in BACKLOG](docs/BACKLOG.md)).

### React frontend (production build)

```bash
cd frontend
npm run build
# → frontend/dist/  (serve with any static host)
```

### Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Individual suites
python -m pytest tests/test_db.py -v
python -m pytest tests/test_scenario_registry.py -v
python -m pytest tests/test_remediator.py -v
```

---

## Architecture Decisions

All significant decisions are recorded as ADRs in [`docs/decisions/`](docs/decisions/).

| ADR | Decision | Outcome |
|---|---|---|
| [001](docs/decisions/ADR-001-persistence-layer.md) | SQLite over PostgreSQL/DuckDB | Zero-dependency persistence |
| [002](docs/decisions/ADR-002-workspace-hierarchy.md) | Org → Portfolio → Project → Component hierarchy | Scope-aware risk aggregation |
| [003](docs/decisions/ADR-003-semantic-deduplication.md) | Embedding-based scenario identity | Deterministic results across rescans |
| [004](docs/decisions/ADR-004-incremental-scanning.md) | Interface-aware incremental scanning | Cost-efficient rescans (planned) |
| [005](docs/decisions/ADR-005-memory-architecture.md) | Four-level compounding intelligence | Long-term calibration and pattern learning |
| [006](docs/decisions/ADR-006-architecture-graph.md) | Code-derived dependency graph | Context-aware cross-component risk |
| [007](docs/decisions/ADR-007-react-frontend.md) | React + Vite over Streamlit extension | Full layout control; multi-persona UX |
| [008](docs/decisions/ADR-008-fastapi-layer.md) | FastAPI as the API bridge | Pydantic → OpenAPI; SSE for pipeline progress |

---

## What's Next

The highest-priority item is **[B-001: FastAPI API layer](docs/BACKLOG.md)** — connecting the
React frontend to the Python pipeline so users see live results instead of mock data.

See the full prioritised backlog: [`docs/BACKLOG.md`](docs/BACKLOG.md)

---

## Compliance context

The scoring model is aligned to common regulatory frameworks:

- **GDPR / UK GDPR** — severity scores account for personal data exposure and notification
  obligations (Article 33/34)
- **PCI-DSS** — payment component risks are flagged with card data scope markers
- **SOC 2** — detection scores reflect monitoring and alerting maturity
- **ISO 27001** — remediation plans map to Annex A controls

The platform does not replace a formal risk register or penetration test. It augments them by
providing continuous, code-level evidence that can feed into those processes.
