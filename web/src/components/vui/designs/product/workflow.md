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

- `running`：system blue 轮廓/轻 ring
- `waiting_human`：琥珀 + 人工图标
- `succeeded`：**中性灰 + check，禁止绿色**
- `failed` vs `blocked`：不同图标（x / ban）与文案
- selected：细蓝色 outline；runtime current：独立运行态标识；二者不得互相覆盖

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

### 布局与 fit 协议（T4）

- 布局：`useWorkflowAutoLayout(graph, createWorkflowLayoutEngine, { fitAll })`；结构 hash 缓存避免重复 ELK 调用。
- fit：`initialFitRevision` 首次布局提交后**仅 fit 一次**，`acknowledgeInitialFit()` 后 status-only 更新不再 fit；`WorkflowCanvasControls`「适应全部」经 `onFitAll` 走同一 fit 路径。

### 阶段分区

- 阶段为 React Flow 父节点（`parentId` + 相对坐标）
- 轻量 surface + 编号标题，不抢节点层级
- stageTone：`idle | active | done | attention`

### 状态/交互约束

- `@xyflow/react` 仅允许在 `renderers/shadcn/workflow/**`（入口 `ShadcnWorkflowCanvas.tsx`）
- 业务路由禁止 import renderer 或 xyflow
- 默认不可拖节点、不可连线（运行态，非编辑器）
- 不提供强制 MiniMap（节点量小时不展示）
- 单击节点 → 选中；点空白 → 取消；键盘可聚焦节点（aria-label 含名称/类型/状态）
- 控件：放大、缩小、适应全部、重置、定位当前节点
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
