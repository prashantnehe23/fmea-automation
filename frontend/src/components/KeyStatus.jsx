import { useState, useEffect } from 'react';
import { getModels, getProviders } from '../api';

// B-048 phase 0 (U14): shows whether the active model's provider key is usable, next to the scan controls.
// Renders nothing while the key is valid, unchecked or the API is unreachable.
export default function KeyStatus({ refreshKey, onOpenSettings }) {
  const [info, setInfo] = useState(null);   // { display, status }

  useEffect(() => {
    let live = true;
    Promise.all([getModels(), getProviders()])
      .then(([models, providers]) => {
        const active = models.find(m => m.is_active);
        const prov = providers.find(p => p.id === active?.provider);
        if (live && prov) setInfo({ display: prov.display, status: prov.status });
      })
      .catch(() => { if (live) setInfo(null); });
    return () => { live = false; };
  }, [refreshKey]);

  if (!info) return null;
  const text = {
    missing:    `No ${info.display} API key is set.`,
    invalid:    `Your ${info.display} API key was rejected. It may have expired.`,
    unverified: `Your ${info.display} API key could not be checked.`,
  }[info.status];
  if (!text) return null;
  const bad = info.status !== 'unverified';

  return (
    <div role="status" className={`mt-4 flex items-center gap-3 text-xs rounded-xl px-3 py-2 border ${bad ? 'bg-red-50 border-red-200 text-red-700' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
      <span className="flex-1">{text}</span>
      <button onClick={onOpenSettings} className="font-semibold underline flex-shrink-0">Open Settings</button>
    </div>
  );
}
