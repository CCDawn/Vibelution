# 03 · 钉选模型与 Profile 引用

## 谁决定用哪只模型

| 要改的事 | 改哪里 |
| --- | --- |
| 某个 Agent 的对话、心智、摘要、子代理、视觉 | 该 Agent 的 `llmBindings` 槽位。权威在 Agent 记录，不在全局 Profile |
| 上下文压缩用哪只模型 | 同一个 Agent 的 `summary` 槽。这个槽空着时，用它的对话模型 |
| 子代理规划和执行用哪只模型 | `subagentPlanning`、`subagentExecution` |
| 科研等仍独立的全局角色 | `llm.profiles.<profile_id>.model_ref` |
| 温度、超时、推理、缓存、协议 | 钉选模型的 `defaults`。只有这个角色要和模型默认不同时，才写 `overrides` |
| 地址、密钥、发现 | 供应商连接，见 [02](./02-llm-provider.md) |

Agent 槽位是 `dialogue`、`mentalModel`、`summary`、`subagentPlanning`、`subagentExecution`、`vision`。槽位里写的是模型引用 `provider_id/model_key`。已绑定的 Agent 不会因为改了 `primary` Profile 而换对话模型。

`compression`、`subagent_worker`、`subagent_explorer` 不再是模型用途。配置文件里已经写下的这些 Profile 会保留，压缩和子代理不会读它们来选模型。工具页里的 `subagent_explorer`、`subagent_worker` 是工具权限范围，和模型槽位不是一回事。

## 钉选模型

位置：`llm.providers.<provider_id>.models.<model_key>`

```toml
[llm.providers.deepseek_main.models."deepseek-v4-flash"]
upstream_id = "deepseek-v4-flash"
label = "DeepSeek V4 Flash"

[llm.providers.deepseek_main.models."deepseek-v4-flash".defaults]
temperature = 0.7
max_output_tokens = 4096
timeout = 60
connect_timeout = 30
streaming = true
tool_calling_mode = "auto"

[llm.providers.deepseek_main.models."deepseek-v4-flash".defaults.prompt_cache]
mode = "automatic"
```

`upstream_id` 是发给上游的模型 ID。模型引用是 `deepseek_main/deepseek-v4-flash`。协议写在钉选模型的 `wire_protocol`、`interaction_contract`、`model_protocol`，或由供应商 `protocols` 推导。不要把 `chat_completions` 以外的线路名写进 Profile。

## Profile 只是角色引用

公开配置里，一个 Profile 只能有这些字段：

| 字段 | 作用 |
| --- | --- |
| `model_ref` | 指向已钉选的 `provider_id/model_key` |
| `fallback` | 可选，另一条 Profile 的 id。不能指向自己 |
| `overrides` | 可选，只覆盖这个角色。允许的键与钉选模型 `defaults` 相同 |
| `label` | 可选，显示名，不参与选路 |

```toml
[llm.profiles.primary]
model_ref = "deepseek_main/deepseek-v4-flash"
fallback = "local"

[llm.profiles.primary.overrides]
temperature = 0.2
```

加载时会把钉选模型展开成运行时调用档案，再用 `overrides` 盖住。Profile 上的 `provider_id`、`model`、`transport`、`temperature` 不参与选路。保存配置时这些字段会被拒绝。文件里已经写下的旧字段不会被自动删掉，也不会改结果。

改某个全局角色用的模型：只改它的 `model_ref`。改所有使用该钉选模型的调用的默认温度：改钉选模型的 `defaults`。

## 常见错误

| 错误 | 修复 |
| --- | --- |
| 改了 `primary`，某个 Agent 的对话模型没变 | 改该 Agent 的 `llmBindings.dialogue.modelId` |
| `is not a profile reference field` | 删掉 Profile 上复制的连接或模型字段；参数放进钉选模型 `defaults` 或 `overrides` |
| `fallback references unknown profile` | `fallback` 必须是已有 Profile id |
| 模型引用不存在 | 先在供应商下钉选模型，再让 Profile 或 Agent 槽位引用它 |
