# Vibelution Prompt Assembly v2 设计与迁移方案

> Status: draft
> Date: 2026-07-27
> Owner: `agent-runtime-core`
> Scope: Prompt 装配、会话静态快照、运行时上下文、能力过滤、缓存与诊断
> Baseline: `5b7fd91336825ec3f9ef80cb064aa3a81f130679`

## 1. 目标

在保留 `COMMON / SOUL / AGENTS.md` 三核心的前提下，把当前分散在
`PromptManager`、`ContextEngine`、会话 Prompt 快照、LLM protocol route 和工具权限中的装配规则，
收敛为一份确定、可预算、可诊断、可回滚的 Prompt Assembly 合同。

成功后的可观察行为：

1. 同一模型协议、同一 Agent、同一会话静态快照下，稳定前缀保持字节级一致。
2. 当前目标、Git、日志、记忆、Agent 消息等变化只影响动态层，不破坏稳定前缀。
3. Prompt 只描述当前模型和 Agent 真正具备的工具、Skill、子 Agent 与协议能力。
4. 运行时而不是模型决定实际启用的 Prompt 组件；模型不能通过输出标签改写下一轮系统层。
5. 每轮可以看到不含正文的装配清单：来源、层级、包含/排除原因、Token、hash、缓存与信任级别。
6. 上下文超预算时按确定策略降级；受保护核心超预算或来源无效时失败关闭，不静默丢规则。

## 2. 非目标

- 不删除、合并或弱化 `core/core_prompt/COMMON.md`、`core/core_prompt/SOUL.md`、根 `AGENTS.md`。
- 不复制 OpenCode、Hermes Agent 或 Grok Build 的完整 Prompt 文本。
- 不把工具权限、安全策略或生命周期状态仅交给自然语言 Prompt 执行。
- 不在本轮重写 LLM wire protocol、ToolExecutor、记忆系统或对话历史存储。
- 不把完整 Prompt、用户内容、Secret、本地绝对路径写入公开 DTO 或 runtime scene。
- 不因为模型标称 128K/1M 上下文就默认装满窗口。

## 3. 当前事实

### 3.1 已有能力

- `core_prompt_sources.py` 是三核心名称、顺序、路径、schema 和 hash 的代码权威。
- 会话 `agentPromptSnapshot` 已能冻结三核心、公共 Prompt 和角色 Prompt，并避免实时重复注入。
- `PromptManager` 已有 section 注册、排序、静/动态边界、章节缓存、重用缓存和构建摘要。
- `ContextEngine` 已输出带有 `placement=cache_prefix|volatile_turn` 与
  `stability=agent_static|project_static|turn_dynamic` 的上下文段。
- `agent.py` 已把稳定内容合入首个 system 前缀，把动态 system context 放在历史之后、
  当前用户消息之前。
- LLM 层已有 `ModelProtocol`、`ProtocolPolicy`、能力发现、system-message policy、
  tool schema policy 和 prompt-cache partition。
- Session detail 已有 `lastContextComposition`，可作为 Prompt Inspector 的现有投影基础。

### 3.2 需要收敛的问题

1. `SystemPromptSection` 只有 `cache_break/cache_prefix` 两个布尔量，
   不能完整表达生命周期、信任、预算、能力依赖和降级策略。
2. `PromptManager` 与 `ContextEngine` 各自定义 section/segment 结构，
   同一段内容的来源、层级与缓存语义没有统一类型。
3. `<active_components>` 会在模型响应后直接修改 `_active_sections_override`，
   让模型参与下一轮系统 Prompt 选择，结果不够确定。
4. `USER_PROFILE`、`DELEGATION_RULES` 等内容虽然每轮计算，却允许进入稳定前缀；
   内容变化时会制造不可见的缓存前缀变化。
5. `LANGUAGE_AWARENESS`、`READING_RULES`、`GIT_RULES`、`SPEC_DIGEST`
   与三核心或 `docs/standards` 存在一定职责重复。
6. 当前构建摘要记录 chars、耗时和 section，但没有统一 Token 预算、信任级别、
   能力过滤原因与降级动作。
