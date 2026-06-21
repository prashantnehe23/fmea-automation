# FMEA Platform — Product Backlog

> Last updated: 2026-06-07  
> Single source of truth — `docs/BACKLOG.md`  
> Status: `[x]` Done · `[~]` In progress · `[ ]` Not started

---

## Tier 0 — Shipped ✅

| # | Item | Key files |
|---|---|---|
| [x] | Multi-agent FMEA pipeline (saboteur → actuary → controls → sre → validator → registry → eval) | `workflows/fmea_pipeline.py` |
| [x] | SQLite persistence layer (workspaces, scans, scenarios, eval_history) | `memory/db.py` — ADR-001 |
| [x] | Scenario registry + semantic deduplication (embedding cosine ≥ 0.85) | `memory/scenario_registry.py` — ADR-003 |
| [x] | Deterministic results — locked S/O/D survive rescan; actuary short-circuit for known scores | `agents/actuary.py`, `agents/saboteur.py` |
| [x] | Auto-remediation agent (code diff + pytest stub + before/after RPN + in-memory apply) | `agents/remediator.py`, `core/models.py` |
| [x] | Four-level memory architecture (L1 workspace learning implemented) | `memory/workspace_store.py` — ADR-005 |
| [x] | Eval / LLM-as-judge pipeline | `agents/validator.py`, `agents/evaluator.py` |
| [x] | ADRs 001–008 | `docs/decisions/` |
| [x] | FastAPI API layer with SSE streaming (scan, remediation, github routers) | `api/main.py`, `api/routers/` — ADR-008 |
| [x] | GitHub-first scan flow — README fetched for business context, entire repo scanned | `api/routers/github.py`, `core/github_fetcher.py` |
| [x] | React + Vite + Tailwind frontend — 5 personas, 6 pages, scope-aware views | `frontend/` — ADR-007 |
| [x] | ScanPage 4-scenario state machine (no-selection / no-repo / repo-no-scan / has-scan) | `frontend/src/pages/ScanPage.jsx` |
| [x] | Dynamic workspace hierarchy — create portfolios and projects at runtime, persists on refresh | `frontend/src/App.jsx`, `frontend/src/components/HierarchyTree.jsx` |
| [x] | Scan history persistence — localStorage per project; project switch restores last scan | `frontend/src/App.jsx` |
| [x] | Rich failure scenario UI — attack chain, code evidence, validator confidence, S/O/D rationale, business context card | `frontend/src/pages/ScenariosPage.jsx`, `ScoringPage.jsx`, `MitigationsPage.jsx` |
| [x] | Cache transparency — ⚡/🔬 badge, registry lock badge, new-scenario count | `frontend/src/pages/ScanPage.jsx`, `DashboardPage.jsx` |
| [x] | Mock data removal — all pages use `liveRisks ?? []` with proper empty states | All page components |
| [x] | RemediationPage — mock fallback removed; real API call + proper empty state | `frontend/src/pages/RemediationPage.jsx` |
| [x] | Test suite — 34 tests passing (db, scenario_registry, remediator) | `tests/` |
| [x] | Scenario Lock/Unlock UI — lock badge, 🆕 new badge, Unlock & Rescan button | `ScanPage.jsx`, `ScenariosPage.jsx`, `api.js`, `App.jsx` |
| [x] | Expert Score Adjustment (B-001) — L2 memory loop closed; adjustments persist to DB and override locked S/O/D on rescan | `api/routers/scoring.py`, `memory/db.py`, `memory/scenario_registry.py`, `ScoringPage.jsx` |
| [x] | Workspace Business Tier (B-003) — Business Tier + User Type dropdowns in New Project form; values flow through to saboteur via workspace object | `HierarchyTree.jsx`, `App.jsx`, `ScanPage.jsx` |
| [x] | Multi-File Repository Context (B-005) — File selection right-rail panel; user picks which repo files to scan; backend filters before pipeline | `api/routers/github.py`, `frontend/src/pages/ScanPage.jsx`, `frontend/src/api.js` |
| [x] | Full Hierarchy Persistence (B-007) — portfolios/projects moved to SQLite; API-first with localStorage cache; one-time Option A migration of existing data | `memory/db.py`, `api/routers/workspace.py`, `frontend/src/App.jsx`, `frontend/src/api.js` — ADR-010 |

