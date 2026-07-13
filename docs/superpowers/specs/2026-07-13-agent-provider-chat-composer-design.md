# Agent 固定模型、多模型 Provider 与 Codex Composer 设计

**Status:** approved / pending-spec-review
**Date:** 2026-07-13
**Owner:** model-config-governance + web-workbench-surface
**Task tier:** HIGH_RISK
**Version impact:** minor candidate（本设计阶段不修改版本文件）

## 1. 设计结论

本设计采用用户已批准的组合方案：

1. 一个中转站对应一个稳定 Provider；Provider 统一拥有 endpoint、凭据引用、协议和动态模型目录。
2. Agent 是独立主体，固定绑定一个主对话模型；普通对话框不能切换模型。
3. Agent 设置页可以从中转站动态发现的模型目录中选择模型；首次选择尚未固定的模型时，系统完成“固定模型 + 绑定 Agent”的受控变更。
4. Agent 记录默认推理强度；当前会话可以覆盖推理强度，且不会影响其他会话。
5. 主对话工作台使用 Codex 风格 Composer；进化和自进化中的嵌入式对话保持现有紧凑外观。
6. 当前被拆分的 Ai-Pixel Provider 通过有预览、备份、引用迁移、验证和回滚的迁移流程收敛为一个 Provider，不直接删除或覆盖。

复用决策为 `ADAPT + REFERENCE_ONLY`：

- 参考 OpenCode 的 `provider -> models -> variants`、`provider_id/model_id` 和 Agent 固定模型结构；
- 参考 Hermes 对 OpenAI-compatible endpoint 的 `/models`、`/v1/models` 动态发现和短期缓存；
- 保留 Vibelution 已有 schema v2、Provider discovery、catalog、pinned model、modelRef 和引用扫描实现；
- 不引入 OpenCode、Hermes 或新的第三方运行时依赖，不复制外部实现。

## 2. 与相邻设计的边界

本设计补充但不取代以下现有规格：

- `2026-07-13-codex-chat-frontend-alignment-design.md` 继续拥有 canonical transcript、错误单元、消息层级和整体 Chat 响应式布局；本设计只拥有 Composer 外观和模型/强度控件。
- `2026-07-13-config-settings-console-refactor.md` 继续拥有 `/config` 的整体信息架构和设置页布局；本设计只拥有 Provider 模型目录如何进入 Agent 配置的行为契约。
- `2026-07-13-compact-quick-provider-setup-design.md` 继续拥有快速配置流程；本设计不改变快速配置的检测、确认和保存门禁。
- `2026-07-12-llm-v2-migration-recovery-design.md` 继续拥有 schema v2 迁移恢复和 API Key 编辑；本设计复用其备份、引用扫描、确认和回滚原则。

明确不做：

- 不重写 canonical transcript、SSE、消息存储或工具调用链；
- 不让普通对话框切换 Luna、Sol、Terra 等模型；
- 不把动态发现到的所有模型无条件写入 operator config；
- 不静默切换备用模型或把失败模型自动替换成另一个模型；
- 不新增语音输入链路，不显示无实际功能的麦克风按钮；
- 不修改图片生成、音频、视觉等专用模型的业务调用方式；
- 不推送远端、不创建 PR、不调整版本号。

## 3. 已确认现状

### 3.1 已有能力

当前 schema v2 已经具备：

- `ProviderConfig.models`，一个 Provider 可拥有多个 pinned model；
- `providerId/modelKey` canonical modelRef；
- 独立保存真实 `upstream_id`，避免把展示 ID 与上游请求 ID 混为一体；
- OpenAI-compatible `/models` 与 `/v1/models` 发现；
- Provider catalog 缓存、include/exclude、发现状态与 capabilities；
- pinned model 的新增、删除和引用冲突检查；
- Agent `llmBindings` 与 dialogue/summary/vision 等 slot；
- 模型级推理强度能力和前端选项投影。

### 3.2 当前断点

