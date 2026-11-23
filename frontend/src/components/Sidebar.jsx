import { useState } from 'react';
import { PERSONAS, NAV_GROUPS, PERSONA_PRIMARY } from '../data';
import ProjectSwitcher from './ProjectSwitcher';

const ROLE_LABEL = { admin: 'Administrator', security_engineer: 'Security engineer', risk_manager: 'Risk manager', developer: 'Developer', viewer: 'Viewer' };

export default function Sidebar({ persona, step, sel, hierarchy, scanHistory, onPersona, onStep, onSelect, onAddPortfolio, onAddProject, onOpenSettings, user, canSwitchPersona, onLogout, counts }) {
  const [personaOpen, setPersonaOpen] = useState(false);
  const current      = PERSONAS.find(p => p.id === persona);
  const primarySteps = PERSONA_PRIMARY[persona];

  return (
    <div className="w-56 flex-shrink-0 h-screen flex flex-col" style={{ backgroundColor: '#DBEAFE' }}>

      {/* Brand */}
      <div className="px-4 pt-5 pb-4 flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-blue-600 rounded-xl flex items-center justify-center text-white text-sm font-black shadow-sm">FM</div>
          <div>
            <p className="font-black text-gray-900 text-sm leading-tight">FMEA Platform</p>
            <p className="text-xs text-blue-500">Risk Intelligence</p>
          </div>
        </div>
      </div>

      {/* Persona picker */}
      <div className="px-3 pb-3 flex-shrink-0">
        {!canSwitchPersona && (
          <div className="flex items-center gap-2.5 p-2.5 rounded-xl bg-white border border-blue-100">
            <span className="text-lg">{current.icon}</span>
            <div className="flex-1 min-w-0 text-left">
              <p className="text-sm font-bold text-gray-900 leading-tight truncate">{user?.display_name}</p>
              <p className="text-xs text-gray-400 truncate">{ROLE_LABEL[user?.role] ?? user?.role}</p>
            </div>
          </div>
        )}
        {canSwitchPersona && <button
          onClick={() => setPersonaOpen(!personaOpen)}
          className="w-full flex items-center gap-2.5 p-2.5 rounded-xl bg-white shadow-sm hover:shadow-md transition-all border border-blue-100"
        >
          <span className="text-lg">{current.icon}</span>
          <div className="flex-1 min-w-0 text-left">
            <p className="text-sm font-bold text-gray-900 leading-tight">{current.label}</p>
            <p className="text-xs text-gray-400 truncate">{current.desc}</p>
          </div>
          <span className="text-gray-300 text-xs">{personaOpen ? '▴' : '▾'}</span>
        </button>}

        {canSwitchPersona && personaOpen && (
          <div className="mt-1.5 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-20 relative">
            {PERSONAS.map(p => (
              <button
                key={p.id}
                onClick={() => { onPersona(p.id); setPersonaOpen(false); }}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors ${p.id === persona ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
              >
                <span className="text-base">{p.icon}</span>
                <div>
                  <p className="text-sm font-semibold text-gray-800">{p.label}</p>
                  <p className="text-xs text-gray-400">{p.desc}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Where you are: one switcher replaces the View level buttons and the tree (ADR-034) */}
      <ProjectSwitcher
        persona={persona}
        sel={sel}
        hierarchy={hierarchy}
        scanHistory={scanHistory}
        onSelect={onSelect}
        onAddPortfolio={onAddPortfolio}
        onAddProject={onAddProject}
      />

      {/* Navigation: four plain entries (B-054 step 1) */}
      <nav aria-label="Main" className="px-3 py-3 border-t border-blue-200 flex-shrink-0">
        {NAV_GROUPS.map(g => {
          const isMain   = g.steps.some(id => primarySteps.includes(id));
          const isActive = g.steps.includes(step);
          const count    = counts?.[g.id === 'fixes' ? 'fixes' : g.id === 'findings' ? 'findings' : null];
          const noun       = count === 1 ? 'finding' : 'findings';
          const countWords = g.id === 'fixes' ? `${count} ${noun} with an urgent fix` : `${count} ${noun}`;
          return (
            <button
              key={g.id}
              onClick={() => onStep(g.steps[0])}
              aria-current={isActive ? 'page' : undefined}
              aria-label={count > 0 ? `${g.label}, ${countWords}` : undefined}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs mb-0.5 transition-colors text-left font-semibold ${
                isActive ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-700 hover:bg-blue-200'
              }`}
            >
              <span>{g.icon}</span>
              <span className="flex-1">{g.label}</span>
              {count > 0 && <span className={`text-xs font-bold px-1.5 rounded-full ${isActive ? 'bg-white text-blue-700' : 'bg-blue-200 text-blue-800'}`}>{count}</span>}
              {isMain && <span data-main-step title="A main area for your role" className="w-1.5 h-1.5 rounded-full bg-blue-500" />}
            </button>
          );
        })}
        <button onClick={onOpenSettings}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs mt-2 text-gray-700 hover:bg-blue-200 text-left font-semibold">
          <span>⚙️</span><span className="flex-1">Settings</span>
        </button>
      </nav>

      {/* User footer */}
      <div className="px-4 py-3 border-t border-blue-200 flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold">
            {current.label[0]}
          </div>
          <div>
            <p className="text-xs font-bold text-gray-700">{user?.display_name ?? current.label}</p>
            <button onClick={onLogout} className="text-xs text-blue-500 hover:text-blue-700 underline">Sign out</button>
          </div>
        </div>
      </div>
    </div>
  );
}
