# Product — Team management

> 科研/资料搜集等团队域组合件。
> 阶段卡、结果列表等 **不是** 通用 kanban；通用壳用 Board recipe。
> 设计选型先读 **功能 / 适用范围 / 使用方式**。

## TeamWorkspaceFrame

### 功能
团队工作台共用的页面外框与导航、内容、检查器三栏组合；内容区保留当前 Teams 页面各自的业务组件。

### 适用范围
- **适用**：团队主页、组织/流程画布等使用左侧团队导航、中心内容与可选检查器的桌面工作台。
- **不适用**：普通团队列表/详情 → `VListDetailPage`；总览看板 → `VBoardWorkbenchPage`。

### 使用方式
沿用 `TeamWorkspaceFrame` 包装业务槽位，保留 `VCanvasWorkbenchPage`、`WORKBENCH_LAYOUT_IDS` 与 shared pane persistence；不增加团队专用页面 recipe 或宽度状态。团队讨论与成员单聊切换后都占用同一个中心内容列，由 `TeamConversationRail` 提供会话选择。

团队讨论和成员单聊在中心列嵌入 `TeamNativeConversation`，复用现有 `ChatCodingRoute`。嵌入层只处理工作台几何并隐藏重复的会话导航栏；Session、transcript、SSE 实时输出、发送和停止仍由原生 Chat 链路负责，不形成第二套会话实现或状态权威。
团队与成员日常切换留在 `/teams`；原生分叉等创建新独立会话的操作沿用 `/chat`，并提供返回团队入口。成员以 `Team.members` 为名单，按关联房间 `agentId` 映射原生 `sessionId`；缺少会话或已失效成员不能打开其他成员的会话。

### 视觉与布局
- 外框与左右栏复用 `vuiRailFillClass` / `--vui-surface-rail`；左右面板不覆盖 `--shell-surface`，由外框的 rail surface 提供连续背景。
- 中心内容面只在内容面板设置 `--shell-surface`、`--vui-surface-panel` 与 `--vui-surface-workspace` 为 `--vui-surface-chat`，保持主题中的对话背景、VUI 软圆角与平面无阴影。
- AppShell 对 `/teams` 使用 `VWorkbenchFrame flush`，由团队 recipe 自己管理 pane 间距。外框使用 `p-0`，顶边与会话 Agent 工作台齐平；中心列使用 `mx-1 mb-1`，700px 以下收为 `mx-0.5 mb-0.5`，避免外框与中心列叠加左侧留白。布局缩放、可选检查器和既有响应行为继续由 `VCanvasWorkbenchPage` 管理。

### 实现落点
`web/src/routes/teams/TeamWorkspaceFrame.tsx` 与 `TeamWorkspaceFrame.styles.ts`。

## TeamStageCard

### 功能
阶段卡片展示当前阶段名称与状态，表达流水线中的某一阶段。

### 适用范围
- **适用**：阶段 pipeline 中的阶段语义卡。
- **不适用**：总览看板列 → Board recipe。

| 场景 | 选择 |
| --- | --- |
| 阶段 pipeline | `TeamStageCard` |
| 看板列 | Board 域 kanban |

### 使用方式
```tsx
<TeamStageCard
  index={0}
  label="知识采集"
  status="当前"
  metric="42 / 48"
  nextLabel="完成交接"
  tone="active"
  onActivate={openStage}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label / status | 主名称与状态 | 状态使用中性文字，不模拟按钮或 success 胶囊 |
| metric / nextLabel / title | 进度与补充信息 | 仅 hover / focus 展示，不增加卡片行数 |

### 视觉与状态
- 普通、悬停与选中卡片保持平面，不叠加浮起阴影；选中保留左侧状态标记，键盘聚焦保留可见焦点环。粘底操作区使用实色面与上边框分隔。

### 反冗余
- 不与通用 kanban 卡平行扩张。

---

## TeamStageCommandBar

### 功能
阶段命令/统计条，承载阶段级操作与计数；补充说明只在 hover / focus 读取。

### 适用范围
- **适用**：团队阶段视图命令带。
- **不适用**：通用页工具条 → `VToolbar`/`VDenseToolbar`。

| 场景 | 选择 |
| --- | --- |
| 阶段命令 | `TeamStageCommandBar` |
| 页级工具条 | `VToolbar` |

### 使用方式
```tsx
<TeamStageCommandBar title="知识采集" subtitle="当前科研阶段" stats={stats} steps={steps} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / subtitle | 当前阶段与补充说明 | subtitle 仅 hover / focus 展示 |
| stats / steps | 统计与阶段导航 | 单一中性分段组；每项保持局部相邻，不使用分散对齐 |

