import { describe, it, expect } from 'vitest';
import { deriveScope, selectable, componentsOf, findingFiles, filterByComponent, limitSel, EMPTY_SEL } from '../selection';

const sel = (p = null, pr = null, c = null) => ({ portfolioId: p, projectId: pr, componentId: null, componentName: c });

describe('which depths a role is offered (ADR-034 point 3)', () => {
  it.each([
    ['developer',         { org: false, portfolio: false, project: true,  component: true  }],
    ['sre',               { org: false, portfolio: false, project: true,  component: true  }],
    ['security_engineer', { org: false, portfolio: true,  project: true,  component: true  }],
    ['risk_manager',      { org: true,  portfolio: true,  project: true,  component: false }],
    ['executive',         { org: true,  portfolio: true,  project: false, component: false }],
  ])('%s', (persona, expected) => {
    expect(selectable(persona)).toEqual(expected);
  });
});

describe('scope follows the selection (ADR-034 point 1)', () => {
  it('is the deepest thing selected that the role may work at', () => {
    expect(deriveScope(sel('p1', 'pr1', 'public.py'), 'security_engineer')).toBe('component');
    expect(deriveScope(sel('p1', 'pr1'), 'security_engineer')).toBe('project');
    expect(deriveScope(sel('p1'), 'security_engineer')).toBe('portfolio');
    expect(deriveScope(sel(), 'risk_manager')).toBe('org');
    expect(deriveScope(sel('p1'), 'executive')).toBe('portfolio');
  });

  it('never goes deeper than the role allows, and never contradicts the selection', () => {
    expect(deriveScope(sel('p1', 'pr1', 'public.py'), 'risk_manager')).toBe('project');   // no component depth
    expect(deriveScope(sel('p1', 'pr1'), 'executive')).toBe('portfolio');                  // no project depth: the portfolio of that project
  });

  it('shows the empty state, not an organisation view, for a role that has no organisation view', () => {
    expect(deriveScope(sel(), 'developer')).toBe('project');
    expect(deriveScope(sel('p1'), 'developer')).toBe('project');
  });
});

describe('limiting a saved selection to what the role may use', () => {
  it('drops the project and component for a role that works at portfolio level', () => {
    expect(limitSel(sel('p1', 'pr1', 'a.py'), 'executive')).toEqual(sel('p1'));
  });
  it('drops the component for a role without component depth and keeps everything otherwise', () => {
    expect(limitSel(sel('p1', 'pr1', 'a.py'), 'risk_manager')).toEqual(sel('p1', 'pr1'));
    expect(limitSel(sel('p1', 'pr1', 'a.py'), 'security_engineer')).toEqual(sel('p1', 'pr1', 'a.py'));
  });
  it('has an empty selection', () => {
    expect(EMPTY_SEL).toEqual(sel());
  });
});

describe('components come from the files a finding cites', () => {
  it('reads the exploit path steps and the evidence, once each', () => {
    const f = {
      exploit_path: [{ file: 'public.py', lines: '9' }, { file: 'internal_admin.py', lines: '7' }, { file: 'public.py', lines: '12' }],
      evidence: 'public.py:9 `r = requests.get(url)`',
    };
    expect(findingFiles(f)).toEqual(['public.py', 'internal_admin.py']);
  });

  it('reads the evidence alone, and gives nothing for a finding that cites no file', () => {
    expect(findingFiles({ evidence: 'src/app/auth.py:40-45 `check()`' })).toEqual(['src/app/auth.py']);
    expect(findingFiles({ evidence: '', exploit_path: [] })).toEqual([]);
    expect(findingFiles({})).toEqual([]);
  });

  it('lists each component with how many findings cite it, most first', () => {
    const risks = [{ files: ['a.py', 'b.py'] }, { files: ['b.py'] }, { files: ['b.py', 'c.py'] }, { files: [] }, {}];
    expect(componentsOf(risks)).toEqual([{ name: 'b.py', count: 3 }, { name: 'a.py', count: 1 }, { name: 'c.py', count: 1 }]);
    expect(componentsOf(null)).toEqual([]);
  });

  it('keeps only the findings that cite the chosen component', () => {
    const risks = [{ name: 'x', files: ['a.py'] }, { name: 'y', files: ['b.py', 'a.py'] }, { name: 'z', files: [] }];
    expect(filterByComponent(risks, 'a.py').map(r => r.name)).toEqual(['x', 'y']);
    expect(filterByComponent(risks, null)).toBe(risks);
    expect(filterByComponent(null, 'a.py')).toBeNull();
  });
});
