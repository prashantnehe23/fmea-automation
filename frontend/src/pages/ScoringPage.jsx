/**
 * ScoringPage.jsx
 *
 * Risk scoring view with:
 *  - Left panel: risk selector list (priority + RPN)
 *  - Right panel:
 *      • S / O / D sliders with rationale text under each one explaining WHY
 *        that score was given (from the actuary's LLM output)
 *      • Overall justification
 *      • Validator assessment: confidence %, verdict, checks, challenges
 *      • Score adjustment (security_engineer only) with audit trail
 */

import { useState, useEffect } from 'react';
import ScopeHeader from '../components/ScopeHeader';
import KpiRow from '../components/KpiRow';
import { PChip } from '../components/Chip';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel, PRI } from '../helpers';
import { postScoringAdjustment, getScoringAdjustments } from '../api';

// ── Validator panel (within scoring detail) ───────────────────────────────────

function ValidatorPanel({ r }) {
  if (r.confidence == null && !r.verdict && !r.challenges?.length) return null;
  const pct = r.confidence != null ? Math.round(r.confidence * 100) : null;

  const Check = ({ ok, label }) => (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${
      ok ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-600'
    }`}>
      {ok ? '✓' : '✗'} {label}
    </span>
  );

  return (
    <div className="bg-purple-50 border border-purple-200 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-bold text-purple-800">🔍 Validator Assessment</h4>
        {pct != null && (
          <div className="flex items-center gap-2">
            <div className="h-2 w-24 bg-purple-200 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${pct >= 80 ? 'bg-green-500' : pct >= 60 ? 'bg-amber-500' : 'bg-red-500'}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className={`text-sm font-bold ${pct >= 80 ? 'text-green-700' : pct >= 60 ? 'text-amber-600' : 'text-red-600'}`}>
              {pct}%
            </span>
            <span className="text-xs text-purple-500">confidence</span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <Check ok={r.is_realistic}          label="Realistic" />
        <Check ok={r.attack_chain_complete} label="Chain complete" />
        <Check ok={r.rpn_calibrated}        label="RPN calibrated" />
      </div>

      {r.verdict && (
        <p className="text-xs text-purple-700 italic mb-3 leading-relaxed">"{r.verdict}"</p>
      )}

      {r.challenges?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-purple-600 mb-1.5">Challenges raised:</p>
          <ul className="space-y-1">
            {r.challenges.map((ch, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-purple-700">
                <span className="flex-shrink-0 text-purple-400 mt-0.5">·</span>{ch}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Score slider with rationale ───────────────────────────────────────────────

function ScoreSlider({ label, dim, colorClass, hint, value, rationale, onChange, disabled }) {
  return (
    <div className="mb-5">
      <div className="flex justify-between items-start mb-1.5">
        <div>
          <p className="text-sm font-semibold text-gray-700">{label}</p>
          <p className="text-xs text-gray-400">{hint}</p>
        </div>
        <span className={`text-2xl font-bold ${colorClass}`}>{value}</span>
      </div>
      <input
        type="range" min="1" max="10" value={value}
        onChange={e => onChange(+e.target.value)}
        disabled={disabled}
        className="w-full accent-blue-600 disabled:opacity-60"
      />
      <div className="flex justify-between text-xs text-gray-300 mt-0.5 mb-2">
        <span>1 · Low</span><span>5 · Medium</span><span>10 · High</span>
      </div>
      {rationale && (
        <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
          <p className="text-xs text-gray-500 font-semibold mb-0.5">Why this score:</p>
          <p className="text-xs text-gray-700 leading-relaxed">{rationale}</p>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ScoringPage({ persona, sel, scope, liveRisks, hierarchy = [], workspaceId, onAdjustmentSaved }) {
  const risks  = liveRisks ?? [];
  const label  = getSelectionLabel(sel, scope, hierarchy);

  const defaultRisk = risks[0] ?? null;
  const [selRisk,   setSelRisk]   = useState(defaultRisk);
  const [adj,       setAdj]       = useState({ s: defaultRisk?.s ?? 5, o: defaultRisk?.o ?? 5, d: defaultRisk?.d ?? 5 });
  const [reason,    setReason]    = useState('');
  const [log,       setLog]       = useState([]);
  const [saveState, setSaveState] = useState('idle'); // 'idle' | 'saving' | 'saved' | 'error'

  // Load persisted adjustments from API when workspaceId is available
  useEffect(() => {
    if (!workspaceId) return;
    getScoringAdjustments(workspaceId)
      .then(rows => {
        setLog(rows.map(r => ({
          risk:   r.failure_mode,
          from:   null,
          to:     r.new_rpn,
          reason: r.justification,
          date:   new Date(r.created_at).toLocaleDateString('en-GB'),
          saved:  true,
          flagged: r.flagged,
        })));
      })
      .catch(() => {}); // non-critical — audit trail simply stays empty
  }, [workspaceId]);

  useEffect(() => {
    if (liveRisks?.length) {
      const first = liveRisks.find(r => r.name === selRisk?.name) ?? liveRisks[0];   // keep the open risk
      setSelRisk(first);
      setAdj({ s: first.s, o: first.o, d: first.d });
      setReason('');
    }
  }, [liveRisks]);

  const pick = r => { setSelRisk(r); setAdj({ s: r.s, o: r.o, d: r.d }); setReason(''); setSaveState('idle'); };
  const newRpn  = adj.s * adj.o * adj.d;
  const changed = selRisk && (adj.s !== selRisk.s || adj.o !== selRisk.o || adj.d !== selRisk.d);
  // B-034: lowering a Severity 9-10 scenario below 9 needs a real justification (the server enforces it too)
  const lowersCatastrophic = selRisk && selRisk.s >= 9 && adj.s < 9;
  const reasonTooShort = lowersCatastrophic && reason.trim().length < 15;

  const propose = async () => {
    if (!reason.trim() || !selRisk || reasonTooShort) return;
    const entry = {
      risk: selRisk.name, from: selRisk.rpn, to: newRpn, reason,
      date: new Date().toLocaleDateString('en-GB'),
      saved: false,
    };
    if (workspaceId) {
      setSaveState('saving');
      try {
        const saved = await postScoringAdjustment(workspaceId, selRisk.name, adj.s, adj.o, adj.d, reason);
        entry.saved = true;
        entry.flagged = saved.flagged;
        setSaveState('saved');
        onAdjustmentSaved?.();
      } catch {
        setSaveState('error');
      }
    }
    setLog(p => [entry, ...p]);
    setReason('');
  };

  // Executive / org / portfolio: RPN bar chart
  if (persona === 'executive' || scope === 'org' || scope === 'portfolio') {
    const sorted = [...risks].sort((a, b) => b.rpn - a.rpn);
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="RPN scores across scope" />
        <KpiRow risks={risks} />
        <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
          <h3 className="font-bold text-gray-700 text-sm uppercase tracking-wide mb-5">Risk Priority Numbers</h3>
          {sorted.map(r => (
            <div key={r.id} className="mb-4">
              <div className="flex justify-between text-xs mb-1.5">
                <span className="text-gray-600 truncate flex-1 pr-4">{r.name}</span>
                <span className="font-bold text-gray-900 flex-shrink-0">{r.rpn}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${PRI[r.priority]?.dot}`}
                  style={{ width: `${(r.rpn / 400) * 100}%`, transition: 'width 0.4s' }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const canAdjust = persona === 'security_engineer';

  if (risks.length === 0) {
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label || 'No project selected'} sub="No scan data yet" />
        <div className="mt-16 text-center">
          <p className="text-4xl mb-3">📊</p>
          <p className="text-gray-400 text-sm">Run a scan to see risk scores and rationale.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <ScopeHeader
        scopeLabel={SCOPE_LABEL[scope]}
        name={label}
        sub={canAdjust ? 'Review and adjust RPN scores — human in the loop' : 'RPN scores and rationale'}
      />
      <div className="flex gap-5">
        {/* Risk selector list */}
        <div className="w-60 flex-shrink-0 space-y-1.5 overflow-y-auto scrollbar-thin" style={{ maxHeight: 'calc(100vh - 220px)' }}>
          {risks.map(r => (
            <button
              key={r.id}
              onClick={() => pick(r)}
              className={`w-full text-left p-3 rounded-xl border transition-all ${selRisk?.id === r.id ? 'border-blue-300 bg-blue-50' : 'border-gray-100 bg-white hover:border-blue-200'}`}
            >
              <div className="flex justify-between items-center mb-1">
                <PChip p={r.priority} />
                <span className="text-xs font-bold text-gray-700">{r.rpn}</span>
              </div>
              <p className="text-xs font-semibold text-gray-800 leading-snug">{r.name}</p>
              {r.confidence != null && (
                <p className="text-xs text-purple-500 mt-1">
                  Validator: {Math.round(r.confidence * 100)}% conf
                </p>
              )}
            </button>
          ))}
        </div>

        {/* Detail panel */}
        {selRisk && (
          <div className="flex-1 space-y-4 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 220px)' }}>
            {/* Score card */}
            <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
              <h3 className="font-bold text-gray-900 text-base mb-1">{selRisk.name}</h3>
              <p className="text-xs font-mono text-blue-600 mb-1">{selRisk.comp}</p>
              <p className="text-sm text-gray-500 mb-5 leading-relaxed">{selRisk.impact}</p>

              {/* Overall justification */}
              {selRisk.justification && (
                <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 mb-5">
                  <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-1">Overall Justification</p>
                  <p className="text-xs text-blue-900 leading-relaxed">{selRisk.justification}</p>
                </div>
              )}

              <ScoreSlider
                label="Severity (S)"
                hint="How severe is the business impact if this fails?"
                colorClass="text-red-500"
                value={adj.s}
                rationale={selRisk.severity_rationale}
                onChange={v => setAdj(p => ({ ...p, s: v }))}
                disabled={!canAdjust}
              />
              <ScoreSlider
                label="Occurrence (O)"
                hint="How likely is this to be exploited in practice?"
                colorClass="text-orange-500"
                value={adj.o}
                rationale={selRisk.occurrence_rationale}
                onChange={v => setAdj(p => ({ ...p, o: v }))}
                disabled={!canAdjust}
              />
              <ScoreSlider
                label="Detection (D)"
                hint="How hard is this to detect before harm occurs?"
                colorClass="text-blue-500"
                value={adj.d}
                rationale={selRisk.detection_rationale}
                onChange={v => setAdj(p => ({ ...p, d: v }))}
                disabled={!canAdjust}
              />

              {/* RPN summary */}
              <div className="flex items-center gap-6 pt-5 border-t border-gray-100">
                <div className="text-center">
                  <p className="text-xs text-gray-400 mb-1">Actuary RPN</p>
                  <p className="text-3xl font-bold text-gray-300">{selRisk.rpn}</p>
                </div>
                {changed && <>
                  <span className="text-gray-200 text-xl">→</span>
                  <div className="text-center">
                    <p className="text-xs text-gray-400 mb-1">Proposed</p>
                    <p className={`text-3xl font-bold ${newRpn > selRisk.rpn ? 'text-red-500' : 'text-green-600'}`}>{newRpn}</p>
                  </div>
                  <span className={`px-3 py-1.5 rounded-xl text-xs font-bold border ${newRpn > selRisk.rpn ? 'bg-red-50 border-red-200 text-red-700' : 'bg-green-50 border-green-200 text-green-700'}`}>
                    {newRpn > selRisk.rpn ? '▲ Escalated' : '▼ De-prioritised'}
                  </span>
                </>}
              </div>
            </div>

            {/* Validator panel */}
            <ValidatorPanel r={selRisk} />

            {/* Justification box — security_engineer only */}
            {canAdjust && changed && (
              <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
                <label className="block text-sm font-bold text-gray-700 mb-2">
                  Justification <span className="text-red-400">*</span>
                </label>
                <textarea
                  className="w-full h-20 p-3 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200 resize-none bg-gray-50"
                  placeholder="Explain the adjustment — this goes to the audit trail…"
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                />
                {lowersCatastrophic && (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mt-2">
                    This lowers a catastrophic finding (Severity {selRisk.s}) below 9. Give a specific reason
                    (at least 15 characters); the change is flagged in the audit trail.
                  </p>
                )}
                <div className="flex items-center justify-between mt-3">
                  <button
                    onClick={propose}
                    disabled={!reason.trim() || reasonTooShort || saveState === 'saving'}
                    className="px-5 py-2 bg-blue-600 text-white text-sm font-bold rounded-xl hover:bg-blue-700 disabled:opacity-40 shadow-sm"
                  >
                    {saveState === 'saving' ? 'Saving…' : 'Propose Adjustment'}
                  </button>
                  {saveState === 'saved' && (
                    <span className="text-xs text-green-600 font-semibold">✓ Saved to registry</span>
                  )}
                  {saveState === 'error' && (
                    <span className="text-xs text-red-500">Failed to save — adjustment is local only</span>
                  )}
                  {saveState === 'idle' && log.length > 0 && (
                    <span className="text-xs text-gray-400">{log.length} adjustment{log.length > 1 ? 's' : ''} in audit trail</span>
                  )}
                </div>
              </div>
            )}

            {/* Audit trail */}
            {canAdjust && log.length > 0 && (
              <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
                <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">Audit Trail</h4>
                <div className="space-y-2">
                  {log.map((e, i) => (
                    <div key={i} className="flex justify-between items-start py-2 border-b border-gray-50 last:border-0">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-xs font-semibold text-gray-700 truncate">{e.risk}</p>
                          {e.saved && (
                            <span className="flex-shrink-0 text-xs bg-green-50 border border-green-200 text-green-700 px-1.5 py-0.5 rounded-full">✓ registry</span>
                          )}
                          {e.flagged && (
                            <span className="flex-shrink-0 text-xs bg-amber-50 border border-amber-300 text-amber-700 px-1.5 py-0.5 rounded-full">⚠ severity lowered below 9</span>
                          )}
                        </div>
                        <p className="text-xs text-gray-400 italic mt-0.5">"{e.reason}"</p>
                      </div>
                      <div className="text-right ml-4 flex-shrink-0">
                        <p className="text-sm font-bold">
                          {e.from != null && (
                            <span className="text-gray-300 line-through mr-1">{e.from}</span>
                          )}
                          <span className={e.from == null || e.to < e.from ? 'text-green-600' : 'text-red-600'}>{e.to}</span>
                        </p>
                        <p className="text-xs text-gray-300">{e.date}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
