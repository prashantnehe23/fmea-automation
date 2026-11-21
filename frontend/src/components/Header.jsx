import { useState, useEffect } from 'react';
import { PERSONAS, PROCESS_STEPS, HIERARCHY, SCOPE_LABEL } from '../data';
import { ORG } from '../data';
import { getModels, setActiveModel, getProviders, setProviderKey, deleteProviderKey, getReasoning, setReasoning, verifyProviderKey,
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
  const [reasoning, setReasoningState]  = useState('off');
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
      await refreshModels();
    } catch (e) { setKeyError(e.message); }
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
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Model key</p>
                    <p className="text-xs text-gray-400">{selectedProvider?.display ?? 'Active provider'}</p>
                  </div>
                  {selectedProvider && (
                    <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${KEY_STATUS[selectedProvider.status]?.cls ?? ''}`}>
                      {KEY_STATUS[selectedProvider.status]?.label ?? selectedProvider.status}
                    </span>
                  )}
                </div>
                <hr className="border-gray-50" />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Risk Registry</p>
                    <p className="text-xs text-gray-400">Scenario lock &amp; history</p>
                  </div>
                  <span className="text-xs text-green-600 font-semibold bg-green-50 px-2 py-1 rounded-lg">Active</span>
                </div>
                <hr className="border-gray-50" />
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
                {isAdmin && (
                  <>
                    <hr className="border-gray-50" />
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
                {models.length > 0 && (
                  <>
                    <hr className="border-gray-50" />
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
                      {selected && (
                        <div className="mt-2">
                          {selected.key_set && (
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <p className="text-xs text-gray-400">
                                {selectedProvider?.display} key {selectedProvider?.key_hint}
                                {selectedProvider?.source === 'env' ? ' (env var)' : ''}
                              </p>
                              <span className="flex gap-2">
                                <button onClick={handleCheckKey} className="text-xs text-blue-600 font-semibold hover:text-blue-800">Check</button>
                                {selectedProvider?.source === 'settings' && (
                                  <button onClick={handleRemoveKey} className="text-xs text-red-500 font-semibold hover:text-red-700">Remove</button>
                                )}
                              </span>
                            </div>
                          )}
                          {(!selected.key_set || selectedProvider?.status === 'invalid') && (
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
                            </div>
                          )}
                          {keyError && <p className="text-xs text-red-500 mt-1">{keyError}</p>}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
