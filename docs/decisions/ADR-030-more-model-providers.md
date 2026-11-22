# ADR-030: More Model Providers over the OpenAI Protocol (Anthropic, Azure OpenAI, Local); Bedrock Later

**Status:** Accepted (engineer, 2026-11-22: "OpenAI-protocol first")  **Date:** 2026-11-22  **Backlog:** B-047  **Extends:** [ADR-011](ADR-011-multi-provider-llm.md)

## Context
Enterprises ask for Azure OpenAI, AWS Bedrock, Anthropic and self-hosted models. Today only OpenAI and Mistral are registered. ADR-011 already routes every provider through the `openai` SDK and a registry; the question is whether to keep one call path or add native adapters.

## Decision
1. **Keep one call path.** New providers are registry entries (`core/providers.py`) that speak the OpenAI chat-completions protocol:
   - **Anthropic** through its OpenAI-compatibility endpoint (`https://api.anthropic.com/v1/`), fixed model list.
   - **Azure OpenAI** through the v1 route of the user's resource (`https://<resource>.openai.azure.com/openai/v1/`), used with the plain OpenAI client; the model name is the user's deployment name.
   - **Local endpoint**: any OpenAI-compatible server (Ollama, vLLM, LM Studio, a company gateway); base URL set by the user, key optional, the user's own model names, no per-token price.
2. **User-supplied endpoint and models** are stored in settings (`provider_endpoints`, `custom_models`), editable by the `settings` role only, with environment fallbacks for containers (`AZURE_OPENAI_ENDPOINT`, `LOCAL_LLM_BASE_URL`). Azure and hosted endpoints must be `https`; plain `http` is accepted only for the local provider. URLs with credentials, queries or fragments are refused.
3. **No embedding model for any of the three.** Scenario matching then relies on exact names and finding identity (B-031); embedding similarity is skipped, as ADR-011 foresaw for providers without embeddings.
4. **Unknown prices are estimates.** Anthropic models have no built-in price; the live LiteLLM refresh supplies one when it lists the model. Until then, and for custom hosted models without a user-entered price, cost uses the gpt-5.1 rate (which can be higher or lower than the real price), so that spend limits still act, and the interface flags the price as assumed. Local models cost 0.
5. **Provider quirks live in the registry:** `omit_temperature` (Anthropic rejects temperature below 1 on newer models), the token parameter name, and `stream_usage`.
6. **AWS Bedrock is a later phase** with a native adapter (boto3 and SigV4); it is not part of this change.

## What the providers' documentation says (read 2026-11-22)
- Anthropic describes its OpenAI-SDK layer as meant for testing and comparison and "not production-ready for most use cases"; it supports `max_tokens`, streaming and tools, accepts only `json_schema` response formats (the platform sends none), requires temperature 1 or none on newer models, ignores `reasoning_effort`, returns usage, and does not state embeddings.
- Azure's v1 route works with the standard OpenAI client with only a base URL and key; the page does not state the token parameter or stream-usage support for v1. We send `max_completion_tokens` and do not request stream usage; **neither is verified against a live resource**.

## Alternatives considered
- **Native Anthropic and Bedrock adapters now** (new SDKs, a second call path through streaming, tools, usage, block detection and retries): full features, but a large change touching B-040's block handling and B-042's usage counting, needing several live keys to verify.
- **LiteLLM as a gateway:** one library for many providers, but a heavy dependency in the hot path and a second place for key handling.
- **Local and Azure only:** smallest, leaves Anthropic out.

## Consequences
- Anthropic through a compatibility layer can lose features or change without notice; a native adapter remains the way out and is a registry-plus-adapter change.
- Provider-specific block shapes (B-040) for the new providers are not classified: a block from them shows as an ordinary provider error until observed.
- Anthropic and Azure behaviour is verified with fake clients only; the live runs (a hosted provider on the benchmark, a full local scan) are recorded on the backlog item when done.
- A user-set endpoint makes the server send requests to a URL an administrator chose; the `settings` role gates it. `https` is required except for local; link-local and metadata addresses are refused; hosted providers refuse private and loopback IP literals; a stored key is cleared when its endpoint changes. A host name that resolves to an internal address is not checked, and a key supplied by environment variable follows whatever endpoint is set.
