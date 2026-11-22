import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
  getFindings: vi.fn(),
  setFindingState: vi.fn(),
}));

import { getFindings, setFindingState } from '../api';
import FindingsPage from '../pages/FindingsPage';

const sql = {
  id: 1, name: 'SQL injection in login', comp: 'src/auth.py', s: 9, o: 5, d: 6, rpn: 270, priority: 'Critical',
  priority_reason: 'Critical: RPN 270', impact: 'Attackers read every customer record', blast_radius: 'All customers',
  trigger: 'A crafted login request', evidence: 'src/auth.py:12 `q = "SELECT * FROM users WHERE n=" + name`',
  attack_chain: ['Send a quote in the name', 'Query runs with attacker text'],
  justification: 'No parameterised queries anywhere in the module', severity_rationale: 'Full read of the user table',
  occurrence_rationale: 'Public endpoint', detection_rationale: 'No query logging',
  verdict: 'Realistic and complete', confidence: 0.82, challenges: ['Is the endpoint behind a gateway?'],
  controls: { validation: 'none' }, gaps: ['No parameterised queries'], control_maturity: 'low',
  root_cause: 'security', root_cause_also: ['engineering'],
  root_cause_chain: { symptom: 'Login returns other users', proximate_cause: 'String-built query', root_cause: 'No data-access rules' },
  cwe: 'CWE-89', source: 'fmea', also_reported_by: ['CodeQL'],
  corrective: [{ id: 'c1', title: 'Parameterise the query', detail: 'Use bound parameters', kind: 'code_fix', target: 'src/auth.py',
                 verification: 'A test sends a quote and gets no rows', owner_role: 'developer', urgency: 'now' }],
  preventive: [{ id: 'p1', title: 'Ban string-built SQL in CI', detail: '', kind: 'guardrail', target: 'CI', verification: '', owner_role: 'developer', urgency: 'next' }],
};
const lowRpnCatastrophe = {
  ...sql, id: 2, name: 'Backup deletion by any admin', comp: 'ops', s: 10, o: 2, d: 2, rpn: 40, priority: 'High',
  priority_reason: 'High: severity 10 floor, RPN 40 alone would be Medium', cwe: 'unmapped', root_cause: 'operational',
  root_cause_chain: null, evidence: '', corrective: [], preventive: [], source: 'import:Semgrep OSS', also_reported_by: [],
};
const minor = { ...sql, id: 3, name: 'Verbose error page', comp: 'web', s: 3, o: 4, d: 3, rpn: 36, priority: 'Low', priority_reason: 'Low: RPN 36',
                evidence: '', corrective: [], preventive: [], root_cause: 'engineering', root_cause_chain: null, source: 'fmea', also_reported_by: [] };
const oldScan = { ...minor, id: 4, name: 'From an old scan', priority_reason: undefined, root_cause: undefined, cwe: undefined, source: undefined,
                  corrective: undefined, preventive: undefined, root_cause_chain: undefined, also_reported_by: undefined };

const findingsData = {
  findings: [{ failure_mode: 'SQL injection in login', state: 'confirmed' }, { failure_mode: 'Backup deletion by any admin', state: 'fix_candidate' }],
  events: [{ failure_mode: 'SQL injection in login', from_state: 'new', to_state: 'confirmed', actor: 'scan', note: '', at: '2026-11-20T10:00:00' }],
};

const renderPage = (props = {}) => render(
  <FindingsPage persona="security_engineer" sel={{ projectId: 1 }} scope="project" hierarchy={[]}
                liveRisks={[minor, sql, lowRpnCatastrophe]} workspaceId={7} canDecideFindings={false} {...props} />,
);

beforeEach(() => {
  vi.clearAllMocks();
  getFindings.mockResolvedValue(findingsData);
  setFindingState.mockResolvedValue({});
});

describe('the findings list', () => {
  it('shows a watchlist with every severity 9+ finding, even when its RPN is low, with the reason for its band', () => {
    renderPage();
    const watch = screen.getByRole('region', { name: 'Watchlist: severity 9 and above' });
    expect(within(watch).getByRole('button', { name: /SQL injection in login/ })).toBeInTheDocument();
    expect(within(watch).getByRole('button', { name: /Backup deletion by any admin/ })).toBeInTheDocument();
    expect(within(watch).queryByText(/Verbose error page/)).not.toBeInTheDocument();
    expect(within(watch).getByText(/severity 10 floor, RPN 40 alone would be Medium/)).toBeInTheDocument();
  });

  it('lists all findings with the highest priority first', () => {
    renderPage();
    const all = screen.getByRole('region', { name: 'All findings' });
    const names = within(all).getAllByRole('button').map(b => b.textContent);
    expect(names[0]).toMatch(/SQL injection/);
    expect(names[names.length - 1]).toMatch(/Verbose error page/);
  });

  it('filters by priority with a labelled control', async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText('Filter by priority'), 'Low');
    const all = screen.getByRole('region', { name: 'All findings' });
    expect(within(all).getAllByRole('button')).toHaveLength(1);
    expect(within(all).getByRole('button', { name: /Verbose error page/ })).toBeInTheDocument();
  });

  it('says what to do when there is no scan data', () => {
    renderPage({ liveRisks: [] });
    expect(screen.getByText(/Run a scan on this project/)).toBeInTheDocument();
  });

  it('renders findings from scans stored before root cause, CWE, source and actions existed', () => {
    renderPage({ liveRisks: [oldScan] });
    expect(screen.getByRole('button', { name: /From an old scan/ })).toBeInTheDocument();
  });
});

