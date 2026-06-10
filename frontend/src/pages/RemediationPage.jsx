import { useState } from 'react';
import ScopeHeader from '../components/ScopeHeader';
import KCard from '../components/KCard';
import { Chip } from '../components/Chip';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel } from '../helpers';
import { streamRemediate } from '../api';

export default function RemediationPage({ persona, sel, scope, liveRisks, liveScanId, hierarchy = [] }) {
  const risks  = liveRisks ?? [];
  const label  = getSelectionLabel(sel, scope, hierarchy);
  const sorted = [...risks].sort((a, b) => b.rpn - a.rpn);

  const [running,  setRunning]  = useState(false);
  const [results,  setResults]  = useState(null);
  const [remError, setRemError] = useState('');

  const runAll = async () => {
    setRunning(true);
    setRemError('');
    setResults(null);

    // If we have a live scan id, use the real API
    if (liveScanId) {
      try {
        for await (const event of streamRemediate(liveScanId)) {
          if (event.stage === 'complete') {
            // Merge API results with sorted risks for display
            const merged = sorted.map(r => {
              const api = event.results?.find(x => x.failure_mode === r.name);
              return api
                ? { ...r, afterRpn: api.after_rpn, diff: api.code_diff, testCode: api.test_code, desc: api.test_description, rpnDelta: api.rpn_delta }
                : { ...r, afterRpn: r.rpn, diff: '', testCode: '', desc: '', rpnDelta: 0 };
            });
            setResults(merged);
            setRunning(false);
          } else if (event.stage === 'error') {
            setRemError(event.msg ?? 'Remediation failed');
            setRunning(false);
          }
        }
      } catch (err) {
        setRemError(String(err));
        setRunning(false);
      }
      return;
    }

    // No live scan — nothing to do
    setRemError('No scan found. Run a GitHub scan first, then return to this page.');
    setRunning(false);
  };

  // Executive: visibility-only panel
  if (persona === 'executive') {
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="Auto-remediation is handled by development and SRE teams" />
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 flex items-start gap-3">
          <span className="text-2xl">ℹ️</span>
          <div>
            <p className="font-bold text-amber-800 text-sm">Visibility only</p>
            <p className="text-sm text-amber-700 mt-1">Auto-remediation is executed by developers and SREs. This view shows the remediation pipeline status.</p>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-2 gap-4">
          <KCard label="Scenarios" value={sorted.length} sub="awaiting remediation" accent="bg-gray-300" />
          <KCard label="Critical"  value={risks.filter(r => r.priority === 'Critical').length} sub="immediate action" accent="bg-red-400" color="text-red-600" />
        </div>
      </div>
    );
  }

  if (risks.length === 0) {
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label || 'No project selected'} sub="AI-generated code fixes with before / after RPN validation" />
        <div className="mt-16 text-center">
          <p className="text-4xl mb-3">🔧</p>
          <p className="text-gray-400 text-sm">Run a scan first to enable auto-remediation.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="AI-generated code fixes with before / after RPN validation" />

      {/* Remediation queue table */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden mb-5">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-bold text-gray-800 text-sm">Remediation Queue — highest RPN first</h3>
          <button
            onClick={runAll}
            disabled={running}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-bold rounded-xl hover:bg-blue-700 disabled:opacity-40 inline-flex items-center gap-2 shadow-sm"
          >
            {running ? (
              <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />Generating fixes…</>
            ) : '⚡ Remediate All by Priority'}
          </button>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Failure Mode', 'Component', 'Before RPN', 'After RPN', 'Delta', 'Status'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const res = results?.find(x => x.id === r.id);
              return (
                <tr key={r.id} className="border-b border-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{r.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">{r.comp}</td>
                  <td className="px-4 py-3 font-bold text-gray-700">{r.rpn}</td>
                  <td className="px-4 py-3 font-bold">
                    {res ? <span className="text-green-600">{res.afterRpn}</span> : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    {res?.rpnDelta > 0 ? <span className="text-green-600 font-bold text-sm">↓ {res.rpnDelta}</span> : <span className="text-gray-200">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <Chip
                      label={res ? '✓ Applied' : running ? 'Generating…' : 'Queued'}
                      cls={res ? 'bg-green-100 text-green-700' : running ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {remError && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <p className="font-bold mb-1">⚠ Remediation failed</p>
          <p className="text-xs">{remError}</p>
        </div>
      )}

      {/* Per-fix detail cards */}
      {results && (
        <div className="space-y-3">
          {results.filter(r => r.diff).map(r => (
            <div key={r.id} className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <div>
                  <p className="font-bold text-gray-800 text-sm">{r.name}</p>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">{r.comp}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-center">
                    <p className="text-xs text-gray-400">Before</p>
                    <p className="text-lg font-bold text-gray-400 line-through">{r.rpn}</p>
                  </div>
                  <span className="text-gray-300">→</span>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">After</p>
                    <p className="text-lg font-bold text-green-600">{r.afterRpn}</p>
                  </div>
                  {r.rpnDelta > 0 && (
                    <span className="px-2 py-1 bg-green-50 text-green-700 text-xs font-bold rounded-lg border border-green-200">
                      🟢 −{r.rpnDelta}
                    </span>
                  )}
                </div>
              </div>
              <div className="p-5 space-y-4">
                {r.diff && (
                  <>
                    <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Code Diff</p>
                    <pre className="bg-gray-900 text-green-400 text-xs p-4 rounded-xl overflow-x-auto font-mono leading-relaxed">{r.diff}</pre>
                  </>
                )}
                {r.testCode && (
                  <>
                    <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Test Stub</p>
                    <pre className="bg-gray-50 text-gray-700 text-xs p-4 rounded-xl overflow-x-auto font-mono leading-relaxed border border-gray-100">{r.testCode}</pre>
                  </>
                )}
                {r.desc && (
                  <p className="text-xs text-gray-500 italic border-l-4 border-blue-200 pl-3">{r.desc}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
