# 推理强度（思考深度）：厂商协议合同 — 已确认需求与任务说明

> **状态：** 已确认（2026-07-24）；调研对齐增补同日
> **范围：** Chat Composer / Agent 思考强度 / Config 模型协议合同 / 中转站 / runtime 注入
> **关联设计：** `2026-07-13-agent-provider-chat-composer-design.md` §4 / §6.3 / §8.2 / §10.3
> **调研笔记：** `Agent论文/search-results/2026-07-24-opencode-hermes-reasoning-effort-config.md`
> **实现状态：** 需求与任务边界已锁定；代码尚未按本文件改动

## 1. 一句话

思考深度是**模型级厂商协议能力**：**协议合同有则配置、投影、显示、发送；合同无则全链路不显示、不注入。**

中转站只共享连接；**每个 pin 模型自己的合同**决定是否出现深度菜单（对齐 OpenCode `provider → models → variants`，不采用 Hermes/Codex 式全局 effort 作为唯一真相）。

## 2. 确认决策

| ID | 议题 | 确认结果 |
| --- | --- | --- |
| D1 | 运营已声明 `reasoning_effort_values` + adapter 时，是否还须 probe 才显示？ | **A：直接显示**；probe 为可选取证 / re-verify，不是显示前提 |
| D2 | 无合同时，runtime 是否允许名称启发式注入 effort？ | **A：无合同绝不注入**（关闭 gpt-5 名称兜底发送） |
| D3 | Anthropic `thinking_type` 与 multi-level effort 是否同一 Composer 入口？ | **A：同一入口，分轨选项**；选项来自该协议自己的 values/label，不把 thinking 伪装成 low/medium/high |
| R1 | pin/promotion 是否按名称自动填合同？ | **否**；仅可拷贝「同 modelRef + 当前 fingerprint 已 verified」的 contract，否则合同为空 |
| R2 | 未知中转默认路径 | **能写协议就 ① 手写；不确定就 ② 单模型 probe**；两者皆无 → 不显示 |
| R3 | probe 是否一期扩展 beyond low/high + `reasoning_object`？ | **二期**；一期保持现 probe + ① 手写完整档位/adapter |

## 3. 开源调研结论（任务约束来源）

| 项目 | 配置形态 | 对 Vibelution 的取舍 |
| --- | --- | --- |
| **OpenCode** | `provider.models.X.options` + **`variants`**；自定义中转写 `npm: openai-compatible` + 每模型手写 variants；`reasoning: true` 才出现切换 | **主 ADAPT**：per-model variants ⇔ 合同 values；中转必须显式声明；无 variants 不显示 |
| **Hermes** | `agent.reasoning_effort` 全局默认；`api_mode` 随有效模型；会话 `/reasoning`；`base_url` 自定义端点 | **部分 ADAPT**：会话级改深度、wire/api_mode 跟模型重算；**不采用**全局 effort 作中转唯一真相 |
| **Codex CLI** | 全局 `model_reasoning_effort` + profile / `--config` | **REFERENCE**：会话/profile 分层可参考；**不采用**全局一把梭多模型中转方案 |
| **CC Switch** | catalog 投影 + 按平台适配 effort/thinking 字段 | **REFERENCE**：适配层思想；不把名称启发式当 confirmed |

### 3.1 OpenCode 字段映射（实现与文档统一用语）

| OpenCode | Vibelution |
| --- | --- |
| `provider.models.<id>.variants` 的键集合 | `reasoning_effort_values` |
| `options.reasoningEffort` 默认 | `default_reasoning_effort` |
| variant / options 如何编码进请求 | `reasoning_effort_adapter` + `reasoning_effort_map` |
| Anthropic `options.thinking` | `thinking_type` / `thinking_display`（与 effort **分轨**，同一 Composer 入口） |
| `reasoning: true` 且有 variants | `supportsReasoningControl = true` |
| 无 variants / reasoning 关闭 | 只显示模型名，不注入 reasoning 字段 |

等价心智模型：

```text
OpenCode:
  models."gpt-5.6-luna".variants.low/medium/high
  models."gpt-5.6-luna".options.reasoningEffort = "medium"

Vibelution:
  models."gpt-5.6-luna".defaults.reasoning_effort_values = ["low","medium","high"]
  models."gpt-5.6-luna".defaults.default_reasoning_effort = "medium"
  models."gpt-5.6-luna".defaults.reasoning_effort_adapter = "reasoning_object"
```

### 3.2 明确不照搬

- Hermes 单一 `agent.reasoning_effort` 覆盖站内全部模型
- Codex 全局 `model_reasoning_effort` 作为多模型中转方案
- 仅凭 `/models` 列表或模型名自动生成 variants/合同
- 同 Provider 一模型验证成功 → 批量给全站挂合同
- 引入 OpenCode / Hermes 运行时依赖（只 ADAPT 设计思想）

## 4. 硬原则

