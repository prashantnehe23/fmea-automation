import { useState } from 'react';
import { Chip, PChip } from './Chip';
import { STA } from '../helpers';

export default function RiskTable({ risks, showComp = false, onPick }) {
  const [detail, setDetail] = useState(null);
  const cols = ['Failure Mode', ...(showComp ? ['Component'] : []), 'S', 'O', 'D', 'RPN', 'Priority', 'Status'];

  return (
    <div className="flex gap-4">
      <div className="flex-1 bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {cols.map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {risks.length === 0 && (
              <tr>
                <td colSpan={cols.length} className="px-4 py-12 text-center text-gray-300 text-sm">
                  No risks in scope
                </td>
              </tr>
            )}
            {risks.map(r => (
              <tr
                key={r.id}
                onClick={() => { setDetail(detail?.id === r.id ? null : r); onPick?.(r); }}
                className={`border-b border-gray-50 cursor-pointer transition-colors ${detail?.id === r.id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
              >
                <td className="px-4 py-3 font-medium text-gray-800">{r.name}</td>
                {showComp && <td className="px-4 py-3 font-mono text-xs text-gray-400">{r.comp}</td>}
                {[r.s, r.o, r.d].map((v, i) => (
                  <td key={i} className="px-4 py-3 text-center text-sm font-medium text-gray-600">{v}</td>
                ))}
                <td className="px-4 py-3 font-bold text-gray-900">{r.rpn}</td>
                <td className="px-4 py-3"><PChip p={r.priority} /></td>
                <td className="px-4 py-3"><Chip label={r.status} cls={STA[r.status]} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
          <div className="flex justify-between items-start mb-4">
            <h3 className="font-bold text-gray-900 text-sm leading-snug pr-2">{detail.name}</h3>
            <button onClick={() => setDetail(null)} className="text-gray-300 hover:text-gray-500 text-lg">×</button>
          </div>
          <div className="space-y-3 text-sm">
            <div>
              <p className="text-xs text-gray-400 mb-0.5">Component</p>
              <p className="font-mono text-xs text-blue-700">{detail.comp}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400 mb-0.5">Owner</p>
              <p className="text-sm text-gray-700">{detail.owner}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400 mb-0.5">Business Impact</p>
              <p className="text-xs text-gray-700 leading-relaxed">{detail.impact}</p>
            </div>
          </div>
          <div className="mt-4 pt-4 border-t border-gray-100">
            <div className="grid grid-cols-3 gap-2 text-center mb-3">
              {[['S', detail.s, 'text-red-600'], ['O', detail.o, 'text-orange-500'], ['D', detail.d, 'text-blue-600']].map(([l, v, c]) => (
                <div key={l} className="bg-gray-50 rounded-xl p-2">
                  <p className="text-xs text-gray-400">{l}</p>
                  <p className={`text-xl font-bold ${c}`}>{v}</p>
                </div>
              ))}
            </div>
            <div className="bg-gray-900 rounded-xl p-3 text-center">
              <p className="text-xs text-gray-400 mb-0.5">RPN</p>
              <p className="text-3xl font-bold text-white">{detail.rpn}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
