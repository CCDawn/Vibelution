# Product — Agent management

> 领域组合层：只服务 Agent 工作台。
> **禁止**在此重新实现按钮/输入；必须组合 VUI primitives。

## AgentPageHeader

### 职责
Agent 管理页顶栏：创建、刷新等。

### 非职责
- 不做全局 app shell 导航

### 反冗余
- 不替代 `VRouteHeader` 成为全站顶栏；仅 Agent 域

---

## AgentFilterRail

### 职责
Agent 筛选侧轨：搜索 + 分组过滤器。

### 何时使用
- Agents 列表左栏筛选

### 反冗余
- 通用筛选轨未来若出现第二消费者，再抽 `VFilterRail`；目前禁止空抽

---

## AgentDenseList

### 职责
Agent 密集列表/表。

---

## AgentBulkActionBar

### 职责
批量操作条。

---

## AgentSummaryStrip

### 职责
Agent 汇总指标条。

### 反冗余
- 组合 `VMetricStrip` 思路；不要平行 SummaryBar

---

## AgentWorkspacePanel

### 职责
Agent 三区工作台组合（filter + list + detail 编排容器）。

### 迁移方向
- 外壳逐步让位给 `VListDetailPage` slots；本组件可缩为 slot 内容

---

## AgentPermissionPresetControl

### 职责
权限预设选择控件。

### 非职责
- 不做权限引擎
