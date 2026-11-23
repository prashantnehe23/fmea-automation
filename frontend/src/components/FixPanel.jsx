import { useEffect, useState } from 'react';
import { proposeFix, recordFixDecision } from '../api';

// B-053: a proposed fix for one action, shown in a side panel for a person to accept, edit or reject.
// Nothing is applied to any repository here; accepted code can be copied or downloaded as a patch.

function DiffView({ diff }) {
  return (
    <pre className="text-xs font-mono rounded-xl border border-gray-200 bg-gray-50 p-3 overflow-x-auto leading-relaxed">
      {diff.split('\n').map((line, i) => (
        <div key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'text-green-700 bg-green-50' : line.startsWith('-') && !line.startsWith('---') ? 'text-red-700 bg-red-50' : 'text-gray-500'}>{line || ' '}</div>
      ))}
    </pre>
  );
}

export default function FixPanel({ scanId, failureMode, action, onClose }) {
  const [state, setState]       = useState('loading');     // loading | ready | error | done
  const [error, setError]       = useState('');
  const [proposal, setProposal] = useState(null);
  const [code, setCode]         = useState('');
  const [decision, setDecision] = useState('');
  const [copied, setCopied]     = useState(false);

  useEffect(() => {
    let live = true;
    proposeFix(scanId, failureMode, action.id)
      .then(p => { if (live) { setProposal(p); setCode(p.patched_snippet); setState('ready'); } })
      .catch(e => { if (live) { setError(e.message); setState('error'); } });
    return () => { live = false; };
  }, [scanId, failureMode, action.id]);

  const decide = async (value) => {
    setError('');
    try {
      await recordFixDecision(scanId, failureMode, action.id, value);
      if (value === 'rejected') { onClose(); return; }
      setDecision(value);
      setState('done');
    } catch (e) { setError(e.message); }
  };

  const edited = proposal && code !== proposal.patched_snippet;
  const patchText = proposal ? `${proposal.code_diff}\n\n# Fixed code\n${code}\n\n# Test\n${proposal.test_code}\n` : '';

  return (
    <aside role="dialog" aria-label="Proposed fix" className="fixed top-0 right-0 z-50 h-full w-[34rem] max-w-full bg-white border-l border-gray-200 shadow-2xl flex flex-col">
      <div className="px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-400">Proposed fix</p>
          <p className="text-sm font-bold text-gray-800">{action.title}</p>
          <p className="text-xs text-gray-500 truncate">{failureMode}</p>
        </div>
        <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-700 text-lg leading-none">×</button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {state === 'loading' && <p className="text-sm text-gray-500">The model is writing a fix. This takes up to a minute.</p>}
        {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
        {proposal && (
          <>
            <div>
              <p className="text-xs font-semibold text-gray-700 mb-1">Change</p>
              <DiffView diff={proposal.code_diff} />
            </div>
            <div>
              <label htmlFor="fixed-code" className="text-xs font-semibold text-gray-700 block mb-1">Fixed code</label>
              <textarea id="fixed-code" aria-label="Fixed code" value={code} onChange={e => setCode(e.target.value)} readOnly={state === 'done'}
                        className="w-full h-48 text-xs font-mono border border-gray-200 rounded-xl p-3 focus:outline-none focus:ring-1 focus:ring-blue-300" />
              {edited && state !== 'done' && <p className="text-xs text-amber-600 mt-1">You changed the code; it will be recorded as edited.</p>}
            </div>
            <div>
              <p className="text-xs font-semibold text-gray-700 mb-1">Test</p>
              {proposal.test_description && <p className="text-xs text-gray-500 mb-1">{proposal.test_description}</p>}
              <pre className="text-xs font-mono rounded-xl border border-gray-200 bg-gray-50 p-3 overflow-x-auto">{proposal.test_code}</pre>
            </div>
            <p className="text-xs text-gray-400">Review before use: a model wrote this, and it has not been run against your project.</p>
          </>
        )}
      </div>

      {state === 'ready' && (
        <div className="px-5 py-3 border-t border-gray-100 flex gap-2">
          <button onClick={() => decide(edited ? 'edited' : 'accepted')} className="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold hover:bg-green-700">Accept</button>
          <button onClick={() => decide('rejected')} className="px-4 py-2 rounded-xl bg-white border border-gray-200 text-gray-700 text-sm font-semibold hover:bg-gray-50">Reject</button>
        </div>
      )}
      {state === 'done' && (
        <div className="px-5 py-3 border-t border-gray-100 space-y-2">
          <p className="text-xs text-green-700 font-semibold">Fix {decision} and recorded in the audit trail. It has not been applied to your repository.</p>
          <div className="flex gap-2">
            <button onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); }}
                    className="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs font-semibold">{copied ? 'Copied' : 'Copy code'}</button>
            <a href={`data:text/plain;charset=utf-8,${encodeURIComponent(patchText)}`} download="fix-proposal.txt"
               className="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs font-semibold">Download proposal</a>
          </div>
        </div>
      )}
    </aside>
  );
}
