/**
 * ScenariosPage.jsx
 *
 * Displays identified failure scenarios with:
 *  - Business context summary card (attack surfaces, failure domains, README context)
 *  - Scenario table (sortable by RPN)
 *  - Expandable detail panel per scenario:
 *      • Component & impact
 *      • Attack chain (numbered steps, exploitation point highlighted)
 *      • Evidence code snippet
 *      • Validator assessment (confidence, verdict, challenges)
 *      • Scenario linkage summary
 */

import { useState } from 'react';
import ScopeHeader from '../components/ScopeHeader';

// Strip HTML tags to plain text (for short strings like list items)
function stripHtml(str) {
  if (!str) return str;
  return str.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').trim();
}
import KpiRow from '../components/KpiRow';
import AggTable from '../components/AggTable';
import { PChip } from '../components/Chip';
import { SCOPE_LABEL } from '../data';
import { getSelectionLabel, aggregateBy, PRI } from '../helpers';

// ── Business context summary ──────────────────────────────────────────────────

function ContextCard({ ctx }) {
  const [open, setOpen] = useState(false);
  if (!ctx) return null;
  const hasSurfaces = ctx.attack_surfaces?.length > 0;
  const hasDomains  = ctx.failure_domains?.length  > 0;
  const hasCtx      = ctx.business_context?.trim().length > 0;
  if (!hasSurfaces && !hasDomains && !hasCtx) return null;

  return (
    <div className="mb-6 bg-blue-50 border border-blue-200 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-base">🏗️</span>
          <span className="font-bold text-blue-900 text-sm">
            Business &amp; System Context
            {ctx.customer && <span className="font-normal text-blue-500 ml-2">— {ctx.customer}{ctx.project ? ` / ${ctx.project}` : ''}</span>}
          </span>
          {ctx.business_tier && (
            <span className="text-xs px-2 py-0.5 bg-blue-200 text-blue-700 rounded-full font-semibold">{ctx.business_tier}</span>
          )}
        </div>
        <span className="text-blue-400 text-xs">{open ? '▴ Hide' : '▾ Show'}</span>
      </button>

      {open && (
        <div className="px-5 pb-5 grid grid-cols-1 gap-4 border-t border-blue-200 pt-4">
          {hasCtx && (
            <div>
              <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-1">README / Business Context</p>
              {/* Plain text only: the README comes from the scanned repository and is untrusted (ADR-017) */}
              <p className="text-xs text-blue-900 leading-relaxed whitespace-pre-wrap break-words">
                {stripHtml(ctx.business_context)}
              </p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            {hasSurfaces && (
              <div>
                <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-2">Attack Surfaces</p>
                <ul className="space-y-1">
                  {ctx.attack_surfaces.map((s, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-blue-800">
                      <span className="text-orange-500 mt-0.5 flex-shrink-0">⚠</span>{stripHtml(s)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {hasDomains && (
              <div>
                <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-2">Failure Domains</p>
                <ul className="space-y-1">
                  {ctx.failure_domains.map((d, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-blue-800">
                      <span className="text-red-400 mt-0.5 flex-shrink-0">●</span>{stripHtml(d)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Validator badge (inline in table row) ─────────────────────────────────────

function ValidatorBadge({ r }) {
  if (r.confidence == null) return null;
  const pct   = Math.round(r.confidence * 100);
  const color = pct >= 80 ? 'text-green-700 bg-green-50 border-green-200'
              : pct >= 60 ? 'text-amber-700 bg-amber-50 border-amber-200'
              : 'text-red-700 bg-red-50 border-red-200';
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${color}`}>
      {pct}% conf
    </span>
  );
}

// ── Attack chain display ──────────────────────────────────────────────────────

function AttackChain({ chain }) {
  if (!chain?.length) return null;
  return (
    <div>
      <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Attack Chain</p>
      <ol className="space-y-1.5">
        {chain.map((step, i) => {
          const isLast = i === chain.length - 1;
          return (
            <li key={i} className="flex items-start gap-2.5">
              <span className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold mt-0.5 ${
                isLast ? 'bg-red-500 text-white' : 'bg-blue-100 text-blue-700'
              }`}>
                {i + 1}
              </span>
              <span className={`text-xs leading-relaxed ${isLast ? 'text-red-700 font-semibold' : 'text-gray-700'}`}>
                {step}
                {isLast && <span className="ml-1 text-red-500">← exploitation point</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ── Evidence code snippet ─────────────────────────────────────────────────────

function EvidenceBlock({ evidence }) {
  if (!evidence?.trim()) return null;
  return (
    <div>
      <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
        📍 Code Evidence
      </p>
      <pre className="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono border border-gray-700">
        {evidence}
      </pre>
    </div>
  );
}

// ── Validator detail section ──────────────────────────────────────────────────

function ValidatorSection({ r }) {
  if (r.confidence == null && !r.verdict) return null;
  const pct = r.confidence != null ? Math.round(r.confidence * 100) : null;

  const Check = ({ ok, label }) => (
    <div className="flex items-center gap-1.5 text-xs">
      <span className={ok ? 'text-green-600' : 'text-red-500'}>{ok ? '✓' : '✗'}</span>
      <span className="text-gray-600">{label}</span>
    </div>
  );

  return (
    <div className="bg-purple-50 border border-purple-100 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-bold text-purple-700 uppercase tracking-wide">🔍 Validator Assessment</p>
        {pct != null && (
          <span className={`text-sm font-bold px-3 py-0.5 rounded-full ${
            pct >= 80 ? 'bg-green-100 text-green-700' : pct >= 60 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'
          }`}>
            {pct}% confidence
          </span>
        )}
      </div>
      <div className="flex gap-4 mb-3 flex-wrap">
        <Check ok={r.is_realistic}          label="Realistic scenario" />
        <Check ok={r.attack_chain_complete} label="Attack chain complete" />
        <Check ok={r.rpn_calibrated}        label="RPN calibrated" />
      </div>
      {r.verdict && (
        <p className="text-xs text-purple-800 italic leading-relaxed mb-3">"{r.verdict}"</p>
      )}
      {r.challenges?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-purple-600 mb-1.5">Validator challenges:</p>
          <ul className="space-y-1">
            {r.challenges.map((ch, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-purple-700">
                <span className="text-purple-400 mt-0.5 flex-shrink-0">·</span>{ch}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Scenario detail panel (shown below table on row click) ────────────────────

function ScenarioDetail({ r, onClose }) {
  return (
    <div className="mt-3 bg-white rounded-2xl border border-blue-200 shadow-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-6 py-4 bg-gray-50 border-b border-gray-100">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <PChip p={r.priority} />
            <span className="text-xs font-mono text-gray-400">{r.comp}</span>
            <ValidatorBadge r={r} />
          </div>
          <h3 className="font-bold text-gray-900 text-base leading-snug">{r.name}</h3>
        </div>
        <button onClick={onClose} className="text-gray-300 hover:text-gray-600 text-xl leading-none ml-4">×</button>
      </div>

      <div className="p-6 space-y-6">
        {/* Business impact + blast radius + trigger — three columns */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs font-bold text-red-500 uppercase tracking-wide mb-1">Business Impact</p>
            <p className="text-xs text-gray-700 leading-relaxed">{r.impact || '—'}</p>
          </div>
          <div>
            <p className="text-xs font-bold text-orange-500 uppercase tracking-wide mb-1">Blast Radius</p>
            <p className="text-xs text-gray-700 leading-relaxed">{r.blast_radius || '—'}</p>
          </div>
          <div>
            <p className="text-xs font-bold text-amber-500 uppercase tracking-wide mb-1">Trigger</p>
            <p className="text-xs text-gray-700 leading-relaxed">{r.trigger || '—'}</p>
          </div>
        </div>

        {/* Scenario linkage summary */}
        {r.scenario_summary && (
          <div>
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">Scenario Summary</p>
            <p className="text-sm text-gray-700 leading-relaxed">{r.scenario_summary}</p>
          </div>
        )}
        {r.code_connection && (
          <div>
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">Code Connection</p>
            <p className="text-xs text-gray-600 leading-relaxed italic">{r.code_connection}</p>
          </div>
        )}

        {/* Attack chain */}
        <AttackChain chain={r.attack_chain} />

        {/* Evidence code snippet */}
        <EvidenceBlock evidence={r.evidence} />

        {/* Validator */}
        <ValidatorSection r={r} />
      </div>
    </div>
  );
}

// ── Scenario table ────────────────────────────────────────────────────────────

function ScenarioTable({ risks }) {
  const [detail, setDetail] = useState(null);
  const sorted = [...risks].sort((a, b) => b.rpn - a.rpn);

  return (
    <div>
      <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['#', 'Failure Scenario', 'Component', 'S', 'O', 'D', 'RPN', 'Priority', 'Confidence / New'].map(h => (
                <th key={h} className="px-3 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-10 text-center text-gray-300 text-sm">No scenarios in scope</td></tr>
            )}
            {sorted.map((r, i) => {
              const active = detail?.id === r.id;
              return (
                <tr
                  key={r.id}
                  onClick={() => setDetail(active ? null : r)}
                  className={`border-b border-gray-50 cursor-pointer transition-colors ${active ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-3 py-3 text-xs text-gray-400">{i + 1}</td>
                  <td className="px-3 py-3">
                    <p className="font-semibold text-gray-800 text-sm">{r.name}</p>
                    {r.blast_radius && (
                      <p className="text-xs text-gray-400 mt-0.5 leading-snug line-clamp-1">{r.blast_radius}</p>
                    )}
                  </td>
                  <td className="px-3 py-3 font-mono text-xs text-blue-700">{r.comp}</td>
                  {[r.s, r.o, r.d].map((v, j) => (
                    <td key={j} className="px-3 py-3 text-center text-sm font-semibold text-gray-600">{v}</td>
                  ))}
                  <td className="px-3 py-3 font-bold text-gray-900">{r.rpn}</td>
                  <td className="px-3 py-3"><PChip p={r.priority} /></td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-1.5">
                      <ValidatorBadge r={r} />
                      {r.is_new && (
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-700">🆕</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Detail panel */}
      {detail && <ScenarioDetail r={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function EmptyState({ message }) {
  return (
    <div className="mt-8 py-16 text-center">
      <p className="text-4xl mb-3">🔍</p>
      <p className="text-gray-400 text-sm">{message}</p>
    </div>
  );
}

export default function ScenariosPage({ persona, sel, scope, liveRisks, liveContext, hierarchy = [] }) {
  const risks = liveRisks ?? [];
  const label = getSelectionLabel(sel, scope, hierarchy);

  if (scope === 'org' || scope === 'portfolio') {
    const portfolio = hierarchy.find(p => p.id === sel.portfolioId);
    const rows = scope === 'org'
      ? aggregateBy(risks, r => r.portfolio, r => hierarchy.find(p => p.id === r.portfolio)?.name ?? r.portfolio)
      : aggregateBy(risks, r => r.project,   r => portfolio?.projects.find(p => p.id === r.project)?.name ?? r.project);
    return (
      <div className="p-8">
        <ScopeHeader scopeLabel={scope === 'org' ? 'Organisation' : 'Portfolio'} name={label} sub={`${risks.length} scenarios`} />
        <KpiRow risks={risks} />
        {risks.length === 0
          ? <EmptyState message="No scan data yet — select a project and run a scan first." />
          : <AggTable rows={rows} groupLabel={scope === 'org' ? 'Portfolio' : 'Project'} />
        }
      </div>
    );
  }

  return (
    <div className="p-8">
      <ScopeHeader
        scopeLabel={SCOPE_LABEL[scope]}
        name={label || 'No project selected'}
        sub={risks.length > 0
          ? `${risks.length} failure scenario${risks.length !== 1 ? 's' : ''} identified`
          : 'No scan data for this project yet'}
      />
      <KpiRow risks={risks} />
      {risks.length === 0
        ? <EmptyState message="Run a scan on this project to see failure scenarios." />
        : <>
            <ContextCard ctx={liveContext} />
            <ScenarioTable risks={risks} />
          </>
      }
    </div>
  );
}
