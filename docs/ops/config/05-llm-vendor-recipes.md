# 05 · 厂商菜谱（复制用）

每个厂商：**供应商连接 + 钉选模型**。Profile 只写 `model_ref`。密钥一律 `env:`。调用参数和缓存写在钉选模型 `defaults`。

运行时细节：[PROTOCOL.md](../../../core/llm/PROTOCOL.md)。

---

## OpenAI 官方

```toml
[llm.providers.openai_main]
label = "OpenAI 官方"
vendor = "openai"
driver = "openai"
kind = "openai"
base_url = "https://api.openai.com/v1"
auth_kind = "api_key"
credential_ref = "env:OPENAI_API_KEY"
service_class = "official_api"
compat_mode = "native"

[llm.providers.openai_main.models."gpt-5.5"]
upstream_id = "gpt-5.5"
[llm.providers.openai_main.models."gpt-5.5".defaults.prompt_cache]
mode = "automatic"

[llm.profiles.openai_primary]
model_ref = "openai_main/gpt-5.5"
```

| 检查 | 值 |
| --- | --- |
| Wire | chat_completions 或 responses |
| Cache | automatic → prompt_cache_key |
| 注意 | GPT-5 族 temperature/tool_choice 可能被 adapter 约束 |

---

## OpenAI Responses / Relay

```toml
[llm.providers.relay_openai]
kind = "relay"
driver = "openai"
base_url = "https://your-relay.example/v1"
credential_ref = "env:VIBELUTION_LLM_MODEL_RELAY_..."
compat_mode = "openai_compatible"

[llm.providers.relay_openai.models."gpt-5.6-terra"]
upstream_id = "gpt-5.6-terra"
wire_protocol = "responses"
interaction_contract = "responses_agent"
model_protocol = "relay_responses"

[llm.providers.relay_openai.models."gpt-5.6-terra".defaults.prompt_cache]
mode = "automatic"

[llm.profiles.relay_dialogue]
model_ref = "relay_openai/gpt-5.6-terra"
```

---

## OpenCode 中转站（混合协议）

第三方中转转售 OpenCode Go/Zen 时，同一端点下模型协议不同。声明 `api` 后按模型名分流；模型级 `wire_protocol` 仍然优先。

```toml
[llm.providers.custom_opencode_relay]
label = "OpenCode 中转 / Relay"
kind = "relay"
vendor = "relay"
driver = "openai"
api = "opencode-go"            # 或 opencode-zen；用于按模型名分流
base_url = "https://your-relay.example/v1"
credential_ref = "env:VIBELUTION_LLM_MODEL_OPENCODE_RELAY_API_KEY"
compat_mode = "openai"
service_class = "relay"

[llm.providers.custom_opencode_relay.protocols]
default = "chat_completions"
allowed = ["chat_completions", "responses"]

[llm.providers.custom_opencode_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
wire_protocol = "responses"     # 显式优先；缺省时由 api 规则分流

[llm.providers.custom_opencode_relay.models."deepseek-v4-flash"]
upstream_id = "deepseek-v4-flash"
wire_protocol = "chat_completions"
```

| 检查 | 值 |
| --- | --- |
| 分流 | `api = "opencode-go"`：gpt/grok/muse-spark→responses，minimax/qwen→anthropic_messages，glm/kimi/deepseek/mimo/longcat/hy3/hy4/omen→chat_completions；`api = "opencode-zen"`：gpt/codex/grok/muse-spark→responses，claude 系/qwen→anthropic_messages，其余（含 minimax/glm/kimi/deepseek）→chat_completions |
| 显式优先 | 模型 `wire_protocol` > `api` 规则 > provider `protocols.default`；规则命中但不在 `allowed` 时回退默认 |
| 发现 | `discovery.adapter = "openai_compatible"`，发现的新模型按同一规则分流 |
| 鉴权 | `/messages`（anthropic_messages）只认 `x-api-key`，Bearer 会 401；Vibelution 传输层已按此发送 |
| 限制 | Zen 的 Gemini 走特殊路径 `zen/v1/models/{model-id}`（Google generateContent 形态），当前不支持；OpenAI 系模型可能受 Region 限制（403）；Muse Spark 仅部分区域可用 |
| 注意 | 中转站模型名与官方不一致时以实际声明 `wire_protocol` 为准；规则按官方端点表（2026-09）维护，端点变更时同步更新 |

---

## DeepSeek

```toml
[llm.providers.deepseek_main]
kind = "deepseek"
driver = "openai"
base_url = "https://api.deepseek.com"
credential_ref = "env:DEEPSEEK_API_KEY"
compat_mode = "native"

[llm.providers.deepseek_main.models.deepseek-v4-flash]
upstream_id = "deepseek-v4-flash"

[llm.providers.deepseek_main.models.deepseek-v4-flash.defaults.prompt_cache]
mode = "automatic"

[llm.profiles.deepseek_primary]
model_ref = "deepseek_main/deepseek-v4-flash"
```

| 检查 | 值 |
| --- | --- |
| Cache | **不要**塞 OpenAI key；靠前缀 |
| 观测 | `prompt_cache_hit_tokens` / miss |
| 注意 | Status Bar 必须在消息尾（代码已保证）；勿在 user 前每步改 system |

