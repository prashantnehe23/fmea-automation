# ADR-017: Business Profile and System Map — Short Business Context, Untrusted README

**Status:** Draft; decision 3 (untrusted README handling) accepted and implemented 2026-10-19 as B-027 phase 0, the remainder awaits approval  **Date:** 2026-10-19  **Backlog:** B-027

## Context
The "Business & System Context" card mixes three things: the README's first 2,000 characters (GitHub scans store `readme_text[:2000]` as the business context), and the surveyor's lists of attack surfaces and failure domains. Users want the business context to be short and about the business. Two further problems were found in the code review:
- `ScenariosPage.jsx` renders the business context with `dangerouslySetInnerHTML`. The content comes from a repository README, i.e. untrusted input, so this is a cross-site scripting hole in the platform itself.
- The same README text is injected into every agent prompt as trusted "business context", a prompt-injection vector (the chat already treats scanned content as data, ADR-014).

## Decision
1. **Two separate artifacts.**
   - **Business Profile**: a short, structured summary distilled from the README and code signals: purpose, users, critical assets, the business-specific *catastrophic outcomes* (3-5), and criticality tier; hard-capped at roughly 90 words / 600 characters, enforced by validation with one compression retry. It is the only context shown on the main card. The user can edit it; an edit wins over generated text.
   - **System Map**: the technical inventory (entry points, trust boundaries, data stores, secrets, external calls) from ADR-015. It is data for the agents and for the coverage view, shown only in a collapsed "technical map" section with counts, not as attack-surface prose on the business card.
2. **The Business Profile defines "catastrophic" per business** and feeds severity calibration and the catastrophic pass of ADR-015.
3. **Untrusted README handling:** README text is only ever input to the profile step, delimited and marked as data; the stored profile (model output, length-capped) is what other agents see, never the raw README. Business text is rendered as plain text; `dangerouslySetInnerHTML` is removed.
4. The profile is cached per README/code fingerprint, so it is not regenerated on every scan.

## Alternatives considered
- Truncate the README harder: still raw, still untrusted, still not about business impact.
- Let the user write the profile only: accurate, but most users will not, and the scan needs it to define catastrophic outcomes.
- Keep one combined card with sections: does not address the verbosity complaint.

## Consequences
- One short extra LLM call per README/code change.
- The profile can be wrong; it is shown with its sources and is editable.
- The XSS fix (step 3) is independent of the rest and is scheduled first.
