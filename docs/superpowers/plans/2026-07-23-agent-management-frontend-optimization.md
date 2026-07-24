# Agent 管理前端完整优化方案

**Date:** 2026-07-23
**Status:** partially implemented
**Mode:** `TASK_GRAPH`
**Risk:** `STANDARD_TASK`；共享 VUI 契约、路由状态和危险操作区域按高风险门禁验收
**Scope:** `/agents`、`/agents/prompts`、`/agents/tools`、`/agents/skills`、Agent 创建向导、批量操作、跨中心返回路径和对应视觉回归矩阵

## 0. 当前实施状态

- 已落地：Agent 创建向导的职责头像选择、默认头像修复，以及 Agent 管理页对统一 VUI surface 契约的消费。
- 对应主线提交：`0c72fb869`（职责头像与创建向导）、`a09a28ff8`（VUI surface 单一事实源）。
- 尚未完成：本方案中的完整二级导航、目录比较/批量工作流、运行页重排和全视口验收矩阵。
- 本文继续作为剩余工作路线图；不得把上述两个提交解释为整份方案已经完成。

## 1. 目标与成功结果

把 Agent 管理从“多个面板、按钮和状态同时争夺注意力”的页面，收敛为安静、紧凑、可扫描的运维工作台。

完成后用户应能：

1. 在 3 秒内识别当前位置、当前 Agent、健康状态和下一步主操作。
2. 通过一个稳定的 Agent Center 二级导航进入 Agent、提示词、工具和技能。
3. 在 Agent 目录中快速搜索、筛选、比较和选择对象，不被常驻批量控件干扰。
4. 在“总览 / 配置 / 运行”之间切换时始终看到导航，详情内容只在自己的内容区滚动。
5. 在运行页优先看到运行状态、最近活动和下一步；低频策略默认收纳。
6. 在提示词、工具和技能页复用相同的列表—详情工作区、按钮比例和状态语言。
7. 在 1280×720 到 2560×1440 的桌面视口及 768px 左右的窄视口中，没有覆盖、横向溢出、不可达按钮或被截断的主操作。

## 2. 非目标与保护边界

- 不修改 Agent、Prompt、Tool、Skill 的后端 DTO、权限、持久化和删除语义。
- 不改变 `/api/agents`、`/api/tools`、提示词和技能 API 的事实源。
- 不重做 AppShell、全局导航、品牌色或整个 VUI 设计系统。
- 不把 Agent 记忆管理重新搬回 Agent Center；继续使用 `/memory/agents`，只保留清晰的跨中心入口和返回路径。
- 不用新增卡片层级解决层级混乱，不为视觉优化引入新的状态库或组件依赖。
- 不记录提示词全文、工具明细、Agent 私有配置或用户输入到新增日志。

## 3. 推荐的信息架构

```text
AppShell
└─ Agent Center
   ├─ Agent
   │  ├─ 目录与筛选
   │  └─ Agent 详情
   │     ├─ 总览
   │     ├─ 配置
   │     │  ├─ 基础
   │     │  ├─ 身份与任务
   │     │  ├─ 能力
   │     │  └─ 运维与危险操作
   │     └─ 运行
   │        ├─ 当前状态
   │        ├─ 活动
   │        └─ 高级运行策略
   ├─ 提示词
   │  ├─ 模板目录
   │  └─ 模板详情 / 编辑
   ├─ 工具
   │  ├─ 工具目录
   │  └─ 工具详情 / Agent 授权
   └─ 技能
      ├─ 技能目录
      └─ 技能详情 / 使用方式
```

### 导航规则

- Agent Center 二级导航只表达四个产品域：Agent、提示词、工具、技能。
- Agent 详情只保留“总览 / 配置 / 运行”一组一级详情导航。
- Inspector 不再重复提供“工具 / 运行”等详情导航，只展示上下文摘要、下一步和关联资源。
- 跨中心入口必须携带 `agentId`、`returnTo` 和必要的 focus 参数；返回后恢复原 Agent 与原 pane。
- 所有当前项同时使用位置、文本和 `aria-current` / `aria-selected` 表达，不只依赖颜色。

