# Product workflow surfaces

## VWorkflowCanvas

### 功能

三阶段科研工作流画布：阶段分区、任务节点、运行当前高亮、选中节点与内部 pan/zoom。

### 适用范围

- Challenge Cup / research process workspace 唯一阶段导航表面
- 只读运行投影 + UI selection（`selectedNodeId` 不得回写 runtime）
- graph 输入使用公共 `WorkflowLayoutInput`（从 `components/vui` 导入，禁止 route 直连 renderers/shadcn）

### 使用方式

```tsx
import { VWorkflowCanvas, type WorkflowLayoutInput } from "@/components/vui";

<VWorkflowCanvas
  graph={layoutInput}
  selectedNodeId={selectedNodeId}
  runtimeCurrentNodeIds={runtimeCurrentNodeIds}
  onSelectNode={setSelectedNodeId}
/>
```

### 状态/交互约束

- `@xyflow/react` 仅允许在 `renderers/shadcn/ShadcnWorkflowCanvas.tsx`
- 业务路由禁止 import renderer 或 xyflow
- 不提供独立 MiniMap
- 页面不横向滚动；平移缩放在画布内部
- selected：outline
- runtime current：ring
- blocked / waiting_human 等 run 状态由调用方标题与 inspector 展示，画布不把 blocked 误映射为 failed
- loading/empty：由调用方 `VStateSurface` / `VEmptyState` 处理
- **页面壳**：必须用 `VCanvasWorkbenchPage`（与 `TeamsCanvasComposer` 同构），`layoutId` 用 `WORKBENCH_LAYOUT_IDS.researchFlow`
- 嵌入 Teams board 时：`hideHeader`（壳已有团队标题），动作放 `toolbar`；canvas 外包 `flex h-full min-h-0 flex-1` + 内层 `flex-1 overflow-hidden`
- 画布默认 `height="100%"`；React Flow 在 fill 模式下用 absolute inset 填满宿主（与固定 px 高度互斥）
- **禁止** `height={440}` + 下方再 `flex-1` 空面板
- Inspector 走 recipe `aside`；未选节点用 `VEmptyState`
- 外层 `challengeWorkspaceBody` 须 `overflow-hidden`，避免 fill 子项被压成内容高度 + 滚动空白层
