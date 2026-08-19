# Product workflow surfaces

## VWorkflowCanvas

### 功能

三阶段科研工作流**运行态画布**：阶段分组、语义节点（Agent / 人工 / 系统 / 决策 / 起终点）、节点运行状态、语义边（主路径 / 门禁 / 重跑 / 修订 / 晋级 / 回滚 / 停止）、当前运行高亮、UI 选中与 Inspector 联动、画布内 pan/zoom 与「定位当前 / 适应全部」。

布局所有权：**ELK 引擎 + auto-layout hook**（`renderers/shadcn/workflow/useWorkflowAutoLayout.ts`）。生产走 `?worker` 构建的 `elkjs` worker 引擎（`workflowElkClient.createWorkflowLayoutEngine`），每次画布挂载创建一次、卸载 terminate（StrictMode 不遗留 Worker）。结构不变时 status-only 更新**不触发重新布局**（几何零跳变），拓扑/尺寸变化才重跑 ELK，失败保留 last-good 并标记 degraded。

### 适用范围

- Challenge Cup / research process workspace 唯一阶段导航与运行观察表面
- 只读运行投影 + UI selection（`selectedNodeId` 不得回写 runtime）
- graph 输入使用公共 `WorkflowLayoutInput`（从 `components/vui` 导入，禁止 route 直连 renderers/shadcn）

### 使用方式

```tsx
import { VWorkflowCanvas, type WorkflowLayoutInput } from "@/components/vui";
import { projectionToCanvasGraph } from "./researchProcessGraphModel";

const graph: WorkflowLayoutInput = projectionToCanvasGraph(projection);

<VWorkflowCanvas
  graph={graph}
  selectedNodeId={selectedNodeId}
  runtimeCurrentNodeIds={projection.run.runtimeCurrentNodeIds}
  onSelectNode={setSelectedNodeId}
  height="100%"
/>
```

#### 可延展蛇形模式

挑战杯科研流程正式工作台使用 `layoutMode="serpentine"`：阶段区域纵向堆叠，阶段内部任务横向铺开并逐阶段反向折返；它仍共享一个 React Flow viewport、同一运行投影和同一节点选择事实源。该模式可配合 `showMiniMap` 提供大型流程定位，但小地图只承担导航，不成为第二张流程图或第二状态写入者。

`stage-columns` 保留为默认兼容模式；调用方不得自行复制 renderer 或直接引入 `@xyflow/react` 来实现另一套几何。

节点在 `serpentine` 模式下使用约 `244 × 102` 的紧凑科研步骤卡：第一行仅保留类型图标、名称与执行主体，第二行展示状态徽章和一条运行摘要，底部展示中文角色与绑定结果。长描述、输入/输出、检查项与技术 `agentId` 不在画布常驻，完整信息进入节点 tooltip 与 Inspector。卡片用实底 `--vui-surface-panel` 加 `--vui-elevation-1`（浅色即白卡）；状态按四桶经**边框 + 顶部强调条 + 状态徽章**三通道表达：完成（`--state-success` 绿）、进行（`--accent-cool` 蓝）、等待/关注（`--state-warning` 琥珀）、失败（`--state-error` 红）、待运行（最淡灰）；选中另用细蓝色 outline，不与状态色冲突。

该模式使用三条阶段带做分组：实底为 `accent-cool` 混入 `--vui-surface-workspace`（idle 8% / active 12% / done 4%；attention 用 warning 10%），描边略强于 `border-subtle`。禁止洗白渐变、白色内高光，也禁止三阶段带换色相（蓝/琥珀/红留给运行状态）。阶段头包含编号、名称、完成计数和短进度条；**阶段头的小面积聚合指示器例外于换色相禁令**：编号徽章与进度条按 tone 着色（done 绿、active 蓝、attention 琥珀），并附状态 chip（已完成/进行中/需关注），让阶段完成度不依赖逐节点扫读。不得改全局 `--vui-surface-region`（浅色 rail 等于侧栏白底）。普通相邻边默认不常驻标签；只有 `knowledge_package`、`smoke`、`promotion` 和决策/回路语义常显，其他标签仅在 hover 或 active/attention 状态出现。跨阶段交接使用对齐节点之间的一条短叙事桥；同协议重跑沿所在阶段底部的局部反馈轨道返回，禁止绕画布或阶段绘制大矩形回路。ELK 仍负责节点顺序、阶段位置与空间预算，renderer 只收敛这两类叙事边的可见几何。

画布必须提供平移、缩放、适应全部和定位当前工作；页面本身不得产生横向滚动。

`VCanvasWorkbenchPage` 的 inspector 列只在选中节点或打开 Agent / 时间线 / 团队 / 题目进度 / 创建运行 等工具面板时挂载。未选节点时不要用「选择流程节点」空状态占住 300–520px 白列，让画布吃满主区。点击节点或工具按钮后再展开 inspector。

### 节点视觉种类

| visualKind | 用途 |
| --- | --- |
| `start` / `end` | 流程锚点 |
| `agent_task` | 普通 Agent 任务 |
| `human_gate` | 人工门禁（等待确认） |
| `system_task` | 系统执行 |
| `decision` | 迭代决策多出口 |

