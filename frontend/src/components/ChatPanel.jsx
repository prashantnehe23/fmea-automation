import { useState, useEffect, useRef, useCallback } from 'react';
import Markdown from './Markdown';
import { getChatHistory, streamChat, applyProposal, dismissProposal } from '../api';

/**
 * Results chat (B-025): ask follow-up questions about the selected project's latest scan.
 * Answers stream in; tool use ("read api/main.py") is shown; Stop keeps the partial answer.
 * The conversation lives on the server, so it is restored after a refresh or restart.
 */

const STARTERS = [
  'How could the highest-risk scenario be exploited in this code?',
  'Why is the top scenario scored the way it is?',
  'What should we fix first, and why?',
];

const fmtUsd = (n) => `$${(n ?? 0).toFixed(n >= 0.1 ? 2 : 4)}`;
const fmtTok = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n ?? 0}`);

const ERROR_HINT = {
  no_scan:    'Run a scan for this project first, then ask questions about it.',
  no_api_key: 'Add an API key for the selected model in Settings (gear icon).',
  provider_blocked: 'Open Settings (gear icon), choose another model and ask again.',
};

function ToolChips({ activity }) {
  if (!activity?.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mb-1.5">
      {activity.map((a, i) => (
        <span
          key={i}
          className={`text-[10px] px-1.5 py-0.5 rounded-md font-mono border ${a.ok === false
            ? 'bg-red-50 text-red-500 border-red-100' : 'bg-gray-50 text-gray-500 border-gray-100'}`}
        >{a.ok === false ? '⚠ ' : '🔎 '}{a.label}</span>
      ))}
    </div>
  );
}

function Score({ label, value }) {
  return <span className="font-mono">{label}{value}</span>;
}

const STATUS_BADGE = {
  applied:   { text: 'Applied ✓',      cls: 'bg-green-50 text-green-700' },
  dismissed: { text: 'Dismissed',      cls: 'bg-gray-100 text-gray-500' },
  invalid:   { text: 'No longer applicable', cls: 'bg-gray-100 text-gray-500' },
};

/** A change the model proposed. Nothing happens until the user clicks Apply.
 *  `canDecide` follows the existing rules: score changes are for the Security Engineer persona
 *  (as on the Scoring page); unlocking is open to everyone (as on the Scan page). */
function ProposalCard({ p, busy, error, canDecide, onApply, onDismiss }) {
  const pay = p.payload ?? {};
  const before = pay.before ?? {};
  const open = p.status === 'proposed';
  return (
    <div className="mt-2 border border-amber-200 bg-amber-50/60 rounded-xl p-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-amber-700">
        {p.kind === 'score_adjustment' ? 'Proposed score change' : 'Proposed unlock'}
      </p>
      <p className="text-xs font-semibold text-gray-800 mt-0.5">{p.failure_mode}</p>

      {p.kind === 'score_adjustment' ? (
        <p className="text-xs text-gray-700 mt-1 flex flex-wrap items-center gap-x-1.5">
          <Score label="S" value={before.severity} /><Score label="O" value={before.occurrence} /><Score label="D" value={before.detection} />
          <span className="text-gray-400">→</span>
          <strong><Score label="S" value={pay.severity} /> <Score label="O" value={pay.occurrence} /> <Score label="D" value={pay.detection} /></strong>
          <span className="text-gray-500">· RPN {before.rpn} → <strong>{pay.rpn}</strong></span>
        </p>
      ) : (
        <p className="text-xs text-gray-700 mt-1">Drop this scenario's locked scores so the next scan re-scores it.</p>
      )}

      <p className="text-xs text-gray-600 mt-1.5 leading-relaxed">{p.reason}</p>

      {open && !canDecide && (
        <p className="text-[11px] text-amber-700 mt-2">
          Only a Security Engineer can apply or dismiss score changes. Switch persona to decide.
        </p>
      )}

      {open && canDecide ? (
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => onApply(p)}
            disabled={busy}
            className="text-xs font-semibold px-3 py-1 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
          >{busy ? 'Working…' : 'Apply'}</button>
          <button
            onClick={() => onDismiss(p)}
            disabled={busy}
            className="text-xs font-semibold px-3 py-1 rounded-lg bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >Dismiss</button>
        </div>
      ) : !open && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-md ${STATUS_BADGE[p.status]?.cls ?? ''}`}>
            {STATUS_BADGE[p.status]?.text ?? p.status}
          </span>
          {p.status === 'applied' && p.result?.new_rpn != null && (
            <span className="text-[11px] text-gray-500">RPN now {p.result.new_rpn} ({p.result.priority})</span>
          )}
          {p.status === 'applied' && p.result?.unlocked && (
            <span className="text-[11px] text-gray-500">Re-scan to re-score it</span>
          )}
        </div>
      )}
      {error && <p className="text-xs text-red-500 mt-1.5">{error}</p>}
    </div>
  );
}

