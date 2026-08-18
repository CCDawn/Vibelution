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

节点在 `serpentine` 模式下使用约 `244 × 102` 的紧凑科研步骤卡：第一行仅保留类型图标、名称与执行主体，第二行展示状态徽章和一条运行摘要，底部展示中文角色与绑定结果。长描述、输入/输出、检查项与技术 `agentId` 不在画布常驻，完整信息进入节点 tooltip 与 Inspector。卡片状态按四桶整卡表达：完成（`--state-success` 淡绿 tint + 绿色顶部强调条 + 对勾徽章）、进行（`--accent-cool` 淡蓝 tint + 蓝条）、等待/关注（`--state-warning`）、失败（`--state-error`）、待运行（最淡灰）；选中另用细蓝色 outline，不与状态色冲突。

该模式使用三条轻量阶段带，阶段头包含编号、名称、完成计数和短进度条。普通相邻边默认不常驻标签；只有 `knowledge_package`、`smoke`、`promotion` 和决策/回路语义常显，其他标签仅在 hover 或 active/attention 状态出现。跨阶段交接使用对齐节点之间的一条短叙事桥；同协议重跑沿所在阶段底部的局部反馈轨道返回，禁止绕画布或阶段绘制大矩形回路。ELK 仍负责节点顺序、阶段位置与空间预算，renderer 只收敛这两类叙事边的可见几何。

画布必须提供平移、缩放、适应全部和定位当前工作；页面本身不得产生横向滚动。

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
- `succeeded`：`--state-success` 绿 tint + check 徽章（与 pending 在表面、边框、徽章三通道拉开；沿用 VUI 既有 success token，与 VDenseTable 等一致）
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
- 轻量 surface + 编号标题，不抢节点层级
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

### 限制

- 不接真实 node command adapters（Inspector 仍走现有 ops）
- 不改变迭代决策后端语义
- 不实现 SSE
- 不引入第二套设计系统 / HeroUI