1. **协议驱动，不是名称驱动** — 显示与发送只认模型级协议合同。
2. **有则显、无则隐** — values 非空且 adapter ≠ `none` 且 wire/route 兼容 → 显示；否则只显示模型名。
3. **配置写协议事实** — pin defaults / 显式 capabilities；UI 只消费投影。
4. **不静默伪装** — 不把 on/off 伪装成多档；不把 `high` 显示成 `xhigh`；菜单不得出现合同外档位。
5. **发送跟 adapter** — driver 注入；Composer 不拼 payload。
6. **中转 per-model** — Provider 只拥有连接与默认 wire；推理合同挂在每个 modelRef 上。

## 5. 能力来源与显示权

```text
① 运营协议声明（pinned defaults / 显式 capabilities）  → 可显示、可发送
② 当前 fingerprint 下已验证 reasoningContract         → 可显示、可发送
③ 可信厂商静态协议表（可选，远期 registry）             → 等同①
④ 名称启发式                                          → 仅表单/探测建议，不得单独打开 UI
⑤ unknown                                             → 不显示、不注入
```

- ① 与 ② 冲突：① 覆盖档位/默认；② fingerprint 失效只影响验证状态，不抹掉 ①。
- ④ 永远不能单独打开 Composer 深度菜单（对齐 D2）。

### 显示判定

```text
supportsReasoningControl =
  reasoning_effort_values 非空
  AND adapter ≠ none
  AND 当前 wire/route 与 adapter 兼容
```

- 真：Composer 显示 `模型 · 档位`；菜单 = 合同 values 投影 label
- 假：只显示模型名；请求不带 reasoning/thinking effort 字段

Agent 槽位「思考强度」与 Composer **同源**：合同无则不显示可选档。

## 6. 中转站（relay / aggregator）任务说明

### 6.1 分层

```text
[llm.providers.<relay_id>]     ← 站：base_url、credential、discovery、默认 wire
  models.<model_key>           ← 模型：upstream_id、可选 wire_protocol 覆盖
    defaults.reasoning_*       ← 协议合同（OpenCode variants 等价物）
```

**禁止：** Provider 级统一 effort；因 Luna 验证成功给 Sol 挂合同；pin 时按 `gpt-5*` 猜合同。

### 6.2 建立合同的路径（R2）

| 路径 | 何时用 | 结果 |
| --- | --- | --- |
| ① 手写 pin defaults | 已知中转协议形态（文档/实测） | 立即显示（D1） |
| ② 单模型「验证推理」 | 未知或不信任 ① | catalog `reasoningContract`；成功则可显示 |
| ③ 静态协议表 | 远期可选 | 等同 ① |

### 6.3 中转工作流（产品与验收）

```text
1. 配置 relay Provider（URL + Key + protocols.default）
2. discovery → observed（无 effort）
3. 「固定并选择」→ pin（R1：不猜合同；仅可拷贝同模型已 verified contract）
4. ① 手写 或 ② probe 建立该 model 合同
5. 投影有 values → Composer / Agent 显示深度
6. 同站其他模型各自重复 4；未配置 → 不显示
```

图像等非对话模型（如 `image2`）：不写 reasoning 合同。

### 6.4 配置示例（运营模板，非强制每个模型）

**Responses + `reasoning: { effort }`（常见 OpenAI-compatible 中转）：**

```toml
[llm.providers.relay_openai.models."gpt-5.6-luna".defaults]
reasoning_effort_values = ["low", "medium", "high"]
default_reasoning_effort = "medium"
reasoning_effort_adapter = "reasoning_object"
```

**仅思考开关：**

```toml
reasoning_effort_values = ["off", "on"]
default_reasoning_effort = "on"
reasoning_effort_adapter = "thinking_toggle"
reasoning_effort_map = { off = "off", on = "on" }
```

**协议无思考深度：** 不写 values（或空列表）→ UI 不显示，请求不注入。

### 6.5 Adapter 与 wire 兼容（发送层）

| adapter | 典型协议语义 | 常见 wire |
| --- | --- | --- |
| `reasoning_object` | `reasoning: { effort }` | `responses`（及兼容网关） |
| `reasoning_effort` | 顶层 `reasoning_effort` | 视上游 |
| `thinking_toggle` | 布尔 / enable_thinking | chat 或 responses |
| Anthropic thinking 轨 | `thinking: { type, display? }` | `messages` 等 |
| 无合同 / adapter=`none` | 不注入 | — |

不兼容组合在投影层视为 **不支持**（不显示、不发送），配置校验可给明确错误。

## 7. 会话与 Agent 层级

```text
新 Session：Agent llmReasoningEffort → 模型 default → 合同 default
→ 写入 Session reasoning_effort 后只读 Session
```

- Composer 修改只写当前 Session，不回写 Agent（对齐 Hermes 会话 `/reasoning` 的分层，但数据源是 Session record）
- 运行中禁止改 effort
- 服务端校验必须 ∈ 合同 values
- 换模型后：新 values 不含旧档 → prune；无合同 → 清空 slot 可选档

