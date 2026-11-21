import KCard from './KCard';

export default function KpiRow({ risks }) {
  const avg = risks.length
    ? Math.round(risks.reduce((a, r) => a + r.rpn, 0) / risks.length)
    : 0;
  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      <KCard label="Total Risks" value={risks.length}                                             sub="in scope"         accent="bg-gray-300" />
      <KCard label="Critical"    value={risks.filter(r => r.priority === 'Critical').length}      color="text-red-600"   sub="Immediate action" accent="bg-red-400" />
      <KCard label="High"        value={risks.filter(r => r.priority === 'High').length}          color="text-orange-500" sub="Fix next"         accent="bg-orange-400" />
      <KCard label="Avg RPN"     value={avg}                                                      sub="Risk priority number" accent="bg-blue-400" />
    </div>
  );
}
