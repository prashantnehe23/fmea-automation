# B-047 report

Design: [ADR-030](../../decisions/ADR-030-more-model-providers.md). Plan: [plan.md](plan.md). Date: 2026-11-22.

## Verification evidence
- `python -m pytest tests -q`: **804 passed** (about 55 new in `tests/test_more_providers.py`), in a separate worktree.
- `npm run build`: built. No browser check of the new settings block.
- Anthropic, Azure and local are verified with **fake clients only**. No live request was made to any of them.

## Acceptance criteria
- [x] Fake-client tests for request shape, key and token parameter (three of the four providers; **Bedrock not built**)
- [ ] A local endpoint runs a full scan: **open** (no local model server was run)
- [ ] A hosted provider verified live on the benchmark with the block rate: **open** (needs a key and a spend decision)
- [x] A provider is registry entries plus flags (existing AC5 test)

## Review
Fresh-subagent review. **Critical, fixed:** (1) the pricing refresh raised KeyError for models with no fallback price, which would have turned off live pricing for every model; (2) saving or checking an Azure/local key before an endpoint existed would have sent it to the SDK's default host (OpenAI). **Important, fixed:** chat refused keyless local models; changing an endpoint kept the stored key (now cleared); link-local, metadata, private (for hosted) addresses and bad ports are refused; environment endpoints get the same checks; negative, NaN or one-sided custom prices are refused; custom model ids with slashes can be removed, unknown ones return 404, built-ins cannot be removed; the "conservative price" wording was untrue for Anthropic and now says the GPT-5.1 rate may be higher or lower. Also fixed: reasoning lookup knows custom models; a local key can be added later.
Left (documented in the ADR): a host name that resolves to an internal address is not checked; a key from an environment variable follows whatever endpoint is set; no interface to remove a custom model; the providers list shows endpoints to every role; the benchmark runner does not carry endpoints for keyless local models; semantic dedup is off for the new providers.

## Release notes
- **Behaviour change:** three providers appear; unpriced models are estimated at the GPT-5.1 rate; `/api/settings/models` `key_set` now means "ready to use".
- **Migration:** none. **Rollback:** revert the merge.
- **Monitor:** provider errors from the new providers (block shapes are not classified), cost estimates for unpriced models.
