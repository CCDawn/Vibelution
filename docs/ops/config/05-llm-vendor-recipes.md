# 05 · 厂商菜谱（复制用）

每个厂商：**Provider + 钉选模型 + Profile + Cache**。密钥一律 `env:`。

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
provider_id = "openai_main"
model = "gpt-5.5"
model_ref = "openai_main/gpt-5.5"
transport = "chat_completions"   # 或 responses + protocol openai_responses
contract = "tool_chat"
[llm.profiles.openai_primary.prompt_cache]
mode = "automatic"
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

[llm.profiles.relay_dialogue]
provider_id = "relay_openai"
model = "gpt-5.6-terra"
transport = "responses"
contract = "responses_agent"
protocol = "relay_responses"   # 或 openai_responses
[llm.profiles.relay_dialogue.prompt_cache]
mode = "automatic"
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
| 分流 | `api = "opencode-go"`：gpt→responses，minimax/qwen→anthropic_messages，glm/kimi/deepseek/mimo→chat_completions；`api = "opencode-zen"`：gpt/codex→responses，claude 系/qwen→anthropic_messages，其余 chat_completions |
| 显式优先 | 模型 `wire_protocol` > `api` 规则 > provider `protocols.default`；规则命中但不在 `allowed` 时回退默认 |
| 发现 | `discovery.adapter = "openai_compatible"`，发现的新模型按同一规则分流 |
| 注意 | 中转站模型名与官方不一致时以实际声明 `wire_protocol` 为准；grok 系未做名称规则，需显式声明 |

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

[llm.profiles.deepseek_primary]
provider_id = "deepseek_main"
model = "deepseek-v4-flash"
transport = "chat_completions"
contract = "reasoning_chat"
# protocol 可省略，kind 会倾向 deepseek_reasoning
[llm.profiles.deepseek_primary.prompt_cache]
mode = "automatic"
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

[llm.profiles.claude_primary]
provider_id = "anthropic_main"
model = "claude-sonnet-4-6"
transport = "chat_completions"
contract = "tool_chat"
thinking_type = "adaptive"          # 可选
thinking_display = "summarized"
[llm.profiles.claude_primary.prompt_cache]
mode = "automatic"                  # 顶层 cache_control
# mode = "explicit_cache_control"   # 块级 breakpoint
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

[llm.profiles.qwen_primary]
provider_id = "aliyun_main"
model = "qwen-plus"
transport = "chat_completions"
contract = "tool_chat"
[llm.profiles.qwen_primary.prompt_cache]
mode = "explicit_cache_control"   # 本地/兼容常用
```

Thinking：

```toml
contract = "reasoning_chat"
# protocol = "qwen_thinking_no_prefill"
```

---

## Google Gemini

```toml
[llm.providers.google_main]
kind = "google"
driver = "gemini"
base_url = "https://generativelanguage.googleapis.com"
credential_ref = "env:GOOGLE_API_KEY"

[llm.profiles.gemini_primary]
provider_id = "google_main"
model = "gemini-3-flash-preview"
transport = "chat_completions"
contract = "tool_chat"
[llm.profiles.gemini_primary.prompt_cache]
mode = "automatic"   # 实际命中依赖端点/LiteLLM
```

Wire 可为 `gemini_generate_content`；body 仍为 OpenAI 形经 LiteLLM。

---

## 小米 / MiniMax / 本地 llama.cpp

| 厂商 | kind 提示 | cache |
| --- | --- | --- |
| 小米 MIMO | `xiaomi` | automatic key 可能无效；以实测 usage 为准 |
| MiniMax | `minimax` | 首条 system；缓存弱 |
| llama.cpp | 本地 | 通常无磁盘 prompt cache 计费 |

优先保证 **transport/contract/tools** 正确，再谈 cache。

---

## 一页对照

| 厂商 | kind | driver | transport | cache mode 推荐 |
| --- | --- | --- | --- | --- |
| OpenAI | openai | openai | chat 或 responses | automatic |
| DeepSeek | deepseek | openai | chat_completions | automatic |
| Anthropic | anthropic | anthropic | chat_completions* | automatic 或 explicit |
| Qwen | aliyun | openai | chat_completions | explicit_cache_control |
| Gemini | google | gemini | chat_completions* | automatic（验证） |

\* profile.transport 仍只允许 chat/responses；native wire 由 kind 解析。