function Message({ m, proposalState, persona, onApply, onDismiss }) {
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-blue-600 text-white text-xs rounded-2xl rounded-br-md px-3 py-2 whitespace-pre-wrap break-words">
          {m.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex">
      <div className="max-w-[95%] min-w-0">
        <ToolChips activity={m.tool_activity} />
        <div className="bg-gray-50 border border-gray-100 rounded-2xl rounded-bl-md px-3 py-2">
          {m.content
            ? <Markdown text={m.content} />
            : <span className="text-xs text-gray-400">{m.tool_activity?.length ? 'Looking at the code…' : 'Thinking…'}</span>}
          {m.streaming && m.content && <span className="inline-block w-1.5 h-3 bg-gray-400 ml-0.5 align-middle animate-pulse" />}
        </div>
        {(m.proposals ?? []).map(p => (
          <ProposalCard
            key={p.id} p={p}
            busy={proposalState[p.id]?.busy} error={proposalState[p.id]?.error}
            canDecide={p.kind === 'unlock_scenario' || persona === 'security_engineer'}
            onApply={onApply} onDismiss={onDismiss}
          />
        ))}
        {m.error && (
          <p className="text-xs text-red-500 mt-1">{m.error}{ERROR_HINT[m.errorCode] ? ` ${ERROR_HINT[m.errorCode]}` : ''}</p>
        )}
        {m.usage && !m.streaming && (
          <p className="text-[10px] text-gray-300 mt-1 pl-1">
            {fmtUsd(m.usage.cost_usd)} · {fmtTok(m.usage.prompt_tokens)} in / {fmtTok(m.usage.completion_tokens)} out
          </p>
        )}
      </div>
    </div>
  );
}

