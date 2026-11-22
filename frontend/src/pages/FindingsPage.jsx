/**
 * FindingsPage.jsx — B-048 phase 1
 *
 * Findings first: a watchlist of every severity 9+ finding, the full list, and one detail view in which a
 * finding can be reviewed completely: what it means, its score and why, evidence, root cause, fix actions,
 * where it came from, and its history.
 */

import { useState, useEffect, useRef } from 'react';
import ScopeHeader from '../components/ScopeHeader';
import { PChip, DomainChip, CweChip } from '../components/Chip';
import { ActionList } from './MitigationsPage';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel } from '../helpers';
import { getFindings, setFindingState } from '../api';
import { watchlist, filterFindings, byPriorityThenRpn, describeScore, impactText, STATE_LABEL } from '../findingsModel';

const PRIORITIES = ['Critical', 'High', 'Medium', 'Low'];

function Row({ r, selected, onSelect, showReason }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(r)}
        aria-current={selected ? 'true' : undefined}
        className={`w-full text-left px-3 py-2 rounded-xl border text-sm ${selected ? 'border-blue-300 bg-blue-50' : 'border-gray-100 bg-white hover:bg-gray-50'}`}
      >
        <span className="flex items-center gap-2">
          <span className="flex-1 min-w-0 font-semibold text-gray-800 truncate">{r.name}</span>
          <PChip p={r.priority} />
          <span className="text-xs font-bold text-gray-500">RPN {r.rpn}</span>
        </span>
        {showReason && <span className="block text-xs text-gray-500 mt-0.5">{r.priority_reason || `Band set from RPN ${r.rpn}`}</span>}
      </button>
    </li>
  );
}

function Section({ title, children }) {
  return (
    <section className="mb-5">
      <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">{title}</h3>
      {children}
    </section>
  );
}

