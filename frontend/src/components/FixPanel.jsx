import { useEffect, useState } from 'react';
import { proposeFix, recordFixDecision } from '../api';

// B-053, B-056 (ADR-033): a proposed fix for one action, shown in a side panel for a person to accept, edit or reject.
// The server shows the code the finding cites, checks every edit and builds the diff. Nothing is applied to any repository.

function DiffView({ diff }) {
  return (
    <pre className="text-xs font-mono rounded-xl border border-gray-200 bg-gray-50 p-3 overflow-x-auto leading-relaxed">
      {diff.split('\n').map((line, i) => (
        <div key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'text-green-700 bg-green-50' : line.startsWith('-') && !line.startsWith('---') ? 'text-red-700 bg-red-50' : 'text-gray-500'}>{line || ' '}</div>
      ))}
    </pre>
  );
}

const editBody = (e) => ({ file: e.file, start_line: e.start_line, end_line: e.end_line, replacement: e.replacement });

export default function FixPanel({ workspaceId, scanId, failureMode, action, onClose }) {
  const [state, setState]       = useState('loading');     // loading | ready | error | done
  const [error, setError]       = useState('');
  const [proposal, setProposal] = useState(null);
  const [edits, setEdits]       = useState([]);
  const [outcome, setOutcome]   = useState(null);          // what the server made of the final edits
  const [decision, setDecision] = useState('');
  const [copied, setCopied]     = useState(false);
  const [deciding, setDeciding] = useState(false);

  useEffect(() => {
    let live = true;
    setState('loading'); setProposal(null); setEdits([]); setError(''); setOutcome(null);     // a new fix never shows the old one
    proposeFix(workspaceId, scanId, failureMode, action.id)
      .then(p => { if (live) { setProposal(p); setEdits(p.edits.map(editBody)); setState('ready'); } })
      .catch(e => { if (live) { setError(e.message); setState('error'); } });
    return () => { live = false; };
  }, [workspaceId, scanId, failureMode, action.id]);

  const changed = proposal && edits.some((e, i) => e.replacement !== proposal.edits[i].replacement);

  const decide = async (value) => {
    if (deciding) return;
    setDeciding(true);
    setError('');
    try {
      const result = await recordFixDecision(workspaceId, scanId, failureMode, action.id, value, value === 'rejected' ? [] : edits);
      if (value === 'rejected') { onClose(); return; }
      setOutcome(result);
      setDecision(value);
      setState('done');
    } catch (e) { setError(e.message); }
    finally { setDeciding(false); }
  };

  const setReplacement = (i, text) => setEdits(edits.map((e, k) => (k === i ? { ...e, replacement: text } : e)));
  const finalDiff = outcome?.diff ?? '';

  return (
    <aside role="dialog" aria-label="Proposed fix" className="fixed top-0 right-0 z-50 h-full w-[36rem] max-w-full bg-white border-l border-gray-200 shadow-2xl flex flex-col">
      <div className="px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-400">Proposed fix</p>
          <p className="text-sm font-bold text-gray-800">{action.title}</p>
          <p className="text-xs text-gray-500 truncate">{failureMode}</p>
        </div>
        <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-700 text-lg leading-none">×</button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {state === 'loading' && <p className="text-sm text-gray-500">The model is rewriting the code. This takes up to a minute.</p>}
        {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
        {proposal && (
          <>
            {proposal.reason && <p className="text-sm text-gray-700">{proposal.reason}</p>}
            {proposal.context === 'guess' && <p className="text-xs text-amber-600">The finding cites no file, so the code shown to the model was chosen by a keyword guess. Check that it is the right place.</p>}
            {proposal.parse_errors?.length > 0 && <p className="text-xs text-red-600">{proposal.parse_errors.join(', ')} no longer parses after this change. Review it before use.</p>}
            {proposal.dropped?.length > 0 && (
              <div className="text-xs text-amber-700">
                <p className="font-semibold">Not applied:</p>
                <ul className="list-disc ml-4">{proposal.dropped.map((d, i) => <li key={i}>{d.file}: {d.reason}</li>)}</ul>
              </div>
            )}

            {state === 'ready' && edits.map((e, i) => (
              <div key={i}>
                <p className="text-xs font-semibold text-gray-700 mb-1 font-mono">{e.file} <span className="text-gray-400">{e.end_line < e.start_line ? `insert before line ${e.start_line}` : `lines ${e.start_line}-${e.end_line}`}</span></p>
                {proposal.edits[i].original && <pre className="text-xs font-mono rounded-lg bg-red-50 text-red-700 p-2 mb-1 overflow-x-auto">{proposal.edits[i].original}</pre>}
                <textarea aria-label={`Replacement for ${e.file} lines ${e.start_line}-${e.end_line}`} value={e.replacement} onChange={ev => setReplacement(i, ev.target.value)}
                          className="w-full h-28 text-xs font-mono border border-gray-200 rounded-xl p-2 focus:outline-none focus:ring-1 focus:ring-blue-300" />
              </div>
            ))}
            {state === 'ready' && changed && <p className="text-xs text-amber-600">You changed the code; it will be recorded as edited.</p>}

            <div>
              <p className="text-xs font-semibold text-gray-700 mb-1">{state === 'done' ? 'Final change' : 'Change as proposed'}</p>
              <DiffView diff={state === 'done' ? finalDiff : proposal.diff} />
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
          <button onClick={() => decide(changed ? 'edited' : 'accepted')} disabled={deciding} className="px-4 py-2 rounded-xl bg-green-600 text-white text-sm font-bold hover:bg-green-700">Accept</button>
          <button onClick={() => decide('rejected')} disabled={deciding} className="px-4 py-2 rounded-xl bg-white border border-gray-200 text-gray-700 text-sm font-semibold hover:bg-gray-50">Reject</button>
        </div>
      )}
      {state === 'done' && (
        <div className="px-5 py-3 border-t border-gray-100 space-y-2">
          <p className="text-xs text-green-700 font-semibold">Fix {decision} and recorded in the audit trail. It has not been applied to your repository.</p>
          {outcome?.parse_errors?.length > 0 && <p className="text-xs text-red-600">{outcome.parse_errors.join(', ')} no longer parses.</p>}
          <div className="flex gap-2">
            <button onClick={() => { navigator.clipboard?.writeText(finalDiff).then(() => setCopied(true)).catch(() => setCopied(false)); }}
                    className="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs font-semibold">{copied ? 'Copied' : 'Copy diff'}</button>
            <a href={`data:text/plain;charset=utf-8,${encodeURIComponent(finalDiff)}`} download="fix.patch"
               className="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs font-semibold">Download patch</a>
          </div>
          <p className="text-xs text-gray-400">Apply it yourself with <span className="font-mono">git apply fix.patch</span>.</p>
        </div>
      )}
    </aside>
  );
}
