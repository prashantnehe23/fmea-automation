/**
 * MitigationsPage.jsx
 *
 * Mitigation action queue with fully expanded remediation plan per scenario:
 *  - Component impacted + current controls & gaps
 *  - Code evidence snippet (exactly where the problem lives)
 *  - Corrective and preventive actions (kind, target, owner, verification, now/next/later band)
 *  - Status workflow (Open → In Progress → Mitigated)
 */

import { useState, useEffect } from 'react';
import ScopeHeader from '../components/ScopeHeader';
import KpiRow from '../components/KpiRow';
import KCard from '../components/KCard';
import AggTable from '../components/AggTable';
import { Chip, PChip } from '../components/Chip';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel, aggregateBy, STA } from '../helpers';

// ── Controls & gaps ───────────────────────────────────────────────────────────

function ControlsSection({ r }) {
  const hasControls = r.controls && Object.keys(r.controls).length > 0;
  const hasGaps     = r.gaps?.length > 0;
  if (!hasControls && !hasGaps) return null;

  return (
    <div className="grid grid-cols-2 gap-4 mb-4">
      {hasControls && (
        <div className="bg-blue-50 rounded-xl p-3">
          <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-2">
            Current Controls
            {r.control_maturity && (
              <span className="ml-2 font-normal text-blue-400 normal-case">({r.control_maturity})</span>
            )}
          </p>
          <ul className="space-y-1">
            {Object.entries(r.controls).map(([k, v]) => (
              <li key={k} className="text-xs text-blue-800">
                <span className="font-semibold">{k}:</span> {v}
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasGaps && (
        <div className="bg-red-50 rounded-xl p-3">
          <p className="text-xs font-bold text-red-500 uppercase tracking-wide mb-2">Control Gaps</p>
          <ul className="space-y-1">
            {r.gaps.map((g, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-red-700">
                <span className="flex-shrink-0 text-red-400 mt-0.5">✗</span>{g}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Code evidence ─────────────────────────────────────────────────────────────

function EvidenceBlock({ evidence }) {
  if (!evidence?.trim()) return null;
  return (
    <div className="mb-4">
      <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">
        📍 Vulnerable Code Location
      </p>
      <pre className="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono border border-gray-700">
        {evidence}
      </pre>
    </div>
  );
}

// ── Corrective and preventive actions ─────────────────────────────────────────

const BAND = {
  now:   { label: 'Now',   cls: 'bg-red-50 text-red-600 border-red-200' },
  next:  { label: 'Next',  cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  later: { label: 'Later', cls: 'bg-gray-100 text-gray-500 border-gray-200' },
};
const BAND_ORDER = { now: 0, next: 1, later: 2 };

function ActionList({ title, color, actions }) {
  if (!actions?.length) return null;
  const sorted = [...actions].sort((a, b) => (BAND_ORDER[a.urgency] ?? 1) - (BAND_ORDER[b.urgency] ?? 1));
  return (
    <div className="mb-4">
      <p className={`text-xs font-bold uppercase tracking-wide mb-2 ${color}`}>{title}</p>
      <ul className="space-y-3">
        {sorted.map(a => {
          const band = BAND[a.urgency] ?? BAND.next;
          return (
            <li key={a.id} className="text-sm text-gray-700">
              <div className="flex items-start gap-2">
                <span className={`flex-shrink-0 text-xs font-bold border rounded-lg px-2 py-0.5 ${band.cls}`}>{band.label}</span>
                <div className="min-w-0">
                  <p className="font-semibold text-gray-800">{a.title}</p>
                  {a.detail && <p className="text-xs text-gray-600 leading-relaxed mt-0.5">{a.detail}</p>}
                  <p className="text-xs text-gray-400 mt-0.5">
                    {(a.kind ?? '').replaceAll('_', ' ')}{a.target ? ` · ${a.target}` : ''} · {a.owner_role}
                  </p>
                  {a.verification && <p className="text-xs text-green-700 mt-0.5">Verify: {a.verification}</p>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Expanded remediation panel ────────────────────────────────────────────────

function RemediationDetail({ r }) {
  return (
    <div className="border-t border-gray-100 bg-gray-50 px-6 py-5 space-y-0">
      <ControlsSection r={r} />
      <EvidenceBlock evidence={r.evidence} />
      <ActionList title="🔧 Corrective actions" color="text-green-600" actions={r.corrective} />
      {!r.corrective?.length && (
        <p className="text-xs text-gray-400 italic mb-4">No corrective actions available for this scenario.</p>
      )}
      <ActionList title="🛡️ Preventive actions" color="text-purple-600" actions={r.preventive} />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MitigationsPage({ persona, sel, scope, liveRisks, hierarchy = [] }) {
  const risks = liveRisks ?? [];
  const label = getSelectionLabel(sel, scope, hierarchy);

  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(risks.map(r => [r.id, r.status ?? 'Open']))
  );
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    if (liveRisks?.length) {
      setStatuses(Object.fromEntries(liveRisks.map(r => [r.id, r.status ?? 'Open'])));
    }
  }, [liveRisks]);

  const update = (id, st) => setStatuses(p => ({ ...p, [id]: st }));
  const sorted = [...risks].sort((a, b) => b.rpn - a.rpn);

  const open   = risks.filter(r => statuses[r.id] === 'Open').length;
  const inprog = risks.filter(r => statuses[r.id] === 'In Progress').length;
  const done   = risks.filter(r => statuses[r.id] === 'Mitigated').length;

  // Executive / org / portfolio: summary table
  if (persona === 'executive' || scope === 'org' || scope === 'portfolio') {
    const portfolio = hierarchy.find(p => p.id === sel?.portfolioId);
    const rows = scope === 'org'
      ? aggregateBy(risks, r => r.portfolio, r => hierarchy.find(p => p.id === r.portfolio)?.name ?? r.portfolio)
      : aggregateBy(risks, r => r.project, r =>
          portfolio?.projects.find(pr => pr.id === r.project)?.name ?? r.project
        );
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="Mitigation status across scope" />
        <div className="grid grid-cols-4 gap-4 mb-6">
          <KCard label="Open"        value={open}   color="text-red-600"    accent="bg-red-400" />
          <KCard label="In Progress" value={inprog}  color="text-blue-600"   accent="bg-blue-400" />
          <KCard label="Reviewing"   value={risks.filter(r => statuses[r.id] === 'Reviewing').length} color="text-purple-600" accent="bg-purple-400" />
          <KCard
            label="Mitigated"
            value={done}
            color="text-green-600"
            accent="bg-green-400"
            sub={`${Math.round(done / Math.max(risks.length, 1) * 100)}% resolved`}
          />
        </div>
        <AggTable rows={rows} groupLabel={scope === 'org' ? 'Portfolio' : 'Project'} />
      </div>
    );
  }

  const canAct = persona === 'sre' || persona === 'developer';

  if (risks.length === 0) {
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label || 'No project selected'} sub="No scan data yet" />
        <div className="mt-16 text-center">
          <p className="text-4xl mb-3">🛠️</p>
          <p className="text-gray-400 text-sm">Run a scan to populate the mitigation queue.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-start justify-between mb-6">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="Mitigation queue — sorted by RPN" />
        <div className="flex gap-3">
          {[['Open', open, 'text-red-600', 'bg-red-50'], ['In Progress', inprog, 'text-blue-600', 'bg-blue-50'], ['Mitigated', done, 'text-green-600', 'bg-green-50']].map(([l, v, c, bg]) => (
            <div key={l} className={`${bg} rounded-xl px-4 py-2 text-center`}>
              <p className={`text-xl font-bold ${c}`}>{v}</p>
              <p className="text-xs text-gray-400">{l}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {sorted.map(r => {
          const st  = statuses[r.id];
          const exp = expanded === r.id;
          return (
            <div key={r.id} className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              {/* Row header */}
              <div
                className="flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() => setExpanded(exp ? null : r.id)}
              >
                {/* RPN badge */}
                <div className={`w-11 h-11 rounded-xl flex items-center justify-center font-bold text-white text-xs flex-shrink-0 ${
                  r.priority === 'Critical' ? 'bg-red-500' : r.priority === 'High' ? 'bg-orange-500' : 'bg-amber-400'
                }`}>
                  {r.rpn}
                </div>

                {/* Name + component */}
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-gray-800 text-sm">{r.name}</p>
                  <p className="text-xs text-blue-600 font-mono mt-0.5">{r.comp}</p>
                  {r.trigger && (
                    <p className="text-xs text-gray-400 mt-0.5 truncate">Trigger: {r.trigger}</p>
                  )}
                </div>

                {/* Badges */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <PChip p={r.priority} />
                  <Chip label={st} cls={STA[st]} />
                  {r.confidence != null && (
                    <span className="text-xs text-purple-500 font-semibold">
                      {Math.round(r.confidence * 100)}% conf
                    </span>
                  )}
                </div>

                {/* Action buttons */}
                {canAct && (
                  <div className="flex gap-2 flex-shrink-0">
                    {st === 'Open'        && <button onClick={e => { e.stopPropagation(); update(r.id, 'In Progress'); }} className="px-3 py-1.5 bg-blue-600 text-white text-xs font-bold rounded-lg hover:bg-blue-700">Start Fix</button>}
                    {st === 'In Progress' && <button onClick={e => { e.stopPropagation(); update(r.id, 'Mitigated');  }} className="px-3 py-1.5 bg-green-600 text-white text-xs font-bold rounded-lg hover:bg-green-700">Mark Done</button>}
                    {st === 'Mitigated'   && <span className="text-green-500 text-xs font-bold">✓ Done</span>}
                  </div>
                )}

                <span className="text-gray-300 text-xs ml-1">{exp ? '▴' : '▾'}</span>
              </div>

              {/* Expanded remediation detail */}
              {exp && <RemediationDetail r={r} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