## 8. 明确不做

- 全局单一 `model_reasoning_effort` 覆盖所有 Agent/Session
- 因同 Provider 另一模型验证成功而批量挂合同
- Composer 内切换模型
- 无合同时的名称启发式注入（D2）
- pin 时名称猜合同（R1）
- 一期扩大 probe 矩阵为 medium/xhigh 全量试探（R3 二期）

## 9. 实现任务分解（按本确认稿执行时的顺序）

> 下列为**实现工单**；完成时须满足 §10 验收。每项可独立提交，优先小步可测。

### T1 — Runtime：无合同不注入（D2）

- 关闭 / 删除 `adapters.py` 中 `adapter=none` 时对 `model_supports_gpt_reasoning_effort` 的 legacy 注入
- 单元测试：无 `reasoning_effort_values` 的 profile 请求 payload 不含 reasoning effort 字段
- 有合同 + `reasoning_object` 仍正确注入

### T2 — 投影：运营声明即可显示（D1）

- `project_reasoning_contract` / candidate 投影：`operator_override` 有 values → `supportsReasoningEffort=true`，不依赖 probe
- 来源字段可区分 `operator_override` | `verified` | `unknown`
- 测试：仅 pin defaults、catalog 空 contract 时 values 仍投影到 Session LLM options

### T3 — Agent UI 与合同同源

- `AgentCoreConfigPanel` 思考强度选项改为 candidate `reasoningEffortValues`，去掉写死 low/medium/high（无合同则隐藏）
- prune / 换模型行为与 §7 一致
- 布局/单测更新

### T4 — Composer 保持门闩、文案对齐 OpenCode 语义

- `ConversationInferenceControl`：values 空 → 只模型名（已有）
- label 严格来自合同 options；不伪装 xhigh
- （可选文案）无合同时 title 提示「当前模型未声明推理档位」

### T5 — 中转 / promotion（R1）

- promotion 写入 pin 时：默认不填 reasoning 合同
- 若 observed 存在 **同 fingerprint verified** contract，可拷入 pin defaults（单模型证据）
- 禁止名称启发式填充
- 测试覆盖：discovered 固定后无 contract；有 verified 时可拷贝

### T6 — Probe 边界（一期 / R3）

- 保留现「验证推理 low/high + reasoning_object + responses」
- 文档与 Config UI 标明：完整档位请用 ① 手写；probe 仅证明 low/high 对象形态
- 二期单开：按草稿 adapter/values 探测

### T7 — Anthropic thinking 分轨（D3，可排在 T3 后）

- 同一 inference control 入口
- 选项来自 thinking 协议轨 values/label，不混进 OpenAI multi-level 文案
- 无 thinking 合同且无 effort 合同 → 不显示

### T8 — 运营模板与 Config 引导

- `config` 示例 / 文档：中转 Responses 合同片段（§6.4）
- Config 模型行：无合同时引导「配置协议档位」或「验证推理」
- 不强制每个模型预填 values

### T9 — 日志与安全

- 继续只记 requested / effective / adapter / modelRef / providerId
- 禁止完整 prompt、完整请求体、凭据

## 10. 验收口径

| 场景 | 期望 |
| --- | --- |
| pin 已写 values+adapter | Composer 有深度菜单；无需先 probe |
| pin 无 values、catalog 无 verified contract | 只显示模型名；请求无 reasoning 字段 |
| 名称像 gpt-5 但无合同 | 不显示、不注入（D2） |
| 仅 thinking_toggle 合同 | 菜单仅合同档；无假 multi-level |
| 同站 A 有合同、B 无合同 | 仅 A 显示深度 |
| promotion 新 pin | 默认无合同，除非拷贝 verified |
| 会话改 effort | 只影响当前 Session 下一轮 |
| Agent 思考强度 | 与模型合同同源；无合同不显示假下拉 |
| 日志 | requested/effective/adapter/modelRef；无完整 body |

## 11. 与既有设计的关系

| 文档 | 关系 |
| --- | --- |
| `2026-07-13-agent-provider-chat-composer-design.md` | Provider/Agent/Session/Composer 主设计仍有效；**推理显示/中转细节以本文件为准**（D1–D3、R1–R3、OpenCode 映射） |
| `2026-07-13-agent-provider-chat-composer.md`（plan） | 实施时按本文件 §9 任务重排/补测；不新增 OpenCode/Hermes 依赖 |
| 本文件 | **需求 + 中转 + 开源对齐 + 实现工单** 的单一确认入口 |

## 12. version / refresh

- 仅文档变更：`version impact: none`；Launcher refresh：not needed
- 实现落地（T1–T9）时再单独做 version-impact 与 refresh 判定
- 普通任务 Agent 不改 `VERSION` / `CHANGELOG` / 前端 package 版本，除非发布流程明确要求
