import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import Sidebar from '../components/Sidebar';
import { PERSONAS, PROCESS_STEPS, PERSONA_PRIMARY } from '../data';

function side(persona, onStep = () => {}) {
  render(<Sidebar persona={persona} step="scan" sel={{}} scope="project" hierarchy={[]} scanHistory={{}} onPersona={() => {}} onStep={onStep}
                  onSelect={() => {}} onScope={() => {}} onAddPortfolio={() => {}} onAddProject={() => {}}
                  user={{ display_name: 'Test', role: 'admin' }} canSwitchPersona={false} onLogout={() => {}} />);
}

describe('Process steps in the left pane (B-055)', () => {
  it.each(PERSONAS.map(p => p.id))('shows every step as available for %s: none dimmed, none dotted', (persona) => {
    side(persona);
    for (const s of PROCESS_STEPS) {
      const button = screen.getByRole('button', { name: new RegExp(s.label) });
      expect(button.className).not.toMatch(/text-gray-[34]00/);          // dimmed text read as disabled
      expect(button.textContent).not.toContain('·');
    }
  });

  it.each(PERSONAS.map(p => p.id))('marks only the main steps of %s', (persona) => {
    side(persona);
    const marked = PROCESS_STEPS.filter(s => screen.getByRole('button', { name: new RegExp(s.label) }).querySelector('[data-main-step]')).map(s => s.id);
    expect(marked.sort()).toEqual([...PERSONA_PRIMARY[persona]].sort());
  });

  it('opens any step for any role', async () => {
    const onStep = vi.fn();
    side('security_engineer', onStep);
    const user = userEvent.setup();
    for (const s of PROCESS_STEPS) await user.click(screen.getByRole('button', { name: new RegExp(s.label) }));
    expect(onStep.mock.calls.map(c => c[0])).toEqual(PROCESS_STEPS.map(s => s.id));
  });
});