## 4. 总体布局契约

### 4.1 宽屏三栏、受限空间自适应降级

宽屏默认工作区：

```text
┌──────────────┬──────────────────────────────────────┬──────────────┐
│ 目录         │ 主详情                               │ Inspector    │
│ 搜索/筛选    │ 身份、导航、当前 pane                │ 下一步       │
│ 实体列表     │ minmax(720px, 1fr)                   │ 关联资源     │
└──────────────┴──────────────────────────────────────┴──────────────┘
```

- 三栏是否出现由工作区容器的可用宽度决定，不只依赖浏览器 viewport。
- 左栏默认 300px，可在 260–400px 内调整；只承载搜索、筛选和 Agent 目录。
- 主详情优先获得剩余空间，建议最小可用宽度 720px；不能再沿用当前 360px 的过低下限。
- Inspector 默认 280–320px，只承载管理完整度、下一步和关联资源，不重复“配置 / 运行 / 工具”等导航。
- 当 `左栏 + 主详情最小宽度 + Inspector + 分隔手柄` 无法同时满足时，Inspector 自动进入抽屉。
- 只有继续压缩仍会损害主详情时，目录才进入“列表 / 详情”切换模式。
- 两个 resize handle 可以保留在三栏模式，但必须受主详情最小宽度保护；Inspector 进入抽屉后只保留目录手柄。

### 4.2 断点

| 视口 | 布局 |
|---|---|
| 工作区可用宽度 ≥1320px | 默认三栏；主详情不少于 720px |
| 1100–1319px | 280–320px 目录 + 主详情；Inspector 抽屉 |
| 860–1099px | 260–300px 目录 + 主详情；低频摘要收纳、Inspector 抽屉 |
| <860px | 目录/详情单页切换；详情提供明确“返回 Agent 列表” |
| <640px | 二级导航横向滚动；操作栏贴底；表单与列表单列 |

1320px 是实施起始阈值，不是最终硬编码结论。Task 2 必须通过浏览器测量以下约束后确定最终容器查询值：

- 左栏完整显示典型 Agent 名称、角色和模型摘要；
- 主详情在配置双列表单和运行策略中无水平溢出；
- Inspector 的资源名称和操作按钮不互相挤压；
- 三栏总宽度没有依赖内容覆盖或负空间成立。

### 4.3 滚动所有权

- Route：不承担内容滚动。
- 目录：筛选头保持可见，列表独立滚动。
- 详情：身份头与“总览 / 配置 / 运行”组成固定头部区域；pane 内容独立滚动。
- 编辑器、日志和长预览仅在自身区域滚动。
- 禁止三个直接 grid 子项落入只定义两行的容器；所有固定头部必须有明确 wrapper。

## 5. 统一密度和按钮比例

### 5.1 控件规格

| 类型 | 高度 | 使用位置 |
|---|---:|---|
| Icon | 28px | 刷新、关闭、更多 |
| Compact | 28px | 筛选、资源“打开”、行内辅助操作 |
| Default | 32px | 新增、检查配置、查看日志、普通保存 |
| Dialog primary | 36px | 向导下一步、创建 Agent、危险确认 |

规则：

- 同一操作带最多一个 Primary。
- Primary、Secondary、Ghost 表达优先级，不依靠按钮宽度制造优先级。
- 按钮默认 `w-fit`；仅窄屏底部主操作可全宽。
- 同一工具栏按钮等高；图标 14–16px；左右 padding 8–12px。
- “打开”“查看”等短动作不得占满资源行。
- 禁用态保留足够文字对比度，并提供不可用原因。

### 5.2 列表与标签

- 桌面实体行：44–48px；窄屏：至少 52px。
- 状态 pill：20–22px，不与按钮同尺寸。
- 列表主行只显示名称、角色、模型摘要和一个主状态。
- 内部枚举 `idle`、`active`、`no_recent_runs` 不直接渲染。
- 正常状态保持安静；只有 warning、running、blocked 获得强调色。