7. Provider compatibility 已在 LLM 协议层存在，但没有转化为短小、受约束的模型行为适配段。

## 4. 唯一装配模型

### 4.1 五层合同

| 层 | 名称 | 生命周期 | 典型内容 | 默认放置 |
| --- | --- | --- | --- | --- |
| T0 | `stable_core` | 项目版本级 | `COMMON`、`SOUL`、`AGENTS` | system 稳定前缀最前 |
| T1 | `protocol_adapter` | 模型协议/能力级 | tool calling、reasoning、system-message 兼容提示 | system 稳定前缀 |
| T2 | `session_snapshot` | 会话级 | Agent 角色、Prompt 模板、稳定组织上下文、允许的 Skill 索引 | system 稳定前缀 |
| T3 | `turn_context` | 回合级 | RuntimeGoal、Git、日志索引、记忆摘要、Agent 消息、环境事实 | 历史之后、当前用户前 |
| T4 | `ephemeral_overlay` | 单次调用级 | 当前 Skill 正文、检索片段、工具恢复提示、临时插件上下文 | 当前用户附近，不进入稳定 system |

当前用户消息、助手消息、tool call/result 仍属于 canonical conversation，
不是可被 PromptManager 重排的普通 section。T4 只描述附着在当前调用上的临时上下文。

### 4.2 固定装配顺序

```text
T0 COMMON
T0 SOUL
T0 AGENTS
T1 resolved protocol adapter
T2 session Agent prompt snapshot
T2 stable Agent/runtime organization context
T2 capability-filtered Skill/Agent index
completed conversation history or compacted checkpoint
T3 runtime goal and permission summary
T3 selected live context
T4 current skill/retrieval/temporary context
current user message
```

规则：

- T0 顺序永远固定，不能被 include/exclude、Agent 模板或模型输出改变。
- T1 只能表达协议和模型行为兼容，不能承载项目规则、权限授予或身份。
- T2 创建后在会话内冻结；配置变化只影响新会话或显式重建。
- T3 每轮重建，必须位于稳定历史之后，不能标记为稳定 cache prefix。
- T4 不持久化到 session system snapshot；其来源和生命周期必须可追踪。
- Tool schema 单独由实际授权结果生成，不把工具定义正文复制进 Prompt。

## 5. 共享数据合同

新增共享合同模块，推荐路径：

`core/prompt_manager/assembly_contract.py`

### 5.1 PromptSegment

```python
PromptSegment(
    key: str,
    tier: PromptTier,
    placement: PromptPlacement,
    stability: PromptStability,
    trust: PromptTrust,
    source: str,
    required: bool,
    content: str,
    content_hash: str,
    estimated_tokens: int,
    budget_tokens: int,
    cache_policy: PromptCachePolicy,
    capability_requirements: tuple[str, ...],
    decision: PromptDecision,
    decision_reason: str,
)
```

枚举最小集合：

- `PromptTier`: `stable_core / protocol_adapter / session_snapshot / turn_context / ephemeral_overlay`
- `PromptPlacement`: `system_prefix / before_current_user / conversation`
- `PromptStability`: `project_static / protocol_static / session_static / turn_dynamic / call_ephemeral`
- `PromptTrust`: `protected_core / operator_controlled / derived_runtime / untrusted_content`
- `PromptDecision`: `full / truncated / index_only / omitted / blocked`
- `PromptCachePolicy`: `cacheable / prefix_candidate / never_cache`

### 5.2 PromptAssemblyContext

装配选择只读取明确事实：

- resolved model id、provider id、`ModelProtocol`、transport；
- `LLMCapabilities` 与 `ProtocolPolicy`；
- Agent id、mode、role、session snapshot；
- 实际授权后的 tool names、Skill names、subagent/child-session 能力；
- resolved `context_window`、`max_output_tokens`；
- runtime goal、turn id、prompt mode；
- 当前会话的 legacy/v2 snapshot 状态。

模型输出不是 `PromptAssemblyContext` 的权威输入。

### 5.3 PromptAssemblyManifest

每次构建产生不含正文的 manifest：

