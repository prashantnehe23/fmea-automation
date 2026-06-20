/**
 * ScanPage.jsx
 *
 * 4-scenario state machine driven by the selected project's state:
 *
 *  no-selection  → no project selected; prompt to pick / create one
 *  no-repo       → project exists but has no GitHub repo URL; ask for one
 *  repo-no-scan  → repo linked but never scanned; show info + "Scan Now"
 *  has-scan      → scan results exist; show summary + allow rescan
 *
 * During / after a scan the progress panel and result banner overlay any
 * of the above scenarios.
 *
 * For executive / risk-manager (wide scope) the original portfolio table
 * is kept.
 */

import { useState } from 'react';
import ScopeHeader from '../components/ScopeHeader';
import KpiRow from '../components/KpiRow';
import { SCOPE_LABEL, ALL_RISKS } from '../data';
import { filterRisks, getSelectionLabel, aggregateBy } from '../helpers';
import { streamGithubScan, streamScan, STAGE_LABELS, deleteWorkspaceScenarios } from '../api';

// ── Stage order constants ─────────────────────────────────────────────────────

const GITHUB_STAGES = [
  'repo_scan', 'repo_tree', 'readme', 'fetch_files', 'files_ready',
  'surveyor', 'saboteur', 'controls', 'actuary', 'sre', 'validator', 'registry', 'eval',
];

const CODE_STAGES = [
  'surveyor', 'saboteur', 'controls', 'actuary', 'sre', 'validator', 'registry', 'eval',
];

// ── Progress panel ────────────────────────────────────────────────────────────

function ProgressPanel({ stages, stageOrder, error }) {
  const done = stages.filter(s => s.status === 'done' || s.status === 'running').length;
  const pct  = Math.round((done / stageOrder.length) * 100);

  return (
    <div className="mt-5 p-5 rounded-2xl border border-blue-100 bg-blue-50">
      <div className="flex justify-between text-xs text-blue-600 font-semibold mb-2">
        <span>Pipeline running…</span>
        <span>{pct}%</span>
      </div>
      <div className="w-full bg-blue-100 rounded-full h-2 mb-4">
        <div
          className="bg-blue-500 h-2 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ul className="space-y-1">
        {stages.map(s => (
          <li key={s.stage} className="flex items-center gap-2 text-xs text-blue-800">
            {s.status === 'done'    && <span className="text-green-600">✓</span>}
            {s.status === 'running' && (
              <span className="animate-spin inline-block w-3 h-3 border-2 border-blue-600 border-t-transparent rounded-full" />
            )}
            {!s.status && <span className="text-gray-300">○</span>}
            {STAGE_LABELS[s.stage] ?? s.stage}
          </li>
        ))}
      </ul>
      {error && <p className="mt-3 text-xs text-red-600 font-semibold">⚠ {error}</p>}
    </div>
  );
}

// ── Scan complete banner ──────────────────────────────────────────────────────