---

## Tier 1 — P0: Must-have to complete the core loop ✅

### B-001 · Expert Score Adjustment — Close the L2 Memory Loop `[x]` DONE
**Why:** The Scoring page lets a security engineer propose RPN adjustments with justification. Those adjustments are currently local UI state only — never written back to the scenario registry. Without persistence, every rescan ignores human corrections.

**Scope:**
- `POST /api/scoring/adjustment` — persist `{workspace_id, failure_mode, new_s, new_o, new_d, justification}`
- `memory/db.py` — `adjustments` table; `save_adjustment()`, `get_adjustments(workspace_id)`
- `memory/scenario_registry.py` — apply approved adjustments when loading locked scenarios
- React ScoringPage — call the API on "Propose Adjustment"; show "✓ Saved to registry" confirmation

**Acceptance criteria:**
- [x] Adjustment persisted to DB on "Propose Adjustment" click
- [x] On next rescan for the same workspace, the adjusted S/O/D values are used as the locked baseline
- [x] Audit trail visible in ScoringPage shows saved adjustments with date

**ADR:** ADR-005 (Level 2 memory — closes the loop, updated 2026-06-20)

**Shipped:** 2026-06-20 — `api/routers/scoring.py`, `memory/db.py` (adjustments table), `memory/scenario_registry.py` (overlay), `frontend/src/pages/ScoringPage.jsx`, `tests/test_adjustments.py` (7 tests, all passing)

---

## Tier 2 — P1: High value, next sprint

### B-003 · Workspace Business Tier — User Configurable `[x]` DONE
**Why:** `business_tier` and `user_type` are currently hardcoded to `'Tier 1'` and `'external_customers'` in ScanPage. These affect how the saboteur prioritises failure modes. They must come from the project definition.

**Scope:**
- "New Project" form — optional fields: Business Tier (Tier 1 / 2 / 3), User Type (external / internal / partner)
- Project object in localStorage hierarchy stores `businessTier` and `userType`
- `runGithubScan()` reads these from project when building the workspace object sent to the API

**Acceptance criteria:**
- [x] New project form has Business Tier and User Type dropdowns (optional, defaults to Tier 1 / external)
- [x] Selected values are stored with the project and survive page refresh
- [x] Workspace object sent to API reflects these values, not hardcoded strings

**Shipped:** 2026-06-20 — `frontend/src/components/HierarchyTree.jsx` (form dropdowns), `frontend/src/App.jsx` (addProject signature + project object), `frontend/src/pages/ScanPage.jsx` (reads from project, fallback defaults)

---

### B-004 · Scan History Page
**Why:** Users cannot see previous scan runs for a project. There is no RPN trend, no way to compare two scans, and no record of when a risk was first detected.

**Scope:**
- New "History" sidebar tab (project scope only; `step: 'history'`)
- Table: Scan date | Files scanned | Risks | Critical | Avg RPN | ⚡ Cache / 🔬 Fresh | New scenarios
- Click a row to restore that scan's results across all pages
- RPN trend sparkline (avg RPN across scans) using data already stored in `scanHistory` localStorage
- Backend: `GET /api/history/{workspace_id}` → `get_all_scans()` from `memory/db.py`

**Acceptance criteria:**
- [ ] History tab visible in sidebar when a project is selected
- [ ] Table lists all scans for the project with correct metadata
- [ ] Clicking a past scan loads its results on Scenarios / Scoring / Mitigations pages
- [ ] RPN sparkline shows trend over last N scans

---

### B-005 · Multi-File Repository Context (File Selection) `[x]` DONE
**Why:** For large repos, scanning all files produces too much noise and hits LLM token limits. Users need to select the files or directories most relevant to their review.

**Scope:**
- `POST /api/github/preview` already returns file tree — wire it to the UI
- ScanPage: after repo URL is entered, show the file tree; user can select/deselect files
- "Scan Selected Files" button — passes selected paths to `streamGithubScan()`
- Default: top 30 files by extension relevance (current behaviour) with manual override

**Acceptance criteria:**
- [x] File tree appears after clicking "Select files" (preview load)
- [x] User can select/deselect individual files via checkboxes; grouped by directory
- [x] Only selected files are sent to the pipeline (`selected_files` in API request)
- [x] Default selection is pre-populated with code files (`.py`, `.ts`, `.go`, etc.)

