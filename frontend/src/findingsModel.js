// B-048 phase 1: the findings view's rules, kept apart from the markup so they can be tested on their own.

const RANK = { Critical: 3, High: 2, Medium: 1, Low: 0 };
const CATASTROPHIC = 9;                       // same threshold as core/priority.py: severity 9 and above is the watchlist

export const byPriorityThenRpn = (a, b) => (RANK[b.priority] ?? -1) - (RANK[a.priority] ?? -1) || b.rpn - a.rpn;

/** Every severity 9+ finding, highest RPN first, whatever its RPN or band. Locked findings are in the list too. */
export const watchlist = risks => risks.filter(r => r.s >= CATASTROPHIC).sort((a, b) => b.rpn - a.rpn);

/** filters: { priority, domain, source: 'imported' | 'fmea', state }; a missing or 'all' value keeps everything. */
export function filterFindings(risks, filters = {}, states = {}) {
  const on = v => v && v !== 'all';
  return risks.filter(r => {
    if (on(filters.priority) && r.priority !== filters.priority) return false;
    if (on(filters.domain) && (r.root_cause ?? 'unclassified') !== filters.domain) return false;
    const imported = (r.source ?? 'fmea').startsWith('import:');
    if (on(filters.source) && (filters.source === 'imported') !== imported) return false;
    if (on(filters.state) && (states[r.name] ?? 'new') !== filters.state) return false;
    return true;
  });
}

export function describeScore(s, o, d) {
  return {
    severity:   s >= 9 ? 'Catastrophic' : s >= 7 ? 'Serious' : s >= 4 ? 'Moderate' : 'Minor',
    occurrence: o >= 8 ? 'Very likely' : o >= 5 ? 'Likely' : o >= 3 ? 'Possible' : 'Unlikely',
    detection:  d >= 8 ? 'Very hard to detect' : d >= 5 ? 'Hard to detect' : d >= 3 ? 'Detectable' : 'Easy to detect',
  };
}

const stated = text => (text && text.trim() && text.trim().toLowerCase() !== 'not specified') ? text.trim() : '';

/** The business impact in a sentence a non-specialist can read. */
export function impactText(r) {
  const impact = stated(r.impact).replace(/\.$/, '');
  const blast = stated(r.blast_radius).replace(/\.$/, '');
  if (!impact && !blast) return 'No impact statement was produced for this finding.';
  return [impact && `${impact}.`, blast && `Affects: ${blast}.`].filter(Boolean).join(' ');
}

export const STATE_LABEL = {
  new: 'New', confirmed: 'Confirmed', fix_candidate: 'Fix candidate', fixed: 'Fixed',
  regressed: 'Regressed', accepted: 'Risk accepted', unresolved: 'Unresolved',
};
