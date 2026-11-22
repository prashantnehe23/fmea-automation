import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal()), getFindingChanges: vi.fn().mockResolvedValue(null) }));
import ScanPage from '../pages/ScanPage';

const project = (repoUrl) => ({ id: 'p1', name: 'sdk', repoUrl });
const hierarchy = (repoUrl) => [{ id: 'g1', name: 'Big', projects: [project(repoUrl)] }];
const sel = { portfolioId: 'g1', projectId: 'p1' };
const lastScan = { scanId: 7, risk_count: 7, registry_locked: true, locked_count: 7, workspace_id: 1, timestamp: '2026-10-19T10:00:00' };
const DEEP = /Deep scan/;

function page(repoUrl, scanHistory = {}) {
  render(<ScanPage persona="security" sel={sel} scope="project" hierarchy={hierarchy(repoUrl)} scanHistory={scanHistory}
                   onScanComplete={() => {}} onUpdateProjectRepo={() => {}} onOpenSettings={() => {}} canDecideFindings />);
}

describe('Deep scan option (B-028)', () => {
  it('is offered for a project that was never scanned', () => {
    page('https://github.com/a/b');
    expect(screen.getByLabelText(DEEP)).toBeInTheDocument();
  });

  it('is offered for a project that was scanned before, where only a rescan is possible', () => {
    page('https://github.com/a/b', { p1: lastScan });
    expect(screen.getByLabelText(DEEP)).toBeInTheDocument();
  });

  it('is offered next to pasted code, with or without a linked repository', async () => {
    page('', {});
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /paste code directly/i }));
    expect(screen.getByLabelText(DEEP)).toBeInTheDocument();
  });
});
