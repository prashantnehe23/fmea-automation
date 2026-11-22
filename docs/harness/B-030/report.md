# B-030 report

Design: [ADR-018](../../decisions/ADR-018-corrective-preventive-remediation.md). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **730 passed** (41 new in `tests/test_actions.py`), run in a separate worktree.
- `npm run build`: built. No browser check of the Mitigations page.

## Acceptance criteria
Met with tests: actions with kind, target, verification, owner and band; no roadmap, date or Gantt fields in code, prompts or UI sources; new evaluator rules; preventive focus by domain; remediator from corrective `code_fix` actions; old stored plans mapped; B-010 superseded. **Open:** SRE cost before and after on a real scan (needs a live run and a spend decision). The pipeline passes no root-cause domain yet (B-029), so the preventive agent decides it from the finding.

## Review
Fresh-subagent review: no critical findings. Important, all fixed:
1. The "no action without a target" rule was mostly defeated by a target fallback taken from the finding's evidence, which also gave preventive actions the vulnerable file and matched non-files: the fallback now applies to corrective actions only and matches real source extensions.
2. A failure of one agent discarded the other's result: an ordinary error now leaves that side empty (the evaluator reports it); provider blocks and spend limits still propagate.
3. The spend tracker's counter was unlocked and now meets two threads: locked. Overshoot beyond the limit can still be up to two calls in flight.
Also fixed: owner role matched by substring (DevOps became developer), a malformed stored action broke the chat tool, usage counter created before the workers copy the context.
Minor, left: urgency is fixed at scan time and does not follow later expert adjustments; an unparseable model answer gives an empty side with no explicit message; the estimate's completion tokens are probably high; the legacy Streamlit dashboard renders model text as markdown (existing pattern).

## Release notes
- **Behaviour change:** two model calls per finding (corrective, preventive) replace one; results carry `corrective` and `preventive` instead of the roadmap fields. Stored scans still load and render.
- **Migration:** none. **Rollback:** revert the merge.
- **Monitor:** SRE-stage cost per scan, evaluator issues for missing verification or preventive actions.