**Implementation notes:**
- Right-rail `FilePanel` component renders in ScanPage's own flex layout (`flex h-full`); no App.jsx changes needed
- Quick-select buttons: All / Code / Clear
- "Select files" button appears in `repo-no-scan` and `has-scan` scenarios alongside existing scan buttons
- Backend: `selected_files: list[str] | None` field on `GithubScanRequest`; `None` = scan all (existing behaviour unchanged)
- Preview endpoint now returns all files (removed previous `[:50]` cap)

**Shipped:** 2026-06-21 — `api/routers/github.py` (selected_files filter + full preview), `frontend/src/api.js` (selectedFiles param), `frontend/src/pages/ScanPage.jsx` (FilePanel, loadPreview, flex layout)

---

### ~~B-006 · Eval Drift Detection Dashboard~~ — **Superseded by B-018**
**Why:** The LLM-as-judge eval runs on every scan and results are stored in `eval_history`. There is no UI to show whether model quality is improving, degrading, or drifting. The eval system is currently write-only.

**Scope:**
- React Dashboard page — "Eval Health" panel: sparkline of `overall_score` over last 20 scans
- Red flag if score drops > 0.1 in 3 consecutive scans
- Warning banner on ScanPage if latest eval score < 0.6
- `GET /api/eval/history/{ws_id}` → `get_eval_history()` from `memory/db.py`

**Acceptance criteria:**
- [ ] Eval health sparkline visible on Dashboard for the selected project
- [ ] Banner warning shown on Scan page when quality is degraded
- [ ] API endpoint returns eval history correctly ordered by timestamp

---

### B-018 · Observability — Latency, Quality & System Health `[x]` DONE

**Why:** The platform is currently a black box at runtime. There is no visibility into how long each agent takes, whether scan quality is degrading, which components fail most, or how the SSE stream behaves under load. Without this, every production incident is a guessing game. Observability is the foundation that makes all other improvement loops (B-020, B-021) meaningful.

**Areas to instrument:**

| Signal | What to measure | Why it matters |
|---|---|---|
| **Scan latency** | End-to-end wall time; per-agent duration (saboteur / actuary / controls / SRE / validator / registry / eval) | Identify bottlenecks; detect regressions after prompt or model changes |
| **LLM call latency** | Time-to-first-token, total response time, retries per call | Catch rate-limit degradation; flag models responding slowly |
| **Validator quality score** | `overall_score` per scan (already in `eval_history`); trend over last 20 scans | Detect silent quality drift before it affects users |
| **Cache efficiency** | Cache hit rate per workspace; stale-cache age distribution | Low hit rate → expensive re-scans; very high hit rate → may be stale |
| **Scenario confidence distribution** | p10/p50/p90 of `confidence` across all scenarios in a scan | Shift in distribution signals prompt quality change |
| **Error rate** | Agent exception count; SSE stream drops; scan failure rate | Reliability baseline |
| **API latency** | p50/p95 of FastAPI endpoint response times | UX impact visibility |
| **SSE stream health** | Events-per-second during active scan; client disconnect events | Detect mid-scan dropouts |
| **Registry deduplication rate** | % of new scenarios matched against existing registry (cosine ≥ 0.85) | Very high → stagnant scan; very low → noisy prompt |
| **RPN drift** | Mean RPN per workspace across consecutive scans | Flag unexpected risk score inflation or deflation |

**Scope:**
- `core/telemetry.py` — lightweight structured logger: `record_event(type, payload, scan_id)` writing to `telemetry` table in SQLite
- `memory/db.py` — `telemetry` table: `(id, scan_id, event_type, agent, duration_ms, value, ts)`
- Instrument each agent in `fmea_pipeline.py` with `time.perf_counter()` start/end; log to telemetry on completion
- `api/routers/telemetry.py` — `GET /api/telemetry/{workspace_id}?last_n=20` aggregates: avg latency per agent, quality trend, cache hit rate, error count
- React Dashboard page — new "System Health" panel:
  - Agent latency bar chart (last scan breakdown: saboteur/actuary/SRE/validator)
  - Quality trend sparkline (eval score over last 20 scans — extends B-006)
  - Cache hit rate gauge
  - Error rate indicator (green / amber / red)
  - Scenario confidence distribution (p10/p50/p90)
