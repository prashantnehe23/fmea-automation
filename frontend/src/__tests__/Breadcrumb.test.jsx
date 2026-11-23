import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api', () => ({
  getModels: vi.fn().mockResolvedValue([]), getProviders: vi.fn().mockResolvedValue([]), setActiveModel: vi.fn(), setProviderKey: vi.fn(),
  deleteProviderKey: vi.fn(), setProviderEndpoint: vi.fn(), addCustomModel: vi.fn(), getReasoning: vi.fn().mockResolvedValue({ level: 'off' }),
  setReasoning: vi.fn(), verifyProviderKey: vi.fn(), listRepoCredentials: vi.fn().mockResolvedValue([]), saveRepoCredential: vi.fn(), deleteRepoCredential: vi.fn(),
}));
import Header from '../components/Header';

const hierarchy = [{ id: 'p1', name: 'Big', projects: [{ id: 'pr1', name: 'sdk' }] }];
const components = [{ name: 'public.py', count: 3 }, { name: 'internal_admin.py', count: 1 }];
const sel = (projectId = null, componentName = null) => ({ portfolioId: 'p1', projectId, componentId: null, componentName });

function head(persona, selection, extra = {}) {
  const onSelect = vi.fn();
  render(<Header persona={persona} step="findings" sel={selection} scope="project" hierarchy={hierarchy} components={components}
                 onSelect={onSelect} settingsOpen={false} onSettingsOpenChange={() => {}} isAdmin={false} {...extra} />);
  return { onSelect, user: userEvent.setup() };
}

describe('Breadcrumb and component picker (B-054 step 3, ADR-034 point 2)', () => {
  it('shows Portfolio / Project from the live hierarchy', () => {
    head('security_engineer', sel('pr1'));
    const nav = screen.getByRole('navigation', { name: 'Where you are' });
    expect(nav).toHaveTextContent('Big');
    expect(nav).toHaveTextContent('sdk');
  });

  it('offers All components and each component the findings cite, for a role with component depth', async () => {
    const { onSelect, user } = head('security_engineer', sel('pr1'));
    const picker = screen.getByRole('combobox', { name: 'Component' });
    expect([...picker.options].map(o => o.textContent)).toEqual(['All components', 'public.py (3)', 'internal_admin.py (1)']);
    await user.selectOptions(picker, 'public.py');
    expect(onSelect).toHaveBeenCalledWith({ portfolioId: 'p1', projectId: 'pr1', componentId: null, componentName: 'public.py' });
  });

  it('goes back to the whole project with All components', async () => {
    const { onSelect, user } = head('security_engineer', sel('pr1', 'public.py'));
    expect(screen.getByRole('combobox', { name: 'Component' })).toHaveValue('public.py');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Component' }), 'All components');
    expect(onSelect).toHaveBeenCalledWith({ portfolioId: 'p1', projectId: 'pr1', componentId: null, componentName: null });
  });

  it('has no All components choice for a role that works only at component level', () => {
    head('developer', sel('pr1', 'public.py'));
    const picker = screen.getByRole('combobox', { name: 'Component' });
    expect([...picker.options].map(o => o.textContent)).toEqual(['public.py (3)', 'internal_admin.py (1)']);
  });

  it('shows no picker for a role without component depth, with no project, or with no components', () => {
    const { unmount } = render(<Header persona="risk_manager" step="findings" sel={sel('pr1')} scope="project" hierarchy={hierarchy} components={components}
                                       onSelect={() => {}} settingsOpen={false} onSettingsOpenChange={() => {}} isAdmin={false} />);
    expect(screen.queryByRole('combobox', { name: 'Component' })).not.toBeInTheDocument();
    unmount();
    head('security_engineer', sel(null));
    expect(screen.queryByRole('combobox', { name: 'Component' })).not.toBeInTheDocument();
  });

  it('shows no picker when the scan cites no file', () => {
    head('security_engineer', sel('pr1'), { components: [] });
    expect(screen.queryByRole('combobox', { name: 'Component' })).not.toBeInTheDocument();
  });

  it('starts at All portfolios when nothing is selected', () => {
    head('risk_manager', { portfolioId: null, projectId: null, componentId: null, componentName: null }, { scope: 'org' });
    expect(screen.getByRole('navigation', { name: 'Where you are' })).toHaveTextContent('All portfolios');
  });
});
