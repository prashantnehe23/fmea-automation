/**
 * frontend/src/api.js
 *
 * Fetch wrappers for every FMEA Platform API endpoint.
 * The Vite dev proxy routes /api/* → http://localhost:8000, so BASE is empty
 * in development.  Set VITE_API_URL in production if needed.
 */

const BASE = import.meta.env.VITE_API_URL ?? '';

// B-015: every request carries the session cookie and the header the server requires on changes.
// A 401 anywhere (session expired or ended) tells the app to show the sign-in page.
async function apiFetch(url, init = {}) {
  const res = await fetch(url, {
    ...init,
    credentials: 'same-origin',
    headers: { ...(init.headers ?? {}), 'X-Requested-With': 'fmea' },
  });
  if (res.status === 401 && !String(url).includes('/api/auth/')) {
    window.dispatchEvent(new Event('fmea:unauthorized'));
  }
  return res;
}

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
  const res = await apiFetch(`${BASE}/api/github/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
  return _json(res, `Could not read the repository (HTTP ${res.status}).`);
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
  maxFailureModes = null,      // null = report everything found (B-028 phase 0)
  forceRerun = false,
  selectedFiles = null,
  maxBatches = undefined,      // passes over a large repository; omitted = the server default
  discovery = 'scenarios',     // 'paths' hunts exploit paths across components and verifies them (B-028 phase B)
) {
  const res = await apiFetch(`${BASE}/api/github/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_url: repoUrl,
      workspace,
      max_failure_modes: maxFailureModes,
      force_rerun: forceRerun,
      selected_files: selectedFiles,
      max_batches: maxBatches,
      discovery,
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
  discovery = 'scenarios',
) {
  const res = await apiFetch(`${BASE}/api/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      workspace,
      max_failure_modes: maxFailureModes,
      force_rerun: forceRerun,
      discovery,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  yield* _readSSE(res);
}

/**
 * GET /api/scan/{scanId} — retrieve a completed scan result.
 */
export async function getScan(scanId) {
  const res = await apiFetch(`${BASE}/api/scan/${scanId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Workspace ─────────────────────────────────────────────────────────────────

/**
 * GET /api/workspace — list all saved workspaces.
 */
export async function listWorkspaces() {
  const res = await apiFetch(`${BASE}/api/workspace`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * POST /api/workspace — create or update a workspace.
 */
export async function upsertWorkspace(ws) {
  const res = await apiFetch(`${BASE}/api/workspace`, {
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
  const res = await apiFetch(`${BASE}/api/workspace/${workspaceId}/scans`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * GET /api/workspace/{workspaceId}/scenarios — locked scenario registry.
 */
export async function getWorkspaceScenarios(workspaceId) {
  const res = await apiFetch(`${BASE}/api/workspace/${workspaceId}/scenarios`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * DELETE /api/workspace/{workspaceId}/scenarios — unlock registry.
 */
export async function deleteWorkspaceScenarios(workspaceId) {
  const res = await apiFetch(`${BASE}/api/workspace/${workspaceId}/scenarios`, {
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
  const res = await apiFetch(`${BASE}/api/remediate`, {
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
  const res = await apiFetch(`${BASE}/api/remediate/${remediationId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Eval history ──────────────────────────────────────────────────────────────

/**
 * GET /api/eval/history/{workspaceId} — last N eval rows for a workspace.
 */
export async function getEvalHistory(workspaceId, n = 20) {
  const res = await apiFetch(`${BASE}/api/eval/history/${workspaceId}?n=${n}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Scoring adjustments ───────────────────────────────────────────────────────

/**
 * POST /api/scoring/adjustment — persist a security-engineer score adjustment.
 * @returns {object} { id, workspace_id, failure_mode, new_s, new_o, new_d, new_rpn, justification, created_at }
 */
export async function postScoringAdjustment(workspaceId, failureMode, newS, newO, newD, justification) {
  const res = await apiFetch(`${BASE}/api/scoring/adjustment`, {
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
  const res = await apiFetch(`${BASE}/api/scoring/adjustments/${workspaceId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Telemetry ─────────────────────────────────────────────────────────────────

/**
 * GET /api/telemetry/{workspaceId} — aggregated observability for a workspace.
 * @returns {{ last_scan_latency, agent_avg_ms, error_rate, quality_trend, total_spans }}
 */
export async function getTelemetry(workspaceId, n = 20) {
  const res = await apiFetch(`${BASE}/api/telemetry/${workspaceId}?n=${n}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Model selector (B-021) ───────────────────────────────────────────────────

/**
 * GET /api/settings/models — list available models with pricing.
 * @returns {Array<{id, display, tier, prompt_per_1m, completion_per_1m, is_active}>}
 */
export async function getModels() {
  const res = await apiFetch(`${BASE}/api/settings/models`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * GET /api/settings/model — currently active model ID.
 * @returns {{ active_model: string }}
 */
export async function getActiveModel() {
  const res = await apiFetch(`${BASE}/api/settings/model`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * PATCH /api/settings/model — change the active model.
 * @param {string} modelId
 * @returns {{ active_model: string }}
 */
export async function setActiveModel(modelId) {
  const res = await apiFetch(`${BASE}/api/settings/model`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelId }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Results chat (B-025) ─────────────────────────────────────────────────────

/** GET /api/chat/{workspaceId} → { thread_id, messages, totals, has_scan, snapshot_id } */
export async function getChatHistory(workspaceId) {
  const res = await apiFetch(`${BASE}/api/chat/${workspaceId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * POST /api/chat/stream — ask a question; async generator of events:
 *   {type:'tool', label, ok}  |  {type:'token', text}  |  {type:'done', answer, usage, thread_totals, ...}
 * Throws Error with .code / .message for failures (no_scan, no_api_key, llm_error, ...).
 * Pass an AbortSignal to stop generation; the server keeps the partial answer.
 */
export async function* streamChat(workspaceId, message, signal) {
  const res = await apiFetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, message }),
    signal,
  });
  if (!res.ok) {
    let detail = {};
    try { detail = (await res.json()).detail ?? {}; } catch { /* not JSON */ }
    const err = new Error(detail.message ?? `HTTP ${res.status}`);
    err.code = detail.code ?? 'http_error';
    throw err;
  }
  for await (const ev of _readSSE(res)) {
    if (!ev.type && ev.code) {            // SSE "error" frame
      const err = new Error(ev.message ?? 'Chat failed');
      err.code = ev.code;
      throw err;
    }
    yield ev;
  }
}

async function _proposalCall(proposalId, action) {
  const res = await apiFetch(`${BASE}/api/chat/proposals/${proposalId}/${action}`, { method: 'POST' });
  if (!res.ok) {
    let detail = {};
    try { detail = (await res.json()).detail ?? {}; } catch { /* not JSON */ }
    const err = new Error(detail.message ?? `HTTP ${res.status}`);
    err.code = detail.code ?? 'http_error';
    throw err;
  }
  return res.json();
}

/** POST /api/chat/proposals/{id}/apply — the user accepts a change the model proposed.
 *  @returns {{ proposal, result }}  result has new_rpn/priority (score) or unlocked (scenario) */
export const applyProposal   = (proposalId) => _proposalCall(proposalId, 'apply');

/** POST /api/chat/proposals/{id}/dismiss — the user declines it. */
export const dismissProposal = (proposalId) => _proposalCall(proposalId, 'dismiss');

// ── Reasoning level (B-023) ──────────────────────────────────────────────────

/** GET /api/settings/reasoning → { level, effective, supported, token_multiplier } */
export async function getReasoning() {
  const res = await apiFetch(`${BASE}/api/settings/reasoning`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** PATCH /api/settings/reasoning — set the level (off | low | medium | high). */
export async function setReasoning(level) {
  const res = await apiFetch(`${BASE}/api/settings/reasoning`, {
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
 * @returns {Array<{id, display, key_set, key_hint, source, status}>}  status: missing|unchecked|valid|invalid|unverified
 */
export async function getProviders() {
  const res = await apiFetch(`${BASE}/api/settings/providers`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** PUT /api/settings/providers/{id}/key — store a provider API key. */
export async function setProviderKey(providerId, apiKey) {
  const res = await apiFetch(`${BASE}/api/settings/providers/${providerId}/key`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `Could not save the key (HTTP ${res.status}).`);
  }
  return res.json();
}

/** PUT /api/settings/providers/{id}/endpoint — set the URL of an Azure or local endpoint (B-047). */
export async function setProviderEndpoint(providerId, endpoint) {
  const res = await apiFetch(`${BASE}/api/settings/providers/${providerId}/endpoint`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint }),
  });
  return _json(res, `Could not save the endpoint (HTTP ${res.status}).`);
}

/** POST /api/settings/models/custom — add a model the user names (an Azure deployment, a local model). */
export async function addCustomModel(provider, id, display) {
  const res = await apiFetch(`${BASE}/api/settings/models/custom`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, id, display }),
  });
  return _json(res, `Could not add the model (HTTP ${res.status}).`);
}

/** DELETE /api/settings/models/custom/{id} */
export async function deleteCustomModel(id) {
  const res = await apiFetch(`${BASE}/api/settings/models/custom/${encodeURIComponent(id)}`, { method: 'DELETE' });
  return _json(res, `Could not remove the model (HTTP ${res.status}).`);
}

/** POST /api/import/sarif — add the findings of a SARIF file; they are scored by the project's next scan (B-045). */
export async function importSarif(workspaceId, file) {
  const res = await apiFetch(`${BASE}/api/import/sarif?workspace_id=${workspaceId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: await file.text(),
  });
  return _json(res, `Could not import the file (HTTP ${res.status}).`);
}

/** The URL that downloads a project's latest scan as SARIF 2.1.0. */
export const sarifExportUrl = projectId => `${BASE}/api/projects/${projectId}/sarif`;

/** POST /api/settings/providers/{id}/verify — re-check the key in use; returns {id, status}. */
export async function verifyProviderKey(providerId) {
  const res = await apiFetch(`${BASE}/api/settings/providers/${providerId}/verify`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** DELETE /api/settings/providers/{id}/key — remove a stored key. */
export async function deleteProviderKey(providerId) {
  const res = await apiFetch(`${BASE}/api/settings/providers/${providerId}/key`, { method: 'DELETE' });
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
  const res = await apiFetch(`${BASE}/api/portfolios`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).map(_mapPortfolio);
}

/** POST /api/portfolios — create portfolio. Returns {id, name, projects: []}. */
export async function createPortfolio(name) {
  const res = await apiFetch(`${BASE}/api/portfolios`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return _mapPortfolio(await res.json());
}

/** DELETE /api/portfolios/{id} — delete portfolio and its projects. */
export async function deletePortfolio(portfolioId) {
  const res = await apiFetch(`${BASE}/api/portfolios/${portfolioId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** POST /api/portfolios/{id}/projects — create project. Returns mapped project. */
export async function createProject(portfolioId, name, repoUrl, businessTier, userType) {
  const res = await apiFetch(`${BASE}/api/portfolios/${portfolioId}/projects`, {
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
  const res = await apiFetch(`${BASE}/api/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** DELETE /api/projects/{id} — delete project. */
export async function deleteProject(projectId) {
  const res = await apiFetch(`${BASE}/api/projects/${projectId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Data normalisation ────────────────────────────────────────────────────────

// Corrective and preventive actions (B-030). Plans stored before it carry text lists: fixes become corrective
// actions, monitoring and resilience upgrades become preventive ones.
function actionsOf(rm = {}) {
  if (rm.corrective?.length || rm.preventive?.length) {
    return { corrective: rm.corrective ?? [], preventive: rm.preventive ?? [] };
  }
  const old = (title, kind, i, p) => ({ id: `${p}${i + 1}`, title, detail: '', kind, target: '', verification: '', owner_role: 'developer', urgency: 'next' });
  return {
    corrective: (rm.fixes ?? []).map((t, i) => old(t, 'code_fix', i, 'c')),
    preventive: [...(rm.monitoring ?? []).map(t => [t, 'monitoring']), ...(rm.resilience_upgrades ?? []).map(t => [t, 'design_change'])]
      .map(([t, k], i) => old(t, k, i, 'p')),
  };
}

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
  const rootCauseMap = Object.fromEntries((apiResult.root_causes ?? []).map(r => [r.failure_mode, r]));
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
      priority_reason: risk.priority_reason ?? '',
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
      // ── Root cause (B-029); scans stored before it have none ─────────────
      root_cause:          rootCauseMap[risk.failure_mode]?.primary ?? 'unclassified',
      root_cause_also:     rootCauseMap[risk.failure_mode]?.contributing ?? [],
      root_cause_chain:    rootCauseMap[risk.failure_mode] ?? null,
      // ── Source and CWE (B-045) ───────────────────────────────────────────
      cwe:                 f.cwe ?? 'unmapped',
      source:              f.source ?? 'fmea',
      also_reported_by:    f.also_reported_by ?? [],
      // ── Exploit path across components (B-028 phase B) ───────────────────
      exploit_path:        f.exploit_path ?? [],
      path_status:         f.path_status ?? '',
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
      corrective: actionsOf(rm).corrective,
      preventive: actionsOf(rm).preventive,
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
  paths:       'Exploit paths — hunting across components and verifying',
  actuary:     'Actuary — scoring RPN (S × O × D)',
  root_cause:  'Root-cause analyst — finding where fixes belong',
  sre:         'SRE agent — building remediation plans',
  validator:   'Validator — peer-reviewing scores',
  registry:    'Registry — locking scenarios',
  eval:        'Evaluator — checking pipeline quality',
  complete:    'Scan complete',
  error:       'Error',
};


// ── Sign-in and users (B-015) ────────────────────────────────────────────────

async function _json(res, fallback) {
  if (res.ok) return res.json();
  let detail = '';
  try { detail = (await res.json()).detail; } catch { /* not JSON */ }
  throw new Error(typeof detail === 'string' && detail ? detail : fallback);
}

const _post = (path, body) => apiFetch(`${BASE}${path}`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export async function getAuthStatus() {
  return _json(await apiFetch(`${BASE}/api/auth/status`), 'Could not reach the server.');
}
export async function getMe() {
  const res = await apiFetch(`${BASE}/api/auth/me`);
  return res.ok ? res.json() : null;
}
export async function login(username, password) {
  return _json(await _post('/api/auth/login', { username, password }), 'Could not sign in.');
}
export async function setupAdmin(username, password, setupToken) {
  return _json(await _post('/api/auth/setup', { username, password, setup_token: setupToken || null }), 'Could not create the administrator.');
}
export async function logout() {
  await _post('/api/auth/logout', {});
}
/** GET /api/projects/{id}/latest-scan — the project's stored scan in the shape kept per project, or null. */
export async function getProjectScan(projectId) {
  const res = await apiFetch(`${BASE}/api/projects/${projectId}/latest-scan`);
  return res.ok ? res.json() : null;
}

// ── Private repository access (B-043) ────────────────────────────────────────

/** GET /api/settings/repo-credentials — owners with a stored token: [{provider, owner, hint}]. Never the token. */
export async function listRepoCredentials() {
  return _json(await apiFetch(`${BASE}/api/settings/repo-credentials`), 'Could not load repository access.');
}
/** PUT /api/settings/repo-credentials — validates the token with GitHub, then stores it encrypted. */
export async function saveRepoCredential(owner, token) {
  const res = await apiFetch(`${BASE}/api/settings/repo-credentials`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ owner, token }),
  });
  return _json(res, 'Could not save the token.');
}
export async function deleteRepoCredential(owner) {
  return _json(await apiFetch(`${BASE}/api/settings/repo-credentials?owner=${encodeURIComponent(owner)}`, { method: 'DELETE' }),
               'Could not remove the token.');
}

// ── Finding lifecycle (B-031) ────────────────────────────────────────────────

/** GET /api/workspace/{id}/findings — {findings: [{failure_mode, state, ...}], events: [...]}. */
export async function getFindings(workspaceId) {
  return _json(await apiFetch(`${BASE}/api/workspace/${workspaceId}/findings`), 'Could not load findings.');
}
/** POST /api/workspace/{id}/findings/state — a person confirms a fix, accepts a risk or reopens a finding. */
export async function setFindingState(workspaceId, failureMode, state) {
  return _json(await _post(`/api/workspace/${workspaceId}/findings/state`, { failure_mode: failureMode, state }),
               'Could not change the finding.');
}
