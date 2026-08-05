# 03 · 模型钉选与 Profile

## 概念

| 概念 | 配置位置 | 作用 |
| --- | --- | --- |
| 钉选模型 | `llm.providers.<id>.models.<key>` | 目录中的可选模型 + 默认值 |
| Profile | `llm.profiles.<profile_id>` | **实际调用**用的运行档案 |
| 角色绑定 | `llm.roles` / 角色 → profile | primary / dialogue 等 |

Agent 对话一般走 **dialogue/primary profile**，不是直接写 model 字符串到代码。

## Profile 最小片段

```toml
[llm.profiles.primary]
profile_id = "primary"
provider_id = "deepseek_main"
model = "deepseek-v4-flash"          # 发给上游的模型 id
model_ref = "deepseek_main/deepseek-v4-flash"  # 推荐显式
transport = "chat_completions"       # chat_completions | responses
contract = "tool_chat"               # basic_chat | tool_chat | reasoning_chat | responses_agent
# protocol = "deepseek_reasoning"    # 可选：强制 ModelProtocol
temperature = 0.7
max_output_tokens = 4096
timeout = 60
connect_timeout = 30
streaming = true
tool_calling_mode = "auto"
strict_compatibility = true

[llm.profiles.primary.prompt_cache]
mode = "automatic"                   # 见 04
# key = ""                           # 一般留空，运行时按 partition 生成
# retention = ""                     # in_memory | 24h | 空=按策略默认

[llm.profiles.primary.retry_policy]
max_attempts = 5
backoff_base_seconds = 2.0
```

## 字段字典

| 字段 | 合法值 | 说明 |
| --- | --- | --- |
| `provider_id` | 已存在 provider | 必填关联 |
| `model` | 上游 id | 与钉选 `upstream_id` 一致 |
| `model_ref` | `provider/model_key` | UI/角色引用 |
| `transport` | `chat_completions` \| `responses` | **仅这两种**；不是 wire 全集 |
| `contract` | `basic_chat` `tool_chat` `reasoning_chat` `responses_agent` | 对话链模式提示 |
| `protocol` | 空或 ModelProtocol 名 | 如 `openai_responses` `deepseek_reasoning` `anthropic_chat` |
| `temperature` | 0–2 | GPT-5 族可能被 adapter 强制 1.0 |
| `max_output_tokens` | >0 | |
| `timeout` / `connect_timeout` | >0 秒 | |
| `streaming` | bool | |
| `thinking_type` | `""` `adaptive` `disabled` | Anthropic 等 |
| `thinking_display` | `""` `summarized` `omitted` | |
| `reasoning_effort` | 厂商相关 | OpenAI Responses |
| `reasoning_effort_adapter` | `""` `reasoning_object` `reasoning_effort` `thinking_toggle` `none` | **禁止靠模型名瞎猜**（D2） |
| `reasoning_effort_values` | list | 合同允许值 |
| `supports_image_input` | bool/null | 是否确认支持图 |
| `compat` | object | 覆盖协议 compat 提示 |

## Prompt Cache 子表（profile 或 model.defaults）

见 [04](./04-llm-protocol-wire-cache.md)。

```toml
[llm.profiles.primary.prompt_cache]
mode = "automatic"   # disabled | automatic | explicit_cache_control | unsupported
key = ""
retention = ""       # "" | in_memory | 24h
```

## 角色绑定（示意）

具体键名以当前 `config.toml` / UI 为准，常见模式：

```toml
# 角色 → profile_id（示例，以实际 schema 为准）
# [llm.roles]
# primary = "primary"
# dialogue = "primary"
```

改对话模型：改 **角色绑定的 profile** 的 `provider_id` + `model`，不要只改钉选目录。

## 常见错误

| 错误 | 修复 |
| --- | --- |
| `transport` 写成 `anthropic_messages` | transport 只能 chat/responses；wire 由 kind/api 解析 |
| `contract=tool_chat` 但 `protocol` 禁 tools | 与 ModelProtocol 冲突 |
| 有 thinking 却用 basic_chat | 用 reasoning_chat / 正确 protocol |
| model 与 upstream_id 不一致 | 对齐二者 |
