# 推理强度：运营配置模板（T8）

> 配套确认稿：`2026-07-24-reasoning-effort-protocol-contract-confirmed.md`
> 用途：中转 / 官方 pin 模型手写协议合同示例；**不强制**每个模型都有 values。

## 何时写

- 已知该模型在当前 endpoint 上支持思考/reasoning 档位
- 希望 Composer / Agent **立刻显示**档位（D1，不必先 probe）

## 何时不写

- 图像、非对话、或上游明确无 reasoning 参数
- 不确定 → 对 Responses 模型可先用 Config「验证推理 low / high」（T6：一期仅 low/high + `reasoning_object`）

## Responses 中转（OpenAI-compatible，`reasoning: { effort }`）

```toml
[llm.providers.relay_openai.models."gpt-5.6-luna".defaults]
temperature = 0.7
max_output_tokens = 128000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"
reasoning_effort_values = ["low", "medium", "high"]
default_reasoning_effort = "medium"
reasoning_effort_adapter = "reasoning_object"
```

## 顶层 `reasoning_effort` 字段

```toml
reasoning_effort_values = ["low", "medium", "high"]
default_reasoning_effort = "medium"
reasoning_effort_adapter = "reasoning_effort"
```

## 仅思考开关

```toml
reasoning_effort_values = ["off", "on"]
default_reasoning_effort = "on"
reasoning_effort_adapter = "thinking_toggle"
reasoning_effort_map = { off = "off", on = "on" }
```

## Probe 边界（T6）

| 项 | 一期行为 |
| --- | --- |
| 探测档位 | 仅 `low` + `high` |
| adapter | 固定 `reasoning_object` |
| wire | 要求 Responses |
| 成功结果 | catalog `reasoningContract` 写入 low/high |
| 完整档位 | **手写 pin defaults**（如 medium / xhigh） |

## 当前运营样例

本机 operator `config.toml` 已为 `relay_openai/gpt-5.6-luna` 写入上表 Responses 合同（2026-07-24）。

Launcher 刷新后：Config 模型行应显示「协议已声明 low / medium / high」；绑定该模型的 Session Composer 应出现档位菜单。
