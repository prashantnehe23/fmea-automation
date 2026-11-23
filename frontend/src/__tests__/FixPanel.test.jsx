import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal()), proposeFix: vi.fn(), recordFixDecision: vi.fn() }));
import * as api from '../api';
import FixPanel from '../components/FixPanel';
import { ActionList } from '../pages/MitigationsPage';

const action = { id: 'c1', title: 'Use parameterised queries', kind: 'code_fix', owner_role: 'developer', urgency: 'now' };
const proposal = {
  edits: [
    { file: 'public.py', start_line: 9, end_line: 9, original: "    r = requests.get(url)", replacement: "    r = safe_get(url)" },
    { file: 'internal_admin.py', start_line: 7, end_line: 8, original: "def wipe():\n    return ok", replacement: "def wipe():\n    require_token()\n    return ok" },
  ],
  dropped: [], diff: '--- a/public.py\n+++ b/public.py\n@@ -9 +9 @@\n-    r = requests.get(url)\n+    r = safe_get(url)\n',
  parse_errors: [], context: 'cited', test_code: 'def test_x():\n    assert True', test_description: 'checks it', reason: 'limits where the preview may fetch',
};
const decided = { decision: 'accepted', diff: '--- a/public.py\n+++ b/public.py\n-final\n+final2\n', diff_sha256: 'a'.repeat(64), parse_errors: [] };

function open(extra = {}) {
  const onClose = vi.fn();
  render(<FixPanel workspaceId={3} scanId={5} failureMode="SQL Injection" action={action} onClose={onClose} {...extra} />);
  return onClose;
}

describe('Remediate button and fix review panel (B-053, B-056)', () => {
  beforeEach(() => { vi.clearAllMocks(); api.proposeFix.mockResolvedValue(proposal); api.recordFixDecision.mockResolvedValue(decided); });

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

  it('asks for the fix by project and saved scan, and shows the reason, one section per file and the diff', async () => {
    open();
    expect(api.proposeFix).toHaveBeenCalledWith(3, 5, 'SQL Injection', 'c1');
    expect(await screen.findByText(/limits where the preview may fetch/)).toBeInTheDocument();
    expect(screen.getByLabelText('Replacement for public.py lines 9-9')).toHaveValue('    r = safe_get(url)');
    expect(screen.getByLabelText('Replacement for internal_admin.py lines 7-8')).toHaveValue(proposal.edits[1].replacement);
    expect(screen.getByText(/^\+ r = safe_get\(url\)$/)).toBeInTheDocument();
  });

  it('accepts the fix as proposed, records the exact edits, and shows the final diff to copy or download as a patch', async () => {
    open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalledWith(3, 5, 'SQL Injection', 'c1', 'accepted',
      proposal.edits.map(({ file, start_line, end_line, replacement }) => ({ file, start_line, end_line, replacement }))));
    expect(await screen.findByText(/\+final2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy diff' })).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Download patch' });
    expect(link).toHaveAttribute('download', 'fix.patch');
    expect(decodeURIComponent(link.getAttribute('href'))).toContain('+final2');
  });

  it('records an edited fix as edited, with the person\'s text', async () => {
    open();
    const user = userEvent.setup();
    const box = await screen.findByLabelText('Replacement for public.py lines 9-9');
    await user.type(box, ' # reviewed');
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalled());
    const [, , , , decision, edits] = api.recordFixDecision.mock.calls[0];
    expect(decision).toBe('edited');
    expect(edits[0].replacement).toBe('    r = safe_get(url) # reviewed');
  });

  it('rejects a fix: records it with no edits and closes', async () => {
    const onClose = open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(api.recordFixDecision).toHaveBeenCalledWith(3, 5, 'SQL Injection', 'c1', 'rejected', []));
    expect(onClose).toHaveBeenCalled();
  });

  it('keeps the panel open and shows the reason when recording a decision fails', async () => {
    api.recordFixDecision.mockRejectedValue(new Error('Those edits do not fit the stored files.'));
    const onClose = open();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Accept' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('do not fit');
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument();
  });

  it('warns about a guessed context, dropped edits and code that no longer parses', async () => {
    api.proposeFix.mockResolvedValue({ ...proposal, context: 'guess', parse_errors: ['public.py'],
                                       dropped: [{ file: 'x.py', reason: 'the file was not shown to the model' }] });
    open();
    expect(await screen.findByText(/chosen by a keyword guess/i)).toBeInTheDocument();
    expect(screen.getByText(/public\.py no longer parses/i)).toBeInTheDocument();
    expect(screen.getByText(/x\.py: the file was not shown to the model/)).toBeInTheDocument();
  });

  it('shows the reason when no fix can be proposed, and offers no decision', async () => {
    api.proposeFix.mockRejectedValue(new Error('The source code of this scan is no longer stored (source retention).'));
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('no longer stored');
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
  });

  it('records a decision once even when Accept is pressed twice quickly', async () => {
    let release;
    api.recordFixDecision.mockReturnValue(new Promise(r => { release = () => r(decided); }));
    open();
    const user = userEvent.setup();
    const accept = await screen.findByRole('button', { name: 'Accept' });
    await user.click(accept);
    await user.click(accept);
    release();
    await screen.findByText(/recorded in the audit trail/);
    expect(api.recordFixDecision).toHaveBeenCalledTimes(1);
  });

  it('shows an insertion as an insertion, not as lines 6-5', async () => {
    api.proposeFix.mockResolvedValue({ ...proposal, edits: [{ file: 'public.py', start_line: 6, end_line: 5, original: '', replacement: 'import os' }] });
    open();
    expect(await screen.findByText(/insert before line 6/)).toBeInTheDocument();
  });
});