function Detail({ r, state, events, canDecide, onDecide, error }) {
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, [r.name]);       // a keyboard or screen-reader user lands on the finding
  const words = describeScore(r.s, r.o, r.d);
  const imported = r.source && r.source !== 'fmea';
  const chain = r.root_cause_chain;
  const actions = [...(r.corrective ?? []), ...(r.preventive ?? [])];
  return (
    <section aria-label="Finding detail" className="bg-white rounded-2xl border border-blue-200 shadow-sm p-6">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <PChip p={r.priority} />
        <DomainChip d={r.root_cause} />
        <CweChip cwe={r.cwe} />
        {imported && <span className="text-xs px-2 py-0.5 rounded bg-indigo-50 text-indigo-700">Imported · {r.source.replace('import:', '')}</span>}
        {r.also_reported_by?.length > 0 && <span className="text-xs text-gray-500">also reported by {r.also_reported_by.join(', ')}</span>}
      </div>
      <h2 ref={heading} tabIndex={-1} className="text-lg font-bold text-gray-900 mb-1 outline-none">{r.name}</h2>
      <p className="text-xs font-mono text-gray-400 mb-4">{r.comp}</p>

      <Section title="What it means">
        <p className="text-sm text-gray-700">{impactText(r)}</p>
        {r.trigger && r.trigger !== 'Not specified' && <p className="text-xs text-gray-500 mt-1">Trigger: {r.trigger}</p>}
      </Section>

      <Section title="Score">
        <p className="text-sm text-gray-800 font-semibold">RPN {r.rpn} = severity {r.s} × likelihood {r.o} × detection {r.d}</p>
        <ul className="text-xs text-gray-600 mt-1 space-y-0.5">
          <li>Severity {r.s}/10: {words.severity}</li>
          <li>Occurrence {r.o}/10: {words.occurrence}</li>
          <li>Detection {r.d}/10: {words.detection}</li>
        </ul>
        <p className="text-xs font-semibold text-gray-500 mt-2">Why this priority</p>
        <p className="text-sm text-gray-700">{r.priority_reason || `Band set from RPN ${r.rpn}`}</p>
      </Section>

      <Section title="Why this score">
        {[r.severity_rationale, r.occurrence_rationale, r.detection_rationale, r.justification].filter(Boolean).map((t, i) => (
          <p key={i} className="text-sm text-gray-700 mb-1">{t}</p>
        ))}
        {r.verdict && (
          <p className="text-xs text-gray-600 mt-1">Validator: {r.verdict}{r.confidence != null && ` (${Math.round(r.confidence * 100)}% confidence)`}</p>
        )}
        {r.challenges?.length > 0 && <p className="text-xs text-gray-500">Challenged: {r.challenges.join(' ')}</p>}
      </Section>

      <Section title="Evidence">
        {r.evidence
          ? <pre className="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto whitespace-pre-wrap font-mono">{r.evidence}</pre>
          : <p className="text-sm text-gray-500">No code evidence was recorded for this finding.</p>}
        {r.attack_chain?.length > 0 && (
          <ol className="list-decimal list-inside text-xs text-gray-600 mt-2 space-y-0.5">
            {r.attack_chain.map((step, i) => <li key={i}>{step}</li>)}
          </ol>
        )}
      </Section>

      {chain?.root_cause && (
        <Section title="Root cause">
          <p className="text-xs text-gray-600"><span className="text-gray-400">Symptom:</span> {chain.symptom}</p>
          <p className="text-xs text-gray-600"><span className="text-gray-400">Proximate cause:</span> {chain.proximate_cause}</p>
          <p className="text-xs text-gray-600"><span className="text-gray-400">Root cause:</span> {chain.root_cause}</p>
        </Section>
      )}

      <Section title="Fix">
        {actions.length === 0
          ? <p className="text-sm text-gray-500">No fix actions were produced for this finding.</p>
          : <>
              <ActionList title="Corrective actions" color="text-green-600" actions={r.corrective} />
              <ActionList title="Preventive actions" color="text-purple-600" actions={r.preventive} />
            </>}
      </Section>

      <Section title="History">
        <p className="text-sm text-gray-800">State: <strong>{state ? (STATE_LABEL[state] ?? state) : 'Not tracked'}</strong></p>
        {events.length === 0
          ? <p className="text-xs text-gray-500">No state changes recorded yet.</p>
          : <ul className="text-xs text-gray-600 mt-1 space-y-0.5">
              {events.map((e, i) => (
                <li key={i}><span>{e.from_state ?? 'start'} → {e.to_state}</span> · {String(e.at).slice(0, 10)}{e.actor ? ` · ${e.actor}` : ''}{e.note ? ` · ${e.note}` : ''}</li>
              ))}
            </ul>}
        {canDecide && (
          <div className="flex gap-2 mt-2">
            {state !== 'fixed' && <button type="button" onClick={() => onDecide('fixed')} className="text-xs font-semibold px-2 py-1 rounded-lg bg-green-50 text-green-700">Mark fixed</button>}
            {state !== 'accepted' && <button type="button" onClick={() => onDecide('accepted')} className="text-xs font-semibold px-2 py-1 rounded-lg bg-gray-100 text-gray-700">Accept risk</button>}
            {state !== 'confirmed' && <button type="button" onClick={() => onDecide('confirmed')} className="text-xs font-semibold px-2 py-1 rounded-lg bg-red-50 text-red-700">Still present</button>}
          </div>
        )}
        {error && <p role="alert" className="text-xs text-red-600 mt-1">{error}</p>}
      </Section>
    </section>
  );
}

