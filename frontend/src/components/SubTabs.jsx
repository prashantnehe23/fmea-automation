import { NAV_GROUPS, STEP_TAB_LABEL } from '../data';

// B-054 step 1: the pages inside one left-pane entry (Findings, Scenarios, Scoring; Fix actions, Auto-remediation) as tabs.
// A group with a single page shows nothing.
export default function SubTabs({ step, onStep }) {
  const group = NAV_GROUPS.find(g => g.steps.includes(step));
  if (!group || group.steps.length < 2) return null;
  return (
    <div role="tablist" aria-label={group.label} className="flex gap-1 px-8 pt-4 border-b border-gray-100 bg-gray-50">
      {group.steps.map(s => (
        <button key={s} role="tab" aria-selected={s === step} onClick={() => onStep(s)}
                className={`px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 -mb-px ${s === step ? 'text-blue-700 border-blue-600' : 'text-gray-500 border-transparent hover:text-gray-800'}`}>
          {STEP_TAB_LABEL[s]}
        </button>
      ))}
    </div>
  );
}
