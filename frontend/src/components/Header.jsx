import { useState, useEffect } from 'react';
import { PERSONAS, PROCESS_STEPS, HIERARCHY, SCOPE_LABEL } from '../data';
import { ORG } from '../data';
import { getModels, setActiveModel, getProviders, setProviderKey, deleteProviderKey, setProviderEndpoint, addCustomModel, getReasoning, setReasoning, verifyProviderKey,
  listRepoCredentials, saveRepoCredential, deleteRepoCredential } from '../api';

const LEVEL_LABEL = { off: 'Off', low: 'Low', medium: 'Medium', high: 'High' };
const LEVEL_ORDER = ['off', 'low', 'medium', 'high'];

const KEY_STATUS = {
  valid:      { label: 'Key valid',        cls: 'text-green-600 bg-green-50' },
  invalid:    { label: 'Key rejected',     cls: 'text-red-600 bg-red-50' },
  unverified: { label: 'Not verified',     cls: 'text-amber-600 bg-amber-50' },
  unchecked:  { label: 'Not checked',      cls: 'text-gray-500 bg-gray-50' },
  missing:    { label: 'No key',           cls: 'text-red-600 bg-red-50' },
};

const TIER_BADGE = {
  Fast:     'bg-green-50 text-green-700',
  Standard: 'bg-blue-50 text-blue-700',
  Power:    'bg-purple-50 text-purple-700',
};