export default function FindingsPage({ scope, sel, liveRisks, hierarchy = [], workspaceId, canDecideFindings }) {
  const risks = liveRisks ?? [];
  const label = getSelectionLabel(sel, scope, hierarchy);
  const [data, setData] = useState(null);
  const [selectedName, setSelectedName] = useState(null);
  const [filters, setFilters] = useState({ priority: 'all', domain: 'all', source: 'all' });
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  // A different project starts clean: no carried-over selection, filters, history or message
  useEffect(() => {
    setSelectedName(null); setFilters({ priority: 'all', domain: 'all', source: 'all' }); setError(''); setData(null);
  }, [workspaceId]);
  useEffect(() => {
    let live = true;                                   // a slow answer for a project we left must not overwrite this one
    if (!workspaceId) { setData(null); return undefined; }
    getFindings(workspaceId).then(d => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  }, [workspaceId, reload]);
  const pick = name => { setSelectedName(name); setError(''); };

  const states = Object.fromEntries((data?.findings ?? []).map(f => [f.failure_mode, f.state]));
  const selected = risks.find(r => r.name === selectedName) ?? null;
  const domains = [...new Set(risks.map(r => r.root_cause ?? 'unclassified'))];
  const shown = filterFindings(risks, filters, states).sort(byPriorityThenRpn);
  const watch = watchlist([...risks]);

  const decide = async state => {
    setError('');
    try { await setFindingState(workspaceId, selected.name, state); setReload(n => n + 1); }
    catch (e) { setError(e.message); }
  };

  if (scope === 'org' || scope === 'portfolio') {
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="Select a project to review its findings" />
      </div>
    );
  }

  return (
    <div className="p-8">
      <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label || 'No project selected'}
                   sub={risks.length ? `${risks.length} findings` : 'No scan data for this project yet'} />
      {risks.length === 0
        ? <p className="mt-8 text-sm text-gray-500">Run a scan on this project to see its findings.</p>
        : (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 mt-4">
            <div className="lg:col-span-2">
              {watch.length > 0 && (
                <section aria-label="Watchlist: severity 9 and above" className="mb-5">
                  <h2 className="text-xs font-bold text-red-600 uppercase tracking-wide mb-1.5">Watchlist · severity 9 and above</h2>
                  <ul className="space-y-1.5">
                    {watch.map(r => <Row key={r.id} r={r} selected={r.name === selectedName} onSelect={x => pick(x.name)} showReason />)}
                  </ul>
                </section>
              )}
              <section aria-label="All findings">
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wide">All findings</h2>
                  <select aria-label="Filter by priority" value={filters.priority} onChange={e => setFilters({ ...filters, priority: e.target.value })}
                          className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-white">
                    <option value="all">All priorities</option>
                    {PRIORITIES.filter(p => risks.some(r => r.priority === p)).map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <select aria-label="Filter by root cause" value={filters.domain} onChange={e => setFilters({ ...filters, domain: e.target.value })}
                          className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-white">
                    <option value="all">All root causes</option>
                    {domains.map(d => <option key={d} value={d}>{d === 'unclassified' ? 'Not classified' : d.charAt(0).toUpperCase() + d.slice(1)}</option>)}
                  </select>
                  <select aria-label="Filter by source" value={filters.source} onChange={e => setFilters({ ...filters, source: e.target.value })}
                          className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-white">
                    <option value="all">All sources</option>
                    <option value="fmea">Found here</option>
                    <option value="imported">Imported</option>
                  </select>
                </div>
                <ul className="space-y-1.5">
                  {shown.map(r => <Row key={r.id} r={r} selected={r.name === selectedName} onSelect={x => pick(x.name)} />)}
                </ul>
                {shown.length === 0 && <p className="text-sm text-gray-500 mt-2">No findings match these filters.</p>}
              </section>
            </div>
            <div className="lg:col-span-3">
              {selected
                ? <Detail r={selected} state={states[selected.name]} events={(data?.events ?? []).filter(e => e.failure_mode === selected.name)}
                          canDecide={!!canDecideFindings && !!workspaceId} onDecide={decide} error={error} />
                : <p className="text-sm text-gray-500">Select a finding to review its evidence, score, fix and history.</p>}
            </div>
          </div>
        )}
    </div>
  );
}
