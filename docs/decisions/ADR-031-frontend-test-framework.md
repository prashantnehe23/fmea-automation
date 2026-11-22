# ADR-031: Frontend Test Framework — Vitest, Testing Library, jsdom

**Status:** Accepted (engineer, 2026-11-22: "have the JS test framework rather than depending on browser testing")  **Date:** 2026-11-22  **Backlog:** B-048 phase 1

## Context
The React frontend (about 4,700 lines) had no automated tests. Phase 0 of B-048 was checked by hand in a browser and by a grep test; every later interface change would depend on the same manual checks. B-048 phase 1 needs reviewable behaviour (a finding fully reviewable from one view, labelled and keyboard-reachable controls) that can be asserted in CI.

## Decision
Add **Vitest** (test runner, shares the existing Vite configuration), **@testing-library/react**, **@testing-library/dom**, **@testing-library/jest-dom** and **@testing-library/user-event** (query by role, label and visible text, which also exercises accessibility), and **jsdom** (DOM without a browser). All are development dependencies only; nothing changes in the shipped bundle. Tests live in `frontend/src/__tests__/`, run with `npm test`, and mock the `api` module at the component boundary.

## Alternatives considered
- **Jest:** the most widespread runner, but it needs Babel or SWC transforms to match Vite, so two toolchains to keep in step.
- **Playwright end to end:** covers layout and CSS in a real browser, but is slower, needs a browser download and a running backend with a model key, and does not replace component-level checks. It can be added later for a few critical journeys.
- **Browser checks by hand only:** what phase 0 used; not repeatable and not part of CI.

## Consequences
- jsdom is not a browser: no layout, no CSS, no real focus rendering. Visual correctness and responsive layout still need an occasional look in a browser.
- An automated accessibility check with axe-core can be added on top of Testing Library (planned for the navigation and accessibility slice of B-048).
- About 100 transitive dev packages; `npm audit` reports advisories in the dev tool chain, none in runtime dependencies.
- Python tests still run separately (`python -m pytest`); a CI workflow should run both `npm test` and `pytest`.
