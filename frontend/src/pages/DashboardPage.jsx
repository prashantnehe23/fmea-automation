import { useState, useEffect } from 'react';
import KCard from '../components/KCard';
import AggTable from '../components/AggTable';
import { PRI } from '../helpers';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel, aggregateBy } from '../helpers';
import { getTelemetry } from '../api';

// ── Agent display order & labels ──────────────────────────────────────────────

const AGENT_ORDER = ['surveyor', 'saboteur', 'controls', 'actuary', 'sre', 'validator', 'llm_judge'];
const AGENT_LABEL = {
  surveyor: 'Surveyor',  saboteur: 'Saboteur', controls: 'Controls',
  actuary: 'Actuary',    sre: 'SRE Agent',      validator: 'Validator',
  llm_judge: 'LLM Judge',
};

// ── Tiny SVG sparkline (quality trend) ───────────────────────────────────────

function Sparkline({ points }) {
  if (!points.length) return <span className="text-xs text-gray-300">No data</span>;
  const vals = points.map(p => p.score);
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 1);
  const W = 120, H = 32, PAD = 2;
  const x = (i) => PAD + (i / Math.max(vals.length - 1, 1)) * (W - PAD * 2);
  const y = (v) => H - PAD - ((v - min) / (max - min || 1)) * (H - PAD * 2);
  const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = vals[vals.length - 1];
  const color = last >= 0.8 ? '#22c55e' : last >= 0.6 ? '#f59e0b' : '#ef4444';
  return (
    <svg width={W} height={H} className="overflow-visible">
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(vals.length - 1)} cy={y(last)} r="2.5" fill={color} />
    </svg>
  );
}

// ── Cost panel ────────────────────────────────────────────────────────────────

function CostSparkline({ points }) {
  if (!points.length) return <span className="text-xs text-gray-300">No data</span>;
  const vals = points.map(p => p.total_usd);
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 0.001);
  const W = 120, H = 32, PAD = 2;
  const x = (i) => PAD + (i / Math.max(vals.length - 1, 1)) * (W - PAD * 2);
  const y = (v) => H - PAD - ((v - min) / (max - min)) * (H - PAD * 2);
  const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return (
    <svg width={W} height={H} className="overflow-visible">
      <path d={d} fill="none" stroke="#6366f1" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(vals.length - 1)} cy={y(vals[vals.length - 1])} r="2.5" fill="#6366f1" />
    </svg>
  );
}