function ScanComplete({ result, repo }) {
  const risks        = result?.risks ?? [];
  const critical     = risks.filter(r => r.priority === 'Critical').length;
  const high         = risks.filter(r => r.priority === 'High').length;
  const medium       = risks.filter(r => r.priority === 'Medium').length;
  const maxRpn       = risks.reduce((m, r) => Math.max(m, r.rpn), 0);
  const fromCache    = result?.from_cache      ?? false;
  const locked       = result?.registry_locked ?? false;
  const newScenarios = result?.new_scenarios   ?? [];
  const lockedCount  = risks.length - newScenarios.length;

  return (
    <div className="mt-5 p-5 rounded-2xl border border-green-200 bg-green-50 space-y-3">
      {/* Source + registry badges */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${
          fromCache
            ? 'bg-blue-50 border-blue-200 text-blue-700'
            : 'bg-green-100 border-green-300 text-green-800'
        }`}>
          {fromCache ? '⚡ Served from cache — no LLM calls made' : '🔬 Fresh analysis via LLM'}
        </span>

        {locked && lockedCount > 0 && (
          <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-gray-100 border border-gray-200 text-gray-700">
            🔒 {lockedCount} scenario{lockedCount !== 1 ? 's' : ''} locked — results are deterministic
          </span>
        )}
        {newScenarios.length > 0 && (
          <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">
            🆕 {newScenarios.length} new scenario{newScenarios.length !== 1 ? 's' : ''} registered
          </span>
        )}
        {!locked && (
          <span className="text-xs px-2.5 py-1 rounded-full bg-blue-50 border border-blue-200 text-blue-600">
            🔓 Scenarios locked for future rescans — results will stay consistent
          </span>
        )}
      </div>

      <p className="font-bold text-green-800">
        ✅ {risks.length} failure scenario{risks.length !== 1 ? 's' : ''} identified
      </p>

      {repo && (
        <p className="text-xs text-green-600">
          📦 {repo.owner}/{repo.repo} · {repo.files_scanned} file(s) scanned
          {repo.readme_used && ' · README context applied'}
        </p>
      )}

      <div className="flex flex-wrap gap-4 text-sm text-green-700">
        {critical > 0 && <span>🔴 {critical} Critical</span>}
        {high     > 0 && <span>🟠 {high} High</span>}
        {medium   > 0 && <span>🟡 {medium} Medium</span>}
        {maxRpn   > 0 && <span>Highest RPN: <strong>{maxRpn}</strong></span>}
      </div>

      <p className="text-xs text-green-500">
        Results saved — you can refresh the page and they will still be here.
        Navigate to Failure Scenarios → Risk Scoring → Mitigations to explore.
      </p>
    </div>
  );
}

// ── Inline repo URL form ──────────────────────────────────────────────────────

function RepoUrlForm({ initial = '', onSave, label = 'Link Repository' }) {
  const [url, setUrl] = useState(initial);
  return (
    <form
      onSubmit={e => { e.preventDefault(); if (url.trim()) onSave(url.trim()); }}
      className="flex gap-2"
    >
      <input
        className="flex-1 px-3 py-2 rounded-xl border border-gray-200 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-200 bg-white"
        placeholder="https://github.com/owner/repo"
        value={url}
        onChange={e => setUrl(e.target.value)}
      />
      <button
        type="submit"
        disabled={!url.trim()}
        className="px-5 py-2 rounded-xl bg-blue-600 text-white text-sm font-bold hover:bg-blue-700 disabled:opacity-40 transition-colors shadow-sm"
      >
        {label}
      </button>
    </form>
  );
}

// ── Last scan summary card ────────────────────────────────────────────────────

function LastScanCard({ history }) {
  const risks    = history.result?.risks ?? [];
  const critical = risks.filter(r => r.priority === 'Critical').length;
  const high     = risks.filter(r => r.priority === 'High').length;
  const medium   = risks.filter(r => r.priority === 'Medium').length;
  const date     = history.timestamp
    ? new Date(history.timestamp).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : '—';

  return (
    <div className="p-5 rounded-2xl border border-gray-100 bg-white shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-gray-800 text-sm">Last Scan Results</h3>
        <div className="flex items-center gap-2">
          {history.registry_locked && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 border border-gray-200 text-gray-600">
              🔒 {history.locked_count ?? history.risk_count} locked
            </span>
          )}
          <span className="text-xs text-gray-400">{date}</span>
        </div>
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <span className="text-gray-600">{history.risk_count} scenario{history.risk_count !== 1 ? 's' : ''}</span>
        {critical > 0 && <span className="text-red-600 font-semibold">🔴 {critical} Critical</span>}
        {high     > 0 && <span className="text-orange-500 font-semibold">🟠 {high} High</span>}
        {medium   > 0 && <span className="text-amber-500">🟡 {medium} Medium</span>}
        {history.max_rpn > 0 && (
          <span className="text-gray-600">Highest RPN: <strong className="text-red-600">{history.max_rpn}</strong></span>
        )}
      </div>
    </div>
  );
}

// ── Main ScanPage ─────────────────────────────────────────────────────────────

export default function ScanPage({
  persona,
  sel,
  scope,
  hierarchy = [],
  scanHistory = {},
  liveRisks,
  liveScanId,
  onScanComplete,
  onUpdateProjectRepo,
}) {
  const [scanning,    setScan]      = useState(false);
  const [stages,      setStages]    = useState([]);
  const [stageOrder,  setStageOrder] = useState(GITHUB_STAGES);
  const [scanError,   setScanError] = useState('');
  const [result,      setResult]    = useState(null);
  const [repoInfo,    setRepoInfo]  = useState(null);   // {owner, repo, files_scanned, readme_used}
  const [showPaste,   setShowPaste] = useState(false);  // fallback: paste code directly
  const [pasteCode,   setPasteCode] = useState('');
  const [unlocking,   setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState('');

  // Derive current project from the live hierarchy
  const portfolio = hierarchy.find(p => p.id === sel?.portfolioId);
  const project   = portfolio?.projects.find(pr => pr.id === sel?.projectId);
  const lastScan  = project ? scanHistory[project.id] : null;

  // Determine which scenario we're in
  const scenario = !sel?.projectId
    ? 'no-selection'
    : !project?.repoUrl
    ? 'no-repo'
    : !lastScan
    ? 'repo-no-scan'
    : 'has-scan';

  // ── GitHub scan runner ──────────────────────────────────────────────────────

  const runGithubScan = async (repoUrl, forceRerun = false) => {
    setScan(true);
    setScanError('');
    setResult(null);
    setRepoInfo(null);
    const order = GITHUB_STAGES;
    setStageOrder(order);
    setStages(order.map(s => ({ stage: s })));

    const ws = project
      ? { customer: portfolio?.name ?? '', project: project.name, function: '', business_tier: project.businessTier ?? 'Tier 1', user_type: project.userType ?? 'external_customers' }
      : null;

    try {
      for await (const event of streamGithubScan(repoUrl, ws, 7, forceRerun)) {
        if (event.stage === 'complete') {
          setStages(prev => prev.map(s => ({ ...s, status: 'done' })));
          setResult(event.result);
          setRepoInfo(event.repo ?? null);
          setScan(false);
          onScanComplete?.(event.scan_id, event.result, project?.id, repoUrl);
        } else if (event.stage === 'error') {
          setScanError(event.msg ?? 'Scan failed');
          setScan(false);
        } else {
          setStages(prev => prev.map(s => {
            const idx = order.indexOf(s.stage);
            const cur = order.indexOf(event.stage);
            if (idx < cur)  return { ...s, status: 'done' };
            if (idx === cur) return { ...s, status: 'running' };
            return s;
          }));
        }
      }
    } catch (err) {
      setScanError(String(err));
      setScan(false);
    }
  };

  // ── Code-paste scan runner (fallback) ───────────────────────────────────────

  const runCodeScan = async () => {
    if (!pasteCode.trim()) return;
    setScan(true);
    setScanError('');
    setResult(null);
    setRepoInfo(null);
    const order = CODE_STAGES;
    setStageOrder(order);
    setStages(order.map(s => ({ stage: s })));

    const ws = project
      ? { customer: portfolio?.name ?? '', project: project.name, function: '', business_tier: project.businessTier ?? 'Tier 1', user_type: project.userType ?? 'external_customers' }
      : null;

    try {
      for await (const event of streamScan(pasteCode, ws)) {
        if (event.stage === 'complete') {
          setStages(prev => prev.map(s => ({ ...s, status: 'done' })));
          setResult(event.result);
          setScan(false);
          onScanComplete?.(event.scan_id, event.result, project?.id, null);
        } else if (event.stage === 'error') {
          setScanError(event.msg ?? 'Scan failed');
          setScan(false);
        } else {
          setStages(prev => prev.map(s => {
            const idx = order.indexOf(s.stage);
            const cur = order.indexOf(event.stage);
            if (idx < cur)  return { ...s, status: 'done' };
            if (idx === cur) return { ...s, status: 'running' };
            return s;
          }));
        }
      }
    } catch (err) {
      setScanError(String(err));
      setScan(false);
    }
  };

  // ── Unlock registry then force-rescan ──────────────────────────────────────
  const runUnlockAndRescan = async () => {
    const workspaceId = lastScan?.workspace_id;
    if (!workspaceId) {
      setUnlockError('No workspace ID found — run a scan first.');
      return;
    }
    setUnlocking(true);
    setUnlockError('');
    try {
      await deleteWorkspaceScenarios(workspaceId);
      await runGithubScan(project.repoUrl, true);
    } catch (err) {
      setUnlockError(`Unlock failed: ${err.message}`);
    } finally {
      setUnlocking(false);
    }
  };

  // ── Executive / Risk Manager wide-scope: portfolio overview ─────────────────
  if (persona === 'executive' || (persona === 'risk_manager' && scope !== 'project')) {
    const risks = liveRisks ?? filterRisks(sel, scope);
    const label = getSelectionLabel(sel, scope, hierarchy);
    const rows  = aggregateBy(
      risks,
      r => r.portfolio,
      r => hierarchy.find(p => p.id === r.portfolio)?.name ?? r.portfolio,
    );
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={SCOPE_LABEL[scope]} name={label} sub="Scan status across your scope" />
        <KpiRow risks={risks} />
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h3 className="font-bold text-gray-800 text-sm">Scan Status by Portfolio</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {['Portfolio', 'Risks', 'Critical', 'Highest RPN'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.label} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3 font-semibold text-gray-800">{row.label}</td>
                  <td className="px-4 py-3 text-center">{row.total}</td>
                  <td className="px-4 py-3 text-center text-red-600 font-bold">{row.critical}</td>
                  <td className="px-4 py-3 font-bold text-red-600">{row.maxRpn}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // ── Developer / SRE / Security: GitHub-first journey ────────────────────────
  const label = getSelectionLabel(sel, scope, hierarchy);

  return (
    <div className="p-8 max-w-3xl">
      <ScopeHeader
        scopeLabel={SCOPE_LABEL[scope] ?? 'Project'}
        name={label || 'No project selected'}
        sub={
          scenario === 'no-selection' ? 'Select a project from the sidebar to begin' :
          scenario === 'no-repo'      ? 'Link a GitHub repository to scan' :
          scenario === 'repo-no-scan' ? `Ready to scan — ${project.repoUrl}` :
          `Last scanned · rescan anytime`
        }
      />

      {/* ── Scenario: no project selected ───────────────────────── */}
      {scenario === 'no-selection' && !scanning && !result && (
        <div className="mt-6 p-6 rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50 text-center">
          <p className="text-4xl mb-3">📁</p>
          <p className="font-bold text-gray-700 mb-1">No project selected</p>
          <p className="text-sm text-gray-500">
            Select a project from the sidebar, or click{' '}
            <span className="font-semibold text-blue-600">＋ New Project</span>{' '}
            under a portfolio to create one.
          </p>
        </div>
      )}

      {/* ── Scenario: project has no repo URL ───────────────────── */}
      {scenario === 'no-repo' && !scanning && !result && (
        <div className="mt-6 space-y-5">
          <div className="p-5 rounded-2xl border border-blue-100 bg-blue-50">
            <p className="font-semibold text-blue-800 mb-1">Link a GitHub repository</p>
            <p className="text-xs text-blue-600 mb-4">
              Provide the URL of the public GitHub repo to scan. The README will be read first
              for business context, then all code files will be analysed.
            </p>
            <RepoUrlForm
              onSave={url => {
                onUpdateProjectRepo?.(project.id, url);
                // Immediately kick off the scan with the new URL
                runGithubScan(url);
              }}
              label="Link & Scan"
            />
          </div>

          {/* Code-paste fallback */}
          <div className="text-center">
            <button
              onClick={() => setShowPaste(p => !p)}
              className="text-xs text-gray-400 hover:text-blue-600 underline"
            >
              {showPaste ? 'Hide' : 'Or paste code directly (no repo needed)'}
            </button>
          </div>
          {showPaste && <CodePastePanel code={pasteCode} onChange={setPasteCode} onRun={runCodeScan} />}
        </div>
      )}

      {/* ── Scenario: repo linked, never scanned ────────────────── */}
      {scenario === 'repo-no-scan' && !scanning && !result && (
        <div className="mt-6 space-y-4">
          <div className="p-5 rounded-2xl border border-gray-100 bg-white shadow-sm">
            <div className="flex items-start gap-3">
              <span className="text-2xl">📦</span>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-800 text-sm truncate">{project.repoUrl}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  README will be fetched automatically for business context
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => runGithubScan(project.repoUrl)}
              className="px-6 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-bold hover:bg-blue-700 transition-colors shadow-sm flex items-center gap-2"
            >
              ▶ Run FMEA Scan
            </button>
            <button
              onClick={() => {
                onUpdateProjectRepo?.(project.id, '');
              }}
              className="text-xs text-gray-400 hover:text-red-500"
            >
              Change repo URL
            </button>
          </div>

          {/* Code-paste fallback */}
          <div className="text-center pt-2">
            <button
              onClick={() => setShowPaste(p => !p)}
              className="text-xs text-gray-400 hover:text-blue-600 underline"
            >
              {showPaste ? 'Hide' : 'Or paste code directly'}
            </button>
          </div>
          {showPaste && <CodePastePanel code={pasteCode} onChange={setPasteCode} onRun={runCodeScan} />}
        </div>
      )}

      {/* ── Scenario: existing scan results ─────────────────────── */}
      {scenario === 'has-scan' && !scanning && !result && (
        <div className="mt-6 space-y-4">
          <LastScanCard history={lastScan} />

          <div className="p-4 rounded-2xl border border-gray-100 bg-white shadow-sm flex items-center gap-3">
            <span className="text-lg">📦</span>
            <span className="text-xs font-mono text-gray-600 flex-1 truncate">{project.repoUrl}</span>
          </div>

          {/* Registry status + action buttons */}
          <div className="p-4 rounded-2xl border border-gray-100 bg-white shadow-sm space-y-3">
            {lastScan?.registry_locked ? (
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <p className="text-sm font-semibold text-gray-800">
                    🔒 {lastScan.locked_count ?? lastScan.risk_count} scenarios locked
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Rescanning will reuse these locked scores — results will be identical unless you unlock first.
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-500">
                🔓 No locked scenarios — the next scan will generate a fresh set and lock them.
              </p>
            )}

            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={() => runGithubScan(project.repoUrl, true)}
                disabled={unlocking}
                className="px-5 py-2 rounded-xl bg-blue-600 text-white text-sm font-bold hover:bg-blue-700 disabled:opacity-40 transition-colors shadow-sm"
              >
                🔄 Rescan
              </button>

              {lastScan?.registry_locked && lastScan?.workspace_id && (
                <button
                  onClick={runUnlockAndRescan}
                  disabled={unlocking}
                  className="px-5 py-2 rounded-xl bg-white border border-red-200 text-red-600 text-sm font-bold hover:bg-red-50 disabled:opacity-40 transition-colors"
                >
                  {unlocking
                    ? <span className="flex items-center gap-1.5"><span className="animate-spin inline-block w-3 h-3 border-2 border-red-400 border-t-transparent rounded-full" />Unlocking…</span>
                    : '🔓 Unlock & Rescan'
                  }
                </button>
              )}

              <p className="text-xs text-gray-400 flex-1">
                {lastScan?.registry_locked
                  ? 'Unlock removes all locked scores — the next scan will generate fresh scenarios from scratch.'
                  : 'README will be re-fetched for updated business context.'}
              </p>
            </div>

            {unlockError && (
              <p className="text-xs text-red-600 font-semibold">{unlockError}</p>
            )}
          </div>

          <div className="text-center">
            <button
              onClick={() => setShowPaste(p => !p)}
              className="text-xs text-gray-400 hover:text-blue-600 underline"
            >
              {showPaste ? 'Hide' : 'Or paste code directly'}
            </button>
          </div>
          {showPaste && <CodePastePanel code={pasteCode} onChange={setPasteCode} onRun={runCodeScan} />}
        </div>
      )}

      {/* ── Scanning: progress panel ─────────────────────────────── */}
      {scanning && stages.length > 0 && (
        <ProgressPanel stages={stages} stageOrder={stageOrder} error={scanError} />
      )}

      {/* ── Done: result banner ──────────────────────────────────── */}
      {!scanning && result && (
        <ScanComplete result={result} repo={repoInfo} />
      )}

      {/* ── Error banner ─────────────────────────────────────────── */}
      {!scanning && scanError && !result && (
        <div className="mt-5 p-4 rounded-2xl border border-red-200 bg-red-50 text-sm text-red-700">
          <p className="font-bold mb-1">⚠ Scan failed</p>
          <p className="text-xs">{scanError}</p>
          <p className="text-xs mt-2 text-red-500">
            Is the API server running?{' '}
            <code className="font-mono bg-red-100 px-1 rounded">python -m uvicorn api.main:app --reload --port 8000</code>
          </p>
        </div>
      )}
    </div>
  );
}

// ── Code paste fallback panel ─────────────────────────────────────────────────

function CodePastePanel({ code, onChange, onRun }) {
  return (
    <div className="p-4 rounded-2xl border border-gray-200 bg-gray-50 space-y-3">
      <p className="text-xs text-gray-500 font-semibold">Paste code to scan directly</p>
      <textarea
        className="w-full h-40 p-3 rounded-xl border border-gray-200 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-200 resize-none bg-white"
        placeholder={'def process_payment(amount, card):\n    # paste your code here…'}
        value={code}
        onChange={e => onChange(e.target.value)}
      />
      <button
        onClick={onRun}
        disabled={!code.trim()}
        className="px-5 py-2 rounded-xl bg-gray-700 text-white text-sm font-bold hover:bg-gray-900 disabled:opacity-40 transition-colors"
      >
        ▶ Scan Pasted Code
      </button>
    </div>
  );
}
