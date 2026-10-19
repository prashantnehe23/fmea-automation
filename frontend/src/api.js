/**
 * frontend/src/api.js
 *
 * Fetch wrappers for every FMEA Platform API endpoint.
 * The Vite dev proxy routes /api/* → http://localhost:8000, so BASE is empty
 * in development.  Set VITE_API_URL in production if needed.
 */

const BASE = import.meta.env.VITE_API_URL ?? '';

// ── Internal SSE reader ───────────────────────────────────────────────────────

/**
 * Async generator that reads a fetch Response body as SSE frames.
 * Yields one parsed JSON object per "data: …" line.
 */
async function* _readSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by double newlines
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';

    for (const part of parts) {
      let data = '';
      for (const line of part.split('\n')) {
        if (line.startsWith('data: ')) data = line.slice(6);
      }
      if (data) {
        try { yield JSON.parse(data); } catch { /* skip malformed frame */ }
      }
    }
  }
}

// ── GitHub ────────────────────────────────────────────────────────────────────

/**
 * POST /api/github/preview — return file listing for a repo without scanning.
 * @param {string} repoUrl  Full GitHub URL (https://github.com/owner/repo)
 * @returns {object} { ref, file_count, files, readme_path, has_readme }
 */
export async function previewGithubRepo(repoUrl) {
  const res = await fetch(`${BASE}/api/github/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

/**
 * POST /api/github/scan — stream a full GitHub repo FMEA scan.
 *
 * @param {string} repoUrl            Full GitHub URL.
 * @param {object|null} workspace     Optional WorkspaceIn (customer, project, …).
 * @param {number} maxFailureModes    Cap on failure modes (default 7).
 * @param {boolean} forceRerun        Skip cache.
 *
 * Yields the same shapes as streamScan(), plus repo-specific stages:
 *   {stage: "repo_scan",   msg: string}
 *   {stage: "repo_tree",   file_count: number, readme: string|null, ref: object}
 *   {stage: "readme",      msg: string}
 *   {stage: "fetch_files", msg: string}
 *   {stage: "files_ready", fetched_count: number, code_length: number}
 *   … then the standard pipeline stages …
 *   {stage: "complete",    scan_id: number, result: object, repo: object}
 *   {stage: "error",       msg: string}
 */
export async function* streamGithubScan(
  repoUrl,
  workspace = null,
  maxFailureModes = 7,
  forceRerun = false,
  selectedFiles = null,
) {
  const res = await fetch(`${BASE}/api/github/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_url: repoUrl,
      workspace,
      max_failure_modes: maxFailureModes,
      force_rerun: forceRerun,
      selected_files: selectedFiles,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  yield* _readSSE(res);
}

// ── Scan ──────────────────────────────────────────────────────────────────────

/**
 * POST /api/scan — stream FMEA pipeline progress events.
 *
 * @param {string} code               Python source to analyse.
 * @param {object|null} workspace     Optional workspace config (see WorkspaceIn).
 * @param {number} maxFailureModes    Cap on failure modes (default 7).
 * @param {boolean} forceRerun        Skip cache and force a fresh scan.
 *
 * Yields objects of shapes:
 *   {stage: "init"|"surveyor"|"saboteur"|"controls"|"actuary"|"sre"|
 *           "validator"|"registry"|"eval",  status?: "running"|"done"}
 *   {stage: "complete", scan_id: number, result: ScanResult}
 *   {stage: "error",    msg: string}
 */
export async function* streamScan(
  code,
  workspace = null,
  maxFailureModes = 7,
  forceRerun = false,
) {
  const res = await fetch(`${BASE}/api/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      workspace,
      max_failure_modes: maxFailureModes,
      force_rerun: forceRerun,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  yield* _readSSE(res);
}

/**
 * GET /api/scan/{scanId} — retrieve a completed scan result.
 */
export async function getScan(scanId) {
  const res = await fetch(`${BASE}/api/scan/${scanId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Workspace ─────────────────────────────────────────────────────────────────

/**
 * GET /api/workspace — list all saved workspaces.
 */
export async function listWorkspaces() {
  const res = await fetch(`${BASE}/api/workspace`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * POST /api/workspace — create or update a workspace.
 */
export async function upsertWorkspace(ws) {
  const res = await fetch(`${BASE}/api/workspace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ws),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * GET /api/workspace/{workspaceId}/scans — scan history for a workspace.
 */
export async function getWorkspaceScans(workspaceId) {
  const res = await fetch(`${BASE}/api/workspace/${workspaceId}/scans`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * GET /api/workspace/{workspaceId}/scenarios — locked scenario registry.
 */
export async function getWorkspaceScenarios(workspaceId) {
  const res = await fetch(`${BASE}/api/workspace/${workspaceId}/scenarios`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * DELETE /api/workspace/{workspaceId}/scenarios — unlock registry.
 */
export async function deleteWorkspaceScenarios(workspaceId) {
  const res = await fetch(`${BASE}/api/workspace/${workspaceId}/scenarios`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Remediation ───────────────────────────────────────────────────────────────

/**
 * POST /api/remediate — stream auto-remediation progress events.
 *
 * Yields objects of shapes:
 *   {stage: "init"|"remediating", msg: string, count?: number}
 *   {stage: "complete", remediation_id: number, results: RemediationResult[]}
 *   {stage: "error",    msg: string}
 */
export async function* streamRemediate(scanId) {
  const res = await fetch(`${BASE}/api/remediate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scan_id: scanId }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  yield* _readSSE(res);
}

/**
 * GET /api/remediate/{remediationId} — retrieve completed remediation results.
 */
export async function getRemediation(remediationId) {
  const res = await fetch(`${BASE}/api/remediate/${remediationId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Eval history ──────────────────────────────────────────────────────────────

/**
 * GET /api/eval/history/{workspaceId} — last N eval rows for a workspace.
 */
export async function getEvalHistory(workspaceId, n = 20) {
  const res = await fetch(`${BASE}/api/eval/history/${workspaceId}?n=${n}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Scoring adjustments ───────────────────────────────────────────────────────

/**
 * POST /api/scoring/adjustment — persist a security-engineer score adjustment.
 * @returns {object} { id, workspace_id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at }
 */
export async function postScoringAdjustment(workspaceId, failureMode, newS, newO, newD, justification) {
  const res = await fetch(`${BASE}/api/scoring/adjustment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace_id:  workspaceId,
      failure_mode:  failureMode,
      new_s:         newS,
      new_o:         newO,
      new_d:         newD,
      justification,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

/**
 * GET /api/scoring/adjustments/{workspaceId} — audit trail for a workspace.
 * @returns {Array} list of adjustment objects ordered newest first
 */
export async function getScoringAdjustments(workspaceId) {
  const res = await fetch(`${BASE}/api/scoring/adjustments/${workspaceId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Telemetry ─────────────────────────────────────────────────────────────────

/**
 * GET /api/telemetry/{workspaceId} — aggregated observability for a workspace.
 * @returns {{ last_scan_latency, agent_avg_ms, error_rate, quality_trend, total_spans }}
 */
export async function getTelemetry(workspaceId, n = 20) {
  const res = await fetch(`${BASE}/api/telemetry/${workspaceId}?n=${n}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Model selector (B-021) ───────────────────────────────────────────────────

/**
 * GET /api/settings/models — list available models with pricing.
 * @returns {Array<{id, display, tier, prompt_per_1m, completion_per_1m, is_active}>}
 */
export async function getModels() {
  const res = await fetch(`${BASE}/api/settings/models`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * GET /api/settings/model — currently active model ID.
 * @returns {{ active_model: string }}
 */
export async function getActiveModel() {
  const res = await fetch(`${BASE}/api/settings/model`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * PATCH /api/settings/model — change the active model.
 * @param {string} modelId
 * @returns {{ active_model: string }}
 */
export async function setActiveModel(modelId) {
  const res = await fetch(`${BASE}/api/settings/model`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelId }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Reasoning level (B-023) ──────────────────────────────────────────────────

/** GET /api/settings/reasoning → { level, effective, supported, token_multiplier } */
export async function getReasoning() {
  const res = await fetch(`${BASE}/api/settings/reasoning`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** PATCH /api/settings/reasoning — set the level (off | low | medium | high). */
export async function setReasoning(level) {
  const res = await fetch(`${BASE}/api/settings/reasoning`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Provider API keys (B-022) ────────────────────────────────────────────────

/**
 * GET /api/settings/providers — providers with masked key status.
 * @returns {Array<{id, display, key_set, key_hint, source}>}
 */
export async function getProviders() {
  const res = await fetch(`${BASE}/api/settings/providers`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** PUT /api/settings/providers/{id}/key — store a provider API key. */
export async function setProviderKey(providerId, apiKey) {
  const res = await fetch(`${BASE}/api/settings/providers/${providerId}/key`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

/** DELETE /api/settings/providers/{id}/key — remove a stored key. */
export async function deleteProviderKey(providerId) {
  const res = await fetch(`${BASE}/api/settings/providers/${providerId}/key`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Portfolio / Project hierarchy (B-007) ────────────────────────────────────

function _mapProject(p) {
  return {
    id:           p.id,
    portfolio_id: p.portfolio_id,
    name:         p.name,
    repoUrl:      p.repo_url ?? null,
    businessTier: p.business_tier ?? 'Tier 1',
    userType:     p.user_type ?? 'external_customers',
    created_at:   p.created_at,
  };
}

function _mapPortfolio(p) {
  return {
    id:         p.id,
    name:       p.name,
    created_at: p.created_at,
    projects:   (p.projects ?? []).map(_mapProject),
  };
}

/** GET /api/portfolios — nested portfolios + projects (camelCase). */
export async function listPortfolios() {
  const res = await fetch(`${BASE}/api/portfolios`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).map(_mapPortfolio);
}

/** POST /api/portfolios — create portfolio. Returns {id, name, projects: []}. */
export async function createPortfolio(name) {
  const res = await fetch(`${BASE}/api/portfolios`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return _mapPortfolio(await res.json());
}

/** DELETE /api/portfolios/{id} — delete portfolio and its projects. */
export async function deletePortfolio(portfolioId) {
  const res = await fetch(`${BASE}/api/portfolios/${portfolioId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** POST /api/portfolios/{id}/projects — create project. Returns mapped project. */
export async function createProject(portfolioId, name, repoUrl, businessTier, userType) {
  const res = await fetch(`${BASE}/api/portfolios/${portfolioId}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      repo_url:      repoUrl || null,
      business_tier: businessTier,
      user_type:     userType,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return _mapProject(await res.json());
}

/** PATCH /api/projects/{id} — partial update (only fields in patch are sent). */
export async function updateProject(projectId, patch) {
  const body = {};
  if ('repoUrl'      in patch) body.repo_url      = patch.repoUrl;
  if ('businessTier' in patch) body.business_tier = patch.businessTier;
  if ('userType'     in patch) body.user_type     = patch.userType;
  const res = await fetch(`${BASE}/api/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** DELETE /api/projects/{id} — delete project. */
export async function deleteProject(projectId) {
  const res = await fetch(`${BASE}/api/projects/${projectId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Data normalisation ────────────────────────────────────────────────────────

/**
 * Convert a run_fmea() API result to the rich risk row shape used by all UI
 * components.  Every row carries not just scoring fields but also the full
 * attack chain, rationales, validator output, and remediation plan so that
 * detail panels can render without a separate lookup.
 *
 * @param {object} apiResult  The "result" object from a "complete" SSE event.
 * @param {object} sel        The current hierarchy selection from App state.
 * @returns {Array}           Array of rich risk rows.
 */
export function normalizeScanResult(apiResult, sel) {
  if (!apiResult?.risks?.length) return [];

  const newScenarioSet = new Set(apiResult.new_scenarios ?? []);
  const failureMap     = Object.fromEntries((apiResult.failures     ?? []).map(f => [f.failure_mode, f]));
  const controlMap     = Object.fromEntries((apiResult.controls     ?? []).map(c => [c.failure_mode, c]));
  const remediationMap = Object.fromEntries((apiResult.remediations ?? []).map(r => [r.failure_mode, r]));
  const validationMap  = Object.fromEntries((apiResult.validations  ?? []).map(v => [v.failure_mode, v]));
  const linkageMap     = Object.fromEntries(
    (apiResult.scenario_linkage?.explanations ?? []).map(e => [e.failure_mode, e])
  );

  return apiResult.risks.map((risk, i) => {
    const f  = failureMap[risk.failure_mode]     ?? {};
    const c  = controlMap[risk.failure_mode]     ?? {};
    const rm = remediationMap[risk.failure_mode] ?? {};
    const v  = validationMap[risk.failure_mode]  ?? {};
    const lk = linkageMap[risk.failure_mode]     ?? {};

    return {
      // ── Identity ──────────────────────────────────────────────────────────
      id:        i + 1,
      name:      risk.failure_mode,
      // ── Scores ───────────────────────────────────────────────────────────
      s:         risk.severity,
      o:         risk.occurrence,
      d:         risk.detection,
      rpn:       risk.rpn,
      priority:  risk.priority,
      status:    'Open',
      // ── Workspace / hierarchy ─────────────────────────────────────────────
      comp:      sel?.componentName ?? 'Scanned',
      project:   sel?.projectId     ?? 'pr1',
      portfolio: sel?.portfolioId   ?? 'p1',
      owner:     'Dev Team',
      // ── Failure mode details ──────────────────────────────────────────────
      impact:              f.business_impact ?? '',
      attack_chain:        f.attack_chain    ?? [],
      blast_radius:        f.blast_radius    ?? '',
      trigger:             f.trigger         ?? '',
      evidence:            f.evidence        ?? '',   // code snippet
      // ── Scoring rationales ────────────────────────────────────────────────
      justification:         risk.justification          ?? '',
      severity_rationale:    risk.severity_rationale     ?? '',
      occurrence_rationale:  risk.occurrence_rationale   ?? '',
      detection_rationale:   risk.detection_rationale    ?? '',
      // ── Controls ─────────────────────────────────────────────────────────
      controls:         c.controls         ?? {},
      control_maturity: c.control_maturity ?? '',
      gaps:             c.gaps             ?? [],
      // ── Remediation plan ─────────────────────────────────────────────────
      fixes:               rm.fixes               ?? [],
      monitoring:          rm.monitoring          ?? [],
      resilience_upgrades: rm.resilience_upgrades ?? [],
      roadmap_90_day:      rm.roadmap_90_day      ?? {},
      roadmap_tasks:       rm.roadmap_tasks        ?? [],
      dependency_notes:    rm.dependency_notes    ?? '',
      rpn_priority_note:   rm.rpn_priority_note   ?? '',
      // ── Validator ────────────────────────────────────────────────────────
      is_realistic:          v.is_realistic          ?? true,
      attack_chain_complete: v.attack_chain_complete ?? true,
      rpn_calibrated:        v.rpn_calibrated        ?? true,
      challenges:            v.challenges            ?? [],
      confidence:            v.confidence            ?? null,
      verdict:               v.verdict               ?? '',
      // ── Scenario linkage ──────────────────────────────────────────────────
      scenario_summary:  lk.scenario_summary ?? '',
      code_connection:   lk.code_connection  ?? '',
      // ── Registry ─────────────────────────────────────────────────────────────
      is_new: newScenarioSet.has(risk.failure_mode),
    };
  });
}

/**
 * Extract the business / system context summary from a scan result.
 * Returns null when no context is available.
 */
export function getContextSummary(apiResult) {
  if (!apiResult) return null;
  const ctx = apiResult.context;
  const ws  = apiResult.workspace;
  if (!ctx && !ws) return null;
  return {
    attack_surfaces:   ctx?.attack_surfaces   ?? [],
    failure_domains:   ctx?.failure_domains   ?? [],
    tiering:           ctx?.tiering           ?? {},
    business_context:  ws?.business_context   ?? '',
    customer:          ws?.customer           ?? '',
    project:           ws?.project            ?? '',
    business_tier:     ws?.business_tier      ?? '',
  };
}

/**
 * Stage label map for progress display in the UI.
 */
export const STAGE_LABELS = {
  // GitHub pre-pipeline stages
  repo_scan:   'Fetching repository tree…',
  repo_tree:   'Repository tree ready',
  readme:      'Reading README for business context…',
  fetch_files: 'Downloading code files…',
  files_ready: 'Files downloaded — starting pipeline',
  // Core pipeline stages
  init:        'Starting pipeline…',
  surveyor:    'Surveyor — mapping system context',
  saboteur:    'Saboteur — generating failure scenarios',
  controls:    'Controls assessor — reviewing mitigations',
  actuary:     'Actuary — scoring RPN (S × O × D)',
  sre:         'SRE agent — building remediation plans',
  validator:   'Validator — peer-reviewing scores',
  registry:    'Registry — locking scenarios',
  eval:        'Evaluator — checking pipeline quality',
  complete:    'Scan complete',
  error:       'Error',
};