Agent 模型选择器只读取 `list_llm_model_options()` 产生的已固定模型。动态 catalog 虽然能展示在 Provider 管理中，却不会进入 Agent 选择目录。因此“发现成功”不等于“Agent 可选择”。

2026-07-13 的脱敏检查结果：

- `ai-pixel`：`service_class=relay`，发现 20 个模型，但只固定了 `image2`；
- 发现目录包含 `gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra` 等模型；
- `ai-pixel_ad214f09`：同一站点的 `/v1` 形式，单独固定 `gpt-5.6-luna`；
- 同一逻辑中转站被拆成两份 Provider，Agent 绑定和完整发现目录不在同一个 Provider 下。

## 4. 外部参考结论

### 4.1 OpenCode

OpenCode 对自定义 Provider 使用稳定的 Provider key 保存 `baseURL`、凭据和协议，在 `provider.models` 下声明多个模型。完整模型 ID 是 `provider_id/model_id`，Agent 直接绑定这个完整 ID。模型可以拥有独立的 `options` 和 `variants`，推理强度属于模型/variant，而不是整个中转站的统一属性。

参考：

- https://opencode.ai/docs/providers/
- https://opencode.ai/docs/models/
- https://opencode.ai/docs/agents/
- https://github.com/anomalyco/opencode/blob/dev/LICENSE

### 4.2 Hermes

Hermes 对命名 custom provider 保存 endpoint 和凭据，可从 `/models` 或 `/v1/models` 动态发现模型并短期缓存。交互选择以 Provider 和模型共同确定目标。其配置目录、实时目录和内置目录存在多源合并，官方仓库已有目录不一致问题，因此 Vibelution 只参考动态发现，不复制多事实源行为。

参考：

- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md
- https://github.com/NousResearch/hermes-agent/blob/main/agent/model_metadata.py
- https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/model_switch.py
- https://github.com/NousResearch/hermes-agent/issues/6799
- https://github.com/NousResearch/hermes-agent/blob/main/LICENSE

## 5. 单一事实源

| 事实 | Canonical source | Writer | Readers / derived surfaces | 刷新或失效规则 | 旧来源处理 |
| --- | --- | --- | --- | --- | --- |
| Provider endpoint、协议、凭据引用 | operator `config.toml` 的 `llm.providers.<providerId>` | Config provider service | runtime projection、设置页、discovery | 保存后重载；endpoint/credential 变化使旧 catalog fingerprint 失效 | 重复 Provider 经迁移删除 |
| 动态发现目录 | model catalog state | Provider discovery service | Provider 管理、Agent candidate projection | TTL、手动刷新、fingerprint 变化 | 仅作派生目录，不能覆盖 pinned config |
| 可运行的固定模型 | `llm.providers.<providerId>.models.<modelKey>` | Provider config service / promotion coordinator | runtime model library、Agent binding validation | operator config 保存后重载 | 不再从临时 catalog 直接运行 |
| Agent 固定主模型 | Agent `llmBindings.dialogue.modelId` | Agent config service | Agent runtime、Agent 设置、Composer read-only label | Agent 设置保存后下一轮生效 | 会话接口不再写 modelId |
| Agent 默认推理强度 | Agent metadata `llmReasoningEffort.dialogue` | Agent config service | 新会话初始化 | Agent 设置保存后只影响未来新会话 | 明确定义现有字段为 default，不再作为会话当前值 |
| 当前会话推理强度 | Session `reasoningEffort` | Session creation / reasoning selection service | Composer、下一轮 runtime | 创建时复制默认值，之后只在当前会话修改 | 不再回写或动态继承 Agent metadata |
| 单轮实际模型与强度 | run/turn immutable metadata + bounded logs | turn runtime | 历史详情、诊断、验收 | 单轮创建后不可变 | 不从当前 Agent/Session 设置反推历史 |

禁止双写：

- 会话强度变更不得同时写 Session 和 Agent；
- Agent model binding 不得复制 Provider endpoint 或凭据；
- catalog 不得以后台刷新方式覆盖 pinned model 的人工 label、capabilities 或 defaults；
- 历史回合不得根据后来修改的 Agent 配置重新标注。

