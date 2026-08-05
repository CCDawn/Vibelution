# LLM Protocol Chain (runtime authority)

Agent/session turn orchestration is shared. **Outbound model I/O is protocol-routed.**

**Operator 配置索引（如何写 config.toml）**：[docs/ops/config/INDEX.md](../../docs/ops/config/INDEX.md)
尤其是 [协议/缓存](../../docs/ops/config/04-llm-protocol-wire-cache.md) 与 [厂商菜谱](../../docs/ops/config/05-llm-vendor-recipes.md)。

## Layers

| Layer | Owner | Role |
| --- | --- | --- |
| `ModelProtocol` | `protocols.py` | Request contract (tools, reasoning, prefill, content shape) |
| `WireProtocol` | `protocols.py` + `protocol_resolver.py` | On-wire family id |
| `WireAdapter` | `wire/*` | Encode/decode body |
| `ProviderAdapter` | `adapters.py` | Vendor quirks (thinking, tool_choice, stream usage) |
| `prompt_cache` strategy | `payload_builder.py` | How cache is requested for the active provider |
| Dialogue chain mode | `invocation_context.dialogue_chain_mode_for_protocol` | tool_chat / reasoning_chat / responses_agent / basic_chat |

## Registered wires (can call)

| WireProtocol | Adapter | Body shape | Notes |
| --- | --- | --- | --- |
| `chat_completions` | `ChatCompletionsWireAdapter` | OpenAI chat | Default path |
| `responses` | `ResponsesWireAdapter` | OpenAI Responses | OpenAI / relay |
| `anthropic_messages` | `AnthropicMessagesWireAdapter` | OpenAI-shaped via LiteLLM | Not raw REST `/v1/messages` reimplementation |
| `gemini_generate_content` | `GeminiGenerateContentWireAdapter` | OpenAI-shaped via LiteLLM | Not raw generateContent REST |

## Cache strategies (`profile.prompt_cache.mode`)

| mode | DeepSeek | OpenAI / relay | Anthropic | Qwen |
| --- | --- | --- | --- | --- |
| `automatic` | `deepseek_automatic` (no key; prefix match) | `prompt_cache_key` (+ retention) | **top-level** `cache_control: ephemeral` | `prompt_cache_key` (compat; may be ignored) |
| `explicit_cache_control` | n/a | block markers if present | **block** `cache_control` on system/history | Qwen block markers |
| `disabled` | strip markers | strip | strip | strip |

## Product rules that affect hit rate

1. **Stable prefix first**: system + agent static must not change mid-turn.
2. **Turn Status Bar** is rewritten every iteration and must stay at **message list tail** (see `turn_status_bar.py`) so DeepSeek automatic prefix can grow with pure-append tool trails.
3. Tool **results** are never part of static agent partition by design; they only join automatic prefix if the entire prior message bytes are unchanged.

## Cleared debt (this pass)

- Missing wire adapters for anthropic/gemini → LiteLLM-compat adapters registered.
- Anthropic cache strategy name without injection → automatic top-level + explicit block markers.
- Explicit marker path only applied Qwen branch → `_apply_explicit_prompt_cache_markers` dispatcher.

## Residual debt (intentional / follow-up)

- Full native Anthropic Messages REST + tool `cache_control` on tools array (not only message blocks) if bypassing LiteLLM.
- Full native Gemini `generateContent` body (currently OpenAI-shaped via LiteLLM).
- `ProtocolPolicy.transport` remains dialogue-family (`chat_completions`/`responses`); do not conflate with `WireProtocol`.
- Other `insert_volatile_context_before_current_user` call sites can still sever prefix if content mutates mid-turn.
- OpenAI GPT-5.6+ `prompt_cache_options.ttl` vs legacy `prompt_cache_retention` generational mapping needs config audits when models change.
