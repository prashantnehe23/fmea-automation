# Discovery: direction, gaps, recommendations and go-to-market

> Date: 2026-11-17 · Scope: `README.md`, `docs/BACKLOG.md`, ADR-001..025, the Python and React code on `feature/b036-code-index-phase2`, the running app (empty states only, see "What was not checked"), and a short market scan.
> Nothing here is implemented or prioritised. Proposed backlog items at the end need the engineer's decision.

## 1. Answer in brief

**The scan engine is being built with unusual discipline, but nothing that makes the product purchasable has been started.** Almost all effort since October has gone into scan quality (benchmark, severity guardrails, scope, code index). Authentication, private-repository access, CI and ticketing integration, exports, deployment and a legal basis for handling customer code are either P3 or absent from the backlog. An engineering or security team cannot use this on its own code today, however good the findings are.

**Detection alone is a weak place to compete.** Since February 2026 the model vendors and the incumbents have shipped LLM-based code security (see section 5). The parts of this product that they do not have are the risk-register layer: business-calibrated scoring, the catastrophic floor, locked and auditable scores, expert adjustment with an audit trail, coverage and residual risk stated honestly, and corrective-plus-preventive action. That is what should be sold.

Confidence: high on the gaps (read from code and backlog); medium on market positioning (sources are mostly vendor-written).

## 2. Where the product is heading

| Stage | State |
|---|---|
| Demo pipeline: one LLM pass, 7 findings, RPN scores, Streamlit | Shipped (May-June) |
| React UI, API, hierarchy, cost and telemetry, multi-provider, chat with proposals | Shipped (June-October) |
| Scan-effectiveness programme: benchmark, severity floor, scope and secrets, line numbers, code index | In progress (B-026, B-034, B-033, B-036) |
| Goal-based discovery: inventory, hunters, verifier, coverage ledger, no cap (B-028, B-035, B-031) | Proposed, large, not started |
| Preventive remediation and root-cause classes (B-029, B-030) | Proposed, not started |
| Cross-component and cross-customer memory (B-009, B-017, B-019) | Later |
| Auth, CI gate, alerting, IDE (B-012..B-016) | P3 "strategic" |

Measured progress on the internal benchmark (Mistral Medium, 3 runs per repository): recall 0.92 to 0.96, catastrophic recall 0.89 to 1.00, evidence validity 0.55 to 1.00, line accuracy 0.26 to 0.92. Precision is 0.39 and cannot be read as a false-positive rate while every scan returns exactly 7 findings.

The trajectory is toward a verified, coverage-tracked discovery engine. The stated company goal has three parts: understand risk, remediate it, prevent it long term. The first is well advanced, the second is partial (patches exist only in memory), the third is unbuilt.

## 3. Gaps

Severity: **Blocker** = no paying customer without it · **Major** = loses evaluations · **Minor** = polish.

### A. Cannot be bought or deployed

| # | Gap | Evidence | Sev |
|---|---|---|---|
| A1 | No authentication, tenancy or roles. Every endpoint is open, including the ones that set API keys and delete scenarios. Personas are a dropdown. | `api/main.py`, `api/routers/settings.py`; B-015 is P3 | Blocker |
| A2 | Public GitHub repositories only. No token, GitHub App, GitLab, Bitbucket or Azure DevOps. Customers' code is private. Not in the backlog. | `core/github_fetcher.py:2` | Blocker |
| A3 | Scan results live in the browser. A fresh browser shows "No scan data" for a project with scans in the database, so a team cannot share a result. | `KEY_HISTORY` in `frontend/src/App.jsx`; observed in the app | Blocker |
| A4 | No deployment story: no Dockerfile, no CI for this repository, no licence, SQLite, and global LLM call counters that force one scan at a time per process. | repo root; B-026 phase 3 notes | Blocker |
| A5 | Customer code and provider keys are stored unencrypted (`scan_sources` in SQLite, keys in `core/settings.json`). No retention or deletion controls. | `memory/db.py`, `core/settings.py` | Blocker |
| A6 | `memory/fmea.db` and `memory/workspaces/**` are committed to git, including scan output for third-party repositories. | `git ls-files memory/` | Major |
| A7 | No terms, data-processing agreement, or confirmation that the user is authorised to assess the repository. | B-040 open question 1, deferred | Major |