### 运行状态

严格使用 `NodeRunStatus`：`pending | ready | running | waiting_human | succeeded | failed | blocked | skipped | stale | cancelled`。

- `running`：system blue tint/轮廓/轻 ring
- `waiting_human`：琥珀 + 人工图标
- `succeeded`：`--state-success` 绿边框 + 绿顶部强调条 + check 徽章（与 pending 在边框、强调条、徽章三通道拉开；沿用 VUI 既有 success token，与 VDenseTable 等一致）
- `failed` vs `blocked`：不同图标（x / ban）与文案
- selected：细蓝色 outline；runtime current：独立运行态标识；二者不得互相覆盖
- 阶段头：`done` 绿实心编号 + 对勾徽章，`active` 蓝实心编号 + 旋转进行中徽章，`attention` 琥珀实心编号 + 需关注徽章；进度条随 tone 着色

### 边语义

| semanticKind | 说明 |
| --- | --- |
| `main` | 主流程；auto 标签默认隐藏，hover 显示 |
| `human_gate` | 人工门禁边，标签常显 |
| `decision_branch` / `rerun` / `revise` / `promote` / `rollback` / `stop` | 条件与回路；决策节点多 Handle 出边；标签常显；回路外侧 routing |

pathState：`idle | traversed | active | attention | danger` — 仅由 nodeRuns + runtimeCurrent 推导，**不猜测**未观测的决策分支选择。所有有向边带箭头 marker。

#### 边几何（引擎所有权，T3）

- 边路径由 `workflowElkEdgePath.sectionsToSvgPath` 从引擎 `WorkflowEdgeSection[]` 直接生成（绝对坐标正交 section，无重复与虚假连接线）；生产源码禁止 smooth-step 重路由（`getSmoothStepPath`），有契约测试断言源码不含该符号。
- 标签锚点由引擎 `labelBounds`（中心）决定，缺失时回退首 section 中点；三阶段统一 viewport，跨阶段边同坐标空间。
- z-index 层级固定：stageRegion `0` < edge `1` < task node `2`；**边不浮在节点上方**，选中/hover 不抬升 zIndex，用描边加粗与变色表达。

### 布局与 fit 协议（T4 + 两级布局 2026-08-08 + 外层真实 ELK 2026-08-08b）

- 布局：`useWorkflowAutoLayout(graph, createWorkflowLayoutEngine)` 内部走**两级布局**（`layoutTwoLevel`）。默认 `stage-columns` 为阶段 A 各自 ELK DOWN、阶段 B 外层 ELK RIGHT；`serpentine` 为阶段 A 依次 RIGHT / LEFT / RIGHT、阶段 B 外层 ELK DOWN。两种模式都只包含真实 edges；跨阶段边通过 label spacer 交给 ELK 分配通道，任务绝对坐标 = meta 位置 + 阶段本地坐标，结构 hash 包含 layout mode 并避免重复布局。
- 标签契约：`workflowEdgeLabelGeometry` 是唯一几何权威——布局 spacer 尺寸与渲染 label box 完全一致（同宽高、同截断策略）；长标签截断后矩形仍参与布局；禁止渲染后 transform 移动。
- 目标：默认模式阶段内主链单列；蛇形模式阶段内横向铺开、阶段纵向延展；gap 由 ELK 按内容自动决定（非固定值）。
- fit：`useWorkflowInitialFit` 编排——`initialFitRevision` 只在 **settled 布局**提交后设置；等待节点进入 React Flow 内部（`useNodesInitialized`）并在下一帧执行**仅一次**；校准重排不取消 pending fit，拓扑切换（structureKey 变化）取消并重新武装；`acknowledgeInitialFit()` 后 status-only 更新不再 fit。`<ReactFlow>` 不设隐式 `fitView`；「适应全部」经 `onFitAll` 显式 fit。

### 阶段分区

- 阶段为 React Flow 父节点（`parentId` + 相对坐标）
- 分组靠明度（workspace 实底 + 不透明卡片），编号标题不抢节点层级；状态色不用于阶段带身份，仅出现在阶段头的小型聚合指示器（编号徽章 / 状态 chip / 进度条）
- stageTone：`idle | active | done | attention`

### 状态/交互约束

- `@xyflow/react` 仅允许在 `renderers/shadcn/workflow/**`（入口 `ShadcnWorkflowCanvas.tsx`）
- 业务路由禁止 import renderer 或 xyflow
- 默认不可拖节点、不可连线（运行态，非编辑器）
- MiniMap 默认关闭；长流程由生产工作台显式 `showMiniMap` 开启
- 单击节点 → 选中；点空白 → 取消；键盘可聚焦节点（aria-label 含名称/类型/状态）
- 控件：放大、缩小、适应全部、定位当前工作
- loading/empty：由调用方 `VStateSurface` / `VEmptyState` 处理
- **页面壳**：`VCanvasWorkbenchPage`，`layoutId` = `WORKBENCH_LAYOUT_IDS.researchFlow`
- 画布默认 `height="100%"`；fill 宿主 absolute inset
- **禁止**固定 `height={440}` 式死高

