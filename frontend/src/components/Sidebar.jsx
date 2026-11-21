import { useState } from 'react';
import { PERSONAS, PROCESS_STEPS, PERSONA_PRIMARY, PERSONA_SCOPE_OPTIONS, SCOPE_LABEL } from '../data';
import HierarchyTree from './HierarchyTree';

export default function Sidebar({ persona, step, sel, scope, hierarchy, scanHistory, onPersona, onStep, onSelect, onScope, onAddPortfolio, onAddProject }) {
  const [personaOpen, setPersonaOpen] = useState(false);
  const current      = PERSONAS.find(p => p.id === persona);
  const primarySteps = PERSONA_PRIMARY[persona];
  const scopeOptions = PERSONA_SCOPE_OPTIONS[persona];

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
        <button
          onClick={() => setPersonaOpen(!personaOpen)}
          className="w-full flex items-center gap-2.5 p-2.5 rounded-xl bg-white shadow-sm hover:shadow-md transition-all border border-blue-100"
        >
          <span className="text-lg">{current.icon}</span>
          <div className="flex-1 min-w-0 text-left">
            <p className="text-sm font-bold text-gray-900 leading-tight">{current.label}</p>
            <p className="text-xs text-gray-400 truncate">{current.desc}</p>
          </div>
          <span className="text-gray-300 text-xs">{personaOpen ? '▴' : '▾'}</span>
        </button>

        {personaOpen && (
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

      {/* Scope switcher — only shown when persona has >1 scope option */}
      {scopeOptions.length > 1 && (
        <div className="px-3 pb-3 flex-shrink-0">
          <p className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-1.5 px-1">View level</p>
          <div className="flex flex-col gap-0.5">
            {scopeOptions.map(l => (
              <button
                key={l}
                onClick={() => onScope(l)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors text-left ${
                  scope === l ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-600 hover:bg-blue-200'
                }`}
              >
                <span>{l === 'component' ? '📄' : l === 'project' ? '🗂️' : l === 'portfolio' ? '📁' : '🏢'}</span>
                {SCOPE_LABEL[l]}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Hierarchy tree */}
      <div className="flex-1 overflow-hidden flex flex-col border-t border-blue-200">
        <p className="px-4 pt-2.5 pb-1 text-xs font-bold text-blue-400 uppercase tracking-wider flex-shrink-0">Workspace</p>
        <div className="flex-1 overflow-y-auto scrollbar-thin">
          <HierarchyTree
            persona={persona}
            sel={sel}
            hierarchy={hierarchy}
            scanHistory={scanHistory}
            onSelect={onSelect}
            onAddPortfolio={onAddPortfolio}
            onAddProject={onAddProject}
          />
        </div>
      </div>

      {/* Process steps nav */}
      <div className="px-3 py-3 border-t border-blue-200 flex-shrink-0">
        <p className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-2 px-1">Process</p>
        {PROCESS_STEPS.map(s => {
          const isPrimary = primarySteps.includes(s.id);
          const isActive  = step === s.id;
          return (
            <button
              key={s.id}
              onClick={() => onStep(s.id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs mb-0.5 transition-colors text-left font-semibold ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm'
                  : isPrimary
                  ? 'text-gray-700 hover:bg-blue-200'
                  : 'text-gray-400 hover:bg-blue-100'
              }`}
            >
              <span className={isActive ? '' : 'opacity-70'}>{s.icon}</span>
              <span className="flex-1">{s.label}</span>
              {!isPrimary && !isActive && <span className="text-gray-300 text-xs">·</span>}
            </button>
          );
        })}
      </div>

      {/* User footer */}
      <div className="px-4 py-3 border-t border-blue-200 flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold">
            {current.label[0]}
          </div>
          <div>
            <p className="text-xs font-bold text-gray-700">{current.label}</p>
            <p className="text-xs text-blue-400">{current.desc}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