## 6. Provider 与模型身份

### 6.1 Provider 身份

一个逻辑中转站使用一个用户可识别、长期稳定的 `providerId`，例如 `ai-pixel`。Provider 统一拥有：

- `base_url`；
- `credential_ref`；
- `service_class=relay`；
- driver、protocols 和 compatibility；
- discovery adapter、TTL、include/exclude；
- pinned models。

不得因为 `base_url` 是否包含尾部 `/v1`、模型不同或 API Key 环境变量名不同，就自动创建第二个 Provider。是否合并必须经过显式预览，因为路径和 credential ref 可能具有真实语义差异。

### 6.2 模型身份

每个模型保留三个不同概念：

- `modelRef = providerId/modelKey`：Vibelution 内部稳定引用；
- `modelKey`：Provider 范围内稳定、安全的配置 key；
- `upstreamId`：请求发送给中转站的精确模型 ID，不进行展示性改写。

安全的 upstream ID 可以直接生成 modelKey；包含 `/`、空格、超长或不安全字符时，继续使用已有 `make_model_key()` 的 slug + hash 规则，防止碰撞。任何 UI 都显示 label/upstreamId，不要求用户理解 hash 后的 modelKey。

### 6.3 能力与 slot 兼容

Provider 的所有发现模型都进入 Agent 配置目录，但按当前 slot 决定可选择性：

- dialogue：需要文本输出和对话兼容；有工具能力时优先；
- vision：需要图片输入能力；
- image generation、audio、realtime 等非 dialogue 模型在 dialogue 列表中可见但禁用，并显示原因；
- capability 为 unknown 时允许用户先执行模型验证；未经验证不得伪装成 confirmed。

## 7. 动态目录进入 Agent 选择器

### 7.1 Candidate projection

Agent 配置接口返回按 Provider 分组的统一 candidate list：

```text
pinned models UNION observed catalog models
-> provider/model identity normalization
-> slot compatibility projection
-> verification / stale / availability projection
-> stable sorting and search
```

每个 candidate 至少包含：

- `providerId`、`providerLabel`；
- `modelRef`、`modelKey`、`upstreamId`、`label`；
- `source = pinned | discovered | both`；
- `availability`、`verificationStatus`、`catalogStale`；
- `slotCompatibility` 与 disabled reason；
- capabilities、context window、reasoning effort values/default/source。

同一个 `modelRef` 只出现一次。pinned 配置优先于 catalog 的 label/default/capability override；catalog 只补充未声明信息和实时 availability。

### 7.2 首次选择 discovered model

选择尚未固定的 discovered candidate 时，使用一个受控 promotion coordinator：

1. 重新读取 operator config 和 catalog，拒绝未保存的 Config 草稿、stale base hash、未知 Provider、已消失模型或不兼容 slot；
2. 从 `upstreamId` 生成 modelKey/modelRef，并准备 pinned model；
3. 向用户确认 Provider config 变更和 Agent binding 变更；该确认即“固定并选择”的明确写入授权；
4. 创建 operator config 备份并以原子替换方式写入 pinned model；
5. 重载并验证新 modelRef 可解析；
6. 更新 Agent `llmBindings.<slot>.modelId`；
7. 若 Agent 更新失败，恢复 operator config 备份并重载；
8. 只有两部分都成功才返回 `completed`。

失败时不得留下“Agent 已绑定但模型未固定”的悬空引用。若 config rollback 自身失败，返回 `partial/rollback_failed`，保留备份和 manifest，并阻止继续发送。

已经 pinned 的模型只更新 Agent binding，不重复写 operator config。

如果 `/config` 存在未保存草稿，Agent 设置不得绕过草稿直接写 operator config；应提示先保存或放弃草稿，再重新执行“固定并选择”。

### 7.3 不自动固定全部发现模型

discovery refresh 只更新 catalog，不批量写入 `provider.models`。原因：