- Header component — amber warning badge if last eval score < 0.6 or error rate > 10%

**Acceptance criteria:**
- [x] Every scan writes per-agent duration to `telemetry` table
- [x] `GET /api/telemetry/{ws_id}` returns correctly aggregated latency, quality, cache, and error metrics
- [x] Dashboard Health panel shows agent latency breakdown for the last scan
- [x] Quality trend sparkline covers last 20 scans and highlights drops in 3 consecutive scans
- [ ] Header warning badge appears when quality is degraded *(deferred — requires workspaceId in App state)*
- [x] All telemetry writes are non-blocking (failures silently logged, never crash the scan pipeline)

**ADR:** ADR-009

**Note:** This item overlaps with B-006 (Eval Drift Dashboard). B-006 should be folded into B-018 and closed. The `eval_history` data B-006 depended on is already available — this item expands the surface.

---

### B-021 · Cost Per Run Tracking

**Why:** Each scan makes multiple LLM calls across 7 agents. Token usage is currently invisible — there is no way to know the cost of a single scan, which agent spends the most tokens, or how costs change as repositories grow. Without this, cost attribution and budgeting are impossible.

**Scope:**
- Capture `usage` from every LLM response (prompt_tokens, completion_tokens) in each agent
- `core/telemetry.py` — extend `record_event()` to accept `prompt_tokens`, `completion_tokens`, `model`
- Cost calculation: apply per-model $/1M token rates as a config constant (`core/costs.py`)
- `memory/db.py` — `cost_tokens` and `cost_usd` columns on `telemetry` table
- `GET /api/telemetry/{ws_id}` — include `cost_summary`: total USD per scan, breakdown by agent, trend over last N scans
- React Dashboard — "Cost" panel:
  - Cost per scan (last run and 30-day average)
  - Per-agent cost breakdown bar chart (which agent spends most tokens)
  - Cumulative cost trend (USD over last 20 scans)
  - Estimated monthly cost projection at current scan cadence

**Acceptance criteria:**
- [ ] Token usage captured from LLM response objects in every agent (no estimation — use actual usage data)
- [ ] `cost_usd` computed per agent per scan using configurable rate table in `core/costs.py`
- [ ] API returns per-scan cost breakdown with per-agent detail
- [ ] Dashboard shows cost per run, cost trend, and per-agent breakdown
- [ ] Cost data persists to DB and survives server restart

---

### B-007 · Full Hierarchy Persistence in SQLite (Replace localStorage) `[x]` DONE
**Why:** Portfolios and projects are stored in browser localStorage. This means the hierarchy is device-local, lost on clearing storage, and cannot be shared across team members. The DB already has a `workspaces` table; projects and portfolios should be rows, not localStorage keys.

**Scope:**
- `memory/db.py` — `portfolios`, `projects` tables; `create_portfolio`, `list_portfolios`, `delete_portfolio`, `create_project`, `update_project`, `delete_project`
- `api/routers/workspace.py` — 6 new endpoints: `GET/POST /api/portfolios`, `DELETE /api/portfolios/{id}`, `POST /api/portfolios/{id}/projects`, `PATCH /api/projects/{id}`, `DELETE /api/projects/{id}`
- `api/schemas.py` — `PortfolioIn`, `ProjectIn`, `ProjectPatch` models
- `frontend/src/api.js` — `listPortfolios`, `createPortfolio`, `deletePortfolio`, `createProject`, `updateProject`, `deleteProject` + camelCase mappers
- `frontend/src/App.jsx` — bootstrap effect (API-first, localStorage as cache); async `addPortfolio`/`addProject`/`updateProjectRepo`; one-time Option A migration (remap scanHistory keys)
- `tests/test_hierarchy.py` — 6 tests covering all ACs
- `docs/decisions/ADR-010-hierarchy-persistence.md` — new ADR

**Migration strategy (Option A):** On first load after upgrade, if API is empty but localStorage has old hierarchy, sequential POST of each portfolio/project to API, scanHistory rekeyed to new integer IDs, old hierarchy key cleared, selection reset to empty.

**Acceptance criteria:**
- [ ] Creating a portfolio/project writes to SQLite, not just localStorage
- [ ] Hierarchy loads from API on page load (localStorage used only as a cache/fallback)
- [ ] Two browser tabs see the same hierarchy
- [x] All 7 `tests/test_hierarchy.py` tests pass
- [x] Existing test suite (48 tests total) still passes

