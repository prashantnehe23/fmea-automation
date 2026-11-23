# ADR-034: Where You Are: Selection, Scope and the Project Switcher

**Status:** Proposed (written 2026-11-23 for the engineer's approval; step 3 of B-054 starts once it is accepted)  **Date:** 2026-11-23  **Backlog:** B-054 (steps 2 and 3, and the hierarchy direction approved 2026-11-23)  **Builds on:** [ADR-027](ADR-027-authentication-roles-and-repository-access.md) (roles), `docs/design/left-pane-proposal.md`

## Context
Two controls in the left pane both say where you are: the tree (portfolio, project, and the components listed under a project) and the "View level" buttons (Component, Project, Portfolio). They can disagree (a project selected with Component on), and a role limits which levels exist (`PERSONA_SCOPE_OPTIONS`). The selection is an object in the top component (`sel`: portfolio id, project id, component id and name) saved in the browser's local storage, with a separate `scope`. Pages read both.

The approved direction (proposal, 2026-11-23) replaces the tree with a project switcher and a breadcrumb, makes the portfolio a page, and makes a component a filter. That needs a decision about what the single source of truth for "where you are" is, and whether to add URL routing at the same time.

## Decision
1. **Scope follows the selection and is no longer a separate control.** A portfolio selected alone means portfolio scope; a project means project scope; a component within a project means component scope. The View level buttons are removed once the switcher and the component picker exist, not before.
2. **The switcher and the breadcrumb are the one place to choose.** A switcher at the top of the left pane lists portfolios and their projects with search and an "all projects in this portfolio" row; the page header shows `Portfolio / Project / Component`, where the component part is a dropdown ("All components" or one component, taken from the components in the project's findings). "New portfolio" and "New project" stay as small actions in the switcher.
3. **Roles limit the depths on offer.** A role that may only work at component level (the developer) is offered components and starts with one selected; a role that works at portfolio level starts there. This replaces the scope-options list as a switch; the server's checks do not change.
4. **State stays where it is.** The selection stays in the top component and in local storage, in the same shape it has today (`sel`), so saved selections keep working; `scope` becomes a value computed from `sel`. **No router is added now.**
5. **Deep links are a separate, later decision.** Links that open a given finding (for pull-request comments from B-012, or sharing) need URLs. That is its own ADR when the first feature needs it, comparing a router library with a few lines of hash handling.
6. **The tree component is deleted** after its replacement passes the same behaviour tests (select a portfolio, a project, a component; add a project; roles' limits).

## Alternatives considered
- **Keep the tree and the View level buttons** and only restyle: no risk, but the conflict between the two controls remains, which is the main complaint.
- **Add a router now (for example React Router) and make the URL the source of truth:** gives deep links and back-button behaviour, but adds a dependency and rewrites how every page reads the selection, which is too much to do before the demo and before any feature needs the links.
- **Hash-based routing written by hand:** no dependency, but still a rewrite of selection handling; better done together with the deep-link decision.
- **Command palette (Ctrl+K) as the only switcher:** quick for experts, hidden for new users; can be added on top later.

## Consequences
- One place says where you are; scope can no longer contradict it.
- The selection object keeps its shape, so saved state and every page keep working; the pages that read `scope` receive the computed value.
- The tree's quick browsing of a large portfolio is replaced by search and the portfolio page; the portfolio page itself (a table of projects) and the Component filter on Findings are separate steps after this one (B-054 stage 2).
- Browser back, bookmarks and shared links still do not work; that is the cost of postponing routing.

## For the engineer to decide
Accept, change or reject points 1 to 6, in particular point 3 (what each role starts with) and point 5 (no router now).
