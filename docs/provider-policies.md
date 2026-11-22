# Provider policies and defensive use

Providers can refuse prompts that read as offensive. This product is defensive (ADR-024): it analyses code the user
owns or is authorised to assess, to rank risk and plan fixes, and every model call says so (`core/prompt_context.py`).
When a provider blocks a request anyway, the user sees which provider, model and stage, and chooses another model;
nothing is retried with disguised wording and nothing switches model silently.

| Provider | Block shapes we classify | Official defensive-use or security-research route |
|---|---|---|
| Mistral AI | HTTP 403 `guardrail_violation` (message "Request blocked by guardrail policy", code 1920) | **Not confirmed.** The engineer must supply it from Mistral's documentation or account. |
| OpenAI | HTTP 400 with `content_filter`, `content_policy_violation` or `invalid_prompt`; `finish_reason: content_filter`; a `refusal` in the answer | **Not confirmed.** The engineer must supply it from OpenAI's documentation or account. |

Not detected: a plain-text refusal returned as a normal answer (the scan then yields few or no findings and counts as a
normal run). Providers added later (B-047) need their own row.
