# ADR-011: Multi-Provider LLM via OpenAI-Compatible Registry

**Status:** Accepted  **Date:** 2026-10-18  **Backlog:** B-022

## Context
`core/llm.py` was hardwired to OpenAI and one env-var key. Users want to choose OpenAI or Mistral models and enter their own key; more providers will follow.

## Decision
1. **Provider registry** (`core/providers.py`) plus a `provider` field per model in `core/costs.py`. Adding a provider/model is data, not code.
2. **OpenAI-compatible endpoint for Mistral** (`https://api.mistral.ai/v1`) using the existing `openai` SDK, rather than the `mistralai` SDK.
3. **Embeddings follow the provider.** Each provider declares an `embed_model` (OpenAI `text-embedding-3-small`, Mistral `mistral-embed`); scenario dedup (ADR-003) uses the active model's provider, so one key covers everything. `scenarios.embed_model` tags each stored vector; rows from a different model are never compared and are re-embedded on the next scan. Pre-existing rows are treated as OpenAI.
4. **API keys stored in `core/settings.json`** (gitignored), masked in the API/UI, with env vars as fallback.

## Alternatives considered
- Official `mistralai` SDK: native features, but a new dependency and a second call path.
- OS keyring: encrypted, but new dependency and breaks headless/Docker use.
- Env vars only: no in-app key entry.

## Consequences
- Providers not speaking the OpenAI protocol (e.g. Anthropic native) need an adapter in `call_llm`.
- Keys are plaintext on local disk; acceptable for single-user local use. B-015 (auth/multi-user) must revisit this (encrypted/secret-store).
- Per-provider quirks (token parameter name) live in the registry; other quirks (e.g. temperature restrictions) would need new registry fields.
- Model IDs use Mistral `-latest` aliases, so behaviour and price can change without code changes.
- After switching provider, semantic dedup is inactive for old scenarios until the next scan re-embeds them (exact-name locking still applies). Providers without an embeddings endpoint need an `embed_model` or a fallback.