- 大型中转站可能返回数百个模型；
- 模型上下线不应造成 operator config 大量 churn；
- pinned inventory 应表达用户实际选择或明确管理的模型；
- 失效 catalog 不能删除仍被 Agent 引用的 pinned model。

## 8. Agent 固定模型与推理强度

### 8.1 Agent 固定模型

- Agent 设置页是模型变更的唯一普通入口；
- 保存后 `llmBindings.dialogue.modelId` 指向 pinned canonical modelRef；
- 同一 Agent 的后续新轮次使用当前固定模型；
- 历史轮次保留自己的 immutable model snapshot；
- 想长期同时使用 Luna、Sol、Terra，应创建或克隆不同 Agent，或明确修改 Agent 设置，而不是在 Composer 中临时切模型。

### 8.2 推理强度层级

新会话初始化顺序：

```text
Agent llmReasoningEffort dialogue default
-> pinned model default
-> provider/model capability default
```

初始化结果立即写入 Session `reasoningEffort`。从此以后，运行时只读取 Session 的 confirmed value；修改 Agent 默认值不会改变任何已经存在的会话。旧会话缺少该字段时，在下一次提交前由兼容迁移按上述顺序补写一次，不能在每轮动态继承。

用户在 Composer 中修改强度时：

- 只写当前 Session；
- 从下一轮开始生效；
- 不影响同 Agent 的其他 Session；
- 运行中禁止修改；
- 服务端验证该值属于固定模型支持的 reasoning effort values；
- 保存失败时前端恢复已确认值，不保留 optimistic 假状态。

会话 API 收敛为只修改 `reasoningEffort`。现有通过 session endpoint 同时修改 `modelId` 和 Agent metadata 的行为必须移除。

### 8.3 无声降级禁止

固定模型不可用时返回明确 provider/model 错误，不自动切换其他模型。未来若增加 fallback，必须：

- 用户或 Agent 配置显式启用；
- 每轮记录 requested/effective model；
- 前端明确显示 degraded/fallback；
- 不把 fallback 报告成普通成功。

本设计不实现 fallback。

## 9. Agent 设置页模型选择

Agent 模型选择器按 Provider 分组，提供搜索和状态筛选。默认行显示：

```text
Luna 5.6
Ai-Pixel · gpt-5.6-luna · 已发现/已固定 · 支持低/中/高
```

交互规则：

- pinned、discovered、stale、unverified、unavailable 使用文字和非颜色标识；
- incompatible 模型可见但不可选，并解释需要的 slot/capability；
- discovered candidate 首次选择时按钮文案为“固定并选择”；
- promotion pending 期间禁止重复提交和离开当前变更；
- promotion 成功后 candidate 变为 pinned，Agent 当前模型同步更新；
- promotion 失败保持原 Agent binding，不关闭选择器，展示可操作错误；
- 列表支持长 upstream ID、数百模型、Provider 折叠和键盘导航。

## 10. Codex 风格 Composer

### 10.1 应用范围

共享 `ConversationView` 增加显式 Composer appearance/variant。只有 `ChatConversationComposerBridge` 传入 `codex`；EvolutionRoute 和 SelfEvolutionTrack 使用默认 compact variant。禁止依靠路由外层 CSS 猜测 DOM。

### 10.2 结构

主对话 Composer 是一个完整圆角容器：

```text
┌────────────────────────────────────────────────────────────┐
│ 多行输入区                                                  │
│                                                            │
│ ＋  [真实权限/模式状态]            Luna 5.6 · 高   [发送]   │
└────────────────────────────────────────────────────────────┘
```

- 上层为无独立边框的 textarea；
- 附件、引用、编辑状态、错误和 slash suggestions 在容器内部形成独立层；
- 下层 toolbar 左侧为附件与真实状态，右侧为固定模型、推理强度和发送/停止；
- 不展示无法从真实权限状态得出的“完全访问”；
- 不展示没有回调和业务链路的麦克风按钮。

### 10.3 模型与强度控件

关闭态显示 `模型短名 · 强度`，例如 `Luna 5.6 · 高`：