---

## TeamStagePipeline

### 功能
阶段流水线布局容器，横向/纵向排列阶段卡。

### 适用范围
- **适用**：多阶段流程展示。
- **不适用**：自由画布 → `VCanvasWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| 阶段流水线 | `TeamStagePipeline` |
| 流程图画布 | Canvas recipe |

### 使用方式
```tsx
<TeamStagePipeline>
  <TeamStageCard ... />
  <TeamStageCard ... />
</TeamStagePipeline>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children | 阶段卡 | 顺序即流程 |

---

## TeamSourceFilterBar

### 功能
资料结果过滤条（关键词/状态等）。

### 适用范围
- **适用**：团队资料搜集结果过滤。
- **不适用**：通用 Agent 筛选 → `AgentFilterRail`。

| 场景 | 选择 |
| --- | --- |
| 资料过滤 | `TeamSourceFilterBar` |
| Agent 过滤 | `AgentFilterRail` |

### 使用方式
```tsx
<TeamSourceFilterBar query={q} onQueryChange={setQ} status={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| query / status | 过滤条件 | 控件 V* |

---

## TeamSourcePagination

### 功能
资料列表分页控件。

### 适用范围
- **适用**：资料结果分页。
- **不适用**：无限滚动列表（另案）。

| 场景 | 选择 |
| --- | --- |
| 分页 | `TeamSourcePagination` |

### 使用方式
```tsx
<TeamSourcePagination page={page} total={total} onPageChange={setPage} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| page / total / onPageChange | 分页态 | 禁用越界 |

---

## TeamSourceResultList

### 功能
资料结果列表（含 `TeamSourceResultItem` 行）。

### 适用范围
- **适用**：资料搜集结果列表。
- **不适用**：通用 EntityList；Item 不单独成为第二列表体系。

| 场景 | 选择 |
| --- | --- |
| 资料结果 | `TeamSourceResultList` |
| 通用列表 | `VEntityList` |

### 使用方式
```tsx
<TeamSourceResultList items={results} onSelect={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| items / onSelect | 数据与选择 | Item 内组合 V* |

### 反冗余
- Item 不单独导出为第二列表体系。

---

## TeamSourceResultItem

### 功能
单条资料结果行（由 ResultList 使用）。

### 适用范围
- **适用**：仅作为 `TeamSourceResultList` 的行渲染。
- **不适用**：独立通用 list item 体系。

| 场景 | 选择 |
| --- | --- |
| 资料行 | 经 ResultList |
| 通用行 | `VDenseRow` 等 |

### 使用方式
```tsx
// 通常不单独使用；由 TeamSourceResultList 渲染
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| item 数据 | 单条结果 | 选中/hover 态统一 |

---

## TeamSourceResultStats

### 功能
资料结果的紧凑指标组，标签和值保持相邻，不横向拉散。

### 适用范围
- **适用**：结果列表上方/下方统计。
- **不适用**：跨页总览指标 → `VMetricStrip`。

| 场景 | 选择 |
| --- | --- |
| 结果统计 | `TeamSourceResultStats` |
| 页指标 | `VMetricStrip` |

