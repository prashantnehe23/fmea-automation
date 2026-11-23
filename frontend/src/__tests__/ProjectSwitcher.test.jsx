import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import ProjectSwitcher from '../components/ProjectSwitcher';
import Sidebar from '../components/Sidebar';

const hierarchy = [
  { id: 'p1', name: 'Big', projects: [{ id: 'pr1', name: 'sdk', repoUrl: 'https://github.com/a/b' }, { id: 'pr2', name: 'Chain API', repoUrl: '' }] },
  { id: 'p2', name: 'Payments', projects: [{ id: 'pr3', name: 'Ledger', repoUrl: '' }] },
];
const EMPTY = { portfolioId: null, projectId: null, componentId: null, componentName: null };

function setup(persona, sel = EMPTY, extra = {}) {
  const onSelect = vi.fn(); const onAddProject = vi.fn(); const onAddPortfolio = vi.fn();
  render(<ProjectSwitcher persona={persona} sel={sel} hierarchy={hierarchy} scanHistory={{}} onSelect={onSelect}
                          onAddProject={onAddProject} onAddPortfolio={onAddPortfolio} {...extra} />);
  return { onSelect, onAddProject, onAddPortfolio, user: userEvent.setup() };
}
const open = (user) => user.click(screen.getByRole('button', { name: /Project switcher|Choose a project|All portfolios|Big|sdk|Chain API|Payments|Ledger/ }));

describe('Project switcher (B-054 step 3, ADR-034)', () => {
  it('shows where you are on its button and opens a searchable list grouped by portfolio', async () => {
    const { user } = setup('security_engineer', { ...EMPTY, portfolioId: 'p1', projectId: 'pr1' });
    const button = screen.getByRole('button', { name: /Big \/ sdk/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await user.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('searchbox', { name: 'Search projects' })).toBeInTheDocument();
    for (const name of ['sdk', 'Chain API', 'Ledger']) expect(screen.getByRole('button', { name })).toBeInTheDocument();
  });

  it('selects a project with its portfolio, with no component, and closes', async () => {
    const { user, onSelect } = setup('security_engineer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await user.click(screen.getByRole('button', { name: 'Ledger' }));
    expect(onSelect).toHaveBeenCalledWith({ portfolioId: 'p2', projectId: 'pr3', componentId: null, componentName: null });
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('filters by what is typed, matching project and portfolio names', async () => {
    const { user } = setup('security_engineer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await user.type(screen.getByRole('searchbox'), 'chain');
    expect(screen.getByRole('button', { name: 'Chain API' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ledger' })).not.toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox'));
    await user.type(screen.getByRole('searchbox'), 'payments');
    expect(screen.getByRole('button', { name: 'Ledger' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'sdk' })).not.toBeInTheDocument();
  });

  it('offers all projects of a portfolio only to a role that works at portfolio level', async () => {
    const eng = setup('security_engineer');
    await eng.user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await eng.user.click(screen.getByRole('button', { name: 'All projects in Big' }));
    expect(eng.onSelect).toHaveBeenCalledWith({ portfolioId: 'p1', projectId: null, componentId: null, componentName: null });
  });

  it('does not offer portfolio or organisation views to a developer', async () => {
    const { user } = setup('developer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    expect(screen.queryByRole('button', { name: /All projects in/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'All portfolios' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'sdk' })).toBeInTheDocument();
  });

  it('offers all portfolios to a risk manager and only portfolios (no projects) to an executive', async () => {
    const rm = setup('risk_manager', { ...EMPTY, portfolioId: 'p1' });
    await rm.user.click(screen.getByRole('button', { name: /Big/ }));
    await rm.user.click(screen.getByRole('button', { name: 'All portfolios' }));
    expect(rm.onSelect).toHaveBeenCalledWith(EMPTY);
  });

  it('shows an executive the portfolios and no projects', async () => {
    const { user } = setup('executive', { ...EMPTY, portfolioId: 'p1' });
    await user.click(screen.getByRole('button', { name: /Big/ }));
    expect(screen.getByRole('button', { name: 'All projects in Payments' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'sdk' })).not.toBeInTheDocument();
  });

  it('adds a project to a portfolio and a new portfolio from the list', async () => {
    const { user, onAddProject, onAddPortfolio } = setup('security_engineer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await user.click(screen.getAllByRole('button', { name: /New project/ })[0]);
    await user.type(screen.getByPlaceholderText('Project name'), 'Billing');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(onAddProject).toHaveBeenCalledWith('p1', 'Billing', '', 'Tier 1', 'external_customers');

    await user.click(screen.getByRole('button', { name: /Choose a project|Project switcher|Big/ }));
    await user.click(screen.getByRole('button', { name: /New portfolio/ }));
    await user.type(screen.getByPlaceholderText('Portfolio name'), 'Risk');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(onAddPortfolio).toHaveBeenCalledWith('Risk');
  });

  it('says so when nothing matches, and when there are no projects at all', async () => {
    const { user } = setup('security_engineer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await user.type(screen.getByRole('searchbox'), 'zzz');
    expect(screen.getByText('No project matches')).toBeInTheDocument();
  });

  it('closes with Escape', async () => {
    const { user } = setup('security_engineer');
    await user.click(screen.getByRole('button', { name: /Choose a project/ }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });
});

describe('Left pane without the tree and the View level buttons (ADR-034 points 2 and 6)', () => {
  it('has the switcher and no View level or Workspace tree', () => {
    render(<Sidebar persona="security_engineer" step="scan" sel={EMPTY} scope="project" hierarchy={hierarchy} scanHistory={{}} onPersona={() => {}}
                    onStep={() => {}} onSelect={() => {}} onAddPortfolio={() => {}} onAddProject={() => {}} onOpenSettings={() => {}}
                    user={{ display_name: 'T', role: 'admin' }} canSwitchPersona={false} onLogout={() => {}} />);
    expect(screen.queryByText(/View level/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Workspace$/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^(📄|🗂️|📁)?\s*(Component|Project|Portfolio)$/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Choose a project/ })).toBeInTheDocument();
  });
});