export default function Header({ persona, step, sel, scope, chatOpen, onToggleChat, settingsOpen, onSettingsOpenChange, isAdmin }) {
  const showSettings    = settingsOpen;
  const setShowSettings = onSettingsOpenChange;
  const [models, setModels]             = useState([]);
  const [activeModel, setActiveModelState] = useState(null);
  const [providers, setProviders]       = useState([]);
  const [keyInput, setKeyInput]         = useState('');
  const [keyError, setKeyError]         = useState('');
  const [replacingKey, setReplacingKey]  = useState(false);   // show the key box for a key that is already set
  const [reasoning, setReasoningState]  = useState('off');
  const [conn, setConn]                 = useState({ provider: 'local', endpoint: '', model: '', key: '' });   // B-047
  const [connError, setConnError]       = useState('');
  const [repoCreds, setRepoCreds]       = useState([]);     // B-043: [{owner, hint}]
  const [repoOwner, setRepoOwner]       = useState('');
  const [repoToken, setRepoToken]       = useState('');
  const [repoError, setRepoError]       = useState('');

  const refreshModels = () =>
    Promise.all([getModels(), getProviders()]).then(([list, provs]) => {
      setModels(list);
      setProviders(provs);
      return list;
    });

  useEffect(() => {
    if (!showSettings) return;
    refreshModels()
      .then(list => {
        const active = list.find(m => m.is_active);
        if (active) setActiveModelState(active.id);
      })
      .catch(() => {});
    getReasoning().then(r => setReasoningState(r.level)).catch(() => {});
    if (isAdmin) listRepoCredentials().then(setRepoCreds).catch(() => {});
  }, [showSettings]);

  const handleReasoningChange = async (level) => {
    setReasoningState(level);
    try { await setReasoning(level); } catch { /* API unavailable */ }
  };

  const selected = models.find(x => x.id === activeModel);
  const selectedProvider = providers.find(p => p.id === selected?.provider);

  const handleModelChange = async (modelId) => {
    setActiveModelState(modelId);
    setKeyInput('');
    setReplacingKey(false);
    setKeyError('');
    const m = models.find(x => x.id === modelId);
    if (!m?.key_set) return;  // key input shown; model activates once a key is saved
    try { await setActiveModel(modelId); } catch { /* API unavailable */ }
  };

  const handleSaveKey = async () => {
    setKeyError('');
    try {
      await setProviderKey(selected.provider, keyInput);
      await setActiveModel(selected.id);
      setKeyInput('');
      setReplacingKey(false);
      await refreshModels();
    } catch (e) { setKeyError(e.message); }
  };

  const handleConnect = async () => {
    setConnError('');
    try {
      await setProviderEndpoint(conn.provider, conn.endpoint.trim());
      if (conn.key.trim()) await setProviderKey(conn.provider, conn.key.trim());
      if (!models.some(m => m.id === conn.model.trim() && m.provider === conn.provider)) await addCustomModel(conn.provider, conn.model.trim(), conn.model.trim());
      await setActiveModel(conn.model.trim());
      setActiveModelState(conn.model.trim());
      setConn({ ...conn, key: '' });
      await refreshModels();
    } catch (e) { setConnError(e.message); }
  };

  const handleSaveRepoToken = async () => {
    setRepoError('');
    try {
      await saveRepoCredential(repoOwner.trim(), repoToken.trim());
      setRepoToken('');
      setRepoOwner('');
      setRepoCreds(await listRepoCredentials());
    } catch (e) { setRepoError(e.message); }
  };

  const handleRemoveRepoToken = async (owner) => {
    setRepoError('');
    try { await deleteRepoCredential(owner); setRepoCreds(await listRepoCredentials()); }
    catch (e) { setRepoError(e.message); }
  };

  const handleCheckKey = async () => {
    setKeyError('');
    try { await verifyProviderKey(selected.provider); await refreshModels(); }
    catch (e) { setKeyError(e.message); }
  };

  const handleRemoveKey = async () => {
    setKeyError('');
    try { await deleteProviderKey(selected.provider); await refreshModels(); }
    catch (e) { setKeyError(e.message); }
  };
  const current  = PERSONAS.find(p => p.id === persona);
  const stepInfo = PROCESS_STEPS.find(s => s.id === step);
  const portfolio = HIERARCHY.find(p => p.id === sel.portfolioId);
  const project   = portfolio?.projects.find(p => p.id === sel.projectId);

  const crumbs = [{ label: ORG.name }];
  if (['portfolio', 'project', 'component'].includes(scope) && portfolio)
    crumbs.push({ label: portfolio.name });
  if (['project', 'component'].includes(scope) && project)
    crumbs.push({ label: project.name });
  if (scope === 'component' && sel.componentName)
    crumbs.push({ label: sel.componentName, mono: true });

  return (
    <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center gap-4 flex-shrink-0 shadow-sm">
      <div className="flex-1 min-w-0">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs mb-0.5">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-200 mx-0.5">/</span>}
              <span className={`${c.mono ? 'font-mono' : 'font-medium'} ${i < crumbs.length - 1 ? 'text-gray-300' : 'text-gray-600'}`}>
                {c.label}
              </span>
            </span>
          ))}
        </div>
        {/* Step title */}
        <div className="flex items-center gap-2">
          <span>{stepInfo?.icon}</span>
          <p className="text-sm font-bold text-gray-900">{stepInfo?.label}</p>
          <span className="text-xs text-gray-300">·</span>
          <p className="text-xs text-gray-400">Step {stepInfo?.step} of {PROCESS_STEPS.length}</p>
        </div>
      </div>

      {/* Right — persona label + actions */}
      <div className="flex items-center gap-1.5 flex-shrink-0 relative">
        <span className="text-xs text-gray-400 font-medium mr-1">{current.icon} {current.label}</span>
        <button
          title="Ask about the results"
          onClick={onToggleChat}
          className={`w-8 h-8 rounded-lg text-sm flex items-center justify-center transition-colors ${chatOpen ? 'bg-blue-50 text-blue-600' : 'hover:bg-gray-100 text-gray-400'}`}
        >💬</button>
        <button
          title="Settings"
          onClick={() => setShowSettings(!showSettings)}
          className={`w-8 h-8 rounded-lg text-sm flex items-center justify-center transition-colors ${showSettings ? 'bg-gray-100 text-gray-700' : 'hover:bg-gray-100 text-gray-400'}`}
        >⚙️</button>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full bg-green-50 border border-green-200 ml-1">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse inline-block" />
          <span className="text-xs text-green-700 font-semibold">Live</span>
        </div>

        {/* Settings panel */}
        {showSettings && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setShowSettings(false)} />
            <div className="absolute right-0 top-10 z-50 w-72 bg-white border border-gray-100 rounded-2xl shadow-xl p-5">
              <p className="text-sm font-bold text-gray-800 mb-4">Settings</p>
              <div className="space-y-3">
                {models.length > 0 && (
                  <>
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div>
                          <p className="text-xs font-semibold text-gray-700">AI Model</p>
                          <p className="text-xs text-gray-400">Used for all scan agents</p>
                        </div>
                        {activeModel && (() => {
                          const m = models.find(x => x.id === activeModel);
                          return m ? (
                            <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${TIER_BADGE[m.tier] ?? 'bg-gray-50 text-gray-600'}`}>
                              {m.tier}
                            </span>
                          ) : null;
                        })()}
                      </div>
                      <select
                        value={activeModel ?? ''}
                        onChange={e => handleModelChange(e.target.value)}
                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-300"
                      >
                        {models.map(m => (
                          <option key={m.id} value={m.id}>
                            {providers.find(p => p.id === m.provider)?.display ?? m.provider} · {m.display} — ${m.prompt_per_1m}/${m.completion_per_1m} per 1M
                          </option>
                        ))}
                      </select>
                      {selected && selected.rates_known === false && (
                        <p className="text-xs text-amber-600 mt-1">No listed price for this model: costs are estimated at the GPT-5.1 rate, which may be higher or lower than the real one.</p>
                      )}
                      {selected && (
                        <div className="mt-2">
                          {selected.key_set && selectedProvider?.key_hint && (
                            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 mb-1">
                              <div className="flex items-center gap-1.5">
                                <p className="text-xs text-gray-400 whitespace-nowrap">
                                  {selectedProvider?.display} key {selectedProvider?.key_hint}
                                  {selectedProvider?.source === 'env' ? ' (env var)' : ''}
                                </p>
                                {KEY_STATUS[selectedProvider?.status] && (
                                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${KEY_STATUS[selectedProvider.status].cls}`}>{KEY_STATUS[selectedProvider.status].label}</span>
                                )}
                              </div>
                              <span className="flex gap-2">
                                <button onClick={handleCheckKey} className="text-xs text-blue-600 font-semibold hover:text-blue-800">Check</button>
                                <button onClick={() => { setReplacingKey(true); setKeyError(''); }} className="text-xs text-blue-600 font-semibold hover:text-blue-800">Replace</button>
                                {selectedProvider?.source === 'settings' && (
                                  <button onClick={handleRemoveKey} className="text-xs text-red-500 font-semibold hover:text-red-700">Remove</button>
                                )}
                              </span>
                            </div>
                          )}
                          {(replacingKey || !selected.key_set || selectedProvider?.status === 'invalid' || (selectedProvider?.key_optional && !selectedProvider?.key_hint)) && (
                            <div className="flex gap-1">
                              <input
                                type="password"
                                autoComplete="off"
                                value={keyInput}
                                onChange={e => setKeyInput(e.target.value)}
                                placeholder={`${selectedProvider?.display ?? ''} API key`}
                                className="flex-1 min-w-0 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-300"
                              />
                              <button
                                onClick={handleSaveKey}
                                disabled={!keyInput.trim()}
                                className="text-xs font-semibold px-2 py-1 rounded-lg bg-blue-50 text-blue-700 disabled:opacity-40"
                              >Save</button>
                              {replacingKey && (
                                <button onClick={() => { setReplacingKey(false); setKeyInput(''); setKeyError(''); }}
                                        className="text-xs font-semibold px-2 py-1 rounded-lg text-gray-500 hover:bg-gray-50">Cancel</button>
                              )}
                            </div>
                          )}
                          {keyError && <p className="text-xs text-red-500 mt-1">{keyError}</p>}
                        </div>
                      )}
                      {selected?.reasoning_levels?.length > 0 && (() => {
                        // Highest level the model supports at or below the chosen one
                        const lv = selected.reasoning_levels;
                        const applied = [...lv].reverse().find(
                          x => LEVEL_ORDER.indexOf(x.level) <= LEVEL_ORDER.indexOf(reasoning)
                        ) ?? lv[0];
                        return (
                          <div className="mt-3">
                            <p className="text-xs font-semibold text-gray-700">Reasoning</p>
                            <p className="text-xs text-gray-400 mb-1.5">
                              Higher is slower and costs more
                              {applied.token_multiplier > 1 ? ` (up to ~${applied.token_multiplier}× output tokens)` : ''}
                            </p>
                            <div className="flex gap-1">
                              {lv.map(x => (
                                <button
                                  key={x.level}
                                  onClick={() => handleReasoningChange(x.level)}
                                  className={`flex-1 text-xs font-semibold py-1 rounded-lg border ${applied.level === x.level ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50'}`}
                                >{LEVEL_LABEL[x.level]}</button>
                              ))}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  </>
                )}
                <details className="pt-3 border-t border-gray-100">
                  <summary className="text-xs font-semibold text-gray-500 cursor-pointer select-none">Advanced</summary>
                  <div className="space-y-3 mt-3">
                      {isAdmin && (
                        <div className="mt-3 pt-3 border-t border-gray-50">
                          <p className="text-xs font-semibold text-gray-700 mb-1">Your own endpoint</p>
                          <p className="text-xs text-gray-400 mb-2">Azure OpenAI or any OpenAI-compatible server (Ollama, vLLM, a gateway).</p>
                          <select value={conn.provider} onChange={e => setConn({ ...conn, provider: e.target.value })}
                                  className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-1 bg-white">
                            {providers.filter(p => p.endpoint_editable).map(p => <option key={p.id} value={p.id}>{p.display}</option>)}
                          </select>
                          <input value={conn.endpoint} onChange={e => setConn({ ...conn, endpoint: e.target.value })}
                                 placeholder={providers.find(p => p.id === conn.provider)?.endpoint ?? 'https://… or http://localhost:11434/v1'}
                                 className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-1" />
                          <input value={conn.model} onChange={e => setConn({ ...conn, model: e.target.value })}
                                 placeholder="Model or deployment name"
                                 className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-1" />
                          <input type="password" autoComplete="off" value={conn.key} onChange={e => setConn({ ...conn, key: e.target.value })}
                                 placeholder={conn.provider === 'local' ? 'API key (optional)' : 'API key'}
                                 className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-1" />
                          <button onClick={handleConnect} disabled={!conn.endpoint.trim() || !conn.model.trim()}
                                  className="text-xs font-semibold px-2 py-1 rounded-lg bg-blue-50 text-blue-700 disabled:opacity-40">Connect and use</button>
                          {connError && <p className="text-xs text-red-500 mt-1">{connError}</p>}
                        </div>
                      )}
                {isAdmin && (
                  <>
                    <div>
                      <p className="text-xs font-semibold text-gray-700">Private repositories</p>
                      <p className="text-xs text-gray-400 mb-1.5">GitHub access token for one owner (read-only Contents). Use * for every owner: wider, since anyone who can scan can then read every private repository it reaches.</p>
                      {repoCreds.map(c => (
                        <div key={c.owner} className="flex items-center justify-between text-xs text-gray-600 mb-1">
                          <span>{c.owner === '*' ? 'every owner (*)' : c.owner} <span className="text-gray-400">{c.hint}</span></span>
                          <button onClick={() => handleRemoveRepoToken(c.owner)} className="text-red-500 font-semibold hover:text-red-700">Remove</button>
                        </div>
                      ))}
                      <div className="flex gap-1">
                        <input aria-label="GitHub owner" placeholder="owner" value={repoOwner} onChange={e => setRepoOwner(e.target.value)}
                               className="w-20 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-300" />
                        <input aria-label="GitHub access token" type="password" autoComplete="off" placeholder="access token" value={repoToken}
                               onChange={e => setRepoToken(e.target.value)}
                               className="flex-1 min-w-0 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-300" />
                        <button onClick={handleSaveRepoToken} disabled={!repoToken.trim() || !repoOwner.trim()}
                                className="text-xs font-semibold px-2 py-1 rounded-lg bg-blue-50 text-blue-700 disabled:opacity-40">Save</button>
                      </div>
                      {repoError && <p role="alert" className="text-xs text-red-500 mt-1">{repoError}</p>}
                    </div>
                  </>
                )}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Clear Local Data</p>
                    <p className="text-xs text-gray-400">Wipe scan history &amp; hierarchy</p>
                  </div>
                  <button
                    onClick={() => {
                      if (confirm('Clear all local scan data and hierarchy? This cannot be undone.')) {
                        localStorage.clear();
                        window.location.reload();
                      }
                    }}
                    className="text-xs text-red-500 font-semibold hover:text-red-700 bg-red-50 px-2 py-1 rounded-lg"
                  >Clear</button>
                </div>
                  </div>
                </details>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
