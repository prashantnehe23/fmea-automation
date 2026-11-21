import { useState, useEffect } from 'react';
import { getFindings, setFindingState } from '../api';

// B-031 (ADR-019): what the last scan changed. Findings the code no longer shows wait here for a person to
// confirm the fix (or say it is still there); findings that returned after a fix are listed as regressed.
export default function FindingChanges({ workspaceId, refreshKey, canDecide }) {
  const [data, setData]   = useState(null);
  const [error, setError] = useState('');

  const load = () => {
    if (!workspaceId) { setData(null); return; }
    getFindings(workspaceId).then(setData).catch(() => setData(null));
  };
  useEffect(load, [workspaceId, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = async (failureMode, state) => {
    setError('');
    try { await setFindingState(workspaceId, failureMode, state); load(); }
    catch (e) { setError(e.message); }
  };

  const pending   = data?.findings.filter(f => f.state === 'fix_candidate') ?? [];
  const regressed = data?.findings.filter(f => f.state === 'regressed') ?? [];
  if (!pending.length && !regressed.length) return null;

  return (
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900" role="region" aria-label="Changes since the last scan">
      {pending.length > 0 && (
        <>
          <p className="font-bold mb-1">{pending.length} finding{pending.length > 1 ? 's' : ''} no longer reproduced. Fixed?</p>
          {pending.map(f => (
            <div key={f.failure_mode} className="flex items-center gap-2 py-1">
              <span className="flex-1 min-w-0 truncate" title={f.failure_mode}>{f.failure_mode}</span>
              {canDecide && (
                <>
                  <button onClick={() => decide(f.failure_mode, 'fixed')} className="font-semibold text-green-700 hover:underline">Confirm fixed</button>
                  <button onClick={() => decide(f.failure_mode, 'confirmed')} className="font-semibold text-red-700 hover:underline">Still present</button>
                </>
              )}
            </div>
          ))}
        </>
      )}
      {regressed.length > 0 && (
        <p className={`${pending.length ? 'mt-2 ' : ''}font-bold text-red-700`}>
          Returned after a fix: {regressed.map(f => f.failure_mode).join(', ')}
        </p>
      )}
      {error && <p role="alert" className="mt-1 text-red-600">{error}</p>}
    </div>
  );
}
