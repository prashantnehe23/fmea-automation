import { useState, useRef, useEffect } from 'react';
import { PERSONA_SCOPE_OPTIONS } from '../data';

// ── Inline "new project" form ─────────────────────────────────────────────────

function NewProjectForm({ onSave, onCancel }) {
  const [name,         setName]         = useState('');
  const [repoUrl,      setRepoUrl]      = useState('');
  const [businessTier, setBusinessTier] = useState('Tier 1');
  const [userType,     setUserType]     = useState('external_customers');

  const submit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    onSave(name.trim(), repoUrl.trim(), businessTier, userType);
  };

  const formRef = useRef(null);
  useEffect(() => { formRef.current?.scrollIntoView({ block: 'nearest' }); }, []);

  const selectCls = "w-full text-xs px-2 py-1 rounded border border-gray-200 mb-1 focus:outline-none focus:ring-1 focus:ring-blue-300 bg-white";

  return (
    <form ref={formRef} onSubmit={submit} className="ml-5 mr-2 mt-1 mb-2 p-2 bg-white rounded-lg border border-blue-200 shadow-sm">
      <input
        autoFocus
        className="w-full text-xs px-2 py-1 rounded border border-gray-200 mb-1 focus:outline-none focus:ring-1 focus:ring-blue-300"
        placeholder="Project name"
        value={name}
        onChange={e => setName(e.target.value)}
      />
      <input
        className="w-full text-xs px-2 py-1 rounded border border-gray-200 mb-1 focus:outline-none focus:ring-1 focus:ring-blue-300 font-mono"
        placeholder="https://github.com/owner/repo (optional)"
        value={repoUrl}
        onChange={e => setRepoUrl(e.target.value)}
      />
      <select className={selectCls} value={businessTier} onChange={e => setBusinessTier(e.target.value)}>
        <option value="Tier 1">Tier 1 — Mission-critical</option>
        <option value="Tier 2">Tier 2 — Important</option>
        <option value="Tier 3">Tier 3 — Supporting</option>
      </select>
      <select className={`${selectCls} mb-2`} value={userType} onChange={e => setUserType(e.target.value)}>
        <option value="external_customers">External customers</option>
        <option value="internal_staff">Internal staff</option>
        <option value="b2b_partner">B2B partners</option>
      </select>
      <div className="flex gap-1">
        <button
          type="submit"
          className="flex-1 text-xs py-1 bg-blue-600 text-white rounded hover:bg-blue-700 font-semibold"
        >
          Add
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 text-xs py-1 bg-gray-100 text-gray-600 rounded hover:bg-gray-200"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Inline "new portfolio" form ───────────────────────────────────────────────

function NewPortfolioForm({ onSave, onCancel }) {
  const [name, setName] = useState('');

  const submit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    onSave(name.trim());
  };

  return (
    <form onSubmit={submit} className="mx-2 mt-1 mb-2 p-2 bg-white rounded-lg border border-blue-200 shadow-sm">
      <input
        autoFocus
        className="w-full text-xs px-2 py-1 rounded border border-gray-200 mb-2 focus:outline-none focus:ring-1 focus:ring-blue-300"
        placeholder="Portfolio name"
        value={name}
        onChange={e => setName(e.target.value)}
      />
      <div className="flex gap-1">
        <button
          type="submit"
          className="flex-1 text-xs py-1 bg-blue-600 text-white rounded hover:bg-blue-700 font-semibold"
        >
          Add
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 text-xs py-1 bg-gray-100 text-gray-600 rounded hover:bg-gray-200"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Scan badge for a project ──────────────────────────────────────────────────

function ScanBadge({ history }) {
  if (!history) return <span className="text-gray-300 text-xs">○</span>;
  const hasCritical = history.result?.risks?.some(r => r.priority === 'Critical');
  const hasHigh     = history.result?.risks?.some(r => r.priority === 'High');
  return (
    <span
      title={`${history.risk_count} risks · RPN ${history.max_rpn}`}
      className={`text-xs font-bold px-1 rounded ${
        hasCritical ? 'text-red-500' : hasHigh ? 'text-orange-500' : 'text-green-500'
      }`}
    >
      {hasCritical ? '🔴' : hasHigh ? '🟠' : '🟢'}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function HierarchyTree({
  persona,
  sel,
  hierarchy = [],
  scanHistory = {},
  onSelect,
  onAddPortfolio,
  onAddProject,
}) {
  const scopeOptions = PERSONA_SCOPE_OPTIONS[persona];
  const [openP,       setOpenP]       = useState(() => hierarchy.map(p => p.id));
  const [openPr,      setOpenPr]      = useState(() => hierarchy.flatMap(p => p.projects.map(pr => pr.id)));
  const [addingPrTo,  setAddingPrTo]  = useState(null);   // portfolioId currently adding project to
  const [addingPort,  setAddingPort]  = useState(false);   // showing new-portfolio form

  const tP  = id => setOpenP( s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  const tPr = id => setOpenPr(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  const can = level => scopeOptions.includes(level);

  const handleAddProject = (portfolioId, name, repoUrl, businessTier, userType) => {
    onAddProject?.(portfolioId, name, repoUrl, businessTier, userType);
    setAddingPrTo(null);
  };

  const handleAddPortfolio = (name) => {
    onAddPortfolio?.(name);
    setAddingPort(false);
  };

  return (
    <div className="py-2 overflow-y-auto scrollbar-thin" style={{ maxHeight: 'calc(100vh - 360px)' }}>
      {hierarchy.map(portfolio => {
        const pOpen   = openP.includes(portfolio.id);
        const pActive = sel.portfolioId === portfolio.id && !sel.projectId;
        return (
          <div key={portfolio.id} className="mb-0.5">
            {/* Portfolio row */}
            <div
              onClick={() => {
                if (can('portfolio')) onSelect({ portfolioId: portfolio.id, projectId: null, componentId: null, componentName: null });
                tP(portfolio.id);
              }}
              className={`flex items-center gap-1.5 mx-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors ${pActive && can('portfolio') ? 'bg-blue-600' : 'hover:bg-blue-200'}`}
            >
              <span className={`text-xs w-3 flex-shrink-0 ${pActive && can('portfolio') ? 'text-blue-200' : 'text-gray-400'}`}>{pOpen ? '▾' : '▸'}</span>
              <span className="text-xs">📁</span>
              <span className={`text-xs font-semibold truncate flex-1 ${pActive && can('portfolio') ? 'text-white' : 'text-gray-700'}`}>{portfolio.name}</span>
            </div>

            {pOpen && (
              <>
                {portfolio.projects.map(project => {
                  const prOpen   = openPr.includes(project.id);
                  const prActive = sel.projectId === project.id;
                  const history  = scanHistory[project.id];
                  return (
                    <div key={project.id} className="ml-3">
                      <div
                        onClick={() => {
                          onSelect({ portfolioId: portfolio.id, projectId: project.id, componentId: null, componentName: null });
                          tPr(project.id);
                        }}
                        className={`flex items-center gap-1.5 mx-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors ${prActive ? 'bg-blue-600' : 'hover:bg-blue-200'}`}
                      >
                        <span className={`text-xs w-3 flex-shrink-0 ${prActive ? 'text-blue-200' : 'text-gray-400'}`}>{prOpen ? '▾' : '▸'}</span>
                        <span className="text-xs">🗂️</span>
                        <span className={`text-xs font-medium truncate flex-1 ${prActive ? 'text-white' : 'text-gray-600'}`}>{project.name}</span>
                        {project.repoUrl && (
                          <span className={`text-xs flex-shrink-0 ${prActive ? 'text-blue-200' : 'text-blue-400'}`} title={project.repoUrl}>🔗</span>
                        )}
                        <ScanBadge history={history} />
                      </div>
                    </div>
                  );
                })}

                {/* + New Project button / form */}
                {addingPrTo === portfolio.id ? (
                  <NewProjectForm
                    onSave={(name, repoUrl, businessTier, userType) => handleAddProject(portfolio.id, name, repoUrl, businessTier, userType)}
                    onCancel={() => setAddingPrTo(null)}
                  />
                ) : (
                  <button
                    onClick={() => setAddingPrTo(portfolio.id)}
                    className="ml-5 mr-2 px-2 py-1 text-xs text-blue-400 hover:text-blue-600 flex items-center gap-1 w-full"
                  >
                    <span>＋</span> New Project
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}

      {/* + New Portfolio button / form */}
      {addingPort ? (
        <NewPortfolioForm
          onSave={handleAddPortfolio}
          onCancel={() => setAddingPort(false)}
        />
      ) : (
        <button
          onClick={() => setAddingPort(true)}
          className="mx-2 px-2 py-1 text-xs text-blue-400 hover:text-blue-600 flex items-center gap-1 w-full mt-1"
        >
          <span>＋</span> New Portfolio
        </button>
      )}
    </div>
  );
}