### 文件结构

- product：`VWorkflowCanvas.tsx`、`workflowCanvasTypes.ts`、`workflowCanvasModel.ts`
- renderer：`renderers/shadcn/workflow/*`（节点/边/布局/状态/控件各一文件）

## 假说先行区域

### 功能

科研流程画布的**显示层第一类区域**：把假说先行链（选假说 → 讨论·评审 → 资料搜集 → 再讨论 → 收敛）合成为 `stages[0]` 的「假说先行」阶段带，由链台账状态驱动，不改动任何执行拓扑。区域由路由层纯函数 `buildHypothesisFirstCanvasRegion`（`routes/teams/research-workflow/hypothesisFirstCanvasRegion.ts`）从链状态 + 会议轮 + 搜集请求 + 续轮台账 + 选择记录产出 `{ stage, nodes, edges }` 片段，再经 `composeHypothesisFirstGraph` 插入主图；无链活动时区域不合成，画布保持原 16 节点形态。

卡片映射（nodeId 均以 `hf_` 前缀，Inspector 据此路由到链摘要面板）：

| 卡片 | nodeId | visualKind | 状态事实源 |
| --- | --- | --- | --- |
| 假说选择 | `hf_selection` | `human_gate` | 最新选择记录存在→`succeeded`，否则 `waiting_human` |
| 第 N 轮讨论·评审 | `hf_meeting_<roundIndex>` | `agent_task` | 会议 `open→running`、`summarizing/awaiting_approval→waiting_human`、`closed` 有纪要→`succeeded`、无纪要→`blocked`（fail-closed） |
| 资料搜集 · 缺口 j | `hf_collection_<requestId>` | `system_task` | 请求 `pending→pending`、`handed_off`/有交接引用→`succeeded`、`failed→failed` |
| 假说收敛门 | `hf_convergence_gate` | `human_gate`（单出口门，非迭代决策五出口 `decision`） | `hypothesisConverged→succeeded`；预算耗尽未收敛→`blocked`；否则 `pending` |

边语义（只画台账里真实存在的关联；常显复用现有叙事标签过滤 `workflowEdgeKeepsNarrativeLabel`——只有叙事语义/门禁种类的边在蛇形模式保留标签，`main`+`auto` 边标签始终 hover 才显示，不为区域开口子）：

| 边 | 语义 | 标签 |
| --- | --- | --- |
| `hf_e_sel_m1` 选择→首轮会议 | `decision_branch`（人工选定即分支决策） | 常显「选定假说」 |
| `hf_e_m{i}_c{j}` 会议→其触发的搜集请求 | `decision_branch` | 常显「搜集决策」 |
| `hf_e_c{j}_m{i+1}` 已交接搜集→续轮会议 | `main`（gateKind `knowledge_package`，交接内容即知识包） | 常显「知识包交接」 |
| `hf_e_m{i}_m{i+1}` 无搜集直接续轮 | `main` | 「再讨论」（hover 显示） |
| `hf_e_m{last}_gate` 最新会议→收敛门 | `main` | 无标签 |
| `hf_e_m1_stage1` 首轮会议→`source_finding` | `human_gate`（gateKind `knowledge_package`） | 常显「首轮搜集范围就绪」 |
| `hf_e_gate_stage2` 收敛门→`hypothesis_design` | `human_gate`（gateKind `knowledge_package`） | 常显「假说集就绪」 |

阶段头计数：区域 stage 通过 `WorkflowCanvasStageInput.progress = { completed: 已闭环轮次, total: 轮次预算 }` 覆盖默认的「成功卡数/卡数」，显示「已闭环轮次/预算」（如 2/3）；stageTone 仍复用成员卡聚合规则。`progress` 是可选字段，不进入结构 hash，更新不触发重排。

### 适用范围

- 仅假说先行题目（存在选择记录或 scoped 会议/搜集请求）的科研流程工作区画布；定义视图与运行视图同样合成。
- 区域卡片无后端 node detail：Inspector 显示链摘要 + 深链赛题详情对应面板（选择 / 团队讨论 / 假说轮次时间线），`useNodeDetailState` 对 `hf_` 前缀节点直接返回 empty。
- 轮次增加 = 拓扑变化 → 结构 hash 变化 → 自动重排；状态翻转不重排。

### 使用方式

```tsx
import { buildHypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";
import { composeHypothesisFirstGraph } from "./researchProcessGraphModel";

const base = projectionToCanvasGraph(projection);
const region = buildHypothesisFirstCanvasRegion({
  chainState, meetings, collectionRequests, reviewRoundLinks, selection,
});
const graph = composeHypothesisFirstGraph(base, region); // region 为 null 时原样返回 base
```

链数据由 `useHypothesisFirstChain(teamId, questionId)`（React Query，questionId 为空不发请求）提供；run SSE 事件经 `useHypothesisFirstChainInvalidation` 防抖失效相关 query。

### 限制

- 不接真实 node command adapters（Inspector 仍走现有 ops）
- 不改变迭代决策后端语义
- 不实现 SSE
- 不引入第二套设计系统 / HeroUI
