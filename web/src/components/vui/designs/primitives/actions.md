# Actions（按钮族）

> **Agent 速查：** 完整决策表见 [`docs/guides/button-selection.md`](../../../../../../docs/guides/button-selection.md)。
> 默认 **`VButton`**；仅密集命中区用 **`VNativeButton`**；禁止第三种 button 门面与裸 `<button>` 通用化。

## VButton

### 功能
产品主操作按钮：提交、确认、主要 CTA，统一视觉与禁用/加载态。

### 适用范围
- **适用**：工具条、表单提交、对话框主操作、空态 CTA、标准工作台操作。
- **不适用**：纯图标方钮 → `VIconButton`；SPA 导航 link 语义 → `VRouteLinkButton`；画布/多行卡片超密命中 → `VNativeButton`。

| 场景 | 选择 |
| --- | --- |
| 表单提交 / 主 CTA | `VButton` |
| 仅图标 | `VIconButton` |
| 站内路由跳转 | `VRouteLinkButton` |
| 画布节点点击条 | `VNativeButton` |

### 使用方式
```tsx
import { VButton } from "@/components/vui";

<VButton variant="primary" isPending={saving} onPress={onSave}>
  保存
</VButton>
```

| Prop / 变体 | 说明 | 设计注意 |
| --- | --- | --- |
| `variant` | primary / secondary / ghost / danger | 一页一个 primary 焦点 |
| `density` | 高度/内边距密度 | 工具条可 compact |
| `isDisabled` / `isPending` | 禁用 / 异步中 | pending 自带 spinner，勿只改文案 |
| `icon` / `title` | 图标与原生短提示 | `title` 不创建 overlay，适合已有可见文案的轻量补充 |
| `tooltip` / `disabledReason` | 显式浮层说明 | 只有这两个契约创建 Radix tooltip；disabled 要能说清原因 |

### 非职责
- 不负责路由导航语义；不做纯图标方钮；不做密集零浮层命中条。

### 视觉与状态
- **primary**：高对比实心主 CTA；**secondary**：描边；**ghost**：透明；**danger**：错误色。
- focus ring；disabled opacity；长中文允许调用方控制换行。

### 实现落点
- `primitives/VButton.tsx` → `renderers/shadcn/ShadcnButton.tsx`

### 反冗余
- 禁止 `PrimaryButton` / `HeroButton` 等平行按钮；扩展变体改 shared `buttonVariants`。

---

## VIconButton

### 功能
方形图标按钮：刷新、关闭、更多等单图标操作，强制无障碍 `label`。

### 适用范围
- **适用**：工具条图标操作、紧凑 chrome、面板关闭/刷新。
- **不适用**：图标+文字主 CTA → `VButton`；需要明确可见文案的操作 → `VButton`。

| 场景 | 选择 |
| --- | --- |
| 刷新 / 关闭 | `VIconButton` |
| 图标+文字 | `VButton` |

### 使用方式
```tsx
import { VIconButton } from "@/components/vui";

<VIconButton label="刷新" icon={<RefreshCw size={16} />} onPress={onRefresh} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `label` | 必填无障碍文案 | 不进视觉时可只给 SR |
| `icon` | 图标节点 | 尺寸与工具条对齐 |

### 非职责
- 不承担带文字的主 CTA。

### 实现落点
- `primitives/VIconButton.tsx`（组合 `VButton`）

### 反冗余
- 不要为每个图标各建一个 `VRefreshButton`。

---

## VNativeButton

### 功能
原生 `<button>` 门面：密集操作、画布命中、多行卡片，避免浮层与复杂 slot，样式由调用方 class 主导。

### 适用范围
- **适用**：组织画布节点、kanban 卡片脚注、超密集工具条命中区。
- **不适用**：表单主提交、标准工具条、需要统一 primary 视觉 → `VButton`。

| 场景 | 选择 |
| --- | --- |
| 标准工具条 | `VButton` |
| 画布节点 / 极密列表行 | `VNativeButton` |

### 使用方式
```tsx
import { VNativeButton } from "@/components/vui";

<VNativeButton type="button" className={styles.nodeHit} onClick={onSelect}>
  {label}
</VNativeButton>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| 原生 button 属性 | type / onClick / disabled | 与 HTML 一致 |
| `className` | 几乎全部视觉 | 域内样式 map 负责 |

### 非职责
- 不提供 Radix 浮层与完整 variant 系统。

### 实现落点
- `primitives/VNativeButton.tsx`

### 反冗余
- 与 `VButton` 是 **有意双轨**；禁止第三种 button 门面。

---

## VRouteLinkButton

### 功能
React Router 导航按钮：与 `VButton` 同视觉合同，语义是 link（站内跳转）。

### 适用范围
- **适用**：「返回」「打开配置」等站内导航；工作台顶栏/分段导航（`chrome="shell-nav"`）。
- **不适用**：同页 mutation → `VButton`；外链 → 原生 `a` + 外链约定。

| 场景 | 选择 |
| --- | --- |
| 站内路由 | `VRouteLinkButton` |
| 同页动作 | `VButton` |
| 外链 | 原生 `a` |

### 使用方式
```tsx
import { VRouteLinkButton } from "@/components/vui";

<VRouteLinkButton to="/config" variant="secondary">打开配置</VRouteLinkButton>
<VRouteLinkButton to="/agents" chrome="shell-nav" className={styles.navLink}>
  Agents
</VRouteLinkButton>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `to` | 路由目标 | 与 RR 一致 |
| `chrome` | `button`（默认）\| `shell-nav` | shell-nav 不叠按钮填色，由域 CSS 画导航面 |
| `variant` / `density` | 仅 `chrome="button"` | 与 VButton 对齐 |

### 非职责
- 不发起 mutation。

### 实现落点
- `primitives/VRouteLinkButton.tsx`

### 反冗余
- 不要 `VNavButton` / `VLink` 平行 API。
