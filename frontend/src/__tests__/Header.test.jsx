import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
  getModels: vi.fn(), getProviders: vi.fn(), setActiveModel: vi.fn(), setProviderKey: vi.fn(), deleteProviderKey: vi.fn(),
  setProviderEndpoint: vi.fn(), addCustomModel: vi.fn(), getReasoning: vi.fn(), setReasoning: vi.fn(), verifyProviderKey: vi.fn(),
  listRepoCredentials: vi.fn(), saveRepoCredential: vi.fn(), deleteRepoCredential: vi.fn(),
}));
import * as api from '../api';
import Header from '../components/Header';
import { PERSONAS, PROCESS_STEPS } from '../data';

const model = { id: 'mistral-large-4', provider: 'mistral', display: 'Large 4', tier: 'Power', is_active: true, key_set: true,
                prompt_per_1m: 1, completion_per_1m: 2, rates_known: true, reasoning_levels: [] };
const provider = (extra = {}) => ({ id: 'mistral', display: 'Mistral AI', key_hint: '…abcd', source: 'settings', status: 'valid', ...extra });

function setup(providerRow) {
  api.getModels.mockResolvedValue([model]);
  api.getProviders.mockResolvedValue([providerRow]);
  api.getReasoning.mockResolvedValue({ level: 'off' });
  api.listRepoCredentials.mockResolvedValue([]);
  api.setProviderKey.mockResolvedValue({});
  api.setActiveModel.mockResolvedValue({});
  render(<Header persona={PERSONAS[0].id} step={PROCESS_STEPS[0].id} sel={{}} scope="project" settingsOpen onSettingsOpenChange={() => {}} isAdmin={false} />);
}

describe('API key in Settings (B-048 follow-up)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lets the user replace a key that is already set and valid', async () => {
    setup(provider());
    const user = userEvent.setup();
    expect(screen.queryByPlaceholderText('Mistral AI API key')).not.toBeInTheDocument();     // no input while the key is fine
    await user.click(await screen.findByRole('button', { name: 'Replace' }));
    await user.type(screen.getByPlaceholderText('Mistral AI API key'), 'new-key-1234');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.setProviderKey).toHaveBeenCalledWith('mistral', 'new-key-1234'));
    await waitFor(() => expect(screen.queryByPlaceholderText('Mistral AI API key')).not.toBeInTheDocument());   // closed after saving
  });

  it('keeps the old key when the replacement is cancelled', async () => {
    setup(provider());
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Replace' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByPlaceholderText('Mistral AI API key')).not.toBeInTheDocument();
    expect(api.setProviderKey).not.toHaveBeenCalled();
  });

  it('offers Replace for a key that comes from an environment variable too', async () => {
    setup(provider({ source: 'env' }));
    expect(await screen.findByRole('button', { name: 'Replace' })).toBeInTheDocument();
  });

  it('puts the key controls straight under the model choice, before reasoning, and keeps the rarely used settings under Advanced', async () => {
    setup(provider());
    const replace = await screen.findByRole('button', { name: 'Replace' });
    const model = screen.getByRole('combobox');
    const reasoning = screen.queryByText('Reasoning');
    expect(model.compareDocumentPosition(replace) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    if (reasoning) expect(replace.compareDocumentPosition(reasoning) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const advanced = screen.getByText('Advanced').closest('details');
    expect(advanced).not.toHaveAttribute('open');
    expect(advanced).toHaveTextContent('Clear Local Data');
    expect(screen.queryByText('Risk Registry')).not.toBeInTheDocument();      // a static "Active" label carried no information
  });
});

describe('Header (B-054 step 1)', () => {
  it('no longer numbers the pages as steps of a process', () => {
    api.getModels.mockResolvedValue([]); api.getProviders.mockResolvedValue([]); api.getReasoning.mockResolvedValue({ level: 'off' });
    render(<Header persona={PERSONAS[0].id} step={PROCESS_STEPS[0].id} sel={{}} scope="project" settingsOpen={false} onSettingsOpenChange={() => {}} isAdmin={false} />);
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
  });
});
