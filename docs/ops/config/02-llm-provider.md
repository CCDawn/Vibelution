# 02 · LLM Provider 配置

节路径：`[llm.providers.<provider_id>]`

## 最小可用骨架

```toml
[llm]
schema_version = 2

[llm.providers.deepseek_main]
label = "DeepSeek 官方"
vendor = "deepseek"
driver = "openai"               # LiteLLM 路由族：openai | anthropic | gemini
kind = "deepseek"               # 协议/能力启发式关键
base_url = "https://api.deepseek.com"
auth_kind = "api_key"
credential_ref = "env:DEEPSEEK_API_KEY"
requires_credential = true
service_class = "official_api"
compat_mode = "native"          # native | openai | openai_compatible

[llm.providers.deepseek_main.protocols]
# default / allowed / routes 可选；不配则走 legacy 推断
# default = "chat_completions"
# allowed = ["chat_completions"]

[llm.providers.deepseek_main.discovery]
adapter = "openai_compatible"   # 或 manual
# mode / cache_ttl_seconds / include / exclude 可选

[llm.providers.deepseek_main.models."deepseek-v4-flash"]
upstream_id = "deepseek-v4-flash"
# label / defaults / compatibility / capabilities 可选
```

## 字段说明

| 字段 | 必填 | 合法值 / 说明 |
| --- | --- | --- |
| `label` | 建议 | 展示名 |
| `vendor` | 建议 | 厂商标签 |
| `driver` | 是* | `openai` \| `anthropic` \| `gemini`（LiteLLM 驱动族） |
| `kind` | 是 | `openai` `anthropic` `deepseek` `aliyun` `xiaomi` `relay` `openai_compatible` `google` … |
| `api` | 可选 | 如 `openai-completions` `openai-responses` `anthropic-messages` `deepseek-chat`；影响协议推断 |
| `base_url` | 是 | 服务根；勿带错 path |
| `auth_kind` | 是* | `api_key` \| `oauth` \| `none` |
| `credential_ref` | 密钥场景必填 | `env:VAR_NAME` 或 `none` |
| `requires_credential` | | 默认 true |
| `compat_mode` | 建议 | `native` / `openai` / `openai_compatible` |
| `service_class` | | `official_api` `aggregator` `relay` `self_hosted` `local_runtime` |
| `context_window` | 可选 | 正整数；**不要**瞎填假窗口 |
| `extra_headers` | 可选 | 中转额外头 |
| `legacy_inference_allowed` | 内部 | schema v2 严格模式会限制推断 |

\* schema v2 有钉选模型时走完整校验。

## `protocols` 子表

```toml
[llm.providers.xxx.protocols]
default = "chat_completions"
allowed = ["chat_completions", "responses"]
# routes.chat_completions = "chat/completions"   # 相对 path，仅 legacy_inference 关闭时用
```

| Wire 名 | 含义 |
| --- | --- |
| `chat_completions` | OpenAI Chat Completions 形 |
| `responses` | OpenAI Responses |
| `anthropic_messages` | Anthropic 线 id（body 现为 LiteLLM 兼容形） |
| `gemini_generate_content` | Gemini 线 id（同上） |

**注意**：`allowed` 若设置，模型显式 `wireProtocol` 必须在列表内。

## `discovery` 子表

| 字段 | 说明 |
| --- | --- |
| `adapter` | `openai_compatible` / `manual` / … |
| `mode` | 发现模式 |
| `models_url_override` | 覆盖模型列表 URL |
| `cache_ttl_seconds` | 0–86400 |
| `include` / `exclude` | 过滤 |

## 密钥

优先：

```toml
credential_ref = "env:DEEPSEEK_API_KEY"
```

| kind 默认 env（无 credential_ref 时） |
| --- |
| openai/relay/openai_compatible → `OPENAI_API_KEY` |
| anthropic → `ANTHROPIC_API_KEY`（别名 `ANTHROPIC_AUTH_TOKEN`） |
| deepseek → `DEEPSEEK_API_KEY` |
| aliyun → `DASHSCOPE_API_KEY` |
| xiaomi → `MIMO_API_KEY` / `XIAOMI_MIMO_API_KEY` |
| minimax → `MINIMAX_API_KEY` 等 |

**禁止**把真实 key 写入仓库。

## 钉选模型

```toml
[llm.providers.xxx.models."model-key"]
upstream_id = "upstream-model-id"   # 必填
label = "展示名"

[llm.providers.xxx.models."model-key".defaults]
# 可嵌套 prompt_cache / temperature 等默认，供 UI 创建 profile

[llm.providers.xxx.models."model-key".defaults.prompt_cache]
mode = "automatic"
```

`model_key` 会与 `provider_id` 组成 `model_ref`（见 03）。

## Agent 配置检查点

- [ ] `provider_id` 全局唯一
- [ ] `base_url` 可达且 path 正确
- [ ] `credential_ref` 指向存在的 env
- [ ] 至少一个 `models.*` 且含 `upstream_id`
- [ ] `kind` + `driver` 与厂商匹配（见 05）
