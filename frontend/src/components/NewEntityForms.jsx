import { useState, useRef, useEffect } from 'react';

// The inline forms and the scan badge the project switcher uses (moved from the removed hierarchy tree, B-054 step 3).

// ── Inline "new project" form ─────────────────────────────────────────────────

export function NewProjectForm({ onSave, onCancel }) {
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
  useEffect(() => { formRef.current?.scrollIntoView?.({ block: 'nearest' }); }, []);

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

export function NewPortfolioForm({ onSave, onCancel }) {
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

export function ScanBadge({ history }) {
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
