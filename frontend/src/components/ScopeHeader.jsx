export default function ScopeHeader({ scopeLabel, name, sub }) {
  return (
    <div className="mb-6">
      <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-0.5">{scopeLabel}</p>
      <h2 className="text-xl font-bold text-gray-900">{name}</h2>
      {sub && <p className="text-sm text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}
