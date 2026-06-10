export default function KCard({ label, value, sub, color = 'text-gray-900', accent }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm relative overflow-hidden">
      {accent && <div className={`absolute top-0 left-0 w-1 h-full ${accent} rounded-l-2xl`} />}
      <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-2">{label}</p>
      <p className={`text-3xl font-bold ${color} leading-none`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-2">{sub}</p>}
    </div>
  );
}
