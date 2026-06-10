import { PRI } from '../helpers';

export function Chip({ label, cls }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

export function PChip({ p }) {
  return <Chip label={p} cls={PRI[p]?.badge ?? 'bg-gray-100 text-gray-600'} />;
}
