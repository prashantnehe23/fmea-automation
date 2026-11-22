import { describe, it, expect } from 'vitest';
import { watchlist, filterFindings, describeScore, impactText, byPriorityThenRpn } from '../findingsModel';

const risk = (over = {}) => ({
  id: 1, name: 'A finding', s: 5, o: 5, d: 5, rpn: 125, priority: 'Medium', priority_reason: 'Medium: RPN 125',
  root_cause: 'security', source: 'fmea', cwe: 'CWE-89', ...over,
});

describe('watchlist', () => {
  it('lists every severity 9 or 10 finding, highest RPN first, including ones with a low RPN', () => {
    const list = [risk({ id: 1, s: 4, rpn: 400 }), risk({ id: 2, s: 9, o: 2, d: 2, rpn: 36 }), risk({ id: 3, s: 10, rpn: 300 })];
    expect(watchlist(list).map(r => r.id)).toEqual([3, 2]);
  });
  it('is empty when nothing is catastrophic', () => {
    expect(watchlist([risk({ s: 8 })])).toEqual([]);
  });
});

describe('ordering and filters', () => {
  const list = [risk({ id: 1, priority: 'Low', rpn: 500 }), risk({ id: 2, priority: 'Critical', rpn: 100 }), risk({ id: 3, priority: 'Critical', rpn: 300 })];
  it('puts the highest priority first, then the highest RPN', () => {
    expect([...list].sort(byPriorityThenRpn).map(r => r.id)).toEqual([3, 2, 1]);
  });
  it('filters by priority, root cause, source and state, and "all" keeps everything', () => {
    const mixed = [
      risk({ id: 1, priority: 'High', root_cause: 'security', source: 'fmea' }),
      risk({ id: 2, priority: 'Low', root_cause: 'operational', source: 'import:CodeQL' }),
    ];
    const states = { 'A finding': 'confirmed' };
    expect(filterFindings(mixed, { priority: 'High' }, states).map(r => r.id)).toEqual([1]);
    expect(filterFindings(mixed, { domain: 'operational' }, states).map(r => r.id)).toEqual([2]);
    expect(filterFindings(mixed, { source: 'imported' }, states).map(r => r.id)).toEqual([2]);
    expect(filterFindings(mixed, { state: 'fixed' }, states)).toEqual([]);
    expect(filterFindings(mixed, {}, states)).toHaveLength(2);
  });
});

describe('plain language', () => {
  it('describes severity, likelihood and detection in words', () => {
    expect(describeScore(10, 8, 9)).toEqual({
      severity: 'Catastrophic', occurrence: 'Very likely', detection: 'Very hard to detect',
    });
    expect(describeScore(2, 1, 1)).toEqual({ severity: 'Minor', occurrence: 'Unlikely', detection: 'Easy to detect' });
  });
  it('states the impact from the finding, and says so when it is missing', () => {
    expect(impactText(risk({ impact: 'Customer data is exposed', blast_radius: 'All users' }))).toBe('Customer data is exposed. Affects: All users.');
    expect(impactText(risk({ impact: '', blast_radius: '' }))).toBe('No impact statement was produced for this finding.');
    expect(impactText(risk({ impact: 'Not specified', blast_radius: 'Not specified' }))).toBe('No impact statement was produced for this finding.');
  });
});