### 使用方式
```tsx
<TeamSourceResultStats stats={[{ key: "ready", label: "候选", value: 48 }]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| stats | 标签和值 | 每项为内容宽度，不用等分列 |

---

## TeamStatusLabel

### 功能
团队域的非交互状态文字，以小圆点和文字传达状态，不使用按钮、胶囊或填充底色。

### 适用范围
- **适用**：`TeamCandidateCard`、`TeamSourceResultItem` 内的紧凑状态。
- **不适用**：可点击筛选或操作；这类需求使用对应 VUI 控件。

| 场景 | 选择 |
| --- | --- |
| 非交互状态 | `TeamStatusLabel` |
| 可点击筛选 | `VChip` / 对应产品筛选控件 |

### 使用方式
```tsx
<TeamStatusLabel tone="ready">候选</TeamStatusLabel>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone / children | 状态语义与短标签 | `ready` 保持中性；仅 warning / danger 使用告警色 |

---

## TeamSourceEmptyState

### 功能
资料空态（可带领域 facts）。默认以居中的图标、标题和可选操作形成紧凑 blank slate。

### 适用范围
- **适用**：资料无结果且需领域说明。
- **不适用**：通用空态 → `VEmptyState`。

| 场景 | 选择 |
| --- | --- |
| 资料空 | `TeamSourceEmptyState` |
| 通用空 | `VEmptyState` |

### 使用方式
```tsx
<TeamSourceEmptyState title="暂无结果" facts={[...]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / icon | 标题与视觉锚点 | 标题必填；图标默认使用中性检索空态 |
| description / facts | 可选补充内容 | 无必要时不渲染说明；facts 使用紧凑键值对 |
| actions / footer | 操作与尾部 | 居中排列，不制造整行色块 |

### 反冗余
- 通用空态用 `VEmptyState`。

---

## TeamCandidateCard

### 功能
候选卡片，展示团队候选实体的主名称、状态与明确动作。

### 适用范围
- **适用**：团队候选列表卡。
- **不适用**：通用 surface 卡 → `VSurface`。

| 场景 | 选择 |
| --- | --- |
| 候选卡 | `TeamCandidateCard` |
| 任意卡片壳 | `VSurface` |

### 使用方式
```tsx
<TeamCandidateCard title="文献记录" statusLabel="待复核" tone="warning" actions={actions} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / statusLabel / actions | 主数据与操作 | 默认一行；状态无控件外观，动作使用 VUI 按钮 |
| summary / meta / source | 支撑信息与来源 | hover / focus 可读；来源以独立图标链接保留 |

---

## TeamCanvasNodeCard

### 功能
组织画布节点卡（`TeamOrganizationCanvasSurface` 内联渲染模式），表达团队中的一个角色/Agent 分工：主标签、职能 badge、绑定 Agent 显示名与职责说明。组织边（reports_to 等）带方向箭头，通讯边双向语义不挂箭头。

### 适用范围
- **适用**：teams 组织画布上的角色/Agent 节点卡。
- **不适用**：通用流程图节点 → `VWorkflowCanvas`；看板列卡 → Board 域。

| 场景 | 选择 |
| --- | --- |
| 组织画布节点 | `TeamCanvasNodeCard` 模式 |
| 工作流图节点 | `VWorkflowCanvas` |