## 6. `/agents` 页面契约

### 6.1 顶部区域

- 页面标题和说明只保留一行紧凑 header。
- 状态条最多四项：可用、需处理、运行中、待处理消息。
- “正常”不占据与异常同等的整条强调带；有问题时才提升问题状态。
- 刷新保持 icon button，不和新增 Agent 争夺主操作。

### 6.2 目录与筛选

- 第一行：搜索。
- 第二行：可用 / 需处理 / 已归档。
- “更多筛选”收纳模式、角色、缺配置项、存储路径等低频条件。
- 分组标题可折叠，显示数量和简短说明。
- 正常浏览态不显示所有 checkbox；点击“批量”后进入 selection mode，才显示 checkbox 和批量工具栏。
- 批量工具栏固定在列表区域顶部，只在有选中项时出现。
- 行点击选择 Agent，checkbox 只控制批量选择，两个点击目标不互相抢事件。

### 6.3 Agent 详情头

- 第一行：头像、名称、角色、健康状态、一个上下文主操作。
- 第二行：“总览 / 配置 / 运行”。
- 两行共同组成固定 `detailHeaderRegion`。
- 不在详情头重复模型、提示词、工具、记忆等长摘要。

### 6.4 总览

首屏只回答五件事：

1. 当前是否可用。
2. 绑定了什么模型。
3. 使用什么提示词。
4. 关键配置是否完整。
5. 下一步需要做什么。

推荐结构：

- 左侧：运行焦点与下一步。
- 右侧：最近活动；没有活动时压缩为空状态行。
- 下方：模型、提示词、工具、记忆四个紧凑事实行。
- 策略摘要和技术信息默认折叠。
- 关联资源由 Inspector 统一承载；宽屏保持第三栏，受限空间自动进入“关联资源”抽屉。

### 6.5 配置

配置分组保持四类，但每次只展示一个：

- 基础：名称、角色、模式、模型和提示词入口。
- 身份与任务：Persona、Task、Team/Room 引用。
- 能力：工具、记忆、上下文压缩和 LLM slots。
- 运维与危险操作：健康、重置、归档、永久删除。

规则：

- 表单使用 2 列桌面网格、单列窄屏。
- 保存条只在 dirty 时出现；包含“放弃修改 / 保存”。
- 跨中心配置按钮放在相关字段旁，不集中堆成按钮墙。
- 危险操作与日常保存不能出现在同一 action band。
- 归档、永久删除和调试重置继续使用确认对话框，保留影响说明与对象名。

### 6.6 运行

默认结构：

```text
当前状态
  状态 / 原因 / 更新时间 / 最近运行 / 主操作

活动
  时间线 | 运行历史 | Inbox

高级运行策略（默认折叠）
  委托策略 / 监督策略 / 上下文模式
```

- “会话 / 群聊 / 工作区”合并进当前状态的上下文行。
- 没有活动时只显示一条紧凑提示和“开始会话 / 检查配置”。
- Timeline、历史、Inbox 不再各自占据整张空卡片。
- 高级策略只有 dirty 时固定显示保存条。
- 日志证据显示用户标签，内部 scene id 放入 tooltip 或复制菜单。

## 7. Agent 创建向导

- 保留三步：身份与用途 → Provider/模型 → 提示词与工具。
- Header、body、footer 三行；只有 body 滚动。
- Footer 操作顺序固定：取消 / 上一步 / 下一步或创建 Agent。
- 推荐配置是默认选项，但不使用大面积强调卡。
- 每一步只显示当前决策需要的信息，技术 ID 收纳到“高级信息”。
- 成功页只保留三个动作：开始对话、继续高级配置、完成。
- dirty close、pending lock、submit error 和 session 创建失败维持现有安全语义。

## 8. `/agents/prompts` 页面契约

