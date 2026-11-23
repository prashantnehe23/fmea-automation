// B-054 step 3 (ADR-034): where you are. The selection object keeps the shape it always had; the scope is computed from it
// and from what the role may work at, so the two can no longer disagree.

import { PERSONA_SCOPE_OPTIONS } from './data';

export const EMPTY_SEL = { portfolioId: null, projectId: null, componentId: null, componentName: null };

/** Which depths a role is offered in the switcher and the breadcrumb. */
export function selectable(persona) {
  const allowed = PERSONA_SCOPE_OPTIONS[persona] ?? [];
  return {
    org:       allowed.includes('org'),
    portfolio: allowed.includes('portfolio'),
    project:   allowed.includes('project') || allowed.includes('component'),   // components are reached through a project
    component: allowed.includes('component'),
  };
}

/** A saved selection cut back to what the role may use. */
export function limitSel(sel, persona) {
  const can = selectable(persona);
  if (!can.project) return { ...sel, projectId: null, componentId: null, componentName: null };
  if (!can.component) return { ...sel, componentId: null, componentName: null };
  return sel;
}

/** The scope of the pages: the deepest thing selected that the role may work at. */
export function deriveScope(sel, persona) {
  const can = selectable(persona);
  if (sel.projectId && can.project) return sel.componentName && can.component ? 'component' : 'project';
  if (sel.portfolioId && can.portfolio) return 'portfolio';
  if (!sel.portfolioId && !sel.projectId && can.org) return 'org';
  return 'project';          // nothing usable selected: the pages show their "select a project" state
}

// ── components: the files a finding cites ─────────────────────────────────────

const EVIDENCE_FILE = /([\w./\\-]+\.\w+):\d+/g;

/** Files named by a finding's exploit path steps and its evidence, each once, in the order cited. */
export function findingFiles(finding) {
  const files = [];
  const add = (f) => { const name = String(f ?? '').replace(/\\/g, '/'); if (name && !files.includes(name)) files.push(name); };
  (finding?.exploit_path ?? []).forEach(step => add(step.file));
  for (const m of String(finding?.evidence ?? '').matchAll(EVIDENCE_FILE)) add(m[1]);
  return files;
}

/** [{name, count}] of the files the findings cite, most cited first. */
export function componentsOf(risks) {
  const counts = new Map();
  (risks ?? []).forEach(r => (r.files ?? []).forEach(f => counts.set(f, (counts.get(f) ?? 0) + 1)));
  return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function filterByComponent(risks, componentName) {
  if (!risks || !componentName) return risks;
  return risks.filter(r => (r.files ?? []).includes(componentName));
}

/** A role that may work at project level can choose 'All components'; a component-only role always has one selected. */
export function allowsAllComponents(persona) {
  return (PERSONA_SCOPE_OPTIONS[persona] ?? []).includes('project');
}

/** The component a component-only role starts with: the most cited one. */
export function defaultComponent(persona, components) {
  return !allowsAllComponents(persona) && selectable(persona).component && components?.length ? components[0].name : null;
}
