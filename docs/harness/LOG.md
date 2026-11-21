# Delivery log

State for the feature-delivery harness. The feature list is `docs/BACKLOG.md` (the go-to-market build order at its top), not a separate `FEATURES.md`; design records are ADRs in `docs/decisions/`. One line per stage transition.

| Date | Item | Stage | Outcome |
|---|---|---|---|
| 2026-11-21 | B-044 | Close | Done, PR 15 merged |
| 2026-11-21 | B-048 phase 0 | Close | Done, PR 16 merged |
| 2026-11-21 | B-042 | Select / Design | Blocked: ADR-026 needs engineer acceptance (draft written) |
| 2026-11-21 | B-015, B-043 | Select | Blocked: ADR-027 needs engineer acceptance (draft written); B-043 also needs B-015 |
| 2026-11-21 | B-031, B-040 | Select | Blocked: ADR-019 and ADR-024 are Draft and need acceptance |
| 2026-11-21 | B-028 phase 0, B-012, B-045, B-011, B-016 | Select | Blocked by dependencies (B-031, B-015, B-043) |
| 2026-11-21 | B-046, B-048 phase 1, B-049 | Select | Blocked by dependencies (B-028 phase 0, B-015, B-043) |
| 2026-11-21 | B-047 | Select | Eligible; not started (live verification needs a valid key and a local endpoint) |
| 2026-11-21 | ADR-019, 024, 026, 027 | Design | Accepted by the engineer |
| 2026-11-21 | B-042 | Plan / Build / Verify / Review | Implemented; independent review: no critical, important findings fixed; container run unverified |
| 2026-11-21 | B-042 | Close | PR opened and merged; stays in progress for the container run and licence |
| 2026-11-21 | B-015 | Plan / Build / Verify / Review | Implemented; independent review: no critical, important findings fixed |
| 2026-11-21 | B-015 | Close | PR opened and merged |
| 2026-11-21 | B-043 | Plan / Build / Verify / Review | Implemented; independent review: no critical, important findings fixed; real private repo not tested |
| 2026-11-21 | B-043 | Close | PR opened and merged |