```text
schemaVersion
assemblyMode
modelProtocol
capabilityFingerprint
permissionFingerprint
stablePrefixHash
sessionSnapshotHash
totalEstimatedTokens
budgetTokens
segments[]:
  key/tier/placement/stability/trust/source
  chars/estimatedTokens/budgetTokens/contentHash
  decision/decisionReason/cachePolicy
```

公开 DTO 必须：

- 不含 `content`；
- 不含 Secret；
- source 路径转为仓库相对标识或受控枚举；
- 默认不暴露真实 operator config 路径；
- 对 untrusted 内容只暴露类型、长度和 hash。

## 6. 来源权威

| 事实 | Canonical source | Writer | Readers / derived surfaces | 刷新/失效 |
| --- | --- | --- | --- | --- |
| 三核心内容与顺序 | `core_prompt_sources.py` + 三核心文件 | 项目治理变更 | PromptManager、snapshot builder、测试 | Git 内容/schema 变化 |
| 模型协议与能力 | resolved LLM route、model library、provider config | 配置/模型发现 | T1 adapter、tool projection、budget resolver | 模型/配置切换 |
| Agent 稳定 Prompt | `prompt_template_service` 生成的 session snapshot | 会话创建/显式重建 | T2、session detail metadata | 新会话或显式重建 |
| 工具与 Skill 可用性 | Agent tool policy + turn authorization + protocol capability | 授权服务 | tool schema、T2 index、T3 capability summary | 每回合授权决策 |
| 运行目标 | `RuntimeGoalPacket` | 当前入口/turn owner | T3、section resolver | 每回合 |
| 动态 Agent 上下文 | `ContextEngine` | 对应 service/store | T3/T4、context manifest | 每回合 |
| Prompt 装配结果 | `PromptAssemblyManifest` | Prompt assembler | runtime scene、session projection、Inspector | 每次构建 |

projection、日志和 UI 都只能投影这些来源，不能成为第二写入者。

## 7. Section 迁移映射

| 当前 section/来源 | v2 归属 | 动作 |
| --- | --- | --- |
| `COMMON / SOUL / AGENTS` | T0 | 原样保留、固定顺序、required、fail closed |
| 新 `PROTOCOL_ADAPTER` | T1 | 从 resolved `ModelProtocol + capabilities` 确定性生成 |
| `agentPromptSnapshot` | T2 | 保留冻结内容；增加独立 assembly schema/manifest 元数据 |
| `agent_runtime`、`research_organization` | T2 | 保留，统一使用共享 PromptSegment |
| Prompt 模板、角色 Prompt | T2 | 继续由 snapshot owner 生成，不再由 ContextEngine 重复构建 |
| Skills/Agents 索引 | T2 | 只列实际允许项；按预算 full → truncated → names-only |
| `RUNTIME_GOAL` | T3 | 保留 required；移除 `<active_components>` 指导 |
| `USER_PROFILE` | T2 或 T3 | 会话创建时冻结的短偏好进 T2；实时变化内容进 T3，禁止动态内容进入稳定前缀 |
| `TASK_CHECKLIST` | T3 | 保留，按当前任务相关性和预算注入 |
| `GIT_MEMORY` | T3 | 保留，只有开发/验证目标相关时注入 |
| `RUNTIME_LOG_INDEX` | T3 | 保留，只有诊断/验证目标相关时注入 |
| `CONFIG_AWARENESS` | T3 | 保留，只有配置/模型任务相关时注入 |
| `DELEGATION_RULES` | T2 | 仅 `allow_subagents` 且工具真实可用时注入；内容须会话稳定 |
| `DELEGATION_STATE` | T3 | 仅存在活动委派或恢复状态时注入 |
| `SESSION_CHILD_ROUTING` | T2 | 仅 child-session 工具可用且权限允许时注入 |
| `ENV_INFO` | T3 | 只保留 cwd/platform/date/model 等必要事实；规则文字去重 |
| `MEMORY` | T3 | 只注入目标相关摘要和来源；完整记忆按需工具读取 |
| `CODEBASE_MAP` | T2/T4 | 短索引可进 T2；详细代码上下文按需进入 T4 |
| `SPEC_DIGEST` | T3 | 替换为由 RuntimeGoal/项目规则派生的短 mode policy，避免复制规范正文 |
| `LANGUAGE_AWARENESS` | 删除独立 section | 中文默认已由三核心声明；用户本轮覆盖属于用户消息 |
| `READING_RULES` | 删除独立 section | 规则由 `AGENTS.md → docs/standards` 负责；工具能力提示由 T1/T2 负责 |
| `GIT_RULES` | 删除独立 section | 全局 Git 红线由 `AGENTS.md` 承载；当前 Git 事实留在 T3 |
| `project_agent_registry`、`agent_messages` | T3 | 保留，继续按回合动态注入 |
| 当前 Skill 正文、active skill contract | T4 | 保留在当前用户前，不进入 session snapshot |