- 使用统一 Agent Center route frame。
- 默认 320px 模板目录 + 编辑详情。
- 左栏：搜索、分类、模板列表；批量模式按需进入。
- 模板行显示名称、分类、引用次数；路径和内部 ID 作为次级信息或 tooltip。
- 详情顶部：模板名、状态、引用数、一个主操作。
- 编辑器区：元信息 / 内容 / 引用 Agent 三个分组。
- 批量恢复、停用和改分类只在 selection mode 出现。
- 保存、恢复默认和停用使用不同层级；危险或不可逆动作单独确认。
- 长 Markdown 编辑与预览明确分栏或标签切换，不叠加透明面板。

## 9. `/agents/tools` 页面契约

- 从多块卡片改为统一目录—详情工作区。
- 左栏：搜索、来源、风险、启用状态和工具列表。
- 主详情包含四个标签：
  - 概览
  - 权限
  - Agent 使用
  - 测试与日志
- Agent scope 不再作为页面中的第三套并行面板；进入“Agent 使用”标签。
- 工具包应用是上下文操作，不常驻占据整条宽工具栏。
- 高风险、显式授权和内置状态用同一个状态词典。
- 批量启用/停用前显示影响数量、受保护项和跳过原因。
- 工具测试输出与配置表单分区，避免结果刷新导致编辑区跳动。

## 10. `/agents/skills` 页面契约

- 保持只读能力目录的定位。
- 左栏：搜索、来源筛选和技能列表。
- 行显示技能名、来源和一行用途摘要；不要让整行表现成大号按钮。
- 详情显示：用途、触发条件、使用说明、路径/来源、安装状态。
- 命令复制使用紧凑 icon/secondary action。
- 不可用或缺失来源显示明确 reason，不伪装为空详情。
- 移动端列表与详情分屏切换，详情提供返回入口。

## 11. 公共状态与文案契约

新增或收敛一个前端 presentation mapper，统一：

| 领域事实 | 用户状态 |
|---|---|
| ready / healthy | 正常 |
| running | 运行中 |
| warning / action required | 需处理 |
| blocked / failed | 已阻塞 / 失败 |
| idle / no recent run | 空闲 / 暂无运行 |
| inherited | 继承默认 |
| unavailable | 不可用，并显示原因 |

约束：

- 后端原始枚举仍是事实源，mapper 只负责用户呈现。
- 不在各 route 单独维护同义状态。
- 原因和下一步不能只存在于 tooltip。
- loading、empty、error、disabled、dirty、success 均有稳定布局，状态切换不改变主导航位置。

## 12. 组件与文件影响面

优先复用：

- `AgentPageHeader`
- `AgentSummaryStrip`
- `AgentWorkspacePanel`
- `AgentFilterRail`
- `AgentDenseList`
- `VButton` / `VNativeButton`
- `VConfirmDialog`
- VUI layout templates

主要 owning surface：

- `web/src/routes/AgentsRoute.tsx`
- `web/src/routes/AgentsRoute.styles.ts`
- `web/src/routes/AgentWorkspaceLayoutPanel.*`
- `web/src/routes/AgentSelectedDetailContentPanel.*`
- `web/src/routes/AgentDetailHeaderPanel.*`
- `web/src/routes/AgentInspectorRailPanel.*`
- `web/src/routes/AgentOverview*`
- `web/src/routes/AgentActivity*`
- `web/src/routes/AgentConfig*`
- `web/src/routes/PromptTemplatesRoute.*`
- `web/src/routes/ToolsRoute.*`
- `web/src/routes/SkillsRoute.*`
- `web/src/routes/agent-create/*`
- `web/src/routes/AgentManagementNav.*`
- `web/src/components/vui/product/agent-management/*`
- `web/src/visual-regression/workbenchVisualMatrix.ts`

结构风险：

- `AgentsRoute.tsx` 约 5900 行，`ToolsRoute.tsx` 约 2469 行。优化时只提取已经形成稳定职责的 presentation/controller，不进行无关的全面重写。
- `AgentsRoute.layout.test.ts` 是共享热测试文件，各阶段必须串行协调和小范围更新。
- 公共按钮、状态和 workspace primitives 先形成契约，具体 route 不得各自复制新规格。

## 13. 实施任务图

### Critical Path

