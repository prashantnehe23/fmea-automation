import { useState, useEffect, useRef, useMemo } from 'react';
import Sidebar from './components/Sidebar';
import Header  from './components/Header';
import ScanPage        from './pages/ScanPage';
import ScenariosPage   from './pages/ScenariosPage';
import FindingsPage    from './pages/FindingsPage';
import ScoringPage     from './pages/ScoringPage';
import MitigationsPage from './pages/MitigationsPage';
import RemediationPage from './pages/RemediationPage';
import DashboardPage   from './pages/DashboardPage';
import ChatPanel       from './components/ChatPanel';
import { navCounts } from './helpers';
import { EMPTY_SEL, deriveScope, limitSel, componentsOf, filterByComponent, defaultComponent } from './selection';
import {
  PROCESS_STEPS,
  PERSONA_PRIMARY,
  PERSONA_DEFAULT_SCOPE,
} from './data';
import {
  normalizeScanResult,
  getContextSummary,
  getScoringAdjustments,
  listPortfolios,
  createPortfolio,
  createProject,
  updateProject,
  getAuthStatus,
  getMe,
  logout,
  getProjectScan,
} from './api';
import LoginPage from './pages/LoginPage';
import SubTabs from './components/SubTabs';

// The view each real role gets; the persona switcher only exists in demo mode (B-015)
const ROLE_PERSONA = { admin: 'security_engineer', security_engineer: 'security_engineer', risk_manager: 'risk_manager', developer: 'developer', viewer: 'executive' };

const PAGES = {
  scan:        ScanPage,
  findings:    FindingsPage,
  scenarios:   ScenariosPage,
  scoring:     ScoringPage,
  mitigations: MitigationsPage,
  remediation: RemediationPage,
  dashboard:   DashboardPage,
};

// ── Storage keys (v2 = fresh start; old v1 mock data is ignored) ──────────────

const KEY_HIERARCHY       = 'fmea_hierarchy_v2';
const KEY_HISTORY         = 'fmea_scan_history_v2';
const KEY_SEL             = 'fmea_sel_v2';
const KEY_MIGRATION_DONE  = 'fmea_migration_v1_done'; // prevents double-run under React StrictMode
const KEY_CHAT_OPEN       = 'fmea_chat_open_v1';

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

// ── One-time migration: import old localStorage hierarchy into the API ─────────

async function _migrateHierarchy(localHierarchy, localScanHistory) {
  const newHierarchy = [];
  const remappedHistory = {};
  for (const portfolio of localHierarchy) {
    const created = await createPortfolio(portfolio.name);
    const newPortfolio = { ...created, projects: [] };
    for (const project of portfolio.projects) {
      const newProject = await createProject(
        created.id,
        project.name,
        project.repoUrl || null,
        project.businessTier || 'Tier 1',
        project.userType || 'external_customers',
      );
      newPortfolio.projects.push(newProject);
      if (localScanHistory[project.id]) {
        remappedHistory[newProject.id] = localScanHistory[project.id];
      }
    }
    newHierarchy.push(newPortfolio);
  }
  return { newHierarchy, remappedHistory };
}

// Score adjustments (Scoring page or chat) override the scan's scores for display, so a
// change shows immediately; the backend applies the same overlay to locked scores on rescan.
function applyAdjustments(risks, adjustments) {
  if (!Object.keys(adjustments).length) return risks;
  return risks.map(r => {
    const a = adjustments[r.name];
    if (!a) return r;
    return { ...r, s: a.new_s, o: a.new_o, d: a.new_d, rpn: a.new_rpn,
             priority: a.priority || r.priority, priority_reason: `Adjusted by ${a.source ?? 'an expert'}: RPN ${a.new_rpn}`, adjusted: true, original_rpn: r.rpn, adjusted_by: a.source };
  });
}

// ── App ───────────────────────────────────────────────────────────────────────

