# ADR-012: User-Controlled Reasoning Level with Automatic Token Scaling

**Status:** Accepted  **Date:** 2026-10-19  **Backlog:** B-023

## Context
Reasoning models bill thinking tokens against the output limit. At the agents' fixed limits (2k-8k) Mistral Large 4 produced truncated JSON (ADR-011). Reasoning is also a cost/speed/quality trade-off the user should control. Providers expose it differently (Mistral Large 4 accepts only `none`/`high`; OpenAI offers more levels).

## Decision
1. **Generic levels** Off/Low/Medium/High in one global setting (`reasoning_level`), set in Settings next to the model.
2. **Per-model capability in the registry** (`reasoning`: API param + map from generic level to API value). The UI shows only supported levels, hides the control for models without it, and an unsupported chosen level resolves to the nearest supported level at or below it.
3. **Token multiplier per level** (1 / 1.5 / 2.5 / 4) applied to each agent's own base `max_tokens`, capped by the model's `max_output_tokens` (default 32768). The existing retry-on-truncation guard remains.
4. Evaluator cost estimates use the active model's rates.

## Alternatives considered
- Provider-native values in the UI: simpler mapping, but UI differs per model and every provider needs UI work.
- Fixed extra thinking budget per level: over-allocates small agents, under-allocates SRE.
- Per-scan setting: more control, but changes the scan API and makes cached/locked results depend on the level.

## Consequences
- A model with reasoning only works with this control once its registry entry is added; unverified models (Astra, Sol, Luna) have none and run with provider defaults.
- Multipliers are estimates; actual thinking length varies. Cost per run is still tracked by B-021 telemetry.
- Higher levels are slower (Large 4 High measured ~2x time, ~2.5x tokens on a sample prompt) and cost more.

## Implementation note (2026-11-09, B-037)
Mistral's API now rejects `reasoning_effort: "none"` for Large 4 (HTTP 400; accepted values are low, medium, high, or omitting the parameter). The registry therefore offers Large 4 only low/medium/high, and the existing resolution rule (nearest level at or below, else the lowest supported) makes the default "off" send `low`. The decision itself (generic levels mapped per model through the registry) is unchanged; this shows the benefit of keeping the mapping in data.
