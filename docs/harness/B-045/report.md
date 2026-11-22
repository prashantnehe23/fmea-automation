# B-045 report

Design: [ADR-028](../../decisions/ADR-028-sarif-import-export-cwe.md). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **857 passed** (about 70 new in `tests/test_sarif.py`), in a separate worktree.
- `npm run build`: built. No browser check of the import and export buttons.
- Export validated against the official SARIF 2.1.0 schema (vendored, 112 KB, from the OASIS sarif-spec repository). Import fixtures are **hand-written** from Semgrep, CodeQL and Trivy's documented shapes; those tools were not run.

## Acceptance criteria
Met with tests: ADR accepted; three tool fixtures import; same-quote and same-place merges; imported findings scored by the same stages (observed in a scan with the scripted agents; the catastrophic floor is applied inside that shared stage and is not separately tested for imports); a CWE or "unmapped" on every finding; export validates. **Not done:** real tool exports; scoring at import time; not checked in a browser.

## Review
Fresh-subagent review. **Critical, fixed:** imported findings were used once and then no longer carried, so the next scan would have called a still-reported CVE a fix candidate and a person could have closed a real vulnerability; imports now stay active and a newer report from the same tool supersedes the old one. **Important, fixed:** text was not sanitised or bounded (level, rule id and severity were unbounded); crafted files could crash (deep nesting, wrongly typed fields) or burn CPU (huge tags re-read per result); location merges could swallow a different weakness and relabel ours (now done after the root-cause stage, same CWE only, nearest wins); name clashes; imports marked used when the scan was not saved; the cache check wrote a workspace row; dotfile paths and ambiguous file names; export regions below 1 or reversed; the body limit was checked after buffering.
**Left (ADR-028 as-built):** plain-text instructions in imported rule text can still reach the scoring agents as finding fields; two simultaneous scans may both read the same pending imports; export does not carry the original rule id, `ruleIndex` or suppressions for fixed findings.

## Release notes
- **Behaviour change:** a new `imported_findings` table; every finding has `source`, `cwe` and `also_reported_by`; the root-cause stage runs before the actuary; the analyst returns a CWE.
- **Migration:** none (table created on start). **Rollback:** revert the merge; the table can stay.
- **Monitor:** imported findings per project, share of findings left `unmapped`, scans that merge imports.
