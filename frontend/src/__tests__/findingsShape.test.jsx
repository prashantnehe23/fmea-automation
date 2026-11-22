import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api', async importOriginal => ({ ...(await importOriginal()), getFindings: vi.fn().mockResolvedValue({ findings: [], events: [] }), setFindingState: vi.fn() }));

import { normalizeScanResult } from '../api';
import FindingsPage from '../pages/FindingsPage';

// The server's own result shape, run through the app's own mapping, so a change on either side shows up here.
const apiResult = {
  failures: [{ failure_mode: 'Backup deletion', attack_chain: ['Any admin deletes the backups'], business_impact: 'Data cannot be restored',
               blast_radius: 'Whole company', trigger: 'A mistaken or malicious admin', evidence: 'ops/backup.py:8 `os.remove(path)`',
               source: 'import:CodeQL', cwe: 'CWE-285', also_reported_by: ['Semgrep OSS'] }],
  risks: [{ failure_mode: 'Backup deletion', severity: 10, occurrence: 2, detection: 2, rpn: 40, priority: 'High',
            priority_reason: 'High: severity 10 floor, RPN 40 alone would be Medium', justification: 'No separation of duties',
            severity_rationale: 'Total loss', occurrence_rationale: 'Rare', detection_rationale: 'Logged' }],
  controls: [{ failure_mode: 'Backup deletion', controls: { access: 'admin role' }, control_maturity: 'low', gaps: ['No second approver'] }],
  validations: [{ failure_mode: 'Backup deletion', is_realistic: true, attack_chain_complete: true, confidence: 0.9, verdict: 'Plausible', challenges: [] }],
  remediations: [{ failure_mode: 'Backup deletion', corrective: [{ id: 'c1', title: 'Require two approvals', detail: '', kind: 'config_change', target: 'backup policy',
                                                                  verification: 'A single admin cannot delete', owner_role: 'sre', urgency: 'now' }], preventive: [] }],
  root_causes: [{ failure_mode: 'Backup deletion', primary: 'operational', contributing: [], symptom: 'Backups can be deleted',
                  proximate_cause: 'One role may delete', root_cause: 'No separation of duties', confidence: 0.8, cwe: 'CWE-285' }],
  scenario_linkage: { explanations: [] }, new_scenarios: [],
};

describe('the findings page with the real result shape', () => {
  it('shows what the server sent, after the app maps it', async () => {
    const risks = normalizeScanResult(apiResult, { portfolioId: 'p', projectId: 'x' });
    render(<FindingsPage persona="security_engineer" sel={{ projectId: 1 }} scope="project" hierarchy={[]} liveRisks={risks} workspaceId={3} />);
    const watch = screen.getByRole('region', { name: 'Watchlist: severity 9 and above' });
    expect(within(watch).getByText(/severity 10 floor/)).toBeInTheDocument();
    await userEvent.click(within(watch).getByRole('button', { name: /Backup deletion/ }));
    const d = within(screen.getByRole('region', { name: 'Finding detail' }));
    expect(d.getByText(/Data cannot be restored/)).toBeInTheDocument();
    expect(d.getByText('CWE-285')).toBeInTheDocument();
    expect(d.getByText(/Imported · CodeQL/)).toBeInTheDocument();
    expect(d.getAllByText(/No separation of duties/)).toHaveLength(2);                 // in the score's reason and in the root cause chain
    expect(d.getByText('Require two approvals')).toBeInTheDocument();
    expect(d.getByText(/Plausible/)).toBeInTheDocument();
  });
});
