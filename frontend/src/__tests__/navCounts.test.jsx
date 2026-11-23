import { render, screen, within } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import Sidebar from '../components/Sidebar';
import { navCounts } from '../helpers';

const risk = (name, corrective = []) => ({ name, corrective });
const now = { id: 'c1', urgency: 'now' };
const next = { id: 'c2', urgency: 'next' };

describe('navCounts (B-054 step 2)', () => {
  it('counts the findings in scope and those with at least one corrective action in the Now band', () => {
    const risks = [risk('a', [now, next]), risk('b', [next]), risk('c', [now]), risk('d', [])];
    expect(navCounts(risks)).toEqual({ findings: 4, fixes: 2 });
  });

  it('is empty when there is no scan, so nothing is counted that is not known', () => {
    expect(navCounts(null)).toEqual({});
    expect(navCounts(undefined)).toEqual({});
  });

  it('reads findings stored before actions existed (no corrective list) as having no Now action', () => {
    expect(navCounts([{ name: 'old' }])).toEqual({ findings: 1, fixes: 0 });
  });
});

function side(counts) {
  render(<Sidebar persona="developer" step="scan" sel={{}} scope="project" hierarchy={[]} scanHistory={{}} onPersona={() => {}} onStep={() => {}}
                  onSelect={() => {}} onScope={() => {}} onAddPortfolio={() => {}} onAddProject={() => {}} onOpenSettings={() => {}}
                  user={{ display_name: 'T', role: 'admin' }} canSwitchPersona={false} onLogout={() => {}} counts={counts} />);
}
const entry = (name) => screen.getByRole('button', { name: new RegExp(name) });

describe('count badges in the left pane', () => {
  it('shows the counts beside Findings and Fixes, and says what they mean to a screen reader', () => {
    side({ findings: 12, fixes: 3 });
    expect(within(entry('Findings')).getByText('12')).toBeInTheDocument();
    expect(within(entry('Fixes')).getByText('3')).toBeInTheDocument();
    expect(entry('Findings')).toHaveAccessibleName(/12 findings/);
    expect(entry('Fixes')).toHaveAccessibleName(/3 findings with an urgent fix/);
  });

  it('uses the singular for one', () => {
    side({ findings: 1, fixes: 1 });
    expect(entry('Findings')).toHaveAccessibleName('Findings, 1 finding');
    expect(entry('Fixes')).toHaveAccessibleName('Fixes, 1 finding with an urgent fix');
  });

  it('shows no badge for zero, for no data, and never on Overview, Scan or Settings', () => {
    side({ findings: 0, fixes: 0 });
    for (const name of ['Overview', 'Scan', 'Findings', 'Fixes', 'Settings']) expect(entry(name).textContent).not.toMatch(/\d/);
  });

  it('shows nothing when no counts are given', () => {
    side(undefined);
    expect(entry('Findings').textContent).not.toMatch(/\d/);
  });
});
