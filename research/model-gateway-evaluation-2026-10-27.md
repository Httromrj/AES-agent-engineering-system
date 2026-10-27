# Model gateway options — 2026-10-27

Status: initial desk research, not an implementation approval. Provider offerings and terms change; recheck before deployment. No VPS inspection, credentials, latency benchmark, model-quality benchmark, or real API call was available in this repository task.

## Comparison

| Option | Fit | Limits, controls, and trade-offs |
|---|---|---|
| LiteLLM Proxy | Self-hosted OpenAI-compatible gateway with multiple provider adapters, routing, retry/fallback, virtual keys, and spend controls. Offers the strongest fit when AES must own policy and observability. | Virtual keys and tracked spend require PostgreSQL; LiteLLM explicitly warns that budgets are not enforced without a database. Can redact prompts/responses from logs, but the configured provider still receives request content. Requires securing the proxy, admin key, database, migrations, and operational monitoring. |
| OpenRouter | Hosted OpenAI-compatible endpoint with broad model catalog and provider routing; low-friction way to compare models. | Its current Free tier lists 25+ free models and 50 requests/day; provider limits and individual free-model availability also apply. Free tier lacks budget controls and data-policy routing. Privacy terms say inputs are transmitted to selected/routed model providers and provider retention/training practices vary. Do not route sensitive AES content through it based solely on the gateway's own no-training statement. |
| Direct provider APIs | Smallest infrastructure and direct access to provider-specific controls and terms. | Per-provider integration, credentials, budgets, and logging; portability and centralized routing are weaker. Evaluate only providers whose data terms fit each data class. |
| Local inference | Keeps prompts on controlled infrastructure after model download; useful for explicitly local-only tasks. | Feasibility depends on the unknown VPS CPU, RAM, disk, accelerator, model size, and quality target. No server inventory or benchmark exists, so capacity and cost cannot be responsibly estimated yet. |

## Recommendation to test

Prototype LiteLLM behind a private network boundary only after inspecting the VPS. Use PostgreSQL-backed keys and budgets, secret-managed credentials, disabled content logging, a narrow model allowlist, request/time/token/concurrency limits, and an authenticated admin surface. Keep an OpenRouter adapter optional for public/non-sensitive evaluations, with provider-specific privacy checks and conservative rate limits. A local provider remains an option only if the VPS benchmark supports it. AES sensitivity screening must run before the gateway and before every fallback; gateway routing is not a substitute for that policy.

Do not expose an administrative endpoint publicly. Do not treat a zero-price model as unlimited, stable, private, or suitable for sensitive content. Free capacity and provider policies must be rechecked when configured.

## Source evidence

- OpenRouter pricing and plan feature matrix: https://openrouter.ai/pricing/
- OpenRouter support page on logging, upstream providers, and free tier limitations: https://openrouter.ai/support
- OpenRouter privacy policy on provider-specific handling: https://openrouter.ai/privacy
- LiteLLM virtual keys and PostgreSQL requirement: https://docs.litellm.ai/docs/proxy/virtual_keys
- LiteLLM Docker quickstart noting budgets are not enforced without a database: https://docs.litellm.ai/docs/proxy/docker_quick_start
- LiteLLM routing and bounded retry/fallback concepts: https://docs.litellm.ai/docs/proxy/architecture
- LiteLLM content-log redaction: https://docs.litellm.ai/docs/proxy/logging

## Next validation gate

Record the VPS OS/resources/services and secure access method; then estimate LiteLLM plus PostgreSQL footprint, review network exposure, backups and recovery, test mock routing and policy gates, compare direct/local latency and quality, and only then decide whether to install. No installation or service changes are authorized by this evaluation.
