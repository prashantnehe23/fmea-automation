# ADR-032: Model Selection and Our Own Evals; Workflow Changes They Support

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-11-22  **Backlog:** B-052 (informs B-028, B-046, B-026)  **Builds on:** [ADR-023](ADR-023-benchmark-methodology.md), [ADR-024](ADR-024-defensive-framing-and-provider-blocks.md), [ADR-030](ADR-030-more-model-providers.md)

## Context
The model that reads the code changes the product's results a great deal: in internal experiments on real open-source projects (the B-046 write-up, not yet approved for publication), the same files and the same question produced very different recall and very different shares of wrong claims from two models of the same vendor. Today the model is chosen by feel. Three questions follow:
1. How do we choose which models to offer and which to recommend?
2. How do we measure them on our own task, and why should that measurement be trusted over what the industry publishes?
3. Which changes to the scanning workflow do the measurements support?

Published cybersecurity benchmarks (for example CyberSecEval, Cybench, CyberGym and similar suites; to be confirmed and dated in B-052) mostly measure exploit-writing in capture-the-flag tasks, security knowledge questions or insecure-code generation. They are useful signals, but they are self-reported by vendors or run on differing harnesses, they use public tasks that may be in training data, and none measures our task: find the exploitable flaw, including missing checks, in a real repository without being told where to look, and report it with correct evidence.

## Decision

### 1. Two-stage model selection
- **Stage 1, shortlist.** Candidates are drawn from published cyber benchmarks, recording for every claim the benchmark and version, the date, the harness, and whether the result is vendor-reported or independent. Candidates must also pass operational filters: availability through a provider we support (ADR-030), price, refusal and guardrail behaviour on defensive security prompts (ADR-024), data handling and residency, latency, and structured-output reliability. Benchmark scores only rank the shortlist; they never select the default.
- **Stage 2, gate on our own eval** (below): the direct-question probe screens cheaply, then the real pipeline confirms. The gate measures recall on labelled flaws, the share of wrong claims, block rate, JSON failure rate, cost and time per scan.
- **Default model rule.** The default is the model with the best measured claim quality that stays within agreed cost, time and block-rate limits, re-measured whenever a model version or a provider's moving alias (`-latest`) changes. A model without a measured profile is flagged in settings. The product never switches model silently (ADR-024).
- **Per-model profile** is stored as data in the model registry (measurement date, model version, metrics) and shown in settings.

### 2. Our own evals
Five layers, cheapest first:
1. **Deterministic checks, no model:** evidence lines match the cited code (and are corrected when the quote exists elsewhere in the file), redaction placeholders are never reported as secrets, model JSON is parsed or repaired, scan coverage is reported.
2. **Detection against known flaws.** The real-code set (B-046: 3 projects, 11 labels) grows towards about 100 labels in about 20 projects. Labels come from public advisories: the fix commit's removed lines locate the flaw, a script drafts the label, and a sampled subset is signed off by the engineer. Seeded repositories stay as a regression and for exploit chains across components that real data rarely holds.
3. **Patched-version negative control.** The same project is scanned at the fixed release; a finding that still points at the fixed code is a false positive. This gives a precision signal without manual triage.
4. **Verification eval.** The triaged findings from the benchmark (each judged against the code with a strict rubric) form a labelled set for the verifier: its verdicts are compared with the triage verdicts.
5. **Impact, action and drift.** Impact statements are reviewed for consistency with the code (no invented assets); corrective actions are checked by applying the patch and running the project's tests where they exist; a small scheduled run detects change when a provider updates a model.

**Method rules (apply to every layer):**
- **Split.** Projects are divided into a development set and a held-out set (proposed 70/30 by project). Prompts and workflow are tuned only on the development set; the held-out set decides model selection and release gates.
- **Contamination.** Prefer advisories published after the model's training cutoff; record advisory date and model cutoff with every result; treat older ones as less reliable.
- **Variance.** A decision needs at least three runs per model and project; results carry confidence intervals; differences inside the interval are not claimed.
- **Scoring.** The strict, adjudicated figure is the headline; the loose location rule is reported as an upper bound and is applied identically to every tool compared.
- **Readers.** Triage and adjudication are done by model readers with a fixed rubric; the reader's model family differs from the model under test; a sample of verdicts is checked by hand and the checks are recorded.
- **Publication.** The repository is public: results, triage and judgements are published only after the engineer approves, and flaws that are not yet fixed or reported go to the maintainers first.
- **Goodhart guard.** The held-out set is never used for prompt tuning; label changes after seeing results are flagged as post hoc.

### 3. Workflow changes the evidence supports
These are delivered as part of B-028 and measured by the evals above:
- **Focused hunts** replace the single brainstorm over about 300 KB: one concrete, evidence-required question per cluster of related components, with the files chosen by the code index (B-036), in the style of the probe prompt. Generic hardening advice is excluded.
- **Access-control enumeration:** list every entry point and check each against the authorisation layer; report coverage ("N of M handlers have a check").
- **Verification stage:** each claim is checked against the code and against defences the model may not have considered before it is reported or scored.
- **Deterministic evidence checks** as in layer 1.
- **Model-aware execution:** prompt size, timeouts and retries follow the model's profile.
Scoring, finding identity and lifecycle (B-031), business-impact statements, corrective and preventive actions (B-030), actions as pull requests and tickets (B-049, B-016) and the audit trail remain. Business-impact statements are produced only for findings that pass verification and are kept apart from the technical facts, with their assumptions shown.

## Alternatives considered
- **Choose by published benchmarks alone:** cheap, but they do not measure our task and cannot be audited.
- **An LLM judge for everything:** scalable, but it shares biases with the models under test; kept only as a reader with a strict rubric and hand checks.
- **Human-only triage:** most trustworthy, but slow and costly at 100 labels; used for sign-off samples.
- **Adopt an existing evaluation framework** (for example Inspect AI) instead of the in-house harness: gains tooling and comparability, adds a dependency and a learning cost; revisit when the set outgrows `benchmarks/`.
- **Keep the workflow and only change the model:** the experiments show that the model is a large factor, but the missing-check and verification gaps are not model problems.

## Consequences
- Label creation and sign-off cost engineer time; the proposed 100-label target needs a script and a sampling plan.
- Evals cost money: the screening probe is about $0.2 to $0.5 per model for three projects, a full pipeline run about $1 to $5 per project; keys for each provider are entered by the engineer.
- Profiles go stale; the re-measurement trigger and a scheduled run are needed.
- Advisory data is public, but its licence terms must be checked before labels are published.
- Our eval is small and built by us; it is evidence for our decision, not a replacement for independent benchmarks. Publishing the method and labels and inviting re-runs is the route to credibility.
- The workflow changes are a significant part of B-028 and change what a scan costs and how long it takes; the evals are what tell us whether they pay off.

## For the engineer to decide
- The split ratio and the minimum label counts for a gate.
- The numeric limits in the default model rule (cost, time, block rate, share of wrong claims).
- Whether the eval method and labels are to be published, and when.
- Which provider keys to add for screening, and the budget.