describe('one finding, fully reviewable', () => {
  it('shows evidence, score with reason, root cause, fix actions, source and history in one view', async () => {
    renderPage();
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);
    const detail = screen.getByRole('region', { name: 'Finding detail' });
    const d = within(detail);
    expect(d.getByRole('heading', { name: 'SQL injection in login' })).toBeInTheDocument();
    expect(d.getByText('CWE-89')).toBeInTheDocument();
    expect(d.getByText(/Attackers read every customer record/)).toBeInTheDocument();          // impact in words
    expect(d.getByText(/Catastrophic/)).toBeInTheDocument();                                     // severity in words
    expect(d.getByText('Critical: RPN 270')).toBeInTheDocument();                                // why this priority
    expect(d.getByText(/src\/auth\.py:12/)).toBeInTheDocument();                                  // evidence
    expect(d.getByText(/Full read of the user table/)).toBeInTheDocument();                       // why this score
    expect(d.getByText(/Realistic and complete/)).toBeInTheDocument();
    expect(d.getByText(/No data-access rules/)).toBeInTheDocument();                              // root cause chain
    expect(d.getByText('Parameterise the query')).toBeInTheDocument();                            // fix
    expect(d.getByText(/A test sends a quote and gets no rows/)).toBeInTheDocument();
    expect(d.getByText(/also reported by CodeQL/i)).toBeInTheDocument();                          // source
    await waitFor(() => expect(d.getByText(/new → confirmed/)).toBeInTheDocument());             // history
    expect(d.getByText(/Confirmed/)).toBeInTheDocument();                                         // current state
  });

  it('shows an imported finding with its source and without inventing evidence', async () => {
    renderPage();
    await userEvent.click(screen.getAllByRole('button', { name: /Backup deletion by any admin/ })[0]);
    const d = within(screen.getByRole('region', { name: 'Finding detail' }));
    expect(d.getByText(/Imported · Semgrep OSS/)).toBeInTheDocument();
    expect(d.getByText(/No code evidence was recorded/)).toBeInTheDocument();
    expect(d.getByText('CWE unmapped')).toBeInTheDocument();
  });

  it('falls back to the band alone for an old scan, without an error', async () => {
    renderPage({ liveRisks: [oldScan] });
    await userEvent.click(screen.getByRole('button', { name: /From an old scan/ }));
    const d = within(screen.getByRole('region', { name: 'Finding detail' }));
    expect(d.getByText(/Low/)).toBeInTheDocument();
    expect(d.getByText(/Not classified/)).toBeInTheDocument();
  });

  it('offers state changes only to people who may decide, and sends the change', async () => {
    const { unmount } = renderPage();
    await userEvent.click(screen.getAllByRole('button', { name: /Backup deletion by any admin/ })[0]);
    expect(screen.queryByRole('button', { name: 'Mark fixed' })).not.toBeInTheDocument();
    unmount();

    renderPage({ canDecideFindings: true });
    await userEvent.click(screen.getAllByRole('button', { name: /Backup deletion by any admin/ })[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Mark fixed' }));
    expect(setFindingState).toHaveBeenCalledWith(7, 'Backup deletion by any admin', 'fixed');
    await waitFor(() => expect(getFindings).toHaveBeenCalledTimes(3));                              // reloaded after the change
  });

  it('shows an error from a failed state change', async () => {
    setFindingState.mockRejectedValue(new Error('Only administrators can do that.'));
    renderPage({ canDecideFindings: true });
    await userEvent.click(screen.getAllByRole('button', { name: /Backup deletion by any admin/ })[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Accept risk' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only administrators can do that.');
  });
});


describe('review follow-ups', () => {
  it('does not offer the state a finding is already in', async () => {
    renderPage({ canDecideFindings: true });
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);       // confirmed
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark fixed' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Still present' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept risk' })).toBeInTheDocument();
  });

  it('clears an error message when another finding is selected', async () => {
    setFindingState.mockRejectedValue(new Error('Only administrators can do that.'));
    renderPage({ canDecideFindings: true });
    await userEvent.click(screen.getAllByRole('button', { name: /Backup deletion by any admin/ })[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Accept risk' }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('starts clean when the project changes and ignores a late answer for the old one', async () => {
    let resolveOld;
    getFindings.mockImplementationOnce(() => new Promise(res => { resolveOld = res; }));
    const view = renderPage();
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);
    expect(screen.getByRole('region', { name: 'Finding detail' })).toBeInTheDocument();
    getFindings.mockResolvedValue({ findings: [{ failure_mode: 'SQL injection in login', state: 'accepted' }], events: [] });
    view.rerender(<FindingsPage persona="security_engineer" sel={{ projectId: 2 }} scope="project" hierarchy={[]}
                                liveRisks={[sql]} workspaceId={8} canDecideFindings={false} />);
    expect(screen.queryByRole('region', { name: 'Finding detail' })).not.toBeInTheDocument();       // selection did not carry over
    resolveOld({ findings: [{ failure_mode: 'SQL injection in login', state: 'fixed' }], events: [] });   // project 7 answers late
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);
    await waitFor(() => expect(within(screen.getByRole('region', { name: 'Finding detail' })).getByText(/Risk accepted/)).toBeInTheDocument());
  });

  it('moves focus to the finding when it is selected', async () => {
    renderPage();
    await userEvent.click(screen.getAllByRole('button', { name: /SQL injection in login/ })[0]);
    expect(screen.getByRole('heading', { name: 'SQL injection in login' })).toHaveFocus();
  });

  it('offers only the priorities that exist in the data', () => {
    renderPage();
    const options = within(screen.getByLabelText('Filter by priority')).getAllByRole('option').map(o => o.textContent);
    expect(options).toEqual(['All priorities', 'Critical', 'High', 'Low']);
  });
});