### 使用方式
```tsx
// 由 TeamOrganizationCanvasSurface 渲染，不单独导出；
// 内容行自上而下：label（strong）→ 职能 badge → Agent 显示名 / 本地化绑定状态 → purpose（可选）
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label | 节点主名称 | 单行 truncate |
| functionLabel | 职能 badge | 各角色 badge 前景用各自强调色；research 用 `--accent-warm` |
| agentLine | 绑定 Agent 显示名（display name → agentName → agentCode），未绑定显示本地化状态 | 不直接显示英文机器 status |
| purpose | 角色职责 | 可选行，tertiary 色，truncate；无 purpose 不渲染该行 |

### 反冗余
- 不新增第二套画布节点卡；样式集中在 `TeamsRoute.styles.ts` 的 `node*` map，分类纯函数在 `teamCanvasNodePresentation.ts`。

---

## TeamSettingsDialog

“添加”将所选 Agent 与角色加入可编辑成员草稿，清空添加选择后仍可继续填写新成员的职责目标和职责条目；“保存修改”统一提交草稿。多次添加保留各行，重复绑定不会产生重复成员。成员职责经 HTTP 请求模型传入现有团队成员归一化与持久化流程，保存后刷新可读回，清空后不恢复旧值。危险区及确认框须明确说明当前成员 Agent 一并归档、团队只读和群聊删除。

### 功能
统一团队配置面（P0「团队设置」）：一个 VDialog 配齐团队基本信息（名称/描述/用途）、成员管理（换绑 Agent / 加角色绑人 / 解绑，**以及已有成员的 role / purpose / responsibilities 行内编辑**，不依赖组织画布）、绑定群聊房间状态（房间名 / mode / 参与者数，无房给「创建群聊房间」，有房给「前往群聊」）、每成员对话模型状态（已配 / 未配 + 跳转 `/agents?pane=config&agent=<id>`）与归档危险区（`VConfirmDialog` danger 确认后走既有 `archiveTeam`）。成员名单（`Team.members`，role→agentId）是唯一权威，改动经 `PATCH /api/teams/{id}` 提交，画布由服务端投影刷新；团队群聊房间的参与者名单由服务端团队域同步维护（聊天侧直改房成员会被 409 拒绝并引导回本面）。

### 适用范围
- **适用**：`/teams` 工作台顶栏「团队设置」入口（board 与 canvas 两种模式都挂载），针对可编辑（非系统、非归档）团队；归档团队在此接班（画布工具栏不再承载归档）。
- **不适用**：系统团队（research / knowledge-expansion / ai-search / self-evolution / supervised-evolution）整体只读，只展示锁提示、无保存与危险区；模型编辑本身 → `/agents?pane=config`（Agent 配置权威不搬）；群聊 mode/topic 行内改 → 不做（PATCH room 需要整份参与者会话回传，只读 + 跳转）。

| 场景 | 选择 |
| --- | --- |
| 建队后的信息/成员维护（含成员 role/purpose/职责编辑）、空白队加成员 | 用本对话框 |
| 团队归档（危险区，确认后 `DELETE /api/teams/{id}`） | 用本对话框危险区 |
| 画布节点局部绑定微调 | `TeamNodeBindingPanel`（画布 inspector） |
| 单个 Agent 的模型/Prompt 配置 | `/agents?pane=config` |

### 使用方式
```tsx
// 由 TeamSettingsToolbarAction 自包含挂载（顶栏 actions 槽，renderTeamsShellFrame），
// 不需要业务路由直接拼装；组件本身不持 mutation（useTeamSettingsActions 注入）。
<TeamSettingsDialog
  open={open}
  lang={lang}
  team={team}
  agents={activeAgents}
  teams={visibleTeams}
  agentsById={agentsById}
  pending={settings.pending}
  createRoomPending={settings.createRoomPending}
  errorMessage={settings.errorMessage}
  onSubmit={(teamId, payload) => settings.submit(teamId, payload)}
  onCreateRoom={(teamId) => settings.createRoom(teamId)}
  archivePending={settings.archivePending}
  onArchive={(teamId) => settings.archive(teamId)}
  onClose={closeAndReset}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| team | 当前团队 detail（full，含 `members[].model` 投影） | 为空时入口按钮禁用、对话框不渲染 |
| agents / teams / agentsById | Agent 目录与团队列表 | 换绑/加人选项排除已属其它活跃团队的 Agent（disabled 交给服务端二次校验兜底） |
| onSubmit / onCreateRoom | 提交 PATCH / 创建群聊房间 | 保存成功后由 hook 写回 team full/light 缓存并失效 teams + canvas 查询 |
| archivePending / onArchive | 归档危险区接线（可选；未接线不渲染该节） | 二次确认走 `VConfirmDialog` tone="danger"；成功后关闭对话框并走 `afterTeamArchived` 缓存清理 |
| locked（内部派生） | 系统队/归档队只读 | 输入禁用、隐藏保存、成员操作与危险区，展示锁提示 |

### 成员行编辑与预校验
- 已有成员行内提供：role（`VNativeInput`，单行，镜像后端 trim_lines max_lines=1）、purpose（`VTextarea`，最多 4 行）、responsibilities（`VTextarea` 每行一条，去空行、截断 8 条），全部在 `teamSettingsModel` 的 `teamMemberRoleFromInput` / `teamMemberPurposeFromInput` / `teamMemberResponsibilitiesFromInput` 归一化；dirty 判定与 payload 构建共用同一归一化，无差异的往返不产生 members 变更。
- 提交仍走 PATCH 聚合 members 全量替换；服务端 `canvas_normalize` 兜底 trim。
- 模型字面值不在此面编辑（模型权威在 agents.json，行内保留状态 chip + 跳转）。

