# ADR-024: Defensive-Purpose Framing Across Providers, and Handling of Provider Blocks

**Status:** Draft (awaiting engineer approval)  **Date:** 2026-11-09  **Backlog:** B-040

## Context
The first live benchmark run (B-026) showed that Mistral Large 4 blocked 8 of 18 scans with `403 Request blocked by guardrail policy` (code 1920). The provider's stated policy blocks offensive use but allows defensive use; this product is defensive: it analyses code the user owns or is authorised to assess in order to prioritise and fix weaknesses. Several of our prompts nevertheless read as offensive. The surveyor-to-saboteur persona is "an elite red team operative ... who reasons like an attacker planning a real attack on a live production system", the verifier design asks for exploit construction (ADR-015), and the results chat explains how something is exploited. Other providers apply similar policies, so the issue is not specific to Mistral.

## Decision
1. **State the true purpose, once, for every model.** A shared defensive-context preamble is placed in every agent prompt that calls a model: defensive security review of code the user owns or is authorised to assess; the output is used to rank risk and plan fixes. It is identical across providers (model-agnostic, as ADR-011).
2. **Role wording matches what the agent does.** The attacker role-play persona is replaced with an analyst or defender persona that reasons about how a weakness could be abused. "Exploit path" is expressed as the conditions and evidence needed to reach an impact (the path-step schema of ADR-015 addendum 2), not as operating instructions.
3. **Output stays within the purpose.** Agents describe reachability, preconditions, impact and fixes. They are not asked for working exploit code, payloads or step-by-step weaponisation. The remediator, which writes fixes and tests, is unaffected. Tests enforce this on the prompt templates.
4. **Honesty rule, not evasion.** The framing must be true. No obfuscation, encoding tricks, or re-sending a blocked prompt with disguised wording. If a provider offers an official route for defensive or security-research use, we use and document that route.
5. **Provider blocks are a distinct, visible outcome.** A policy block (HTTP 403 guardrail, content-filter finish reason, refusal) is classified as `provider_blocked` with provider, model and stage. It is not retried with the same prompt. The user sees a plain message and can **choose another model** and re-run; nothing switches silently, and each result records the model that produced it. An automatic fallback model is out of scope unless approved separately.
6. **Measured.** The benchmark reports the block rate per model, and the framing change must keep recall and catastrophic recall within an agreed margin of the pre-change baseline.

## Alternatives considered
- **Leave the prompts and accept blocks:** no work, but the product is unreliable on providers with strict policies and tells users nothing useful.
- **Automatic fallback to another model:** hides a change in model, cost and data destination from the user.
- **Reword to avoid trigger terms without changing the purpose statement:** this is evasion of the provider's policy and is rejected.
- **Use only providers or self-hosted models without such policies:** narrows model choice and shifts the risk to the user's infrastructure; remains an option for the user to take.

## Consequences
- Prompts change, so results will shift; the baseline must be rerun and compared, and over-softened wording could reduce depth of analysis (hence the recall guard in decision 6).
- The claim "authorised to assess" is only as true as the user's use. Whether to ask the user for an explicit confirmation before scanning a repository is an open question for the engineer.
- New agents from B-028 should adopt the preamble from the start, so B-040 is best done before B-028 phase B even though it is not P1.
- Verification of each provider's defensive-use route has to come from the provider's own documentation or account; it is not assumed here.
