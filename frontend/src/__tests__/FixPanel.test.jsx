import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal()), proposeFix: vi.fn(), recordFixDecision: vi.fn() }));
import * as api from '../api';
import FixPanel from '../components/FixPanel';
import { ActionList } from '../pages/MitigationsPage';

const action = { id: 'c1', title: 'Use parameterised queries', kind: 'code_fix', owner_role: 'developer', urgency: 'now' };
const proposal = { code_diff: '--- original\n+++ patched\n-bad()\n+good()', test_code: 'def test_x():\n    assert True',
                   test_description: 'checks it', patched_snippet: 'def get_user(x):\n    return good()\n' };

function open(extra = {}) {
  const onClose = vi.fn();
  render(<FixPanel scanId={5} failureMode="SQL Injection" action={action} onClose={onClose} {...extra} />);
  return onClose;
}

describe('Remediate button and fix review panel (B-053)', () => {
  beforeEach(() => { vi.clearAllMocks(); api.proposeFix.mockResolvedValue(proposal); api.recordFixDecision.mockResolvedValue({}); });

  it('puts a Remediate button on every action when a handler is given, and none otherwise', async () => {
    const onRemediate = vi.fn();
    const { rerender } = render(<ActionList title="Corrective" color="" actions={[action, { ...action, id: 'p1', title: 'Add a rule' }]} onRemediate={onRemediate} />);
    const buttons = screen.getAllByRole('button', { name: 'Remediate' });
    expect(buttons).toHaveLength(2);
    await userEvent.setup().click(buttons[1]);
    expect(onRemediate).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }));
    rerender(<ActionList title="Corrective" color="" actions={[action]} />);
    expect(screen.queryByRole('button', { name: 'Remediate' })).not.toBeInTheDocument();
  });

  it('asks for the fix for the chosen action and shows the diff and the code', async () => {
    open();
    expect(api.proposeFix).toHaveBeenCalledWith(5, 'SQL Injection', 'c1');
    expect(await screen.findByText(/\+good\(\)/)).toBeInTheDocument();
    expect(screen.getByLabelText('Fixed code')).toHaveValue(proposal.patched_snippet);
  });

  it('accepts the fix as proposed, records it, and offers the code to copy or download', async () => {
    open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalledWith(5, 'SQL Injection', 'c1', 'accepted'));
    expect(await screen.findByRole('button', { name: 'Copy code' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download patch' })).toHaveAttribute('download');
  });

  it('records an edited fix as edited, and keeps the edit', async () => {
    open();
    const user = userEvent.setup();
    const box = await screen.findByLabelText('Fixed code');
    await user.type(box, '# reviewed');
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalledWith(5, 'SQL Injection', 'c1', 'edited'));
    expect(screen.getByLabelText('Fixed code').value).toContain('# reviewed');
  });

  it('rejects a fix: records it, hands back nothing and closes', async () => {
    const onClose = open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalledWith(5, 'SQL Injection', 'c1', 'rejected'));
    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Copy code' })).not.toBeInTheDocument();
  });

  it('shows the reason when no fix can be proposed, and offers no decision', async () => {
    api.proposeFix.mockRejectedValue(new Error('This scan is no longer available on the server.'));
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('no longer available');
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
  });
});