### 非职责
- 不嵌模型编辑、不写 Agent 配置（Agent 目录是唯一权威）。
- 不提供第二套群聊消息面；房间跳转走 `/chat?room=`；团队房成员不在此直改（由 PATCH members 后服务端同步）。
- 不直接写画布；members→canvas 投影由后端 `update_team` 完成。

### 视觉与状态
- 默认 / 保存中（isPending，隐藏关闭）/ 错误行（error 文案）/ 系统队锁定（lockedNotice + 全禁用）/ 空成员（emptyMembers 提示）/ 未配模型（warning chip + 配置链接）/ 危险区（danger 边框节 + `VConfirmDialog` danger 确认，归档中 isPending）。

### 实现落点
- 源码：`web/src/routes/teams/TeamSettingsDialog.tsx`（面）、`teamSettingsModel.ts`（纯模型 + zh/en copy）、`useTeamSettingsActions.ts`（mutation + 缓存失效，含归档）、`TeamSettingsToolbarAction.tsx`（顶栏自包含入口）。
- 挂载点：`renderTeamsShellFrame.tsx` `renderTeamsShellToolbar` 的 actions 槽（board/canvas 共用顶栏）。

### 反冗余
- 与 `TeamCreateDialog` 的边界：创建向导管「从模板建队」，本面对「已存在团队」的聚合配置。
- 与 `TeamNodeBindingPanel` 的边界：节点绑定面板服务画布选中节点，本面服务团队级聚合配置且不依赖画布。
- 归档入口唯一：画布工具栏不保留第二个归档按钮；`updateTeam(` 仅允许 `useTeamSettingsActions` 调用（有 grep 契约测试锁定）。
- 顶栏配置包按钮使用短可见标签「导入」「导出」，完整名称保留在 `aria-label` 中，避免窄屏换行。
- 禁止再新建第二套团队编辑表单或成员管理面。

---

## TeamHomeSurface

### 功能
已确认的三栏分工：左栏选择团队/人物，中间展示讨论、任务、记录和只读画布，右栏统一轮次、任务、人物与广播操作。右栏保持一个区域，不新增标签页；任务与成员表单按需在栏内展开，编辑字段独立滚动，保存/取消保持可达。窄屏复用 VCanvasWorkbenchPage 的左右侧抽屉，桌面三栏继续使用 WORKBENCH_LAYOUT_IDS.teams 的共享宽度记忆。

普通团队的任务首页：突出当前任务、该轮结论与近期发言，并提供启动/停止、群聊跳转和组织结构入口。

### 适用范围
- **适用**：普通团队工作台 canvas 模式的默认内容。
- **不适用**：科研工作流团队。科研团队仍由其阶段工作区和团队沟通面承载。

| 场景 | 选择 |
| --- | --- |
| 普通团队进入工作台 | 默认显示 `TeamHomeSurface` |
| 查看成员组织关系 | 中间画布只读展示；成员绑定使用右栏人物操作，复用团队设置模型与 mutation |
| 查找完整群聊历史 | 用「打开群聊」进入关联房间 |

### 使用方式
```tsx
// Teams canvas page 注入现有团队查询与 mutation；发言读取共享群聊 timeline 投影。
<TeamHomeSurface
  selectedTeam={selectedTeam}
  latestTeamRound={latestTeamRound}
  linkedChatRoomId={linkedChatRoomId}
  linkedRoomDetail={linkedRoomDetail}
  onStartTeamRound={startTeamRound}
  onStopTeamRound={stopTeamRound}
/>
```

