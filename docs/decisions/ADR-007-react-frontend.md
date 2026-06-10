# ADR-007: Frontend — React + Vite over Streamlit Extension

**Status:** Accepted  
**Date:** 2026-05-28  
**Deciders:** Platform team

---

## Context

The platform originally shipped a 7-page Streamlit dashboard (`dashboard.py`). Streamlit is
excellent for rapid data prototyping but has fundamental limitations for a multi-persona,
role-aware product UI:

- No fine-grained layout control (sidebar width, nested navigation, custom component trees)
- No client-side state machine (page state resets on every interaction)
- All rendering is server-side Python; rich interactive UX requires custom components with
  iframes and bidirectional JS bridges
- No path to a progressive web app or desktop packaging (Electron, Tauri)

A design prototype (`dashboard_demo.html`) was produced as a single-file CDN React/Tailwind
page to validate the 6-step FMEA process flow and five-persona UX model. The question was
whether to extend Streamlit with custom components or migrate to a proper frontend build.

---

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **React + Vite (chosen)** | Full layout control; client-side state; proper component model; path to PWA/Electron | Separate build step; requires API layer to reach Python backend |
| Streamlit custom components | Single codebase; no separate server | iframe isolation; bidirectional bridge latency; state reset still affects parent |
| Dash (Plotly) | Python-native; layout better than Streamlit | Still server-side; table/tree components are limited; no offline mode |
| Next.js | SSR + client; ecosystem | Overkill for a local tool; heavier build; no benefit over Vite for SPA |

---

## Decision

**React 18 + Vite 5 + Tailwind CSS 3**, built as a single-page application in `frontend/`.

### Rationale

1. **Design fidelity.** The prototype established exact component contracts (persona switcher,
   scope/hierarchy tree, 6-step process nav, KPI cards, RPN sliders, diff viewer). React
   components map 1:1 to these design elements. Replicating them in Streamlit would require
   six or more custom component bridges, each with its own iframe lifecycle.

2. **Client-side state machine.** Persona, scope, selection, and active step are coupled —
   switching persona must reset scope, selection, and step in one synchronous update. React
   `useState` with a single `switchPersona()` handler does this atomically. Streamlit session
   state would require multiple `st.session_state` writes across a full re-render cycle.

3. **Role-aware content without page reload.** Executives, developers, SREs, risk managers,
   and security engineers see structurally different layouts for the same page. In React this
   is a conditional render within one component tree. In Streamlit it is a full re-render
   requiring `st.rerun()`.

4. **Path to production deployment.** A React SPA behind a FastAPI backend is a standard
   deployment unit (Nginx + Uvicorn, Docker, Vercel + Railway, etc.). Streamlit's deployment
   model is tightly coupled to its server and does not separate frontend from backend.

5. **Zero new runtime dependencies for the build.** Vite, React, and Tailwind are dev
   dependencies. The production build is static HTML + JS + CSS; it can be served from any
   CDN or embedded in a desktop shell.

### Build output

```
frontend/dist/
  index.html
  assets/index-[hash].js    # 191 kB (57 kB gzip)
  assets/index-[hash].css
```

### Source structure (20 files)

```
frontend/src/
  data.js          # all mock constants (to be replaced by API calls — see ADR-008)
  helpers.js       # filterRisks, aggregateBy, colour maps
  App.jsx          # state machine + router
  components/      # 9 shared components
  pages/           # 6 page components (ScanPage … DashboardPage)
```

---

## Consequences

- **Positive:** Full design fidelity; all five personas render correctly with scope-aware
  navigation and role-differentiated page content.
- **Positive:** Clean separation — `frontend/` is entirely independent; it can be developed,
  tested, and deployed without touching the Python pipeline.
- **Positive:** Standard SPA deployment model; straightforward to containerise or CDN-host.
- **Negative:** Mock data in `data.js` must be replaced by real API calls. Until ADR-008's
  FastAPI layer is built and wired, the frontend shows demo data only.
- **Negative:** Two processes to start in development (`npm run dev` + `streamlit run` or
  `uvicorn`). Mitigated by a root `Makefile` / `start.sh` target.
- **Migration note:** `dashboard.py` remains as the operator/admin interface for running
  pipeline analyses. The React frontend is the end-user-facing product UI.

---

## Superseded by

Nothing. Active.
