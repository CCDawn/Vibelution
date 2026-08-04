# Planned recipes（未实现）

> 仅登记意图，**实现前**必须把专节补全到与现成 recipe 同级详细度，并更新 INDEX「拟新增」状态。
> 原则：能复用现有 recipe **禁止**落地本节组件。

## VSessionWorkbenchPage

### 职责（拟）
Chat 会话工作台：状态轨 + 主会话 + 可选工具轨；响应式 overlay。

### 非职责
- 不替代 `VListDetailPage` 的通用主从页

### 为何暂缓
- Chat 含双写宽度与 domain 数学；需先证明 list-detail 不够

### 反冗余
- 落地后 Chat 禁止再手写顶层 shell

---

## VTrackWorkbenchPage

### 职责（拟）
多 track（如监督/自进化）工作台：顶栏 track 切换 + 主列 + 可选次列。

### 为何暂缓
- 先尝试 `VDenseOpsPage` + 内嵌 `VSplitWorkspace`

### 反冗余
- 与 Session 不同：track 是模式切换，不是会话流

---

## VFilterListDetailPage

### 职责（拟）
筛选轨 + 列表 + 详情三列（Agents）。

### 为何暂缓
- 先把筛选放进 `VListDetailPage` 的 `list` 槽

### 反冗余
- 仅当第二消费者出现或 list 槽证伪后再建