| 内容 | 设计注意 |
| --- | --- |
| 当前任务 / 状态 / 更新时间 | 以详情中的 `latestTeamRound` 为当前轮元数据，避免 timeline 追赶时显示上一轮状态 |
| 近期发言与结论 | 使用 `useGroupRoomTimeline` 投影；只展示与 `latestTeamRound.roundId` 相同的轮次。新轮详情先到时暂不挂载上一轮内容；投影处于 legacy fallback 时沿用详情轮次 |
| timeline 刷新 | 房间首次详情不重复触发请求；后续 `updatedAt` 或当前轮更新时间变化时失效该房间 timeline 缓存 |
| 发言内容 | 工作台中复用完整原生 Chat 的时间线与 composer；独立摘要 fallback 继续复用 `ChatGroupMessageBody`、最多显示当前轮末尾 4 条，不另造过滤规则 |
| 轮次摘要 | 结论直接展示；服务端“参与者成功发言”计数摘要放入折叠的轮次结果，不冒充讨论结论 |
| 主动作 | 空闲时提交下一轮任务，运行时停止前确认且保留已有产出；群聊未关联时提供同步入口 |
| 组织结构切换 | 页面局部切换，组织画布提供明确返回动作；切换团队时回到首页 |
| 布局 | 桌面复用灰色左右栏与白色圆角中心列，左栏顶部切换团队，团队群聊与成员会话同列；画布与对话共用外框和栏宽记忆 |

### 非职责
- 不复制群聊时间线、消息发送/广播能力或团队历史列表。
- 不自建轮次状态、不合成执行阶段；轮次元数据来自 `latestTeamRound`，发言内容复用群聊 timeline 投影。
- 不直接写画布；members→canvas 投影由后端 `update_team` 完成。

### 实现落点
- 源码：`web/src/routes/teams/TeamHomeSurface.tsx`；样式归属同目录的 `TeamHomeSurface.styles.ts`；挂载与首页/组织结构切换在 `renderTeamsWorkbenchCanvasPage.tsx`。
- 预览边界：这是依赖当前团队与原生群聊 timeline 的路由组合，不在通用组件目录构造第二套静态会话；状态与交互由同目录 `TeamHomeSurface.test.tsx`、团队/群聊隔离预览及真实只读数据的浏览器检查覆盖。

### 视觉与状态
- 读取中、读取失败、未关联群聊、空成员、运行与停止中均沿用现有状态和操作；失败原因保持可读。
- 新轮次的消息投影未追上时显示同步提示；长发言沿用群聊的显式展开，桌面和窄屏均保留独立阅读滚动。
- 主页主阅读面沿用共享 panel 圆角与细边，保持无阴影；内部标题、消息、任务及表单依靠分隔和间距组织，不再增加嵌套表面。所有真实操作与内容仍由原组件提供。
- 科研团队从原生群聊切换到组织画布时保留团队归属，显式画布选择不会被科研流程链接归一化覆盖；组织画布保持只读并可切回原群聊。
- 画布在数据加载后挂载或重新挂载时重新测量可视区；节点名称与 Agent 名称相同、职责与目的相同时，各只展示一次。机器生成的节点名称优先投影为已关联成员名称。
- 成员详情采用标签与内容分列、长文本换行；滚动详情中的区块保持自然高度。阶段与节点标题限制在自身列内，状态保留独立宽度。
- 科研状态读取失败时展示错误状态，不继续显示加载提示；封存模式只读取已有 Ledger，不启动研究任务或开放写入。

## Generic workflow workspace

The approved workspace composes existing VUI APIs rather than defining another design system: `VCanvasWorkbenchPage` with `WORKBENCH_LAYOUT_IDS.teams`, `VTabs`, `VButton`, VUI form controls and dialogs. White panels, subdued green accent, a dotted sequential canvas and connected node cards retain the approved preview composition. At narrow widths, the rail and inspector become existing recipe drawers; the title and toolbar wrap, and the canvas scrolls independently. No business topic is mandatory.

Owner: `routes/teams/generic/`; adjacent component `.styles.ts` files own visual utilities. Definition edits are explicit drafts until save. Runs use server snapshots and show only canonical execution status, lifecycle records and native result projections. Stop remains “正在停止” until the server confirms termination. Errors stay visible; deletion requires confirmation; dialog text is rendered as plain text. Existing team conversations and historical research records remain accessible.