## 8. Provider Adapter

### 8.1 选择键

适配器根据下列结构化事实选择，不按模型名称字符串猜测：

```text
ResolvedProtocolRoute.protocol
ResolvedProtocolRoute.transport
ProtocolPolicy
LLMCapabilities
tool authorization result
```

首批只覆盖现有 `ModelProtocol` 族：

- `basic_chat_no_tools`
- `openai_chat_tools`
- `openai_responses`
- `anthropic_chat / anthropic_thinking`
- `deepseek_reasoning`
- `xiaomi_mimo_*_openai_compat`
- `qwen_openai_compat`
- `qwen_thinking_no_prefill`
- `llamacpp_basic`
- `llamacpp_qwen_thinking`
- `minimax_chat`
- `relay_responses`
- 其他协议使用受控 generic adapter

### 8.2 内容边界

T1 只允许说明：

- 是否支持原生 tool calling、并行工具、结构化输出；
- 是否允许多个 system message；
- 是否禁止 assistant prefill；
- reasoning/thinking 的模型可见行为边界；
- 无工具协议下如何给出普通文本回答，以及需要工具的任务如何清楚报告能力不足。

禁止：

- 在 T1 授予工具权限；
- 根据 Prompt 声称某工具可用；
- 重复 `COMMON/SOUL/AGENTS`；
-写 provider Secret、Base URL 或私有 header；
- 为单个模型维护大段复制模板。

T1 目标上限为 512 tokens；超过即构建失败，不能截断协议规则。

## 9. 确定性组件选择

### 9.1 新 owner

由 `PromptSectionResolver` 根据以下事实产生 `PromptSelectionDecision`：

- tier 与 required；
- runtime goal/mode；
- capability requirements；
- actual tool/Skill permissions；
- session snapshot 状态；
-预算和 trust；
- section relevance signal。

### 9.2 `<active_components>` 迁移

1. 从 `COMMON.md`、`RuntimeGoalPacket.render()` 和 available-sections 文案中删除主动请求说明。
2. v2 首个兼容周期继续解析标签，但只记为 `modelRequestedComponents` 诊断信息，
   不修改 `_active_sections_override`。
3. `PromptManager.select_components()` 保留为内部兼容入口，只允许 runtime owner 调用。
4. 聚焦测试和真实会话证明没有依赖后，删除响应协议标签和 parser。

任何 required、受保护、被权限阻止或超预算 section 都不能由模型请求改变。

## 10. Token 预算

### 10.1 总预算

以已解析的真实 `context_window` 为唯一窗口来源；缺失时维持当前 fail-closed 行为。

初始默认：

```text
prompt_assembly_budget =
  min(24_000,
      max(4_000, floor(context_window * 0.18)))
```

总预算只覆盖 T0-T4 非历史上下文，不包含 canonical conversation history 和输出。
实际请求还必须预留模型配置中的 `max_output_tokens` 与压缩安全空间。

### 10.2 分层软上限

| 层 | 初始上限 | 超限动作 |
| --- | --- | --- |
| T0 | `min(6_000, max(3_000, 5% window))` | required，失败关闭 |
| T1 | 512 | required，失败关闭 |
| T2 | `min(10_000, max(2_000, 6% window))` | 先缩索引和可选组织上下文 |
| T3 | `min(8_000, max(1_000, 5% window))` | 按相关性截断/省略，记录原因 |
| T4 | 使用总预算剩余量 | 单来源截断、摘要或拒绝注入 |

