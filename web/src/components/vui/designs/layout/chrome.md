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

## VTabs

### 职责
工作台分段切换（Radix Tabs / shadcn 风格 list + 可选 content）。

### 非职责
- 不做路由级导航（用 `VRouteLinkButton` / router）
- 不做完整 wizard 步骤器

### 何时使用
- Agent/Config/面板内多 section 切换
- 替代手写 `button` 行冒充 tab

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 页面主从列表 | `VListDetailPage` |
| 仅两个开关 | 考虑 `VButton` ghost 组或后续 `VSwitch` |

### API 要点
- `items: { id, label, disabled?, title?, content? }[]` — `title` 挂到 trigger（hint / a11y）
- `value` / `defaultValue` / `onValueChange`
- `density`: compact | normal
- `listClassName` / `triggerClassName` — 域几何；选中态用 `data-[state=active]:…`，勿再维护 twin Active class

### 实现落点
- `layout/VTabs.tsx` → `@radix-ui/react-tabs`

### 已迁业务面
- Chat 群索引、Memory 知识模式、Evolution 评测集筛选、Launcher 维护 profile

### 反冗余
- 禁止再写 `styles.tabActive` 平行 tab 系统；扩展本组件
- 复杂键盘轨（Agent 会话条、监督对话 Agent 条）可暂留 domain 实现

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