### B. Does not fit how security and engineering teams work

| # | Gap | Evidence | Sev |
|---|---|---|---|
| B1 | No pull-request or CI gate. Risk is only seen when someone opens the app. | B-012 is P3 | Blocker |
| B2 | Fixes never leave the app: patches are applied in memory, no pull request is opened, and mitigation status appears to be page state only. | `agents/remediator.py`, `MitigationsPage.jsx:216` | Major |
| B3 | No Jira, Linear, Slack or Teams. Findings need to land where work is tracked. | B-016 is P3 | Major |
| B4 | No standard vocabulary: no CWE, OWASP, CVSS or SARIF anywhere in the code. Security teams and auditors cannot map findings to what they already report. | grep over `agents/`, `core/`, `api/` | Major |
| B5 | No export. A risk manager cannot hand a report to an auditor or a board. | B-011 is P2 | Major |
| B6 | No scan history, trend or "what changed since last scan". | B-004, B-031 | Major |
| B7 | README claims alignment with GDPR, PCI-DSS, SOC 2 and ISO 27001 Annex A. No code implements any mapping. Do not repeat this claim in sales material until it is true. | grep found none | Major |

### C. Scan engine credibility

| # | Gap | Evidence | Sev |
|---|---|---|---|
| C1 | Seven-finding cap and a single pass. With seven locked findings a new vulnerability has no room. | `DEFAULT_MAX_FAILURE_MODES`; B-031 | Blocker for real repositories |
| C2 | Repositories above about 300 KB are sampled. Real services are far larger; the answer (B-028) is the largest unstarted item. | `core/scan_scope.py`; B-033 | Blocker for real repositories |
| C3 | The benchmark is 6 small repositories and 17 labelled items written in-house. A buyer will not accept it as proof. There is no comparison with Semgrep, CodeQL or the model vendors' scanners, and no run on real code with known CVEs. | `benchmarks/repos/` | Major |
| C4 | False-positive rate is unknown. It is the first question every AppSec lead asks. | B-026 baseline notes | Major |
| C5 | Half of the Mistral Large 4 scans were blocked by the provider's guardrail. | B-026; B-040 is P2 | Major |
| C6 | Only OpenAI and Mistral. Enterprises commonly require Azure OpenAI, AWS Bedrock, Anthropic or a self-hosted model. | `core/providers.py` | Major |
| C7 | Index covers Python, Java, C# and TypeScript. No Go, C or C++, PHP, Ruby or Kotlin. | `requirements.txt` | Minor now |
| C8 | No dependency (SCA) view; lockfile inventory is unbuilt. Not worth building; import it (see R4). | B-033 phase 3 | Minor |

### D. Prevention, the third part of the goal

| # | Gap | Evidence | Sev |
|---|---|---|---|
| D1 | Preventive actions and root-cause classes are proposed only. Today's output is a 30/60/90 plan that the backlog itself wants to retire. | B-029, B-030 | Major |
| D2 | No organisational learning: recurring root causes across projects, guardrails, or policy that follows from findings. | B-009, B-019 | Major |

### E. Documentation and hygiene

| # | Gap | Sev |
|---|---|---|
| E1 | README is months stale: says the API is planned, OpenAI only, Python only, 34 tests, ADRs 001-008, mock data. A prospect or investor reading it sees a prototype. | Major |
| E2 | Thirteen of 25 ADRs are Draft while work proceeds on some of them. `SKILSS.md` duplicates `CLAUDE.md`. Two test files are known flaky. | Minor |

## 4. UI/UX review

**What was checked:** the running app in the browser (navigation, personas, empty states, settings) and the page source. **Not checked:** result pages with live data, because the database holds no stored result and I did not spend API credit on a scan. A second pass with one scanned project is recommended.

