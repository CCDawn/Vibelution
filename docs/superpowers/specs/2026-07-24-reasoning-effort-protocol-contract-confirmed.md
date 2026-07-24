# 推理强度（思考深度）：厂商协议合同 — 已确认需求

> **状态：** 已确认（2026-07-24）
> **范围：** Chat Composer / Agent 思考强度 / Config 模型协议合同 / runtime 注入
> **关联：** `2026-07-13-agent-provider-chat-composer-design.md` §6.3 / §8.2 / §10.3
> **实现状态：** 需求锁定；尚未按本确认稿改代码

## 一句话

思考深度是**模型级厂商协议能力**：**协议合同有则配置、投影、显示、发送；合同无则全链路不显示、不注入。**

## 确认决策

| ID | 议题 | 确认结果 |
| --- | --- | --- |
| D1 | 运营已声明 `reasoning_effort_values` + adapter 时，是否还须 probe 才显示？ | **A：直接显示**；probe 为可选取证 / re-verify，不是显示前提 |
| D2 | 无合同时，runtime 是否允许名称启发式注入 effort？ | **A：无合同绝不注入**（关闭 gpt-5 名称兜底发送） |
| D3 | Anthropic `thinking_type` 与 multi-level effort 是否同一 Composer 入口？ | **A：同一入口，分轨选项**；选项来自该协议自己的 values/label，不把 thinking 伪装成 low/medium/high |

## 硬原则

1. **协议驱动，不是名称驱动** — 显示与发送只认模型级协议合同，不因模型名像 `gpt-5*` 自动开菜单或注入。
2. **有则显、无则隐** — `reasoning_effort_values` 非空且 adapter ≠ `none` 且与当前 wire/route 兼容 → 显示；否则只显示模型名。
3. **配置写协议事实** — pin defaults / 显式 capabilities 声明档位、adapter、默认值、map；UI 只消费投影。
4. **不静默伪装** — 不把 on/off 伪装成多档；不把 `high` 显示成 `xhigh`；菜单不得出现合同外档位。
5. **发送跟 adapter** — `reasoning_object` / `reasoning_effort` / `thinking_toggle` / Anthropic `thinking` 由 driver 注入；Composer 不拼 payload。

## 能力来源与显示权

```text
① 运营协议声明（pinned defaults / 显式 capabilities）  → 可显示、可发送
② 当前 fingerprint 下已验证 reasoningContract         → 可显示、可发送
③ 可信厂商静态协议表（若后续内置 registry）             → 等同①
④ 名称启发式                                          → 仅表单/探测建议，不得单独打开 UI
⑤ unknown                                             → 不显示、不注入
```

- ① 与 ② 冲突：① 覆盖档位/默认；② 的 fingerprint 失效只影响验证状态，不抹掉 ①。
- ④ 永远不能单独让 Composer 出现深度菜单。

## 显示判定

```text
supportsReasoningControl =
  reasoning_effort_values 非空
  AND adapter ≠ none
  AND 当前 wire/route 与 adapter 兼容
```

- 真：Composer 显示 `模型 · 档位`；菜单 = 合同 values 投影
- 假：只显示模型名；请求不带 reasoning/thinking effort 字段

Agent 槽位「思考强度」与 Composer **同源**：合同无则不显示可选档（或仅无意义的隐藏）。

## 会话与 Agent 层级（沿用 07-13）

```text
新 Session：Agent llmReasoningEffort → 模型 default → 合同 default
→ 写入 Session reasoning_effort 后只读 Session
```

- Composer 修改只写当前 Session，不回写 Agent。
- 运行中禁止改 effort。
- 服务端校验必须 ∈ 合同 values。

## 明确不做

- 全局单一 `model_reasoning_effort` 覆盖所有 Agent/Session（Codex 风格全局默认不是本需求）
- 因同 Provider 另一模型验证成功而批量挂合同
- Composer 内切换模型
- 无合同时的名称启发式注入（D2=A）

## 实现时注意（非本文件验收范围）

1. 去掉 / 关闭 `adapters.py` 中无 contract 时对 `model_supports_gpt_reasoning_effort` 的 legacy 注入路径（对齐 D2）。
2. 投影层：`operator_override` 有 values 即 `supportsReasoningEffort=true`，不依赖 probe。
3. Agent 固定 low/medium/high 下拉改为消费 candidate 合同 values。
4. Anthropic thinking：同一 inference control，选项来自 thinking 协议轨。
5. 运营模板可按厂商预填示例，**不强制**每个模型都有 values。
6. 现有「验证推理 low/high」保留为 ② 取证路径。

## 验收口径（实现完成后）

| 场景 | 期望 |
| --- | --- |
| pin 已写 values+adapter | Composer 有深度菜单；无需先 probe |
| pin 无 values、catalog 无 verified contract | 只显示模型名；请求无 reasoning 字段 |
| 仅 thinking_toggle 合同 | 菜单仅合同档（如开/关），不出现假 multi-level |
| 会话改 effort | 只影响当前 Session 下一轮 |
| 日志 | requested/effective/adapter/modelRef；无完整 body |

## version / refresh

- 需求文档 alone：`version impact: none`；Launcher refresh：not needed
- 实现落地时再单独做 version-impact 与 refresh 判定
