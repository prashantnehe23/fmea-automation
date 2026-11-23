# Left pane and navigation: comparison and proposal (B-054, stage 1)

Status: **approved by the engineer on 2026-11-23**, including the hierarchy direction below. Step 1 is built (see B-054 in `docs/BACKLOG.md`); steps 2 to 4 and the hierarchy work wait until after the demo.

## What is wrong today

The left pane stacks four different things in one column: the role, a portfolio and project tree, a "Process" list of seven numbered steps, and the user. The seven steps mix a workflow (scan, then findings) with pages that overlap:

- **Failure Scenarios, Risk Scoring and Findings** show the same findings from three angles. The Findings page already carries the score, the reason for it and the evidence.
- **Mitigations and Auto-Remediation** both deal with fixing; the fix actions are on Findings and Mitigations, the generated code is on Auto-Remediation.
- **Numbers (1 to 7) and "Step 1 of 7"** suggest a wizard that has to be followed in order, but nothing enforces it and the role decides which steps are "main".
- **Dimmed steps** (fixed on 2026-11-22, B-055) looked disabled although they were not.
- **Settings** is a gear in the header, away from the rest of the navigation.

## What comparable tools do

These come from public documentation; I did not test the products. Sources are at the end.

| Tool | Structure | What to take from it |
|---|---|---|
| GitHub Security (code scanning) | A Security tab with a left sidebar: Overview, then alert types such as Code scanning. The organisation view has Risk and Coverage tabs. | Overview first, alerts as the main list, coverage as its own view. |
| Semgrep | Top bar with Code and Supply Chain; a dashboard table of findings by project; clicking a project opens its findings with filters and triage states (Open, Ignored, Fixed). | The finding list is the home screen; triage is a state on the finding, not a separate page. |
| Snyk | "Unified navigation" groups items by how security work is done and removes top-level clutter. | Fewer, task-named groups. |
| Linear | Sidebar from personal items at the top to shared items below; favourites; inactive items are muted but never look disabled; the page is the focus. | Few items, plain names, a quiet sidebar, the project switch at the top. |

Common to all four: **a short list of nouns people already use** (Overview, Findings, Coverage, Settings), the finding list as the centre, and fixing as an action on a finding rather than a stage of a process.

## Proposed structure

```
[FM] FMEA Platform
[ Project switcher: Big / sdk  v ]            <- the tree collapses into a switcher with search

  Overview                                    <- today's Dashboard
  Scan                                        <- today's Context & Scan (Deep scan option)
  Findings      7                             <- list + detail: score, evidence, exploit path,
                                                 root cause, actions with Remediate. Absorbs
                                                 Failure Scenarios and Risk Scoring.
  Fixes         3 to review                   <- today's Mitigations + Auto-Remediation: queue of
                                                 proposed, accepted, rejected fixes (B-053)
  Coverage                                    <- what was scanned and what was not (B-028)
  Reports                                     <- SARIF export, history, what changed (B-048)

  ----
  Settings                                    <- moved into the sidebar from the header gear

  [avatar] Name · Role · Sign out
```

- **Role** appears once, in the footer, as a label. The persona switcher stays for demo mode only, tucked under the footer.
- **Counts** replace numbers: Findings shows how many, Fixes how many wait for review.
- **Every item is available to every signed-in role.** What a role may do is shown on the controls inside a page and enforced by the server (already true).
- **Scope** (component, project, portfolio) stays a control on the page, not part of the pane.

## Trade-offs

| Choice | Gain | Cost |
|---|---|---|
| Merge Failure Scenarios and Risk Scoring into Findings | One place for a finding; less to learn | The scenarios table and the scoring table views would be removed or become views inside Findings; some people may like the tables |
| Merge Mitigations and Auto-Remediation into Fixes | One place for fixing, matches the Remediate button | Needs the review queue (B-053 follow-up) before it is worth it |
| Project switcher instead of a tree | More room, quicker project change | Portfolio-level browsing needs the switcher's search or a Portfolio view |
| Drop the "Step 1 of 7" wizard idea | Users can start anywhere | The first-run path has to come from Overview ("Scan your first project") instead |
| Settings into the sidebar | Found where people look | The header gear goes, or becomes a shortcut |

## Suggested build order, if approved

1. Rename and regroup the existing pages without changing them: Overview, Scan, Findings, Fixes, Settings in the sidebar; keep the old pages reachable from inside Findings and Fixes. Role label to the footer. (Small, testable, safe for the demo.)
2. Counts on Findings and Fixes.
3. Project switcher.
4. Fold the scenario and scoring views into Findings, and merge the two fix pages, after the review queue exists.

## Project, portfolio and component structure (stage 2, approved 2026-11-23, not built)

- One place to say where you are: a **project switcher** at the top of the left pane (search, grouped by portfolio) plus a breadcrumb in the page header. The tree and the View level buttons go.
- **Portfolio is a page**: a table of its projects (findings by priority, highest RPN, last scan); click a row to open the project.
- **Component is a filter** on Findings (and a grouping), not a level. Roles limited to one component start with it preset.
- **Projects come from scanning**: the first run asks for a repository URL or pasted code and creates the project, with a default portfolio. New Portfolio and New Project stay as small actions in the switcher.
- Role scope stays enforced on the server.
- Order after the demo: switcher and breadcrumb, portfolio table, Component filter, create-on-scan. It changes the selection state in `App.jsx`, so it is larger and riskier than step 1.

## Decisions I needed (answered 2026-11-23)

Approved the structure; build step 1 before the demo; the Scenarios and Scoring tables survive as tabs inside Findings.

## Original decision list

1. Approve the structure above, change it, or reject it.
2. Whether to build step 1 before the demo or after.
3. Whether the Scenarios and Scoring table views must survive somewhere.

## Sources

- GitHub documentation on security overview and code scanning alerts: https://docs.github.com/en/enterprise-server@3.18/code-security/concepts/security-at-scale/security-overview and https://docs.github.com/en/enterprise-server@3.16/code-security/concepts/code-scanning/code-scanning-alerts
- Semgrep AppSec Platform dashboard: https://docs.semgrep.dev/semgrep-appsec-platform/dashboard
- Snyk, Unified Navigation: https://updates.snyk.io/introducing-unified-navigation-a-faster-way-to-secure-your-application-stack/
- Linear, navigating Linear and the design refresh: https://linear.app/enablement/guides/navigating-linear and https://linear.app/now/behind-the-latest-design-refresh