| # | Finding | Recommendation |
|---|---|---|
| U1 | The default persona (Developer) cannot select a project. The click does nothing, and the empty state tells the user to select a project. First-time users are stuck on screen one. | Any role can open a project. Roles restrict actions, not navigation. |
| U2 | Personas are a role-play switch. Buyers will read it as a mock-up. | Replace with real roles from sign-in (A1). Keep a demo switch only in demo mode. |
| U3 | One finding is spread over four pages (Scenarios, Scoring, Mitigations, Remediation) inside a six-step wizard. Real use is triage, not a linear process. | Findings-first layout: **Overview · Findings · Coverage · Reports · Settings**. One finding detail view with tabs for evidence, score, fix and history. |
| U4 | The dashboard mixes buyer metrics with internal ones (LLM cost, agent latency, eval health). | Move cost and system health to an admin page. The dashboard answers three questions: what could hurt us most, is it getting better, what is unexamined. |
| U5 | RPN and S/O/D are unfamiliar to security teams; "FMEA" is manufacturing vocabulary. | Lead with a plain-language impact sentence and the priority band. Show CWE and the catastrophic flag beside RPN. Keep S/O/D as the explanation. |
| U6 | Emoji are used as icons on every page. They render differently per platform and look informal for a security product. | One icon set (for example Lucide), one size, one stroke weight. |
| U7 | No `aria-*` or `role` attributes anywhere in the front end; rows are clickable `div`s; several labels are light grey on light blue. | Buttons and links for interactive elements, labels on icon buttons, contrast of 4.5:1. Enterprise and public-sector buyers ask for an accessibility statement. |
| U8 | Hard-coded "Acme Financial Services" and `demo@fmea.io`; a notification bell that says "coming soon"; a KPI card that promises "Within 7 days". | Remove placeholders and unbuilt controls. Take SLAs from configuration or omit them. |
| U9 | The scope header shows "COMPONENT" and a dash when a project is selected. | Default the view level to what is selected; never render an empty title. |
| U10 | "Clear local data" sits in the same small panel as configuration. | Move destructive actions behind a confirmation in a separate section. |
| U11 | Time to first value is long: create portfolio, create project, enter key, choose files, scan. | One field on first run: paste a repository URL. Create the hierarchy behind it. Show an estimate of cost and time before starting. |
| U12 | Coverage ("N files examined, M not") is built but buried in the scan page. It is a differentiator. | Give it its own page and a line on the overview. |

**Second pass, 2026-11-17 (scan attempt).** A scan of the `shop-api` benchmark code failed at once with `401 Your API key expired on 2026-11-17` from Mistral, so result pages are still unreviewed. The attempt itself showed:

| # | Finding | Recommendation |
|---|---|---|
| U13 | The failure is shown as the raw provider error (`Error code: 401 - {'detail': ...}`), below the fold, with no next step. | Plain message ("Your Mistral key has expired"), shown where the user is looking, with a button that opens the key setting. |
| U14 | Settings reports "API Endpoint: Connected" while the model key is unusable. The scan button is enabled. | Validate the key when it is saved and before a scan; show key status in Settings and beside the scan button. |
| U15 | The persona resets to Developer on reload while the project selection persists. | Persist the role with the session (resolved by real sign-in, R2). |
| U16 | The inline new-project form is clipped by the workspace tree's scroll area in a normal-height window. | Open it in a dialog or let the tree grow. |

## 5. Market context

Sources are mostly vendor-written; treat rankings as marketing.

- **LLM-based detection became common in 2026.** Vendors describing themselves as AI-native SAST include ZeroPath, Corgea, Aikido, Depthfirst, AISLE, Endor Labs, Cycode and Gecko. Anthropic announced Claude Code Security in February 2026 and OpenAI shipped Codex Security in March 2026, both as previews. GitHub pairs CodeQL with Copilot Autofix.
- **Threat modelling from code is also being automated** (Apiiro, ThreatModeler, Snyk).
- **Price anchors:** Semgrep Teams about $30 per contributor per month; Snyk Team about $25 per developer per month, enterprise by quote; Aikido priced per team (figures from aggregators disagree). Confirm on the vendors' pricing pages before quoting.
- **What nobody in these lists leads with:** a scored, auditable risk register in business terms with a statement of what was *not* examined. That is closer to GRC than to SAST, and it is where this product already has working features.

