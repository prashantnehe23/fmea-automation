import { PRI } from '../helpers';

export function Chip({ label, cls }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

// Root-cause domain (B-029). Ids come from the server's registry; an unknown id still renders.
export const domainLabel = d => (!d || d === 'unclassified') ? 'Not classified' : d.charAt(0).toUpperCase() + d.slice(1);
const DOMAIN_CLS = {
  security:      'bg-red-50 text-red-700',
  architectural: 'bg-purple-50 text-purple-700',
  engineering:   'bg-blue-50 text-blue-700',
  operational:   'bg-amber-50 text-amber-700',
};

export function DomainChip({ d }) {
  return <Chip label={domainLabel(d)} cls={DOMAIN_CLS[d] ?? 'bg-gray-100 text-gray-500'} />;
}

export function CweChip({ cwe }) {
  const known = cwe && cwe !== 'unmapped';
  return <Chip label={known ? cwe : 'CWE unmapped'} cls={known ? 'bg-gray-100 text-gray-700' : 'bg-gray-50 text-gray-400'} />;
}

export function PChip({ p }) {
  return <Chip label={p} cls={PRI[p]?.badge ?? 'bg-gray-100 text-gray-600'} />;
}
