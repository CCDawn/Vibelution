# Layout — Chrome

## VRouteHeader

### 功能
路由级标题带：eyebrow / title / meta / actions，工作台顶栏统一形态。

### 适用范围
- **适用**：任何 page recipe 顶栏、Launcher/Evolution 顶栏。
- **不适用**：侧栏/面板标题 → `VPanelHeader`；全局 App 顶栏导航不在本组件。

| 场景 | 选择 |
| --- | --- |
| 页面标题 + 右侧操作 | `VRouteHeader` |
| 侧栏标题 | `VPanelHeader` |

### 使用方式
```tsx
import { VRouteHeader, VButton } from "@/components/vui";

<VRouteHeader
  eyebrow="Ops"
  title="日志"
  meta="只读"
  actions={<VButton variant="secondary">刷新</VButton>}
/>
// 仅操作条、隐藏 intro（监督聚焦）
<VRouteHeader title="…" hideIntro actions={controls} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| eyebrow / title / meta | 标题列 | hideIntro 时不渲染 intro |
| actions | 右侧操作 | 放 VTabs / VButton 等 |
| `hideIntro` | 只保留 actions 紧凑条 | 勿再用 CSS 藏第一列 |

### 非职责
- 不做侧栏标题。

### 实现落点
- `layout/VRouteHeader.tsx`

### 反冗余
- 禁止 route 自绘 `h1 + subtitle` 顶栏。

---

## VPanelHeader

### 功能
面板/侧栏标题 + 可选 contextual hint，用于队列与列表头。

### 适用范围
- **适用**：队列面板、列表头、inspector 标题。
- **不适用**：整页路由标题 → `VRouteHeader`。

| 场景 | 选择 |
| --- | --- |
| 侧栏标题 | `VPanelHeader` |
| 页面标题 | `VRouteHeader` |

### 使用方式
```tsx
import { VPanelHeader } from "@/components/vui";

<VPanelHeader title="队列" hint="说明…" actions={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / hint / actions | 标题与帮助 | 密度低于 route header |

### 实现落点
- `layout/VPanelHeader.tsx`

---

## VTabs

### 功能
工作台分段切换（Radix Tabs）：固定分段过滤/模式，选中态 `data-[state=active]`。

### 适用范围
- **适用**：面板内多 section、轨道切换、过滤分段。
- **不适用**：路由级导航 → `VRouteLinkButton`；完整 wizard 步骤器；列表行选中。

| 场景 | 选择 |
| --- | --- |
| 模式/过滤分段 | `VTabs` |
| 页面导航 | `VRouteLinkButton` |
| 列表选中 | 列表组件 + 选中态 |

### 使用方式
```tsx
import { VTabs } from "@/components/vui";

<VTabs
  density="compact"
  value={mode}
  onValueChange={setMode}
  items={[
    { id: "a", label: "A" },
    { id: "b", label: "B" },
  ]}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| items | id/label/disabled/content | content 可选 |
| value / onValueChange | 受控 | 固定分段，非无限列表 |
| density / listClassName | 密度与域几何 | 选中用 data-state，勿 twin Active class |

### 非职责
- 不做路由导航；不做 wizard。

### 实现落点
- `layout/VTabs.tsx`

### 反冗余
- 禁止 `styles.tabActive` 平行 tab 系统。

---

## VToolbar

### 功能
操作工具条容器（`role=toolbar`），承载过滤与批量操作。

### 适用范围
- **适用**：DenseOps `toolbar` 槽；需要语义 toolbar 的自定义过滤条外壳。
- **不适用**：需要「条带」美学边框底色 → 可叠 `VDenseToolbar`。

| 场景 | 选择 |
| --- | --- |
| 语义工具条 | `VToolbar` |
| 带边框工具条带 | `VDenseToolbar` |

### 使用方式
```tsx
import { VToolbar, VButton } from "@/components/vui";

<VToolbar ariaLabel="过滤">
  <VButton density="compact">全部</VButton>
</VToolbar>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| ariaLabel / children | 分组与操作 | 子节点用 V* 控件 |

### 实现落点
- `layout/VToolbar.tsx`

---

## VActionGroup

### 功能
一组相关操作的 aria 分组，声明操作簇边界。

### 适用范围
- **适用**：画布工具簇、批量操作簇。
- **不适用**：替代整个 toolbar 布局系统。

| 场景 | 选择 |
| --- | --- |
| 工具簇 | `VActionGroup` |
| 整条工具条 | `VToolbar` |

### 使用方式
```tsx
import { VActionGroup, VButton } from "@/components/vui";

<VActionGroup aria-label="批量">
  <VButton>全选</VButton>
  <VButton variant="danger">删除</VButton>
</VActionGroup>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| aria-label / children | 分组名与按钮 | 危险操作靠右或 danger |

### 实现落点
- `layout/VActionGroup.tsx`

---

## VStatusStrip

### 功能
横向状态摘要条（多组 label/value），轻量页头指标。整组共用一个低对比表面，单项不模拟可点击按钮。

### 适用范围
- **适用**：工作台顶部轻量指标。
- **不适用**：更重指标卡 → `VMetricStrip`；单 pill → `VMetricChip`。

| 场景 | 选择 |
| --- | --- |
| 轻量 status | `VStatusStrip` |
| 多指标卡 | `VMetricStrip` |

### 使用方式
```tsx
import { VStatusStrip } from "@/components/vui";

<VStatusStrip items={[{ label: "运行中", value: "2" }]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| items | label/value/tone | 标签和值相邻；tone 只强调 value，不为每项生成彩色胶囊 |

### 实现落点
- `layout/VStatusStrip.tsx`

---

## VWorkbenchPowerMenu

### 功能
工作台生命周期电源菜单：重启 / 停止 / 强制停止 的**唯一产品入口形态**。

### 适用范围
- **适用**：AppShell 顶栏电源；Launcher 运维条 lifecycle；与顶栏一致的 power 入口。
- **不适用**：域内「停止任务」→ 域 `VButton`；非 lifecycle 更多菜单 → `VDropdownMenu`。

| 场景 | 选择 |
| --- | --- |
| 重启/停止工作台 | `VWorkbenchPowerMenu` |
| 停止单任务 | 域按钮 |

### 使用方式
```tsx
import { VWorkbenchPowerMenu } from "@/components/vui";

<VWorkbenchPowerMenu
  variant="icon"
  labels={{ menu: "电源", restart: "重启", stop: "停止", forceStop: "强制停止" }}
  onAction={(action) => requestLifecycle(action)}
  showForceStop
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| labels / onAction | 文案与回调 | 不直连 Launcher HTTP |
| variant | icon / labeled | 顶栏 vs 工具条 |
| *Disabled / showForceStop | 分项 | force 为 danger |

### 非职责
- 不实现 beforeunload / active-work 文案；不替代 start/refresh 主按钮。

### 实现落点
- `product/workbench-shell/VWorkbenchPowerMenu.tsx`

### 反冗余
- 禁止 AppShell/Launcher 各写一套 power 菜单。