`T0 → T1 → T2 → T3 → (T4 / T5 / T6) → T7 → T8`

### Task 0：关闭已知布局回归

- **Owner/Boundary:** Agent 详情 header 和 pane 布局。
- **Dependency:** 无。
- **Mode:** `BDD_TDD`
- **Output:** 身份头和三枚详情导航进入一个明确头部行；切换运行页不覆盖导航。
- **Verification/Stop:** `AgentsRoute.layout.test.ts`、浏览器 bounding-box 无重叠、console 无错误。

### Task 1：建立 Agent Center 公共界面契约

- **Owner/Boundary:** 二级导航、route frame、按钮尺寸、状态 mapper、公共空状态。
- **Dependency:** T0。
- **Mode:** `BDD_TDD`
- **Output:** 四个 route 使用一致的 header/nav/control/workspace 基线；内部枚举不再直接显示。
- **Verification/Stop:** VUI contract tests、四个 route layout tests、组件导入边界测试。

### Task 2：重构 Agent 目录和工作区框架

- **Owner/Boundary:** 搜索筛选、selection mode、列表密度、自适应三栏、Inspector 抽屉。
- **Dependency:** T1。
- **Mode:** `BDD_TDD`
- **Output:** 宽屏三栏、受限宽度自动收起 Inspector、主详情最小宽度保护、按需批量选择、窄屏列表/详情切换。
- **Verification/Stop:** 目录筛选/选择测试；容器宽度阈值测试；1280/1440/1920/2560 和 768px 浏览器验收；记录三栏实际 bounding box。

### Task 3：收敛 Agent 详情三大 pane

- **Owner/Boundary:** 总览、配置、运行及其保存/危险操作边界。
- **Dependency:** T2。
- **Mode:** `BDD_TDD`
- **Output:** 总览首屏、四类配置、运行状态/活动/高级策略结构。
- **Verification/Stop:** pane 切换、dirty save、empty/error、确认对话框和运行策略测试。

### Task 4：优化提示词中心

- **Owner/Boundary:** `/agents/prompts`。
- **Dependency:** T1；与 T5/T6 可并行，不能同时编辑公共 route contract。
- **Mode:** `BDD_TDD`
- **Output:** 统一目录—编辑详情、按需批量模式、稳定保存区。
- **Verification/Stop:** `PromptTemplatesRoute.layout.test.ts`、编辑/恢复/停用浏览器路径。

### Task 5：优化工具中心

- **Owner/Boundary:** `/agents/tools`。
- **Dependency:** T1；与 T4/T6 可并行。
- **Mode:** `BDD_TDD`
- **Output:** 工具目录 + 四标签详情；Agent scope 收进详情；风险与权限状态统一。
- **Verification/Stop:** `ToolsRoute.layout.test.ts`、授权/批量/测试输出状态、无横向溢出。

### Task 6：优化技能中心

- **Owner/Boundary:** `/agents/skills`。
- **Dependency:** T1；与 T4/T5 可并行。
- **Mode:** `SIMPLE`
- **Output:** 紧凑只读目录—详情、清晰来源与不可用状态。
- **Verification/Stop:** `SkillsRoute.layout.test.ts`、长名称/长描述/空详情/窄屏验收。

### Task 7：创建、批量与危险操作一致性

- **Owner/Boundary:** 创建向导、批量工具栏、归档/删除/重置确认。
- **Dependency:** T3/T4/T5/T6。
- **Mode:** `BDD_TDD`
- **Output:** 操作层级统一，创建和危险操作状态完整，跨中心返回可恢复。
- **Verification/Stop:** 创建向导测试、Agent bulk tests、confirm dialog tests、deep-link/return tests。

### Task 8：集成视觉与无障碍验收

- **Owner/Boundary:** 全 Agent Center，禁止顺手改变业务语义。
- **Dependency:** T7。
- **Mode:** `BDD_TDD`
- **Output:** 扩展视觉矩阵、完成主题/背景/视口/状态验收、修复最后的 UI 回归。
- **Verification/Stop:** 全部 Agent 前端测试、完整 web suite、build、浏览器矩阵、Launcher 刷新。