Strongest counter-argument: buyers may want one tool, and a scanner vendor can add a risk-register view faster than a new entrant can add trusted detection. The response is R4 below: do not depend on your own detection alone.

## 6. Recommendations

Ordered by what unblocks revenue first. Now / Next / Later, no dates.

### Now: make one team able to use it on its own code

| # | Recommendation | Closes |
|---|---|---|
| R1 | Decide the first deployment model before writing more scan code: **single-tenant, self-hosted container with the customer's own model key.** It sidesteps most of A5 and A7 (code never leaves their environment except to their chosen provider), fits the existing bring-your-own-key design, and suits regulated buyers. Hosted SaaS comes later. Needs an ADR. | A4, A5, A7 |
| R2 | Authentication and roles (SSO via OIDC is enough), results stored server-side, private-repository access through a GitHub App or token. Move B-015 from P3 to P0. | A1, A2, A3 |
| R3 | Pull-request check: comment with new or regressed findings, fail on new catastrophic ones. Move B-012 up; it depends on finding identity (B-031), so B-031 moves up with it. | B1, B6 |
| R4 | **Import findings from other scanners (SARIF)** and score, deduplicate and register them alongside your own. This turns competitors into inputs, removes the need for buyers to trust your detection on day one, and makes "the risk layer above your scanners" a true statement. Export SARIF and add CWE to every finding. | B4, C3, C8 |
| R5 | Remove `memory/fmea.db` and `memory/workspaces/` from git, rewrite the README to match the product, and delete the unbacked compliance claims. | A6, B7, E1 |

### Next: make it credible in an evaluation

| # | Recommendation | Closes |
|---|---|---|
| R6 | A public benchmark run: real open-source projects at commits with known CVEs, plus one head-to-head against Semgrep and CodeQL on the same code. Publish method and misses. Report false-positive rate from a triaged sample. | C3, C4 |
| R7 | Finish B-028 in the order already agreed, but put the **cap removal and large-repository handling** first, because C1 and C2 are the two things a pilot hits on day one. | C1, C2 |
| R8 | Add Azure OpenAI, Bedrock and Anthropic providers and an OpenAI-compatible local endpoint. Land B-040 (defensive framing, block handling) before any pilot. | C5, C6 |
| R9 | Fixes as pull requests; Jira or Linear ticket per finding with status synced back; one PDF or DOCX report for auditors. | B2, B3, B5 |
| R10 | Rework the UI to the findings-first layout (U3) together with R2, since both touch every page. | U1-U12 |

### Later: the defensible part

| # | Recommendation | Closes |
|---|---|---|
| R11 | Preventive actions and root-cause classes (B-029, B-030), then root-cause trends across projects: "40% of your high-severity findings come from missing authorisation checks at service boundaries; here is the guardrail." This is the long-term prevention the goal describes and the hardest thing for a scanner vendor to copy. | D1, D2 |
| R12 | Control mapping (ISO 27001, SOC 2, DORA, NIS2) as data, with evidence export. Only then make compliance claims. | B7 |

**Proposed re-ordering in one line:** pause new discovery phases after the in-flight items land; do R1-R5; then resume B-028 with the cap and scale first.

## 7. Go-to-market guidance

**Who to sell to first.** Two candidate beachheads; pick one.

