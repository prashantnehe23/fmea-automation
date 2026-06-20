import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import Header  from './components/Header';
import ScanPage        from './pages/ScanPage';
import ScenariosPage   from './pages/ScenariosPage';
import ScoringPage     from './pages/ScoringPage';
import MitigationsPage from './pages/MitigationsPage';
import RemediationPage from './pages/RemediationPage';
import DashboardPage   from './pages/DashboardPage';
import {
  PROCESS_STEPS,
  PERSONA_PRIMARY,
  PERSONA_DEFAULT_SCOPE,
} from './data';
import { normalizeScanResult, getContextSummary } from './api';

const PAGES = {
  scan:        ScanPage,
  scenarios:   ScenariosPage,
  scoring:     ScoringPage,
  mitigations: MitigationsPage,
  remediation: RemediationPage,
  dashboard:   DashboardPage,
};

// ── Storage keys (v2 = fresh start; old v1 mock data is ignored) ──────────────

const KEY_HIERARCHY = 'fmea_hierarchy_v2';
const KEY_HISTORY   = 'fmea_scan_history_v2';
const KEY_SEL       = 'fmea_sel_v2';

// ── Helpers ───────────────────────────────────────────────────────────────────

function ls(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch { return fallback; }
}

function lsSave(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

const EMPTY_SEL = { portfolioId: null, projectId: null, componentId: null, componentName: null };

function validateSel(sel, hierarchy) {
  if (!sel?.portfolioId) return EMPTY_SEL;
  const portfolio = hierarchy.find(p => p.id === sel.portfolioId);
  if (!portfolio) return EMPTY_SEL;
  if (sel.projectId && !portfolio.projects.some(pr => pr.id === sel.projectId)) {
    return { ...EMPTY_SEL, portfolioId: sel.portfolioId };
  }
  return sel;
}

// ── Compute ALL initial state once on mount ───────────────────────────────────
// Reads localStorage once; avoids three separate reads and mis-matched state.

function loadInitialState() {
  const hierarchy   = ls(KEY_HIERARCHY, []);
  const scanHistory = ls(KEY_HISTORY,   {});
  const rawSel      = ls(KEY_SEL,       EMPTY_SEL);
  const sel         = validateSel(rawSel, hierarchy);
  const entry       = sel.projectId ? scanHistory[sel.projectId] : null;
  return {
    hierarchy,
    scanHistory,
    sel,
    scanResult: entry?.result  ?? null,
    liveScanId: entry?.scanId  ?? null,
  };
}

// ── ID generator ──────────────────────────────────────────────────────────────

function makeId(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // All initial state derived from localStorage in a single read
  const [init] = useState(loadInitialState);

  const [persona, setPersona] = useState('developer');
  const [step,    setStep]    = useState('scan');
  const [scope,   setScope]   = useState('project');
  const [sel,     setSel]     = useState(init.sel);

  const [hierarchy,   setHierarchyState]   = useState(init.hierarchy);
  const [scanHistory, setScanHistoryState] = useState(init.scanHistory);
  const [scanResult,  setScanResult]       = useState(init.scanResult);
  const [liveScanId,  setLiveScanId]       = useState(init.liveScanId);

  // Ref lets the project-switch effect always read latest scanHistory without
  // re-firing on every scan (we only want to fire on project *selection* changes)
  const scanHistoryRef = useRef(init.scanHistory);
  scanHistoryRef.current = scanHistory;

  // ── Persist sel whenever it changes ─────────────────────────────────────────
  useEffect(() => { lsSave(KEY_SEL, sel); }, [sel]);

  // ── Restore scan result when the user switches to a different project ────────
  useEffect(() => {
    if (sel.projectId) {
      const entry = scanHistoryRef.current[sel.projectId];
      setScanResult(entry?.result  ?? null);
      setLiveScanId(entry?.scanId  ?? null);
    } else {
      setScanResult(null);
      setLiveScanId(null);
    }
  }, [sel.projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Hierarchy mutations ───────────────────────────────────────────────────────

  const updateHierarchy = (newH) => {
    setHierarchyState(newH);
    lsSave(KEY_HIERARCHY, newH);
  };

  const addPortfolio = (name) => {
    const id = makeId('p');
    updateHierarchy([...hierarchy, { id, name, projects: [] }]);
  };

  const addProject = (portfolioId, name, repoUrl) => {
    const id = makeId('pr');
    updateHierarchy(hierarchy.map(p =>
      p.id === portfolioId
        ? { ...p, projects: [...p.projects, { id, name, repoUrl: repoUrl || null }] }
        : p,
    ));
    setSel({ portfolioId, projectId: id, componentId: null, componentName: null });
    setScope('project');
    setStep('scan');
    return id;
  };

  const updateProjectRepo = (projectId, repoUrl) => {
    updateHierarchy(hierarchy.map(p => ({
      ...p,
      projects: p.projects.map(pr =>
        pr.id === projectId ? { ...pr, repoUrl } : pr,
      ),
    })));
  };

  // ── Scan history ──────────────────────────────────────────────────────────────

  const recordScan = (projectId, entry) => {
    setScanHistoryState(prev => {
      const updated = { ...prev, [projectId]: entry };
      lsSave(KEY_HISTORY, updated);
      return updated;
    });
  };

  // ── Scan completion callback ──────────────────────────────────────────────────

  const onScanComplete = (scanId, result, projectId, repoUrl) => {
    setScanResult(result);
    setLiveScanId(scanId);
    setStep('scenarios');

    if (projectId) {
      const risks        = result?.risks ?? [];
      const maxRpn       = risks.reduce((m, r) => Math.max(m, r.rpn), 0);
      const newScenarios = result?.new_scenarios ?? [];
      recordScan(projectId, {
        scanId,
        repoUrl:        repoUrl ?? null,
        timestamp:      new Date().toISOString(),
        risk_count:     risks.length,
        max_rpn:        maxRpn,
        from_cache:     result?.from_cache     ?? false,
        registry_locked: result?.registry_locked ?? false,
        locked_count:   risks.length - newScenarios.length,
        workspace_id:   result?.workspace_id   ?? null,
        result,
      });
    }
  };

  // ── Derived display data ──────────────────────────────────────────────────────

  // For project/component scope: use the active scan result.
  // For portfolio/org scope: aggregate risks from every scanned project in scope,
  // tagging each risk with the correct projectId and portfolioId for aggregation tables.
  const liveRisks = (() => {
    if (scope === 'project' || scope === 'component') {
      return scanResult ? normalizeScanResult(scanResult, sel) : null;
    }
    if (scope === 'portfolio') {
      const portfolio = hierarchy.find(p => p.id === sel.portfolioId);
      if (!portfolio) return null;
      const risks = portfolio.projects.flatMap(pr => {
        const entry = scanHistory[pr.id];
        if (!entry?.result) return [];
        return normalizeScanResult(entry.result, {
          portfolioId: sel.portfolioId, projectId: pr.id,
          componentId: null, componentName: null,
        }) ?? [];
      });
      return risks.length ? risks : null;
    }
    if (scope === 'org') {
      const risks = hierarchy.flatMap(portfolio =>
        portfolio.projects.flatMap(pr => {
          const entry = scanHistory[pr.id];
          if (!entry?.result) return [];
          return normalizeScanResult(entry.result, {
            portfolioId: portfolio.id, projectId: pr.id,
            componentId: null, componentName: null,
          }) ?? [];
        })
      );
      return risks.length ? risks : null;
    }
    return null;
  })();

  const liveContext   = scanResult ? getContextSummary(scanResult) : null;
  const workspaceId   = sel.projectId ? (scanHistory[sel.projectId]?.workspace_id ?? null) : null;

  // ── Persona / scope switching ─────────────────────────────────────────────────

  const switchPersona = p => {
    setPersona(p);
    const defaultScope = PERSONA_DEFAULT_SCOPE[p];
    setScope(defaultScope);
    setStep(PROCESS_STEPS.find(s => PERSONA_PRIMARY[p].includes(s.id))?.id ?? 'scenarios');
    if (defaultScope === 'portfolio') setSel(s => ({ ...s, projectId: null, componentId: null, componentName: null }));
    if (defaultScope === 'org')       setSel(EMPTY_SEL);
  };

  const switchScope = s => {
    setScope(s);
    if (s === 'org' || s === 'portfolio') {
      setSel(p => ({ portfolioId: p.portfolioId ?? null, projectId: null, componentId: null, componentName: null }));
    }
  };

  const Content = PAGES[step];

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Sidebar
        persona={persona}
        step={step}
        sel={sel}
        scope={scope}
        hierarchy={hierarchy}
        scanHistory={scanHistory}
        onPersona={switchPersona}
        onStep={setStep}
        onSelect={setSel}
        onScope={switchScope}
        onAddPortfolio={addPortfolio}
        onAddProject={addProject}
      />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header persona={persona} step={step} sel={sel} scope={scope} />
        <main className="flex-1 overflow-y-auto bg-gray-50">
          <Content
            persona={persona}
            sel={sel}
            scope={scope}
            hierarchy={hierarchy}
            scanHistory={scanHistory}
            liveRisks={liveRisks}
            liveContext={liveContext}
            liveScanId={liveScanId}
            workspaceId={workspaceId}
            onScanComplete={onScanComplete}
            onUpdateProjectRepo={updateProjectRepo}
          />
        </main>
      </div>
    </div>
  );
}