额外规则：

- Skill/Agent discovery index 最多占 context window 的 1%，并受 2,000 tokens 上限约束。
- 索引降级固定为 `full description → truncated description → names only → omitted`。
- T0/T1 不允许模糊截断。
- T2 snapshot 内容超限时，新会话创建失败并指出超限来源；不能生成半个角色 Prompt。
- T3/T4 的每次截断、index-only、omitted 都进入 manifest。
- 初始比例是发布策略，不是模型事实；上线前用 16K、32K、128K 三档 golden fixtures 校准。

## 11. 信任与 Prompt Injection

| Trust | 允许层 | 规则 |
| --- | --- | --- |
| `protected_core` | T0 | 仓库受保护文件；hash/schema 校验；缺失失败关闭 |
| `operator_controlled` | T1/T2/T3 | 配置、Agent 模板、明确的管理员规则；长度和来源校验 |
| `derived_runtime` | T2/T3 | 从权威状态派生；使用结构化 renderer，不拼接无界原始对象 |
| `untrusted_content` | T4 | 用户文件、网页、导入文档、检索片段；必须隔离、标源、限长、可删除/重建 |

`untrusted_content` 不得：

- 进入 T0/T1/T2；
- 改变权限、tool schema、Prompt tier 或 cache policy；
- 被保存为 Agent 稳定 Prompt；
- 将其中的“system/developer/ignore previous”等文字解释为更高层指令。

安全验证至少覆盖：

- Markdown/HTML/script/data URI；
- 伪造 `AGENTS.md`、`<active_components>`、tool call、system 标签；
- 超长重复内容；
- 恶意路径、Secret 和本地绝对路径；
- 删除、归档、reindex 后缓存失效。

## 12. 缓存与压缩

### 12.1 缓存键

稳定前缀 partition 至少包含：

```text
model id
provider id
protocol
T0 hash
T1 hash
T2 snapshot hash
capability fingerprint
permission fingerprint
```

T3/T4、turn id、当前时间、Git dirty state、实时日志和当前用户文本不得进入稳定 partition。

### 12.2 快照兼容

- 新增独立 `promptAssemblySchemaVersion`，不滥用 `corePromptSchemaVersion`。
- 现有有效 session snapshot 的正文继续冻结，不因 v2 上线静默重写。
- 旧会话以 `legacy_session_snapshot` segment 包装，manifest 标记 `legacy=true`。
- 新会话生成 v2 snapshot。
- 只有用户显式重建、新会话或现有 invalid snapshot 修复流程才能更换正文。

### 12.3 压缩

- T0/T1/T2 在 compaction 后重新按原 hash 恢复。
- 对话压缩结果进入 conversation checkpoint，不写回 stable system。
- T3 从权威来源重建，不从旧 Prompt 文本反向解析。
- T4 默认不跨回合；确需保留的事实必须先进入有来源的会话事件或记忆候选。

## 13. Prompt Inspector

### 13.1 后端

优先复用：

- `PromptManager.get_status()`；
- `lastContextComposition`；
- session snapshot metadata；
- runtime scene `prompt_build`。

新增 sanitized `promptAssembly` manifest，而不是增加返回完整 Prompt 的调试接口。

### 13.2 UI

后续在 Prompt Center 或会话诊断面板展示：

- 总 Token/预算；
- stable prefix hash、snapshot hash、协议与能力摘要；
- 按 T0-T4 排序的 segment；
- 包含/排除/截断原因；
- cacheable/volatile；
- trust；
- legacy/v2 状态。

默认折叠 source，绝不展示 Secret 或完整 Prompt。完整正文只允许在受控本地开发工具中按单段显式查看，
且日志仍只记 hash/长度。

## 14. 迁移任务图

存在跨模块公共合同、会话兼容和用户可见诊断 DTO，采用 `TASK_GRAPH`，按下列 Critical Path 串行推进。