**ADR:** ADR-010

**Shipped:** 2026-06-21 — `memory/db.py` (portfolios/projects tables + CRUD), `api/schemas.py` (PortfolioIn/ProjectIn/ProjectPatch), `api/routers/workspace.py` (6 new endpoints), `frontend/src/api.js` (6 new functions + camelCase mappers), `frontend/src/App.jsx` (bootstrap effect, async mutations, Option A migration with StrictMode guard), `tests/test_hierarchy.py` (7 tests), `docs/decisions/ADR-010-hierarchy-persistence.md`

---

## Tier 3 — P2: Important, plan for next quarter

### B-008 · Interface-Aware Incremental Scanning (AST Extractor)
**Why:** Scanning large codebases with full LLM pipeline on every rescan is expensive. The AST extractor identifies only functions whose interface or body changed since the last scan. Unchanged functions inherit locked scenarios at zero LLM cost.

**Scope:**
- `core/ast_extractor.py` — `extract_interfaces(code, prev_code) → ChangedSurface`
- `ChangedSurface`: list of changed function names + signatures + call-graph neighbours
- `fmea_pipeline.py` — pass `ChangedSurface` to saboteur; saboteur generates scenarios only for changed functions
- UI indicator: "Incremental scan — {N} functions changed since last scan"

**Acceptance criteria:**
- [ ] `extract_interfaces()` correctly identifies changed functions via AST diff
- [ ] Pipeline skips unchanged functions (locked scenarios reused)
- [ ] LLM call count is proportional to changed functions, not total file size
- [ ] Scan result merges incremental results with locked results from DB

**ADR:** ADR-004 (already written — this is the implementation)  
**Note:** User has deferred this. Confirm priority before starting.

---

### B-009 · Level 3 Memory — Cross-Component Pattern Recognition
**Why:** If `checkout_service.py` and `auth_service.py` both have SQL injection vulnerabilities, the system should proactively flag `payment_service.py` when it is first scanned — even before a vulnerability is found there.

**Scope:**
- `memory/pattern_store.py` — `PatternCluster`: group semantically similar scenarios across components in the same project
- On new scenario registration, check similarity against all scenarios in the same project
- React — "Pattern Alert" badge: "3 other components have a similar SQL injection scenario"

**Acceptance criteria:**
- [ ] Cross-component similarity check runs on every new scenario registration
- [ ] Pattern alert surfaces in Scenarios page when threshold is exceeded
- [ ] No false positives for unrelated vulnerability types

**ADR:** ADR-005 (Level 3 row)

---

### B-019 · Attack Chain Memory — Cross-Scan FMEA Knowledge Base

**Why:** Every scan starts from zero for a new customer or project. Yet many attack chains are structurally similar across systems — SQL injection via an unvalidated API parameter, secrets in environment variables, missing circuit breakers on downstream calls. If the system accumulates memory of confirmed attack chains across all scans, new scans can be seeded with high-confidence prior art — reducing LLM exploration time, increasing first-scan quality, and building a proprietary FMEA dataset that compounds in value over time.

This is different from the existing scenario registry (which deduplicates within a workspace). This is a **cross-workspace, cross-customer knowledge base** of attack chain patterns.

**How it works:**
1. After each validated scan (eval score ≥ 0.7), extract attack chains where `confidence ≥ 0.75`
2. Embed each attack chain using the same embedding model as the scenario registry
3. Store in a shared `attack_chain_library` table (anonymised — no customer name, repo URL, or file paths; only the pattern and its FMEA metadata)
4. When a new scan starts, retrieve the top-K most similar attack chains from the library (cosine similarity)
5. Pass retrieved chains to the saboteur agent as few-shot examples: *"In similar systems, this type of failure was observed..."*

