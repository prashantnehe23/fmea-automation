import { PChip } from './Chip';

export default function AggTable({ rows, groupLabel }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-100">
          <tr>
            {[groupLabel, 'Risks', 'Critical', 'High', 'Highest RPN', 'Remediated'].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const pct = Math.round((row.mitigated / Math.max(row.total, 1)) * 100);
            const top = row.critical > 0 ? 'Critical' : row.high > 0 ? 'High' : 'Medium';
            return (
              <tr key={row.label} className="border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer">
                <td className="px-4 py-3 font-semibold text-gray-800">{row.label}</td>
                <td className="px-4 py-3 text-center text-gray-600">{row.total}</td>
                <td className="px-4 py-3 text-center font-bold text-red-600">{row.critical || '—'}</td>
                <td className="px-4 py-3 text-center font-bold text-orange-500">{row.high || '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900">{row.maxRpn}</span>
                    <PChip p={top} />
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-green-400 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-gray-400">{pct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