function CostPanel({ workspaceId }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspaceId) { setLoading(false); return; }
    setLoading(true);
    getTelemetry(workspaceId)
      .then(d => { setData(d?.cost_summary ?? null); setLoading(false); })
      .catch(() => setLoading(false));
  }, [workspaceId]);

  if (!workspaceId || loading || !data) return null;

  const agents = Object.entries(data.per_agent_usd ?? {});
  const maxAgent = Math.max(...agents.map(([, v]) => v), 0.000001);

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm space-y-4">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Cost Tracking</h3>

      {/* Summary row */}
      <div className="flex gap-4">
        <div>
          <p className="text-xs text-gray-400">Last scan</p>
          <p className="text-lg font-bold text-gray-800">
            ${(data.last_scan_usd ?? 0).toFixed(4)}
          </p>
        </div>
        {data.chat_usd > 0 && (
          <div className="border-l border-gray-100 pl-4">
            <p className="text-xs text-gray-400">Chat ({data.chat_turns} questions)</p>
            <p className="text-lg font-bold text-blue-600">
              ${data.chat_usd.toFixed(4)}
            </p>
          </div>
        )}
        {data.projected_monthly_usd > 0 && (
          <div className="border-l border-gray-100 pl-4">
            <p className="text-xs text-gray-400">Projected / month</p>
            <p className="text-lg font-bold text-indigo-600">
              ${data.projected_monthly_usd.toFixed(2)}
            </p>
          </div>
        )}
      </div>

      {/* Per-agent bars */}
      {agents.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">Last Scan — Cost by Agent</p>
          {agents.sort(([, a], [, b]) => b - a).map(([agent, usd]) => {
            const pct = Math.round((usd / maxAgent) * 100);
            return (
              <div key={agent} className="flex items-center gap-2 mb-1.5">
                <span className="text-xs text-gray-500 w-20 flex-shrink-0">
                  {AGENT_LABEL[agent] ?? agent}
                </span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-indigo-400 transition-all" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-xs font-mono text-gray-500 w-16 text-right flex-shrink-0">
                  ${usd.toFixed(4)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Cost trend */}
      {(data.cost_trend ?? []).length > 1 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">
            Cost Trend
            <span className="font-normal text-gray-400 ml-1">({data.cost_trend.length} scans)</span>
          </p>
          <CostSparkline points={data.cost_trend} />
        </div>
      )}
    </div>
  );
}

// ── System Health panel ───────────────────────────────────────────────────────

function SystemHealthPanel({ workspaceId }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  useEffect(() => {
    if (!workspaceId) { setLoading(false); return; }
    setLoading(true);
    getTelemetry(workspaceId)
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [workspaceId]);

  if (!workspaceId) return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm text-xs text-gray-400">
      Select a project with a completed scan to see health metrics.
    </div>
  );
  if (loading) return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm text-xs text-gray-400 animate-pulse">
      Loading telemetry…
    </div>
  );
  if (error) return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm text-xs text-red-400">
      Telemetry unavailable: {error}
    </div>
  );
  if (!data || data.total_spans === 0) return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">System Health</h3>
      <p className="text-xs text-gray-400">No telemetry yet — run a scan to populate.</p>
    </div>
  );

  const latency = data.last_scan_latency ?? {};
  const maxMs = Math.max(...Object.values(latency), 1);
  const errPct = Math.round((data.error_rate ?? 0) * 100);
  const trend  = data.quality_trend ?? [];
  const lastScore = trend.length ? trend[trend.length - 1].score : null;
  const qualityColor = lastScore == null ? 'text-gray-400'
    : lastScore >= 0.8 ? 'text-green-600' : lastScore >= 0.6 ? 'text-amber-600' : 'text-red-600';

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm space-y-5">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">System Health</h3>

      {/* Status pills */}
      <div className="flex gap-3 flex-wrap">
        <div className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-full ${
          errPct === 0 ? 'bg-green-50 text-green-700' : errPct < 10 ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full inline-block ${errPct === 0 ? 'bg-green-500' : errPct < 10 ? 'bg-amber-500' : 'bg-red-500'}`} />
          {errPct === 0 ? 'No errors' : `${errPct}% error rate`}
        </div>
        {lastScore != null && (
          <div className={`text-xs font-semibold px-3 py-1 rounded-full bg-gray-50 ${qualityColor}`}>
            Quality: {Math.round(lastScore * 100)}%
          </div>
        )}
        <div className="text-xs text-gray-400 px-3 py-1 rounded-full bg-gray-50">
          {data.total_spans} spans recorded
        </div>
      </div>

      {/* Agent latency — last scan */}
      {Object.keys(latency).length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">Last Scan — Agent Latency</p>
          {AGENT_ORDER.filter(a => latency[a] != null).map(agent => {
            const ms = latency[agent];
            const pct = Math.round((ms / maxMs) * 100);
            const color = ms > 10000 ? 'bg-red-400' : ms > 5000 ? 'bg-amber-400' : 'bg-blue-400';
            return (
              <div key={agent} className="flex items-center gap-2 mb-1.5">
                <span className="text-xs text-gray-500 w-20 flex-shrink-0">{AGENT_LABEL[agent] ?? agent}</span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
                </div>
                <span className="text-xs font-mono text-gray-500 w-16 text-right flex-shrink-0">
                  {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Quality trend sparkline */}
      {trend.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">
            Pipeline Quality Trend
            <span className="font-normal text-gray-400 ml-1">({trend.length} scans)</span>
          </p>
          <div className="flex items-end gap-3">
            <Sparkline points={trend} />
            <div className="text-xs text-gray-400 space-y-0.5">
              <p>Latest: <span className={`font-bold ${qualityColor}`}>{lastScore != null ? Math.round(lastScore * 100) + '%' : '—'}</span></p>
              <p>Scans: {trend.length}</p>
            </div>
          </div>
          {trend.length >= 3 && (() => {
            const recent = trend.slice(-3).map(p => p.score);
            const dropping = recent.every((v, i) => i === 0 || v < recent[i - 1]);
            return dropping && lastScore < 0.7 ? (
              <p className="text-xs text-red-500 mt-1.5 font-semibold">
                ⚠ Quality dropping across last 3 scans — review validator confidence
              </p>
            ) : null;
          })()}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage({ persona, sel, scope, liveRisks, liveContext, scanHistory = {}, hierarchy = [] }) {
  const risks = liveRisks ?? [];
  const label = getSelectionLabel(sel, scope, hierarchy);

  const [statuses] = useState(() => Object.fromEntries(risks.map(r => [r.id, r.status ?? 'Open'])));

  const critical  = risks.filter(r => r.priority === 'Critical').length;
  const high      = risks.filter(r => r.priority === 'High').length;
  const open      = risks.filter(r => (statuses[r.id] ?? r.status) === 'Open').length;
  const mitigated = risks.filter(r => (statuses[r.id] ?? r.status) === 'Mitigated').length;
  const avgRpn    = risks.length ? Math.round(risks.reduce((a, r) => a + r.rpn, 0) / risks.length) : 0;

  const portfolio = hierarchy.find(p => p.id === sel?.portfolioId);
  const aggRows = scope === 'org'
    ? aggregateBy(risks, r => r.portfolio, r => hierarchy.find(p => p.id === r.portfolio)?.name ?? r.portfolio)
    : aggregateBy(risks, r => r.project,   r => portfolio?.projects.find(pr => pr.id === r.project)?.name ?? r.project);

  // Last scan metadata for the selected project
  const lastEntry     = sel?.projectId ? scanHistory[sel.projectId] : null;
  const workspaceId   = lastEntry?.workspace_id ?? null;
  const lastScanTs  = lastEntry?.timestamp
    ? new Date(lastEntry.timestamp).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : null;
  const fromCache   = lastEntry?.from_cache ?? false;

  if (risks.length === 0) {
    return (
      <div className="p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-0.5">{SCOPE_LABEL[scope] ?? 'Project'}</p>
            <h2 className="text-xl font-bold text-gray-900">{label || 'No project selected'}</h2>
          </div>
        </div>
        <div className="mt-16 text-center">
          <p className="text-4xl mb-3">📈</p>
          <p className="text-gray-400 text-sm">Run a scan to populate the dashboard.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      {/* Header row */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-0.5">{SCOPE_LABEL[scope] ?? 'Project'}</p>
          <h2 className="text-xl font-bold text-gray-900">{label}</h2>
        </div>
        {lastScanTs && (
          <span className="text-xs text-gray-400 bg-white border border-gray-100 shadow-sm px-3 py-1.5 rounded-full flex items-center gap-2">
            {fromCache ? '⚡ Cache hit' : '🔬 Fresh analysis'} · {lastScanTs}
          </span>
        )}
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {critical > 0 ? (
          <div className="bg-red-600 text-white rounded-2xl p-5 shadow-sm">
            <p className="text-red-200 text-xs uppercase tracking-wide mb-1">Critical</p>
            <p className="text-4xl font-bold">{critical}</p>
            <p className="text-red-200 text-xs mt-1">Immediate action required</p>
          </div>
        ) : (
          <KCard label="Critical" value="0" color="text-green-600" sub="None — well done" accent="bg-green-400" />
        )}
        <KCard
          label="Avg RPN"
          value={avgRpn}
          color={avgRpn > 200 ? 'text-red-600' : 'text-orange-600'}
          sub={`${risks.length} failure modes · threshold 200`}
          accent={avgRpn > 200 ? 'bg-red-400' : 'bg-orange-400'}
        />
        <KCard label="Open Issues" value={open}
          color="text-red-600"
          sub={`${risks.length - open} being addressed`}
          accent="bg-red-300"
        />
        <KCard
          label="Mitigated"
          value={`${Math.round(mitigated / Math.max(risks.length, 1) * 100)}%`}
          color="text-green-600"
          sub={`${mitigated} of ${risks.length}`}
          accent="bg-green-400"
        />
      </div>

      {/* Body */}
      <div className="grid grid-cols-2 gap-5">
        <div>
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">
            {scope === 'org' ? 'Risk by Portfolio' : 'Risk by Project'}
          </h3>
          {aggRows.length > 0
            ? <AggTable rows={aggRows} groupLabel={scope === 'org' ? 'Portfolio' : 'Project'} />
            : (
              <div className="bg-white rounded-2xl border border-gray-100 p-5 text-xs text-gray-400">
                {risks.length} scenarios in current project
              </div>
            )
          }
        </div>

        <div className="space-y-4">
          {critical > 0 && (
            <div className="bg-red-50 border border-red-100 rounded-2xl p-5">
              <p className="font-bold text-red-800 text-sm mb-2">⚠️ Critical scenarios require immediate attention</p>
              <p className="text-sm text-red-700 leading-relaxed">
                {critical} critical failure mode{critical > 1 ? 's' : ''} identified with highest RPN{' '}
                <strong>{Math.max(...risks.filter(r => r.priority === 'Critical').map(r => r.rpn))}</strong>.
                Review mitigations and start remediation.
              </p>
            </div>
          )}

          {/* Remediation progress */}
          <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Risk by Priority</h3>
            {[
              ['Critical', risks.filter(r => r.priority === 'Critical').length, 'bg-red-500'],
              ['High',     risks.filter(r => r.priority === 'High').length,     'bg-orange-400'],
              ['Medium',   risks.filter(r => r.priority === 'Medium').length,   'bg-amber-400'],
              ['Low',      risks.filter(r => r.priority === 'Low').length,      'bg-green-400'],
            ].map(([l, count, c]) => (
              <div key={l} className="flex items-center gap-3 mb-3">
                <span className="text-xs text-gray-500 w-16">{l}</span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${c} transition-all`}
                    style={{ width: `${(count / Math.max(risks.length, 1)) * 100}%` }}
                  />
                </div>
                <span className="text-xs font-bold text-gray-600 w-4 text-right">{count}</span>
              </div>
            ))}
          </div>

          {/* Cost Tracking */}
          <CostPanel workspaceId={workspaceId} />

          {/* System Health */}
          <SystemHealthPanel workspaceId={workspaceId} />

          {/* Top risks */}
          <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Top Risks by RPN</h3>
            {[...risks].sort((a, b) => b.rpn - a.rpn).slice(0, 5).map(r => (
              <div key={r.id} className="flex items-center gap-3 mb-3 last:mb-0">
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${PRI[r.priority]?.dot ?? 'bg-gray-300'}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-gray-700 truncate">{r.name}</p>
                  {r.comp && <p className="text-xs text-gray-400 font-mono">{r.comp}</p>}
                </div>
                <span className={`text-sm font-bold flex-shrink-0 ${r.priority === 'Critical' ? 'text-red-600' : r.priority === 'High' ? 'text-orange-500' : 'text-gray-800'}`}>
                  {r.rpn}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