### Task 1：共享 contract 与无行为变化 manifest

- Owner/Boundary：`core/prompt_manager/assembly_contract.py`、`types.py`、`builder.py`、
  `context_engine.py`、聚焦测试。
- Dependency：本方案。
- Mode：BDD_TDD。
- Verification/Stop：
  - 当前 Prompt 正文与顺序保持不变；
  - PromptManager 与 ContextEngine 都能输出共享 manifest；
  - manifest 不含正文、Secret 或不受控绝对路径；
  - golden fixtures 覆盖 16K/32K/128K。

### Task 2：确定性 resolver、预算与能力过滤

- Owner/Boundary：PromptManager section resolver、ContextEngine segment filtering、
  Agent tool/Skill index renderer、测试。
- Dependency：Task 1 manifest。
- Mode：BDD_TDD。
- Verification/Stop：
  - required floor 不受 include/exclude/model output 影响；
  - disabled/no-tool profile 不注入工具指导或工具索引；
  - Skill index 按预算三档降级；
  - T3/T4 超限有确定决策和 runtime-scene 证据；
  - T0/T1 超限 fail closed。

### Task 3：Provider Adapter 与 `<active_components>` 退役

- Owner/Boundary：`provider_adapters.py`、`agent.py`、`runtime_goal.py`、
  `response_processor.py`、`COMMON.md`、协议相关测试。
- Dependency：Task 2 resolver。
- Mode：BDD_TDD。
- Verification/Stop：
  - adapter 仅由 resolved protocol/capabilities 选择；
  - Laguna/basic chat 无工具纯对话成功，需要工具时得到明确能力不足，不进入 tool loop；
  - OpenAI Responses/Chat、Anthropic、Qwen/llama.cpp 的 system-message 规则保持兼容；
  - `<active_components>` 不再改变下一轮 Prompt；
  - 一轮兼容观测后才删除 parser。

### Task 4：Session snapshot v2 与 Inspector

- Owner/Boundary：`prompt_template_service.py`、session `agent_runtime.py/projection.py`、
  API types、Prompt Center/会话诊断 UI。
- Dependency：Task 1-3 的稳定 schema。
- Mode：BDD_TDD。
- Verification/Stop：
  - 旧 session 正文不被静默重写；
  - 新 session snapshot 带 assembly schema/hash；
  - DTO 只暴露 sanitized manifest；
  - UI 能解释每段为何出现、为何被省略；
  - provider cache partition 与 manifest fingerprint 一致。

Critical Path：Task 1 → Task 2 → Task 3 → Task 4。

Task 4 的前端可以在 schema 冻结后由前端 owner 独立实现；Task 1-3 共享 Prompt 热点，不能并行写入。

## 15. 验证矩阵

### 15.1 结构与确定性

- 相同 context 连续构建：stable prefix bytes/hash 相同。
- 只改变 Git/日志/goal：仅 T3 hash 变化。
- 只改变当前 Skill：仅 T4 变化。
- 切换 Agent：T0/T1 不变，T2 与 permission fingerprint 正确变化。
- 切换模型协议：T1 与 cache partition 变化，T0 保持不变。

### 15.2 权限与能力

- tool calling disabled：无工具 schema、无工具行为指导。
- 子 Agent 禁用：无 delegation/child-session 规则和索引。
- Skill 不允许：索引与正文均不可见。
- 权限中途变化：下一回合 resolver 重算，旧 session snapshot 不授予权限。

### 15.3 预算

- 16K、32K、128K 模型窗口。
- 0、少量、大量 Skills。
- 超长 Agent 模板。
- 超长 memory/log/git/context。
- T0/T1 超限失败；T2/T3/T4 按合同处理。

### 15.4 安全

- Prompt injection 文本不能进入稳定层。
- manifest/scene/API 不含正文或 Secret。
- source path 脱敏。
- 缓存失效后旧内容不继续进入模型。

### 15.5 回归命令

实现阶段至少覆盖：

