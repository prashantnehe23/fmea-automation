# ADR-023: Scan Effectiveness Benchmark Methodology

**Status:** Draft  **Date:** 2026-10-24  **Backlog:** B-026

## Context
"More effective scans" cannot be claimed without ground truth. Today recall, false positives and catastrophic misses are invisible, and every agent change is judged by feel. Findings carry no structured location or threat class (`FailureMode` has free-text `evidence`, `trigger` and `attack_chain`), so a benchmark cannot compare them to a label by field equality.

## Decisions
1. **Seeded repositories with signed-off labels.** `benchmarks/repos/<name>/` holds a small synthetic repository and a `truth.json`. Each truth item has an id, a threat class (closed list), file and line range, a root-cause domain (ADR-016 vocabulary), a catastrophic flag, a description and match keywords. The file carries a `signed_off_by` field; the runner refuses unsigned repositories unless told otherwise. The engineer owns the labels.
2. **Pure, deterministic scorer.** `benchmarks/score.py` takes findings (plain dicts), a truth file and the repository's files, and returns metrics. It makes no LLM calls and no network calls, so it is unit-testable and its numbers are reproducible.
3. **Deterministic matching first.** A finding matches a truth item when its text (failure mode, trigger, evidence, attack chain, impact) mentions the truth file *and* at least one keyword, or at least two distinct keywords without the file. Candidate pairs are assigned one-to-one, strongest first, ties broken by truth id then finding order. Unmatched findings are false positives and are listed for audit.
4. **Semantic fallback is optional and logged.** The scorer accepts a judge callable for leftover pairs; every verdict it gives is recorded in the result. Off by default. The judge's verdicts will be cached by the runner so reruns do not move the numbers.
5. **Agents are not changed for the benchmark.** Adding structured location/threat-class fields to the scanner would alter the thing being measured; that belongs to B-028.
6. **Isolation.** Benchmark runs use a temporary database, cache and settings so they never touch the real `fmea.db`, caches or API keys' settings file (runner, phase 3).

## Metrics
Recall; precision; catastrophic recall; placement (share of caught catastrophic findings in High or Critical, relevant to B-034); evidence validity (cited file exists and the cited line is within it); root-cause agreement (only where findings carry a root cause, otherwise not reported); stability (share of truth items found in any run that are found in every run); cost, time, call count (runner).

## Alternatives considered
- LLM judge for all matching: handles paraphrase, but nondeterministic, costly, and could be biased towards the scanner's own model family.
- Structured finding fields now: clean matching, but changes the system under test and pre-empts B-028.
- Real-world repositories with known CVEs: realistic, but labels are incomplete (unlabelled real issues count as false positives) and licensing/size vary.

## Consequences
- Keyword matching can miss correct findings that are phrased differently (understates recall) and can credit vague findings (overstates it). Mitigation: audit lists of unmatched findings and unmatched truth items in every report; optional fallback.
- Synthetic repositories may be easier or different from real code; the benchmark measures relative change between commits, not absolute real-world recall.
- Labels need engineer time to review; a wrong label silently skews every later comparison.

## Addendum (2026-10-24): anchors and exploit paths
- Every truth item carries an `anchor`, a code snippet that must appear on its labelled lines, so label line numbers cannot drift silently.
- Every catastrophic item carries an expected exploit `path`: entry and sink (file plus anchor, both validated against the repository) and match terms for each end. The scorer reports `path_accuracy` (matched findings whose text names both ends) and lists `path_untraced`. This measures the goal-driven exploit tracing of ADR-015 addendum 2 rather than only whether the right vulnerability was named.
- Threat classes gained `path_traversal`.
- Precision counts any unlabelled finding as a false positive, so seeded repositories are kept small and otherwise clean; unlabelled genuine weaknesses remain a known limit.

## Addendum 2 (2026-11-09): runner
- **Scan and score are separate.** The runner stores raw findings; the report scores them offline, so corrected labels never need a repeat of paid scans.
- **What a scan sees is the real scope rule.** `select_paths` and `file_block` were extracted unchanged from the GitHub fetcher and are shared, so gaps such as Dockerfiles, Terraform, CI workflows and templates not reaching the agents (B-033) show up in the baseline instead of being hidden by a benchmark-only file list.
- **Fresh environment per scan.** The scenario registry locks the first scan's scores, so reusing one database would make runs 2..N copies of run 1 and make stability meaningless.
- **Spend is bounded per invocation** (`--max-usd`, default $12) and the result says when it stopped.
