# Layout — Page recipes & page roots

## 选型总表

| 布局 | Recipe |
| --- | --- |
| 运维表/队列/工具 | `VDenseOpsPage` |
| 左列表右详情 | `VListDetailPage` |
| 设置+底栏保存 | `VSettingsFormPage` |
| 左 rail + 看板 | `VBoardWorkbenchPage` |
| 画布+检查器 | `VCanvasWorkbenchPage` |
| 仅分栏积木 | `VSplitWorkspace` |
| 底层工作台 section | `VWorkbenchPage` |
| 最简 section | `VPage` |

共享几何 class：`layout/pageRecipeClasses.ts`。

---

## VPage

### 职责
最简页面 section（`data-vui="page"`）。

### 非职责
- 不提供满高 fill / 分栏

### 何时使用
- 被 `VSettingsFormPage` 等组合；极简单页

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 工作台满高 | `VWorkbenchPage` fill 或 dense/list recipe |

### 实现落点
- `layout/VPage.tsx`

---

## VWorkbenchPage

### 职责
工作台页面根；`fill` 时视口网格满高。

### 非职责
- 不规定左中右内容

### 何时使用
- 作为 recipe 内部根；很少被 route 直接用

### 实现落点
- `layout/VWorkbenchPage.tsx`

---

## VDenseOpsPage

### 职责
header + 可选 toolbar + body；默认 fill。

### 何时使用
- Git/Logs/Tools/Usage/Reset、加载空态

### 反冗余
- 不要 `VOpsPage` / `VTablePage` 平行

---

## VListDetailPage

### 职责
header + list/detail/optional aside + layoutId 拖拽。

### 何时使用
- Skills、PromptTemplates、Kernel、审查队列

### 反冗余
- 左队列右详情一律本组件；不要手写双栏

---

## VSettingsFormPage

### 职责
设置：header、滚动 body、粘性 footer。

### 何时使用
- Config

### 实现落点
- 内部 `VPage`（有意，非 workbench fill）

---

## VBoardWorkbenchPage

### 职责
左 rail + 工具条 + 看板主区。

### 何时使用
- Teams 看板；未来同类 board

### 反冗余
- 与 `VListDetailPage` 区别：board 强调工作台内容而非 master-detail 选中

---

## VCanvasWorkbenchPage

### 职责
可选 rail + canvas + inspector。

### 何时使用
- Teams 画布；组织图、记忆图、流程画布

### 反冗余
- 与 Board 互斥选型；不要第三种「graph page」

---

## VSplitWorkspace

### 职责
底层可拖分栏（sidebar/main/aside）。

### 何时使用
- recipe 内部；或过渡期 domain 壳

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 已有匹配 page recipe | 对应 recipe |

### 实现落点
- `layout/VSplitWorkspace.tsx` + `usePersistedPaneResize`