```powershell
python -m pytest `
  tests/test_prompt_manager.py `
  tests/test_prompt_cache_hit_optimization.py `
  tests/test_context_engine.py `
  tests/test_agent_protocol.py `
  tests/test_prompt_template_service.py `
  tests/test_session_workspace_isolation.py `
  tests/test_session_context_pipeline.py `
  tests/test_agent_llm_runtime.py `
  tests/test_llm_client.py -q
```

若 Task 4 修改 Web DTO/UI，再增加对应 route tests、Vitest、`tsc -b` 与 production build。

真实运行验收至少创建：

1. 一个 tool-enabled Agent 会话；
2. 一个 `basic_chat_no_tools` Laguna 会话；
3. 一个旧 snapshot 会话；
4. 一个新 v2 snapshot 会话；
5. 一次 compaction 后继续会话。

## 16. 失败检测与回滚

| 风险 | 失败信号 | 保护 | 回滚 |
| --- | --- | --- | --- |
| 稳定前缀漂移 | 同会话无关回合 stable hash 变化 | golden + runtime scene | 恢复 legacy builder |
| 工具指导与真实能力不一致 | Prompt 描述不可用工具或 capability_error | capability fingerprint + schema assertion | 关闭对应 adapter/resolver |
| 旧会话 Prompt 被重写 | snapshot hash 无显式动作变化 | legacy wrapper + snapshot test | 恢复旧 snapshot reader |
| 预算造成核心丢失 | T0/T1 truncated/omitted | required fail closed | 调高明确预算或回退 v2 |
| untrusted 内容越级 | T0-T2 出现 untrusted source | trust gate | 阻断新路径并清除派生缓存 |
| Inspector 泄露 | DTO/log 出现正文、Secret、绝对路径 | allow-list projection | 关闭 manifest public projection |

迁移期间保留 legacy builder/resolver 一个发布周期。回滚只切回 legacy 装配；
不回写 session snapshot，不重置对话，不删除 Agent 配置。

## 17. 外部参考与复用决策

复用决策：`ADAPT / REFERENCE_ONLY`。

- OpenCode：借鉴 Provider/Agent 分层、能力过滤、规则与 Skill 按需发现。
- Hermes Agent：借鉴 stable/context/volatile/ephemeral 生命周期和上下文安全。
- Grok Build：借鉴层级规则、单会话覆盖和 inspect 可观测性。
- 本地参考实现：借鉴动态 boundary、Prompt block、Skill index 预算降级。

不引入外部依赖，不复制上游 Prompt 正文。

官方来源：

- <https://opencode.ai/docs/rules/>
- <https://opencode.ai/docs/agents/>
- <https://opencode.ai/docs/skills/>
- <https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly>
- <https://docs.x.ai/build/features/project-rules>
- <https://docs.x.ai/build/features/skills-plugins-marketplaces>
- <https://docs.x.ai/developers/advanced-api-usage/prompt-caching/best-practices>

## 18. 交付判断

- 模式：`TASK_GRAPH`
- Logging：Task 1-4 都必须更新 bounded `prompt_build/prompt_snapshot/context_composition` 证据；
  只记录 id、hash、tier、reason、count、tokens、timing。
- Launcher：本规划文档阶段 `not needed`；运行代码实现后 `required before release`。
- Project memory：规划阶段记录精确 proposal；Task 1 开始实现时再更新 lane 状态。
- Version impact：规划文档为 `none`；完整 v2 若包含 Inspector DTO 与兼容新能力，建议合并评估为 `minor`。

## 19. 完成定义

只有以下条件同时成立，Prompt Assembly v2 才能标记 implemented：

- 三核心内容、顺序、保护和快照语义未退化；
- 所有 Prompt/Context 段使用同一共享合同；
- 组件选择完全由 runtime resolver、能力、权限和预算决定；
- `<active_components>` 不再影响系统层；
- Provider Adapter 只描述真实协议能力；
- stable prefix 在真实多回合中保持稳定；
- 旧会话兼容，新会话使用 v2 snapshot；
- Token 预算、安全隔离和 Inspector 有自动化及真实运行证据；
- 没有完整 Prompt、Secret 或无界上下文进入日志/API。