- 模型名只读；
- 点击只打开 reasoning effort menu；
- 不显示 models panel，不接收 modelId 变更；
- 不支持推理强度时只显示模型名且无 chevron；
- effort label 严格来自 capability contract；支持 `xhigh` 时显示“最高”，只有 `high` 时显示“高”，不得把 high 伪装成 xhigh。

### 10.4 尺寸和主题

桌面：

- 居中宽度 `min(100%, 960px)`；
- 默认高度约 120px，圆角 24px；
- textarea 默认两行，最大约 220px，随后内部滚动；
- toolbar 约 40px；
- 次级操作最小 32px；
- 发送/停止按钮 36x36px；
- 使用 VUI surface/border/foreground/focus/shadow token，不写死浅色截图值。

窄屏 `<720px`：

- 圆角约 18px；
- 隐藏权限长说明和低优先级文案；
- 模型名可截断，effort 和发送按钮始终可见；
- 不产生视口级横向滚动。

### 10.5 状态

- empty：发送禁用；
- text/attachment/reference present：发送启用；
- running：原位切为停止按钮，effort control 禁用；
- effort pending：原位轻量 loading，失败恢复 confirmed value；
- drag active：整个 shell 高亮；
- edit/rerun：编辑条位于内部上方，toolbar 不跳位；
- long content：textarea 自增长到上限后内部滚动；
- dark/light：边界、焦点、disabled 和 error 均可辨识。

## 11. Ai-Pixel Provider 合并迁移

迁移目标是将 `ai-pixel` 和 `ai-pixel_ad214f09` 收敛到用户确认的 canonical `ai-pixel`，但不通过改变全局 endpoint normalization 自动合并。

迁移流程：

1. 读取两份 Provider、catalog、pinned models、profiles、Agent bindings、工具/Git 引用和 credential refs；
2. 生成 preview，展示 canonical endpoint、canonical credential ref、待复制模型、待重写 modelRef、live/historical 引用和冲突；
3. 用户确认后创建 operator config 备份和 migration manifest；
4. 在 canonical Provider 中补齐 Luna 等仍被引用的 pinned model；
5. 将 live modelRef 从旧 Provider 重写到 canonical Provider；
6. 保留 historical run snapshot，不重写历史事实；
7. 重新发现 canonical Provider，验证 Luna、Sol、Terra 等目录；
8. 执行 Luna 最小真实调用，并在能力支持时验证 effort；
9. 旧 Provider live reference 归零后删除旧 Provider；
10. 任一步失败恢复备份，重载配置并记录失败阶段。

credential ref 不能仅凭环境变量名推断为同一 secret。preview 必须明确选择 canonical credential ref；日志和 manifest 只记录 ref，不记录 secret。

## 12. API 与组件边界

### 12.1 后端职责

- Provider discovery：只拥有 catalog 刷新；
- Agent model candidate service：合并 pinned + catalog 并投影 slot compatibility；
- Model promotion coordinator：拥有 discovered -> pinned + Agent binding 的受控变更与补偿；
- Agent directory/config service：拥有固定 modelRef 与 Agent effort default；
- Session service：只拥有当前 Session effort override；
- Agent runtime：解析 fixed model + effective effort，写 immutable run snapshot；
- Migration service：拥有重复 Provider 预览、应用、回滚和 manifest。

### 12.2 前端职责

- Agent 设置模型选择器：Provider 分组、搜索、状态、promotion UX；
- Composer inference control：read-only model + session effort menu；
- ConversationView：只负责 variant shell 和现有交互编排；
- Chat route/bridge：只选择 `codex` variant，不复制 Composer；
- Evolution/SelfEvolution：继续使用 compact variant。

## 13. 错误和恢复

