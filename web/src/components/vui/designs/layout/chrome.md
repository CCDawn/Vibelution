# Layout — Chrome

## VRouteHeader

### 职责
路由级标题带：eyebrow / title / meta / actions。

### 非职责
- 不做侧栏标题（用 `VPanelHeader`）

### 何时使用
- 任何 recipe 顶栏、Launcher/Evolution 顶栏

### 反冗余
- 禁止 route 自绘 `h1 + subtitle` 顶栏而不走本组件（极特殊 hideIntro 除外）

---

## VPanelHeader

### 职责
面板/侧栏标题 + 可选 contextual hint。

### 何时使用
- 队列面板、列表头

---

## VToolbar

### 职责
操作工具条容器（role=toolbar）。

### 何时使用
- DenseOps `toolbar` 槽；自定义过滤条外壳

### 反冗余
- 与 aesthetic `VDenseToolbar`：本组件语义容器；DenseToolbar 带边框底色美学

---

## VActionGroup

### 职责
一组相关操作的 aria 分组。

### 何时使用
- 画布工具簇、批量操作簇

---

## VStatusStrip

### 职责
横向状态摘要条（label/value 项）。

### 何时使用
- 工作台顶部轻量指标

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 更重的指标卡 | `VMetricStrip` |
