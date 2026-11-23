import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import Sidebar from '../components/Sidebar';
import SubTabs from '../components/SubTabs';
import { PERSONAS, NAV_GROUPS, PERSONA_PRIMARY } from '../data';

function side(persona, { step = 'scan', onStep = () => {}, onOpenSettings = () => {}, role = 'admin' } = {}) {
  render(<Sidebar persona={persona} step={step} sel={{}} scope="project" hierarchy={[]} scanHistory={{}} onPersona={() => {}} onStep={onStep}
                  onSelect={() => {}} onScope={() => {}} onAddPortfolio={() => {}} onAddProject={() => {}} onOpenSettings={onOpenSettings}
                  user={{ display_name: 'Test', role }} canSwitchPersona={false} onLogout={() => {}} />);
}
const entry = (name) => screen.getByRole('button', { name: new RegExp(name) });

describe('Left pane navigation (B-054 step 1, B-055)', () => {
  it('lists four plain entries and Settings, with no numbered process and no merged pages', () => {
    side('developer');
    for (const name of ['Overview', 'Scan', 'Findings', 'Fixes', 'Settings']) expect(entry(name)).toBeInTheDocument();
    for (const gone of [/Failure Scenarios/, /Risk Scoring/, /Mitigations/, /Auto-Remediation/, /Context & Scan/, /Dashboard/]) {
      expect(screen.queryByRole('button', { name: gone })).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/^Process$/i)).not.toBeInTheDocument();
  });

  it('opens the first page of each group, and Settings opens the settings panel', async () => {
    const onStep = vi.fn(); const onOpenSettings = vi.fn();
    side('security_engineer', { onStep, onOpenSettings });
    const user = userEvent.setup();
    for (const name of ['Overview', 'Scan', 'Findings', 'Fixes']) await user.click(entry(name));
    expect(onStep.mock.calls.map(c => c[0])).toEqual(['dashboard', 'scan', 'findings', 'mitigations']);
    await user.click(entry('Settings'));
    expect(onOpenSettings).toHaveBeenCalled();
  });

  it.each(['scenarios', 'scoring'])('keeps Findings highlighted while the %s page is open', (step) => {
    side('developer', { step });
    expect(entry('Findings')).toHaveAttribute('aria-current', 'page');
    expect(entry('Fixes')).not.toHaveAttribute('aria-current');
  });

  it.each(['mitigations', 'remediation'])('keeps Fixes highlighted while the %s page is open', (step) => {
    side('developer', { step });
    expect(entry('Fixes')).toHaveAttribute('aria-current', 'page');
  });

  it.each(PERSONAS.map(p => p.id))('shows every entry as available for %s and marks only groups with a main step', (persona) => {
    side(persona);
    for (const g of NAV_GROUPS) {
      const button = entry(g.label);
      expect(button.className).not.toMatch(/text-gray-[34]00/);
      const main = g.steps.some(s => PERSONA_PRIMARY[persona].includes(s));
      expect(!!button.querySelector('[data-main-step]')).toBe(main);
    }
  });
});

describe('Tabs inside a group', () => {
  it('shows the pages of Findings and of Fixes as tabs and nothing for single-page groups', () => {
    const { rerender } = render(<SubTabs step="scenarios" onStep={() => {}} />);
    expect(screen.getAllByRole('tab').map(t => t.textContent)).toEqual(['Findings', 'Scenarios', 'Scoring']);
    expect(screen.getByRole('tab', { name: 'Scenarios' })).toHaveAttribute('aria-selected', 'true');
    rerender(<SubTabs step="remediation" onStep={() => {}} />);
    expect(screen.getAllByRole('tab').map(t => t.textContent)).toEqual(['Fix actions', 'Auto-remediation']);
    rerender(<SubTabs step="scan" onStep={() => {}} />);
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    rerender(<SubTabs step="dashboard" onStep={() => {}} />);
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  it('opens the chosen page', async () => {
    const onStep = vi.fn();
    render(<SubTabs step="findings" onStep={onStep} />);
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Scoring' }));
    expect(onStep).toHaveBeenCalledWith('scoring');
  });
});
