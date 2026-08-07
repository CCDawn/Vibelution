# VWorkflowCanvas

## 功能

三阶段科研工作流画布：阶段分区、任务节点、运行当前高亮、选中节点与内部 pan/zoom。

## 适用范围

- Challenge Cup / research process workspace 唯一阶段导航表面
- 只读运行投影 + UI selection（`selectedNodeId` 不得回写 runtime）

## 使用方式

```tsx
import { VWorkflowCanvas } from "@/components/vui";

<VWorkflowCanvas
  graph={layoutInput}
  selectedNodeId={selectedNodeId}
  runtimeCurrentNodeIds={runtimeCurrentNodeIds}
  onSelectNode={setSelectedNodeId}
/>
```

## 约束

- `@xyflow/react` 仅允许在 `renderers/shadcn/ShadcnWorkflowCanvas.tsx`
- 业务路由禁止 import renderer 或 xyflow
- 不提供独立 MiniMap
- 页面不横向滚动；平移缩放在画布内部

## 状态

- selected：outline
- runtime current：ring
- loading/empty：由调用方 VStateSurface 处理