| 场景 | 用户可见结果 | 状态保护 |
| --- | --- | --- |
| discovery 失败但有旧 catalog | 显示 stale catalog 和失败原因 | 不删除 pinned models，不伪装 fresh |
| discovery 无 catalog | Provider 显示 unavailable，允许手工 pin/重试 | Agent 原 binding 不变 |
| candidate 在选择前消失 | 提示刷新目录 | 不写 config/Agent |
| promotion config 写入失败 | 显示保存失败 | Agent binding 不变 |
| config 成功、Agent 更新失败 | 显示 rollback 中/失败 | 自动恢复 config；失败则 partial + manifest |
| effort 不受支持 | 服务端 4xx + capability message | Session confirmed value 不变 |
| effort 保存失败 | Composer 恢复旧值 | 不保留 optimistic 值 |
| 固定模型上游失败 | 正常 provider error | 不静默切模型 |
| Provider 迁移冲突 | preview blocked | 不写 operator config |

## 14. 日志契约

新增或补齐有界 runtime-scene 事件：

- `config.provider.discovery_succeeded/failed`（复用）；
- `config.model.promotion_started/completed/failed/rolled_back`；
- `agent.llm_binding.updated/rejected`；
- `session.reasoning_effort.updated/rejected`；
- `llm.turn.selection_resolved`；
- `config.provider.merge_previewed/applied/failed/rolled_back`。

允许字段：providerId、modelRef、upstreamId、agentId、sessionId、turnId、slot、effort、source、status、reasonCode、elapsedMs、count、manifest path。

禁止字段：API Key、Authorization、完整 prompt、完整响应、raw provider payload、完整配置文件和大模型目录。

## 15. 测试与验证

### 15.1 后端自动测试

至少覆盖：

- discovery 返回 Luna/Sol/Terra 时 candidate projection 全部出现；
- pinned + discovered 同 modelRef 去重，pinned override 优先；
- audio/image/realtime 模型在 dialogue slot 可见但禁用；
- discovered model promotion 成功后写 pinned model 和 Agent binding；
- promotion 任一步失败时无悬空 Agent reference，补偿/partial 状态正确；
- Agent model 只能由 Agent 配置入口修改；
- 新 Session 复制 Agent 默认 effort；Session effort 不回写 Agent，不影响已有或其他 Session；
- Config 存在未保存草稿时 discovered model promotion 被阻断；
- runtime 解析正确 upstreamId 和 effort，并记录 immutable snapshot；
- duplicate Provider migration preview、引用重写、历史保留、apply、rollback；
- 凭据和错误日志无 secret 泄漏。

### 15.2 前端自动测试

至少覆盖：

- Agent picker 按 Provider 分组，支持搜索、状态和 disabled reason；
- “固定并选择”的 pending/success/error 状态；
- Composer codex variant 只在 Chat bridge 启用；
- Evolution/SelfEvolution 保持 compact；
- 模型只读，effort 可选；
- running/pending/error 时控制正确；
- textarea 自增长、附件/引用/编辑/drag 状态不破坏 toolbar；
- 键盘 focus、Escape、listbox/menu 语义和 focus-visible。

### 15.3 构建与浏览器验证

实现后必须运行聚焦 pytest、Vitest 和：

```powershell
npm --prefix web run build
```

Launcher refresh：前端、API、runtime/config 行为均变化，因此用户手工验收前为 `required`。若有活动任务，必须先报告标准阻塞信息，不绕过 Launcher guard。

浏览器场景：

| 场景 | 视口 | 必须满足 |
| --- | --- | --- |
| 主对话 idle | 1440x900 light/dark | 960px 内居中、120px 左右、模型只读、effort 可选、发送内嵌 |
| 主对话 running | 1024x768 | 停止按钮原位、effort disabled、无布局跳动 |
| 主对话 narrow | 390x844 | 无横向滚动、发送始终可见、模型名正确截断 |
| 附件/引用/编辑 | 1024x768 | 内部层级清楚、toolbar 不跳位 |
| Agent model picker | 1440x900 | Ai-Pixel 分组包含 Luna/Sol/Terra；非 dialogue 模型有禁用原因 |
| Promotion | 1440x900 | discovered -> pinned -> Agent bound；刷新后仍然存在 |
| Session isolation | 两个会话 | 修改 A 的 effort 不改变 B；刷新后 A 恢复 |

真实调用：