function Workspace({ user, status, onLogout }) {
  // All initial state derived from localStorage in a single read.
  // After B-007, KEY_HIERARCHY is a read-through cache of the API response;
  // it seeds the UI immediately so there is no blank flash on load.
  const [init] = useState(loadInitialState);

  // Real users get the view of their role; the switcher exists only in demo mode (B-015)
  const [persona, setPersona] = useState(ROLE_PERSONA[user.role] ?? 'developer');
  const [step,    setStep]    = useState('scan');
  const [chatOpen, setChatOpen] = useState(() => ls(KEY_CHAT_OPEN, false));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selState, setSel]    = useState(init.sel);
  // what the role may use of the saved selection, and the scope that follows from it (ADR-034)
  const sel   = useMemo(() => limitSel(selState, persona), [selState, persona]);
  const scope = deriveScope(sel, persona);

  const [hierarchy,   setHierarchyState]   = useState(init.hierarchy);
  const [scanHistory, setScanHistoryState] = useState(init.scanHistory);
  const [scanResult,  setScanResult]       = useState(init.scanResult);
  const [liveScanId,  setLiveScanId]       = useState(init.liveScanId);
  const [adjustments, setAdjustments]     = useState({});   // failure_mode → latest score adjustment

  // Ref lets the project-switch effect always read latest scanHistory without
  // re-firing on every scan (we only want to fire on project *selection* changes)
  const workspaceIdRef = useRef(null);
  const scanHistoryRef = useRef(init.scanHistory);
  scanHistoryRef.current = scanHistory;

  // ── Bootstrap: sync hierarchy from API; migrate localStorage on first run ────
  useEffect(() => {
    async function bootstrap() {
      try {
        const portfolios = await listPortfolios();
        if (portfolios.length > 0) {
          // API has data — refresh state and repopulate the localStorage cache
          setHierarchyState(portfolios);
          lsSave(KEY_HIERARCHY, portfolios);
          return;
        }
        // API is empty — check if localStorage has data to migrate (Option A).
        // Guard flag is set synchronously before any await so React StrictMode's
        // double-invocation of this effect cannot trigger a duplicate migration.
        if (init.hierarchy.length > 0 && !ls(KEY_MIGRATION_DONE, false)) {
          lsSave(KEY_MIGRATION_DONE, true);
          const { newHierarchy, remappedHistory } =
            await _migrateHierarchy(init.hierarchy, init.scanHistory);
          setHierarchyState(newHierarchy);
          setScanHistoryState(remappedHistory);
          lsSave(KEY_HIERARCHY, newHierarchy);
          lsSave(KEY_HISTORY, remappedHistory);
          // Reset selection — old string IDs are no longer valid
          setSel(EMPTY_SEL);
          lsSave(KEY_SEL, EMPTY_SEL);
        }
        // else: truly fresh start — nothing to do
      } catch (_) {
        // API unreachable — localStorage cache already loaded by loadInitialState
      }
    }
    bootstrap();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshAdjustments = (wsId = workspaceIdRef.current) => {
    if (!wsId) { setAdjustments({}); return; }
    getScoringAdjustments(wsId)
      .then(rows => {
        const latest = {};
        for (const row of rows) if (!(row.failure_mode in latest)) latest[row.failure_mode] = row;   // newest first
        setAdjustments(latest);
      })
      .catch(() => {});   // non-critical: scores simply show as scanned
  };

  const toggleChat = () => setChatOpen(v => { lsSave(KEY_CHAT_OPEN, !v); return !v; });

  // ── Persist sel whenever it changes ─────────────────────────────────────────
  useEffect(() => { lsSave(KEY_SEL, selState); }, [selState]);

  // ── Restore scan result when the user switches to a different project ────────
  useEffect(() => {
    if (sel.projectId) {
      const entry = scanHistoryRef.current[sel.projectId];
      setScanResult(entry?.result  ?? null);
      setLiveScanId(entry?.scanId  ?? null);
      const projectId = sel.projectId;
      getProjectScan(projectId).then(stored => {
        if (!stored || stored.scanId === scanHistoryRef.current[projectId]?.scanId && stored.timestamp === scanHistoryRef.current[projectId]?.timestamp) return;
        recordScan(projectId, stored);
        setScanResult(stored.result);
        setLiveScanId(stored.scanId);
      }).catch(() => {});
    } else {
      setScanResult(null);
      setLiveScanId(null);
    }
  }, [sel.projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Hierarchy helpers ─────────────────────────────────────────────────────────

  const _applyHierarchy = (newH) => {
    setHierarchyState(newH);
    lsSave(KEY_HIERARCHY, newH);   // keep localStorage as a read-through cache
  };

  // ── Hierarchy mutations (API-first, then update local state + cache) ──────────

  const addPortfolio = async (name) => {
    const created = await createPortfolio(name);
    _applyHierarchy([...hierarchy, created]);
  };

  const addProject = async (portfolioId, name, repoUrl, businessTier = 'Tier 1', userType = 'external_customers') => {
    const newProject = await createProject(portfolioId, name, repoUrl, businessTier, userType);
    _applyHierarchy(hierarchy.map(p =>
      p.id === portfolioId
        ? { ...p, projects: [...p.projects, newProject] }
        : p,
    ));
    setSel({ portfolioId, projectId: newProject.id, componentId: null, componentName: null });
    setStep('scan');
    return newProject.id;
  };

  const updateProjectRepo = async (projectId, repoUrl) => {
    await updateProject(projectId, { repoUrl });
    _applyHierarchy(hierarchy.map(p => ({
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
  // the project's findings before any component filter: the component list is taken from these
  const projectRisks = useMemo(() => {
    const risks = scanResult ? normalizeScanResult(scanResult, { ...sel, componentName: null }) : null;
    return risks && applyAdjustments(risks, adjustments);
  }, [scanResult, sel.portfolioId, sel.projectId, adjustments]); // eslint-disable-line react-hooks/exhaustive-deps
  const projectComponents = useMemo(() => (sel.projectId ? componentsOf(projectRisks) : []), [projectRisks, sel.projectId]);

  // a role that works only at component level always has one selected
  useEffect(() => {
    if (sel.projectId && !sel.componentName) {
      const first = defaultComponent(persona, projectComponents);
      if (first) setSel(s => ({ ...s, componentName: first }));
    }
  }, [persona, sel.projectId, sel.componentName, projectComponents]);

  const liveRisks = useMemo(() => {
    if (scope === 'project' || scope === 'component') {
      return filterByComponent(projectRisks, scope === 'component' ? sel.componentName : null);
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
  }, [scope, projectRisks, sel, hierarchy, scanHistory, adjustments]); // eslint-disable-line react-hooks/exhaustive-deps

  const liveContext   = scanResult ? getContextSummary(scanResult) : null;
  const workspaceId   = sel.projectId ? (scanHistory[sel.projectId]?.workspace_id ?? null) : null;
  workspaceIdRef.current = workspaceId;
  // the saved scan of the selected project: fixes are written from what the database stored (B-056)
  const liveDbScanId  = sel.projectId ? (scanHistory[sel.projectId]?.result?.db_scan_id ?? null) : null;
  useEffect(() => { refreshAdjustments(workspaceId); }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Persona / scope switching ─────────────────────────────────────────────────

  const switchPersona = p => {
    setPersona(p);
    const defaultScope = PERSONA_DEFAULT_SCOPE[p];
    setStep(PROCESS_STEPS.find(s => PERSONA_PRIMARY[p].includes(s.id))?.id ?? 'scenarios');
    if (defaultScope === 'portfolio') setSel(s => ({ ...s, projectId: null, componentId: null, componentName: null }));
    if (defaultScope === 'org')       setSel(EMPTY_SEL);
  };

  const Content = PAGES[step];

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Sidebar
        persona={persona}
        step={step}
        sel={sel}
        hierarchy={hierarchy}
        scanHistory={scanHistory}
        onPersona={switchPersona}
        user={user}
        canSwitchPersona={!!status?.demo_mode}
        onLogout={onLogout}
        onStep={setStep}
        onSelect={setSel}
        onAddPortfolio={addPortfolio}
        onAddProject={addProject}
        onOpenSettings={() => setSettingsOpen(true)}
        counts={navCounts(liveRisks)}
      />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header persona={persona} step={step} sel={sel} hierarchy={hierarchy} components={projectComponents} onSelect={setSel} chatOpen={chatOpen} onToggleChat={toggleChat} settingsOpen={settingsOpen} onSettingsOpenChange={setSettingsOpen} isAdmin={user.role === 'admin'} />
        <div className="flex flex-1 overflow-hidden">
        <main className="flex-1 overflow-y-auto bg-gray-50">
          <SubTabs step={step} onStep={setStep} />
          <Content
            persona={persona}
            sel={sel}
            scope={scope}
            settingsOpen={settingsOpen}
            onOpenSettings={() => setSettingsOpen(true)}
            canDecideFindings={['admin', 'security_engineer'].includes(user.role)}
            hierarchy={hierarchy}
            scanHistory={scanHistory}
            liveRisks={liveRisks}
            liveContext={liveContext}
            liveScanId={liveScanId}
            liveDbScanId={liveDbScanId}
            workspaceId={workspaceId}
            onScanComplete={onScanComplete}
            onUpdateProjectRepo={updateProjectRepo}
            onAdjustmentSaved={refreshAdjustments}
          />
        </main>
        {chatOpen && (
          <ChatPanel
            workspaceId={workspaceId}
            persona={persona}
            projectName={hierarchy.flatMap(p => p.projects).find(pr => pr.id === sel.projectId)?.name ?? null}
            onClose={toggleChat}
            onProposalApplied={() => refreshAdjustments()}
          />
        )}
        </div>
      </div>
    </div>
  );
}

// The browser cache holds one user's results; drop it on sign-out so the next user never sees it
function clearLocalCache() {
  try {
    Object.keys(localStorage).filter(k => k.startsWith('fmea')).forEach(k => localStorage.removeItem(k));
  } catch { /* storage unavailable */ }
}

// ── Sign-in gate (B-015) ──────────────────────────────────────────────────────

export default function App() {
  const [status, setStatus] = useState(null);       // { setup_required, demo_mode, oidc_enabled }
  const [user, setUser]     = useState(undefined);  // undefined = checking, null = signed out

  useEffect(() => {
    Promise.all([getAuthStatus(), getMe()])
      .then(([st, me]) => { setStatus(st); setUser(me); })
      .catch(() => { setStatus({}); setUser(null); });
    const onUnauthorized = () => { clearLocalCache(); setUser(null); };
    window.addEventListener('fmea:unauthorized', onUnauthorized);
    return () => window.removeEventListener('fmea:unauthorized', onUnauthorized);
  }, []);

  if (user === undefined) return null;
  if (!user) {
    return <LoginPage status={status} onSignedIn={u => { setUser(u); getAuthStatus().then(setStatus).catch(() => {}); }} />;
  }
  return <Workspace key={user.id} user={user} status={status} onLogout={async () => { await logout(); clearLocalCache(); setUser(null); }} />;
}
