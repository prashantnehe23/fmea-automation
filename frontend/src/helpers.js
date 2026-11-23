import { ALL_RISKS, HIERARCHY as DEFAULT_HIERARCHY, ORG } from './data';

// ── Colour maps ───────────────────────────────────────────────────────────────

export const PRI = {
  Critical: { badge: 'bg-red-100 text-red-700',       dot: 'bg-red-500'    },
  High:     { badge: 'bg-orange-100 text-orange-700', dot: 'bg-orange-500' },
  Medium:   { badge: 'bg-amber-100 text-amber-700',   dot: 'bg-amber-400'  },
  Low:      { badge: 'bg-green-100 text-green-700',   dot: 'bg-green-500'  },
};

export const STA = {
  'Open':        'bg-gray-100 text-gray-600',
  'In Progress': 'bg-blue-100 text-blue-700',
  'Reviewing':   'bg-purple-100 text-purple-700',
  'Mitigated':   'bg-green-100 text-green-700',
};

// ── Risk filtering ────────────────────────────────────────────────────────────

export function filterRisks(sel, scope) {
  if (scope === 'org')       return ALL_RISKS;
  if (scope === 'portfolio') return ALL_RISKS.filter(r => r.portfolio === sel.portfolioId);
  if (scope === 'project')   return ALL_RISKS.filter(r => r.project   === sel.projectId);
  if (scope === 'component') return ALL_RISKS.filter(r => r.comp      === sel.componentName);
  return ALL_RISKS;
}

// ── Selection label ───────────────────────────────────────────────────────────

export function getSelectionLabel(sel, scope, hierarchy = DEFAULT_HIERARCHY) {
  if (scope === 'org') return ORG.name;
  const portfolio = hierarchy.find(p => p.id === sel.portfolioId);
  if (scope === 'portfolio') return portfolio?.name ?? 'No portfolio selected';
  const project = portfolio?.projects.find(p => p.id === sel.projectId);
  if (scope === 'project') return project?.name ?? 'No project selected';
  return sel.componentName ?? project?.name ?? portfolio?.name ?? 'No project selected';
}

// ── Aggregation ───────────────────────────────────────────────────────────────

export function aggregateBy(risks, groupFn, labelFn) {
  const map = {};
  risks.forEach(r => {
    const key = groupFn(r);
    if (!map[key]) map[key] = { label: labelFn(r), risks: [] };
    map[key].risks.push(r);
  });
  return Object.values(map).map(g => ({
    ...g,
    total:    g.risks.length,
    critical: g.risks.filter(r => r.priority === 'Critical').length,
    high:     g.risks.filter(r => r.priority === 'High').length,
    maxRpn:   Math.max(...g.risks.map(r => r.rpn)),
    mitigated: g.risks.filter(r => r.status === 'Mitigated').length,
  })).sort((a, b) => b.maxRpn - a.maxRpn);
}

// B-054 step 2: the numbers beside Findings and Fixes in the left pane. Nothing is counted when there is no scan.
// Fixes = findings in scope with at least one corrective action in the Now band.
export function navCounts(risks) {
  if (!risks) return {};
  return {
    findings: risks.length,
    fixes: risks.filter(r => (r.corrective ?? []).some(a => a.urgency === 'now')).length,
  };
}