- 对 canonical Ai-Pixel Provider 分别执行 Luna、Sol、Terra 的最小文本调用；
- 对声明支持 reasoning effort 的模型至少验证两个 effort 值进入真实请求；
- 任何 4xx/5xx 必须保留 provider/model/route 有界诊断，不以 UI 通过代替运行验收。

## 16. 逐文件预计影响面

规划阶段预计涉及但不限定为：

### 后端/config

- `config/models.py`
- `config/llm_identity.py`
- `config/llm_projection.py`
- `config/model_catalog.py`
- `config/llm_provider_registry.py`
- `core/llm/provider_discovery/*`
- `core/llm/agent_runtime.py`
- `core/web/services/agent_config_workspace_service.py`
- `core/web/services/agent_directory_service.py`
- `core/web/services/provider_config_service.py`
- `core/web/services/session_service.py`
- 对应 API route/DTO、migration helper 和测试

### 前端

- `web/src/components/conversation/ConversationView.tsx`
- `web/src/components/conversation/ConversationView.styles.ts`
- `web/src/components/conversation/ConversationModelSelector.tsx`（预计收敛/重命名为 inference control）
- `web/src/routes/chat/ChatConversationComposerBridge.tsx`
- Agent 配置模型选择相关组件、types、API client 和测试
- `web/src/routes/ChatCodingRoute.layout.test.ts`

实施计划必须先重新定位精确 owner，不得因为此列表顺带修改全部文件。`session_service.py` 和共享 DTO 属于热文件/串行边界，实施前必须重新检查 claims。

## 17. 实施顺序约束

推荐串行顺序：

1. candidate projection 和只读 API；
2. promotion coordinator 与回滚测试；
3. Agent 固定模型入口；
4. Session effort 单一所有权与 runtime snapshot；
5. Composer codex variant 与 inference control；
6. Ai-Pixel duplicate Provider migration preview/apply；
7. 构建、Launcher refresh、浏览器与真实模型验收。

原因：Composer 必须依赖稳定的 fixed model/effort contract，Provider 合并必须等新引用路径可用后再执行。共享 config、Agent 和 Session 写路径不得并行修改后再尝试事后拼接。

## 18. 完成标准

同时满足以下条件才可报告完成：

- 一个 Ai-Pixel Provider 能发现并展示完整目录；
- Agent 设置可选择 Luna、Sol、Terra，并在首次选择时可靠固定；
- Agent 固定模型不会被普通会话操作修改；
- 当前会话 effort 可调、可恢复且跨会话隔离；
- 主对话 Composer 与参考图在结构、层级、尺寸和交互上对齐；
- 进化/自进化嵌入对话没有视觉回归；
- duplicate Provider 合并有 manifest、备份、引用归零和回滚证据；
- 聚焦测试、前端构建、三个模型真实调用和浏览器截图全部通过；
- Launcher 已刷新，项目 memory 已同步，claims 已释放；
- 日志不包含 secret、完整 prompt 或大 payload。

## 19. 自审清单

- [x] 无 `TODO`、`TBD` 或占位字段；
- [x] Provider、catalog、pinned model、Agent、Session、turn 的事实源唯一；
- [x] 动态发现不会批量污染 operator config；
- [x] discovered model 选择失败不会留下悬空 Agent binding；
- [x] fixed model 与 session effort 没有职责混淆；
- [x] Composer 只影响主 Chat，不影响 Evolution/SelfEvolution；
- [x] duplicate Provider 不依靠危险的自动 endpoint 等价规则删除；
- [x] 错误、partial、rollback 和 stale 状态均显式；
- [x] 自动测试、浏览器、Launcher 和真实模型验收均有明确门禁；
- [x] 与相邻设计的 owner 边界已声明。

## 20. 下一阶段门禁

本规格已按用户逐段批准的方向整理，当前只允许用户审阅和修订。用户确认书面规格后，下一步使用 `writing-plans` 生成详细 implementation plan；在此之前不修改运行代码、不执行 Provider 合并、不修改 operator config。
