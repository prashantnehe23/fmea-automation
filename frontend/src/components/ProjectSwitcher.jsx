import { useState, useEffect, useRef } from 'react';
import { selectable } from '../selection';
import { NewProjectForm, NewPortfolioForm, ScanBadge } from './NewEntityForms';

// B-054 step 3 (ADR-034): one place to choose where you are. A button shows the current portfolio and project; it opens a
// searchable list grouped by portfolio. What each role may pick (a project, all projects of a portfolio, everything) follows
// the role; the server's checks are unchanged.

const EMPTY = { portfolioId: null, projectId: null, componentId: null, componentName: null };

export default function ProjectSwitcher({ persona, sel, hierarchy = [], scanHistory = {}, onSelect, onAddProject, onAddPortfolio }) {
  const can = selectable(persona);
  const [open, setOpen]         = useState(false);
  const [query, setQuery]       = useState('');
  const [addingTo, setAddingTo] = useState(null);       // portfolio id whose new-project form is showing
  const [addingPort, setAddingPort] = useState(false);
  const box = useRef(null);

  const portfolio = hierarchy.find(p => p.id === sel.portfolioId);
  const project   = portfolio?.projects.find(p => p.id === sel.projectId);
  const label = project ? `${portfolio.name} / ${project.name}` : portfolio ? portfolio.name : (can.org ? 'All portfolios' : 'Choose a project');

  const close = () => { setOpen(false); setQuery(''); setAddingTo(null); setAddingPort(false); };
  const pick = (next) => { onSelect(next); close(); };

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const onDown = (e) => { if (box.current && !box.current.contains(e.target)) close(); };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown); };
  }, [open]);

  const q = query.trim().toLowerCase();
  const rows = hierarchy.map(p => {
    const portfolioHit = p.name.toLowerCase().includes(q);
    const projects = p.projects.filter(pr => !q || portfolioHit || pr.name.toLowerCase().includes(q));
    return { portfolio: p, projects, show: !q || portfolioHit || projects.length > 0 };
  }).filter(r => r.show);

  const rowCls = (active) => `w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs text-left transition-colors ${active ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-blue-100'}`;

  return (
    <div ref={box} className="relative px-3 pb-3 flex-shrink-0">
      <p className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-1.5 px-1">Project</p>
      <button
        onClick={() => setOpen(o => !o)}
        aria-haspopup="true" aria-expanded={open}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-xl bg-white border border-blue-100 shadow-sm hover:shadow-md text-left"
      >
        <span className="text-sm">{project ? '🗂️' : '📁'}</span>
        <span className="flex-1 min-w-0 text-xs font-semibold text-gray-800 truncate">{label}</span>
        <span className="text-gray-400 text-xs">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full mt-1 z-30 bg-white rounded-xl shadow-xl border border-gray-100 p-2 max-h-96 overflow-y-auto">
          <input
            type="search" role="searchbox" aria-label="Search projects" autoFocus placeholder="Search projects"
            value={query} onChange={e => setQuery(e.target.value)}
            className="w-full text-xs px-2 py-1.5 mb-1 rounded-lg border border-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-300"
          />

          {can.org && !q && (
            <button onClick={() => pick(EMPTY)} aria-label="All portfolios" className={rowCls(!sel.portfolioId && !sel.projectId)}>
              <span>🏢</span><span className="flex-1">All portfolios</span>
            </button>
          )}

          {rows.length === 0 && q && <p className="px-2 py-2 text-xs text-gray-400">No project matches</p>}
          {rows.length === 0 && !q && <p className="px-2 py-2 text-xs text-gray-400">No projects yet. Add one below.</p>}

          {rows.map(({ portfolio: p, projects }) => (
            <div key={p.id} className="mt-1">
              <p className="px-2 pt-1 text-xs font-bold text-gray-400 uppercase tracking-wider truncate">{p.name}</p>
              {can.portfolio && !q && (
                <button onClick={() => pick({ ...EMPTY, portfolioId: p.id })} aria-label={`All projects in ${p.name}`} className={rowCls(sel.portfolioId === p.id && !sel.projectId)}>
                  <span>📁</span><span className="flex-1 truncate">All projects in {p.name}</span>
                </button>
              )}
              {can.project && projects.map(pr => (
                <button key={pr.id} onClick={() => pick({ ...EMPTY, portfolioId: p.id, projectId: pr.id })} aria-label={pr.name} className={rowCls(sel.projectId === pr.id)}>
                  <span>🗂️</span><span className="flex-1 truncate">{pr.name}</span>
                  <ScanBadge history={scanHistory[pr.id]} />
                </button>
              ))}
              {!q && (addingTo === p.id ? (
                <NewProjectForm
                  onSave={(name, repoUrl, tier, userType) => { onAddProject?.(p.id, name, repoUrl, tier, userType); close(); }}
                  onCancel={() => setAddingTo(null)}
                />
              ) : (
                <button onClick={() => setAddingTo(p.id)} className="px-2 py-1 text-xs text-blue-500 hover:text-blue-700 flex items-center gap-1">
                  <span>＋</span> New project in {p.name}
                </button>
              ))}
            </div>
          ))}

          {!q && (addingPort ? (
            <NewPortfolioForm onSave={(name) => { onAddPortfolio?.(name); close(); }} onCancel={() => setAddingPort(false)} />
          ) : (
            <button onClick={() => setAddingPort(true)} className="mt-1 px-2 py-1 text-xs text-blue-500 hover:text-blue-700 flex items-center gap-1">
              <span>＋</span> New portfolio
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