---

## Anthropic Claude

```toml
[llm.providers.anthropic_main]
kind = "anthropic"
driver = "anthropic"
base_url = "https://api.anthropic.com"
credential_ref = "env:ANTHROPIC_API_KEY"
compat_mode = "native"

[llm.providers.anthropic_main.models.claude-sonnet-4-6]
upstream_id = "claude-sonnet-4-6"
[llm.providers.anthropic_main.models.claude-sonnet-4-6.defaults.prompt_cache]
mode = "automatic"

[llm.providers.anthropic_main.models.claude-sonnet-4-6.defaults]
thinking_type = "adaptive"
thinking_display = "summarized"

[llm.profiles.claude_primary]
model_ref = "anthropic_main/claude-sonnet-4-6"
```

| 检查 | 值 |
| --- | --- |
| Wire | `anthropic_messages`（kind 推断） |
| Body | LiteLLM 兼容形，非手写完整 REST |
| Cache automatic | 请求含 `cache_control` |
| Cache explicit | system/history 文本块 ephemeral |

---

## Qwen / 阿里云

```toml
[llm.providers.aliyun_main]
kind = "aliyun"
driver = "openai"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
credential_ref = "env:DASHSCOPE_API_KEY"
compat_mode = "openai_compatible"

[llm.providers.aliyun_main.models."qwen-plus"]
upstream_id = "qwen-plus"

[llm.providers.aliyun_main.models."qwen-plus".defaults.prompt_cache]
mode = "explicit_cache_control"

[llm.profiles.qwen_primary]
model_ref = "aliyun_main/qwen-plus"
```

思考模型把 `interaction_contract` 设为 `reasoning_chat`，`model_protocol` 设为 `qwen_thinking_no_prefill`，写在钉选模型上。

---

## Google Gemini

```toml
[llm.providers.google_main]
kind = "google"
driver = "gemini"
base_url = "https://generativelanguage.googleapis.com"
credential_ref = "env:GOOGLE_API_KEY"

[llm.providers.google_main.models."gemini-3-flash-preview"]
upstream_id = "gemini-3-flash-preview"
wire_protocol = "gemini_generate_content"

[llm.providers.google_main.models."gemini-3-flash-preview".defaults.prompt_cache]
mode = "automatic"

[llm.profiles.gemini_primary]
model_ref = "google_main/gemini-3-flash-preview"
```

Wire 可为 `gemini_generate_content`；body 仍为 OpenAI 形经 LiteLLM。

---

## 小米 / MiniMax / 本地 llama.cpp

| 厂商 | kind 提示 | cache |
| --- | --- | --- |
| 小米 MIMO | `xiaomi` | automatic key 可能无效；以实测 usage 为准 |
| MiniMax | `minimax` | 首条 system；缓存弱 |
| llama.cpp | 本地 | 通常无磁盘 prompt cache 计费 |

优先保证钉选模型的 `wire_protocol`、`interaction_contract` 和工具调用正确，再谈 cache。

---

## 智谱官方 / 月之暗面 Kimi / 火山方舟豆包 / OpenRouter

内置预设（`zhipu_glm_4_7` / `moonshot_kimi_k2_5` / `volcengine_doubao_seed_1_6` / `openrouter_aggregator`），配置页添加 Provider 时直接选预设填 key 即可；静态模型条目为初始参考，实际可用模型以 discovery 自动发现为准。

```toml
[llm.providers.zhipu_main]
kind = "zhipu"
driver = "openai"
base_url = "https://open.bigmodel.cn/api/paas/v4"
credential_ref = "env:ZHIPU_API_KEY"

[llm.providers.moonshot_main]
kind = "moonshot"
driver = "openai"
base_url = "https://api.moonshot.cn/v1"
credential_ref = "env:MOONSHOT_API_KEY"

[llm.providers.volcengine_main]
kind = "volcengine"
driver = "openai"
base_url = "https://ark.cn-beijing.volces.com/api/v3"
credential_ref = "env:ARK_API_KEY"

[llm.providers.openrouter_main]
kind = "openrouter"
driver = "openai"
base_url = "https://openrouter.ai/api/v1"
credential_ref = "env:OPENROUTER_API_KEY"
```

| 检查 | 值 |
| --- | --- |
| Wire | chat_completions |
| 密钥 env | ZHIPU_API_KEY / MOONSHOT_API_KEY / ARK_API_KEY / OPENROUTER_API_KEY |
| Discovery | 建议 auto（OpenRouter 模型面最大，尤其依赖发现） |

## 一页对照

| 厂商 | kind | driver | transport | cache mode 推荐 |
| --- | --- | --- | --- | --- |
| OpenAI | openai | openai | chat 或 responses | automatic |
| DeepSeek | deepseek | openai | chat_completions | automatic |
| Anthropic | anthropic | anthropic | chat_completions* | automatic 或 explicit |
| Qwen | aliyun | openai | chat_completions | explicit_cache_control |
| Gemini | google | gemini | chat_completions* | automatic（验证） |

\* profile.transport 仍只允许 chat/responses；native wire 由 kind 解析。