## 14. 验证矩阵

### 自动化

至少覆盖：

```powershell
npm --prefix web test -- --run `
  src/components/vui/product/agent-management/AgentManagementProduct.test.tsx `
  src/routes/AgentsRoute.layout.test.ts `
  src/routes/AgentOverviewOperationsPanel.test.tsx `
  src/routes/AgentOverviewPanel.test.tsx `
  src/routes/AgentOverviewResourcesPanel.test.tsx `
  src/routes/PromptTemplatesRoute.layout.test.ts `
  src/routes/ToolsRoute.layout.test.ts `
  src/routes/SkillsRoute.layout.test.ts `
  src/routes/agent-create/AgentCreateWizardDialog.test.ts `
  src/routes/agent-create/agentCreateContract.test.ts `
  src/routes/agentCenterRoutes.test.ts `
  src/design/multilineVButtonContract.test.ts `
  src/visual-regression/workbenchVisualMatrix.test.ts

npm --prefix web test
npm --prefix web run build
git diff --check
```

### 浏览器状态

每个 route 至少覆盖：

- dense
- empty
- loading
- error/unavailable
- selected
- dirty（可编辑页）
- destructive（有危险操作页）

### 视口与主题

- 1280×720，light/default
- 1440×900，dark/default
- 1920×1080，light/custom background
- 2560×1440，light/custom background
- 768×900，light/default

检查：

- 导航不覆盖。
- 没有横向滚动。
- 主操作始终可达。
- 长名称、路径、模型和提示词 ID 不撑破布局。
- 焦点可见，Tab 顺序与视觉顺序一致。
- selected/warning/blocked 不只靠颜色。
- 背景可见但不降低正文、禁用态和输入框的可读性。
- console 无新增 error；API error 显示可恢复 UI。

## 15. 日志、版本、刷新与回滚

- **Logging:** UI 布局本身不新增运行日志；继续使用现有浏览器 telemetry 和 API runtime-scene。新增交互日志只记录 route、状态枚举、成功/失败和耗时，不记录提示词、工具内容或私有 Agent 配置。
- **Version impact:** `patch`；若拆成多批本地合并，各任务只报告影响，最终发布统一决定版本。
- **Runtime refresh:** 每批合并到 `main` 后，用户验收前必须通过 Launcher 刷新；有活跃任务时遵循 active-work guard。
- **Rollback:** 每个任务独立 commit/merge；公共契约 T1 可整体回滚。具体 route 的 T4/T5/T6 不应要求同时回滚其他 route。
- **Memory:** 最终界面契约和视觉验收完成后，更新 Agent UI lane；中间实现细节不写入共享 memory。

## 16. 合并与协作策略

- T0、T1、T2、T3 串行，避免 `AgentsRoute.tsx`、VUI product 组件和共享 layout test 冲突。
- T4、T5、T6 只在 T1 公共契约稳定后并行；各自拥有独立 route、styles 和 layout test。
- T7 串行消费四个 route 的最终操作契约。
- T8 由一个集成 owner 完成，不让各 route owner分别修改视觉矩阵和共享 VUI 测试。
- 每个任务从最新本地 `main` 建工作树，使用窄 claim，先自审、验证，再合入本地 `main`。

## 17. 完成定义

只有同时满足以下条件才算完成：

1. 四个 Agent Center route 使用统一导航、控件密度和列表—详情框架。
2. Agent 详情导航在所有 pane 和目标视口中保持可见且不重叠。
3. 一个 action band 最多一个主操作；短辅助按钮不再和主操作同权重。
4. 运行页不再是默认全展开的信息墙。
5. 宽屏三栏能够充分利用空间；空间不足时 Inspector 自动降级且主详情不被压缩到不可用。
6. 后端业务语义、权限、删除和配置事实源没有改变。
7. 聚焦测试、完整 web suite、build 和浏览器矩阵全部通过。
8. Launcher 刷新后的真实页面与任务分支验证一致。