| | A. Regulated software teams, 50-500 engineers (fintech, health, B2B SaaS selling to enterprises) | B. Safety-critical software (medical devices, automotive, industrial) |
|---|---|---|
| Why they buy | Must show auditors and customers a current risk register; small AppSec team; EU DORA and NIS2 pressure | FMEA is already mandated practice (ISO 14971, ISO 26262); they do it by spreadsheet |
| Fit today | Languages match (Python, Java, C#, TypeScript) | The name fits perfectly, but their code is mostly C and C++, which is not indexed |
| Buyer | Head of security or engineering; risk and compliance as co-sponsor | Quality and safety engineering |
| Verdict | **Recommended first** | Strong second act once C and C++ are supported |

**Positioning.** Not "AI SAST". Proposed line: *the risk register that is written from your code*. Three proof points that are true today: findings ranked by business impact with a floor so catastrophic items cannot be buried; every score locked, explained and auditable with human override; an explicit list of what was not examined. Add "above your existing scanners" once R4 exists.

**Name.** "FMEA" will not mean anything to most security buyers and is descriptive rather than ownable. Choose a company name that is not the method, check the domain and trade mark, and keep "FMEA for software" as the explanation, not the brand. The landing page uses a placeholder.

**Offer and price.** Start with paid design partners, not self-serve.
- *Risk assessment* (lead offer): fixed fee, one to three repositories, delivered as a report and a walkthrough. Needs only R5, an export, and manual operation. Sellable soonest.
- *Pilot*: 8-12 weeks, self-hosted, fixed fee credited against the first year. Needs R1-R3.
- *Subscription*: per active contributor per month. The market anchors at roughly $25-40; a risk-register product with fewer seats per customer may price better per repository or per business unit. Decide after three pilots, not before.

**Motion.** Founder-led sales to 15-20 named accounts; aim for three to five design partners. Lead magnet: a public write-up of the benchmark (R6) and a scan of a well-known open-source project with maintainers' agreement. Channel partners worth testing: consultancies and auditors who already produce risk registers by hand.

**Before the first customer conversation.** Company entity and name; terms, DPA and an authorised-use clause; a one-page security statement describing exactly where code and keys go; professional indemnity and cyber insurance; the README and landing page telling the same story.

**What to measure in pilots.** Share of findings accepted as real after triage; time from scan to first merged fix; number of catastrophic items the customer did not already know; whether the risk owner uses the register in an actual audit or board pack.

**Largest unknowns, and the cheapest way to resolve them.** (1) Whether buyers want a risk layer separate from their scanner: ten discovery calls with heads of security before building R4. (2) Real-code false-positive rate: R6 on three open-source projects. (3) Whether self-hosted is acceptable or SaaS is expected: ask in the same ten calls.

## 8. Proposed backlog items (need engineer approval and priority)

| Proposed | Title | Suggested |
|---|---|---|
| new | Deployment model ADR and container packaging (R1) | P0 |
| B-015 | Authentication, roles, server-side results (R2), move from P3 | P0 |
| new | Private repository access: GitHub App or token, then GitLab (R2) | P0 |
| new | Repository hygiene: untrack runtime data, README rewrite, remove unbacked claims (R5) | P0, small |
| B-012 + B-031 | Pull-request check and finding identity (R3), move up | P1 |
| new | SARIF import and export, CWE on findings (R4) | P1 |
| new | Public benchmark and head-to-head (R6) | P1 |
| new | Additional providers: Azure OpenAI, Bedrock, Anthropic, local (R8) | P1 |
| new | UI restructure to findings-first, accessibility pass (R10) | P1 |
| B-011, B-016, new | Report export, ticketing, fix-as-pull-request (R9) | P1 |
| new | Control mapping as data (R12) | P2 |

## Sources

Market statements come from: [Aikido](https://www.aikido.dev/blog/top-ai-powered-sast-tools), [Cycode](https://cycode.com/blog/ai-sast/), [Endor Labs](https://www.endorlabs.com/learn/best-ai-sast-tools), [ZeroPath](https://zeropath.com/articles/best-ai-sast-tools-business-logic-flaws), [Corgea](https://corgea.com/blog/top-ai-sast-tools-for-2026), [Veracode](https://www.veracode.com/blog/llm-code-security-vs-hybrid-sast/), [DevOps.com on Claude Code Security](https://devops.com/claude-code-security-finds-the-bugs-that-static-analysis-cant-and-wall-street-noticed/), [Codex Security notes](https://codex.danielvaughan.com/2026/03/31/codex-security-agent-vulnerability-scanning-threat-modelling/), [Help Net Security on ThreatModeler](https://www.helpnetsecurity.com/2026/06/26/threatmodeler-introduces-nexus-to-automate-threat-modeling-with-ai-governance/), [Snyk on threat modelling](https://snyk.io/blog/future-threat-modeling-ai-native-apps/), [Semgrep pricing](https://semgrep.dev/pricing), [AppSec pricing guide](https://appsecsanta.com/appsec-pricing-guide). Regulatory references (DORA, NIS2, ISO 14971, ISO 26262) are from general knowledge and were not re-verified.