export default function ChatPanel({ workspaceId, projectName, persona, onClose, onProposalApplied }) {
  const [messages, setMessages] = useState([]);
  const [totals, setTotals]     = useState(null);
  const [hasScan, setHasScan]   = useState(true);
  const [input, setInput]       = useState('');
  const [busy, setBusy]         = useState(false);
  const [loading, setLoading]   = useState(false);
  const [proposalState, setProposalState] = useState({});   // id → { busy, error }
  const abortRef  = useRef(null);
  const bottomRef = useRef(null);

  const loadHistory = useCallback(async () => {
    if (!workspaceId) { setMessages([]); setTotals(null); return; }
    setLoading(true);
    try {
      const h = await getChatHistory(workspaceId);
      setMessages(h.messages.map(m => ({
        id: m.id, role: m.role, content: m.content,
        tool_activity: m.tool_activity, usage: m.role === 'assistant' ? m.usage : null,
        proposals: m.proposals ?? [],
      })));
      setTotals(h.totals);
      setHasScan(h.has_scan);
    } catch {
      setMessages([]);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  // Restore the conversation whenever the project changes (and after a refresh).
  useEffect(() => {
    abortRef.current?.abort();
    setBusy(false);
    loadHistory();
  }, [loadHistory]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ block: 'end' }); }, [messages]);

  const patchLast = (patch) => setMessages(prev => {
    const next = [...prev];
    next[next.length - 1] = { ...next[next.length - 1], ...patch };
    return next;
  });

  const send = async (text) => {
    const question = text.trim();
    if (!question || busy || !workspaceId) return;
    setInput('');
    setBusy(true);
    setMessages(prev => [...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', tool_activity: [], streaming: true },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const ev of streamChat(workspaceId, question, controller.signal)) {
        if (ev.type === 'tool') {
          setMessages(prev => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, tool_activity: [...(last.tool_activity ?? []), ev] };
            return next;
          });
        } else if (ev.type === 'token') {
          setMessages(prev => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, content: last.content + ev.text };
            return next;
          });
        } else if (ev.type === 'proposal') {
          setMessages(prev => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, proposals: [...(last.proposals ?? []), ev.proposal] };
            return next;
          });
        } else if (ev.type === 'done') {
          patchLast({ content: ev.answer, tool_activity: ev.tool_activity, usage: ev.usage,
                      proposals: ev.proposals ?? [], streaming: false });
          setTotals(ev.thread_totals);
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        await loadHistory();            // the server saved what was written before Stop
      } else {
        patchLast({ streaming: false, error: err.message, errorCode: err.code });
        if (err.code === 'no_scan') setHasScan(false);
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const setProposal = (id, patch) =>
    setMessages(prev => prev.map(m => ({
      ...m, proposals: (m.proposals ?? []).map(p => (p.id === id ? { ...p, ...patch } : p)),
    })));

  const decide = async (p, action) => {
    setProposalState(s => ({ ...s, [p.id]: { busy: true } }));
    try {
      const out = await (action === 'apply' ? applyProposal(p.id) : dismissProposal(p.id));
      setProposal(p.id, out.proposal);
      setProposalState(s => ({ ...s, [p.id]: {} }));
      if (action === 'apply') onProposalApplied?.(out);
    } catch (err) {
      setProposalState(s => ({ ...s, [p.id]: { error: err.message } }));
      if (['already_decided', 'stale', 'not_found'].includes(err.code)) await loadHistory();   // sync with the server
    }
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); }
  };

  const noProject = !workspaceId;
  const canAsk = !noProject && hasScan;

  return (
    <aside className="w-[26rem] max-w-[45vw] flex-shrink-0 border-l border-gray-100 bg-white flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2 flex-shrink-0">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-gray-900">Ask about the results</p>
          <p className="text-[11px] text-gray-400 truncate">
            {projectName ? `${projectName} · latest scan` : 'No project selected'}
            {totals?.cost_usd > 0 && ` · ${fmtUsd(totals.cost_usd)} so far (${fmtTok(totals.prompt_tokens + totals.completion_tokens)} tokens)`}
          </p>
        </div>
        <button onClick={onClose} title="Close chat" className="w-7 h-7 rounded-lg hover:bg-gray-100 text-gray-400">✕</button>
      </div>

      {/* Conversation */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {loading && <p className="text-xs text-gray-400">Loading conversation…</p>}

        {!loading && noProject && (
          <p className="text-xs text-gray-400 text-center mt-8">
            Select a project that has been scanned to ask questions about its results.
          </p>
        )}
        {!loading && !noProject && !hasScan && messages.length === 0 && (
          <p className="text-xs text-gray-400 text-center mt-8">{ERROR_HINT.no_scan}</p>
        )}

        {!loading && canAsk && messages.length === 0 && (
          <div className="space-y-2 mt-2">
            <p className="text-xs text-gray-400">
              The assistant already knows this scan's findings and can read the scanned code. Try:
            </p>
            {STARTERS.map(q => (
              <button
                key={q}
                onClick={() => send(q)}
                className="block w-full text-left text-xs text-gray-600 bg-gray-50 hover:bg-blue-50 hover:text-blue-700 border border-gray-100 rounded-xl px-3 py-2 transition-colors"
              >{q}</button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <Message
            key={m.id ?? `new-${i}`} m={m} proposalState={proposalState} persona={persona}
            onApply={p => decide(p, 'apply')} onDismiss={p => decide(p, 'dismiss')}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-gray-100 flex-shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={!canAsk}
            rows={2}
            placeholder={canAsk ? 'Ask why, how it is exploited, what to fix…' : 'Scan a project first'}
            className="flex-1 text-xs border border-gray-200 rounded-xl px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-300 disabled:bg-gray-50 disabled:text-gray-300"
          />
          {busy ? (
            <button
              onClick={() => abortRef.current?.abort()}
              className="text-xs font-semibold px-3 py-2 rounded-xl bg-red-50 text-red-600 hover:bg-red-100"
            >Stop</button>
          ) : (
            <button
              onClick={() => send(input)}
              disabled={!canAsk || !input.trim()}
              className="text-xs font-semibold px-3 py-2 rounded-xl bg-blue-600 text-white disabled:opacity-40"
            >Send</button>
          )}
        </div>
        <p className="text-[10px] text-gray-300 mt-1.5">Enter to send · Shift+Enter for a new line</p>
      </div>
    </aside>
  );
}