**Scope:**
- `memory/attack_chain_library.py` — `save_chain(chain_embedding, chain_text, rpn, s, o, d, component_type)`, `retrieve_similar(embedding, top_k=5, threshold=0.80)`
- `memory/db.py` — `attack_chain_library` table: `(id, embedding_blob, chain_text, component_type, rpn, s, o, d, scan_count, last_seen_ts, is_anonymised)`
- `workflows/fmea_pipeline.py` — on scan start, retrieve top-5 similar chains and inject into saboteur prompt as few-shot context
- `workflows/fmea_pipeline.py` — on scan completion (eval score ≥ 0.7), save high-confidence chains to library
- Privacy: no PII, file names, repo URLs, or customer identifiers stored in the library — only the attack chain text and FMEA scores
- React Dashboard — "Knowledge Base" card: total attack chains in library, top component types, chains contributed by this workspace

**Acceptance criteria:**
- [ ] `attack_chain_library` table exists with embedding storage and metadata
- [ ] High-confidence chains (confidence ≥ 0.75, eval ≥ 0.7) are persisted after each successful scan
- [ ] New scan retrieves top-5 similar chains and injects them into the saboteur prompt as few-shot context
- [ ] Retrieval adds no more than 200ms to scan startup (pre-embedding lookup)
- [ ] No customer-identifying data stored in the library (privacy test: assert no repo URLs or file paths in stored records)
- [ ] Dashboard shows library size and this workspace's contribution count

**ADR:** Requires new ADR extending ADR-005 (Level 4 memory — cross-workspace knowledge, opt-in for cross-customer sharing)  
**Dependency:** B-018 (observability) recommended first — need quality signal to know which chains are trustworthy enough to save

---

### B-020 · Confidence-Driven Improvement Loop

**Why:** The validator already produces a confidence score and verdict for every scenario. These signals are written to `eval_history` and displayed in the UI — but they are never used to improve the system that generated them. Low-confidence patterns reveal where prompts are under-specified, FMEA rules are ambiguous, or the attack chain is structurally weak. Closing this feedback loop — without touching the current agent setup — turns every scan into a self-improvement signal.

**Design principle:** No agent prompts are changed automatically. The loop **surfaces improvement suggestions** to the engineer, who approves changes before they go live. This preserves trust and determinism.

**How it works:**
1. After each scan, identify scenarios where `confidence < 0.65` or `is_realistic = False`
2. Cluster low-confidence scenarios by failure type and component type
3. Run a lightweight analysis agent: *"Given these low-confidence FMEA scenarios and their validator verdicts, what is the most likely root cause of the low confidence — vague attack chain, uncalibrated RPN, or missing business context?"*
4. Produce a structured `ImprovementSuggestion`: `{agent: 'saboteur', area: 'attack_chain_specificity', suggestion: '...', evidence_scenario_ids: [...]}`
5. Store suggestions in `improvement_suggestions` table (never auto-applied)
6. React: "Quality Insights" panel in Dashboard — list of open suggestions with evidence; engineer can mark as "Applied" or "Dismissed"

**Scope:**
- `agents/improvement_analyst.py` — reads low-confidence scenarios from the last scan; clusters by type; calls LLM with the validator verdicts as input; returns `ImprovementSuggestion[]`
- `memory/db.py` — `improvement_suggestions` table: `(id, scan_id, agent_target, area, suggestion_text, evidence_ids, status, created_ts)`
- `workflows/fmea_pipeline.py` — run `improvement_analyst` as a post-scan step (async, non-blocking — does not delay scan result delivery)
- `api/routers/improvements.py` — `GET /api/improvements/{ws_id}` (open suggestions), `PATCH /api/improvements/{id}` (mark applied / dismissed)
- React Dashboard — "Quality Insights" panel:
  - Count of open suggestions
  - List: agent target + area + suggestion text + scenario evidence count
  - "Applied" / "Dismiss" buttons; applied suggestions show timestamp
- **No agent prompts are modified by this system** — suggestions are advisory only

**What the improvement loop covers:**
| Area | Example suggestion produced |
|---|---|
| Saboteur prompt | "Attack chains for `database` components lack specific exploitation steps — add concrete SQL/ORM examples to the saboteur prompt" |
| Actuary RPN calibration | "Severity scores for `data_loss` scenarios are consistently 2 points above validator expectations — review Severity rubric for data-loss class" |
| SRE fix steps | "Fix steps for `auth` components do not include token rotation — add to SRE prompt checklist" |
| Validator rules | "Validator marks `race_condition` scenarios as unrealistic despite high RPN — clarify realistic threshold in validator rules" |

