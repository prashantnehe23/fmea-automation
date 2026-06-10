import { useState } from 'react';
import { PERSONAS, PROCESS_STEPS, HIERARCHY, SCOPE_LABEL } from '../data';
import { ORG } from '../data';

export default function Header({ persona, step, sel, scope }) {
  const [showSettings, setShowSettings] = useState(false);
  const current  = PERSONAS.find(p => p.id === persona);
  const stepInfo = PROCESS_STEPS.find(s => s.id === step);
  const portfolio = HIERARCHY.find(p => p.id === sel.portfolioId);
  const project   = portfolio?.projects.find(p => p.id === sel.projectId);

  const crumbs = [{ label: ORG.name }];
  if (['portfolio', 'project', 'component'].includes(scope) && portfolio)
    crumbs.push({ label: portfolio.name });
  if (['project', 'component'].includes(scope) && project)
    crumbs.push({ label: project.name });
  if (scope === 'component' && sel.componentName)
    crumbs.push({ label: sel.componentName, mono: true });

  return (
    <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center gap-4 flex-shrink-0 shadow-sm">
      <div className="flex-1 min-w-0">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs mb-0.5">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-200 mx-0.5">/</span>}
              <span className={`${c.mono ? 'font-mono' : 'font-medium'} ${i < crumbs.length - 1 ? 'text-gray-300' : 'text-gray-600'}`}>
                {c.label}
              </span>
            </span>
          ))}
        </div>
        {/* Step title */}
        <div className="flex items-center gap-2">
          <span>{stepInfo?.icon}</span>
          <p className="text-sm font-bold text-gray-900">{stepInfo?.label}</p>
          <span className="text-xs text-gray-300">·</span>
          <p className="text-xs text-gray-400">Step {stepInfo?.step} of {PROCESS_STEPS.length}</p>
        </div>
      </div>

      {/* Right — persona label + actions */}
      <div className="flex items-center gap-1.5 flex-shrink-0 relative">
        <span className="text-xs text-gray-400 font-medium mr-1">{current.icon} {current.label}</span>
        <button
          title="Notifications — coming soon"
          className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-400 text-sm flex items-center justify-center"
        >🔔</button>
        <button
          title="Settings"
          onClick={() => setShowSettings(v => !v)}
          className={`w-8 h-8 rounded-lg text-sm flex items-center justify-center transition-colors ${showSettings ? 'bg-gray-100 text-gray-700' : 'hover:bg-gray-100 text-gray-400'}`}
        >⚙️</button>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full bg-green-50 border border-green-200 ml-1">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse inline-block" />
          <span className="text-xs text-green-700 font-semibold">Live</span>
        </div>

        {/* Settings panel */}
        {showSettings && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setShowSettings(false)} />
            <div className="absolute right-0 top-10 z-50 w-72 bg-white border border-gray-100 rounded-2xl shadow-xl p-5">
              <p className="text-sm font-bold text-gray-800 mb-4">Settings</p>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">API Endpoint</p>
                    <p className="text-xs text-gray-400">Backend URL for scan requests</p>
                  </div>
                  <span className="text-xs text-green-600 font-semibold bg-green-50 px-2 py-1 rounded-lg">Connected</span>
                </div>
                <hr className="border-gray-50" />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Risk Registry</p>
                    <p className="text-xs text-gray-400">Scenario lock &amp; history</p>
                  </div>
                  <span className="text-xs text-green-600 font-semibold bg-green-50 px-2 py-1 rounded-lg">Active</span>
                </div>
                <hr className="border-gray-50" />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Clear Local Data</p>
                    <p className="text-xs text-gray-400">Wipe scan history &amp; hierarchy</p>
                  </div>
                  <button
                    onClick={() => {
                      if (confirm('Clear all local scan data and hierarchy? This cannot be undone.')) {
                        localStorage.clear();
                        window.location.reload();
                      }
                    }}
                    className="text-xs text-red-500 font-semibold hover:text-red-700 bg-red-50 px-2 py-1 rounded-lg"
                  >Clear</button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