**Acceptance criteria:**
- [ ] `improvement_analyst` runs after every scan (async, does not block results)
- [ ] Suggestions stored in DB with correct agent target, area, and evidence scenario IDs
- [ ] Dashboard Quality Insights panel lists open suggestions with evidence
- [ ] Engineer can mark suggestions as Applied or Dismissed; status persists
- [ ] No prompt or rule is ever automatically modified — all changes are manual and engineer-approved
- [ ] Suggestions are generated only when at least 2 low-confidence scenarios share a common pattern (avoid noise from single outliers)

**Dependency:** B-018 (observability/telemetry) provides the quality trend data that makes improvement suggestions more targeted

---

### B-010 · Gantt / 90-Day Remediation Roadmap
**Why:** The SRE agent already produces `roadmap_90_day` data per failure mode. A consolidated Gantt view gives executives and risk managers a time-boxed delivery plan from the FMEA output — Day 30 Visibility → Day 60 Controls → Day 90 Automation.

**Scope:**
- `agents/roadmap_agent.py` — aggregate per-scenario roadmap items into a portfolio-level `RoadmapItem` list
- React Dashboard — Gantt chart grouped by phase (Visibility / Controls / Automation)
- Export: "Download Roadmap as CSV"

**Acceptance criteria:**
- [ ] Roadmap agent produces non-overlapping phases from the SRE plans
- [ ] Gantt chart renders correctly for 5–20 failure modes
- [ ] CSV export contains all columns needed for board distribution

---

### B-011 · PDF / DOCX Report Export
**Why:** Stakeholders who don't use the app need a shareable deliverable. A one-click export covering the executive summary, KPI cards, risk table, and mitigation plan covers this without requiring access.

**Scope:**
- "Export Report" button on Dashboard page
- PDF sections: Business Context, KPI summary, Failure Scenarios table, Risk Scoring, Mitigation Plan
- Use skill `pdf` or `docx` for generation

**Acceptance criteria:**
- [ ] Export button triggers download of a formatted PDF/DOCX
- [ ] Document includes all key FMEA outputs for the selected project
- [ ] Readable without access to the app

---

## Tier 4 — P3: Future / strategic

| # | Item | Notes |
|---|---|---|
| [ ] | **B-012 · CI/CD integration** (GitHub Actions / Jenkins) | Block PR merge if new Critical risks introduced. `POST /api/ci/check` returns pass/fail + risk delta. |
| [ ] | **B-013 · Multi-language AST support** (TypeScript, Java, Go) | Extend `core/ast_extractor.py` with Tree-sitter grammars. Detect language from file extension. |
| [ ] | **B-014 · IDE integration** (VS Code extension) | Right-click a function → "Run FMEA on this function". Inline risk annotations as diagnostics. |
| [ ] | **B-015 · Authentication + multi-user support** | OAuth2 + JWT. Per-user workspace ownership. Role-based API access. Hard dependency for cloud/SaaS. |
| [ ] | **B-016 · Slack / Teams alerting** | Webhook POST when new Critical risk registered or eval score drops. Configurable per workspace. |
| [ ] | **B-017 · Level 4 memory — cross-customer anonymised patterns** | Opt-in. Anonymised embedding sharing across opted-in workspaces. Requires privacy review. See ADR-005. |

---

## Assumptions and constraints

- B-001 (Lock UI) is the only item blocking a complete demo of the deterministic-results feature.
- B-007 (hierarchy in SQLite) is a prerequisite for any team or cloud deployment.
- B-015 (authentication) is a hard dependency for any external beta; scope it into the sprint that precedes release.
- B-008 (incremental scanning) is deferred by user decision — do not start without re-confirming.
- B-006 (Eval Drift Dashboard) is superseded by B-018 (Observability) — B-018 covers a superset of B-006 scope. B-006 can be closed once B-018 is implemented.
- B-018 (Observability) is a recommended prerequisite for B-020 (Confidence-Driven Improvement) — improvement suggestions are more targeted with quality trend context.
- B-019 (Attack Chain Memory) requires a new ADR extending ADR-005 before implementation starts. Privacy review required for any cross-customer sharing.
- B-020 (Confidence-Driven Improvement) is advisory only — no agent prompt or rule is ever auto-modified. Engineer approval required for every suggestion.
- All new architectural decisions must produce an ADR in `docs/decisions/` before implementation.
