# Feedback（反馈与浮层）

## VChip

### 功能
状态/标签小片：过滤、分类等轻量元信息展示。默认采用 6px 小圆角与中性底色，不使用按钮式胶囊轮廓。

### 适用范围
- **适用**：列表元信息、非紧急状态徽章。
- **不适用**：强调状态条 → `VStatusChip`/`VStateSurface`；指标键值 → `VMetricChip`；可点击主操作 → 按钮。

| 场景 | 选择 |
| --- | --- |
| 标签/过滤 chip | `VChip` |
| 工作台状态 tone | `VStatusChip` |
| label+value 指标 | `VMetricChip` |

### 使用方式
```tsx
import { VChip } from "@/components/vui";

<VChip>pending</VChip>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children / className | 文案与几何 | 不做主 CTA；短标签不使用大圆角 |
| tone | 语义 | success 保持中性；仅 warning / danger 使用语义告警色 |

### 非职责
- 不做可点击主操作。

### 实现落点
- `primitives/VChip.tsx` → `ShadcnChip`

### 反冗余
- Chip 通用；`VStatusChip`/`VMetricChip` 绑定工作台美学。

---

## VTooltip

### 功能
悬停/焦点时的短解释，把非关键说明外置到控件旁。

### 适用范围
- **适用**：图标按钮释义、截断字段全文、次要 hint。
- **不适用**：错误阻断说明 → `VErrorSummary`；持久帮助 → `VContextualHint` 或内联。

| 场景 | 选择 |
| --- | --- |
| 图标释义 | `VTooltip` |
| 标题旁「这是什么」 | `VContextualHint` |
| 表单错误 | 字段 error / `VErrorSummary` |

### 使用方式
```tsx
import { VTooltip, VIconButton } from "@/components/vui";

<VTooltip content="刷新状态">
  <VIconButton label="刷新" icon={...} onPress={...} />
</VTooltip>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `content` | 提示文案 | 短句；关键信息勿只藏在 tip |

### 非职责
- 不做必须先读完才能操作的主文案。

### 实现落点
- `primitives/VTooltip.tsx` → `ShadcnTooltip`

### 反冗余
- 禁止手写 `title=` 作为唯一无障碍解释。

---

## VContextualHint

### 功能
上下文帮助触发器（问号/信息），常与标题配对，提供「这是什么」的持久可发现帮助。

### 适用范围
- **适用**：面板标题旁说明。
- **不适用**：通用任意 hover tip → `VTooltip`。

| 场景 | 选择 |
| --- | --- |
| 标题旁帮助 | `VContextualHint` |
| 图标短释义 | `VTooltip` |

### 使用方式
```tsx
import { VContextualHint } from "@/components/vui";

<VContextualHint label="字段说明">{/* 内容 */}</VContextualHint>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| 触发器 + 内容 | 与 header 配对 | 文案可稍长于 tooltip；触发器只用轻描边问号，不加第二层圆框 |

### 非职责
- 不做通用 tooltip 替代一切 hover。

### 实现落点
- `primitives/VContextualHint.tsx`

### 反冗余
- 不新建 `VHelpIcon` / `VInfoTip`。

---

## VDialog

### 功能
模态对话框容器：打断主流程的编辑/说明，带遮罩与焦点陷阱。

### 适用范围
- **适用**：需打断主流程的确认/编辑表单。
- **不适用**：仅 yes/no 危险确认 → `VConfirmDialog`；非模态 → `VPopover`/`VTooltip`。

| 场景 | 选择 |
| --- | --- |
| 多字段编辑模态 | `VDialog` |
| 删除确认 | `VConfirmDialog` |
| 非模态短面板 | `VPopover` |

### 使用方式
```tsx
import { VDialog } from "@/components/vui";

<VDialog open={open} onOpenChange={setOpen} title="编辑">
  {body}
</VDialog>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `open` / `onOpenChange` | 受控开关 | 关闭后焦点回触发器 |
| title / children | 标题与正文 | 正文内部可滚动 |

### 非职责
- 不做抽屉；不做动作菜单（`VDropdownMenu`）。

### 实现落点
- `primitives/VDialog.tsx` → `ShadcnDialog`

### 反冗余
- 禁止 route 内 `fixed inset-0` 手写遮罩。

---

## VConfirmDialog

### 功能
标准确认对话框（危险/普通），统一删除、归档等不可逆操作的确认交互。

### 适用范围
- **适用**：删除、归档、不可逆操作确认。
- **不适用**：复杂多步表单 → `VDialog` + body。

| 场景 | 选择 |
| --- | --- |
| 危险确认 | `VConfirmDialog` |
| 多步编辑 | `VDialog` |

### 使用方式
```tsx
import { VConfirmDialog } from "@/components/vui";

<VConfirmDialog
  open={open}
  onOpenChange={setOpen}
  title="删除该项？"
  confirmLabel="删除"
  onConfirm={onDelete}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / confirm / cancel | 文案 | 危险操作用 danger 确认 |
| `onConfirm` | 确认回调 | pending 时禁用重复点 |
| `onCloseAutoFocus` | Radix 关闭后焦点回调 | 删除等等待 composer 接管的场景可 `preventDefault` |

### 非职责
- 不做复杂多步表单。

### 实现落点
- 与 `VDialog` 同文件族

### 反冗余
- 禁止每个域一个 `XxxConfirmModal`。

---

## VDropdownMenu

### 功能
下拉菜单 / 右键锚定菜单：操作列表（含危险项），Radix 浮层对齐。

### 适用范围
- **适用**：按钮触发操作表；右键/坐标锚定上下文菜单。
- **不适用**：分段浏览 → `VTabs`；表单单选 → `VSelect`；复杂命令面板 → 域实现或后续 `VCommand`。

| 场景 | 选择 |
| --- | --- |
| 更多操作 | `VDropdownMenu` |
| 表单枚举 | `VStringSelect` |
| 分段 tab | `VTabs` |

### 使用方式
```tsx
import { VDropdownMenu } from "@/components/vui";

<VDropdownMenu
  trigger={<VButton variant="ghost">更多</VButton>}
  items={[
    { id: "edit", label: "编辑", onSelect: onEdit },
    { id: "del", label: "删除", danger: true, onSelect: onDelete },
  ]}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `trigger` / `items` | 触发器与菜单项 | danger 项视觉区分 |
| `position` + 受控 open | 右键锚定 | 虚拟 anchor |

### 非职责
- 不做路由级导航本体；不做多级树 Sub（未暴露）。

### 实现落点
- `primitives/VDropdownMenu.tsx` → `ShadcnDropdownMenu`

### 反冗余
- 禁止手写 `role="menu"` + `fixed` 坐标面板平行系统。

---

## VPopover

### 功能
非模态浮层面板：trigger + 任意内容（短表单、说明、工具菜单体）。

### 适用范围
- **适用**：工具菜单、状态说明、短表单浮层、可滚动内容面板。
- **不适用**：纯操作列表 → `VDropdownMenu`；模态编辑 → `VDialog`；悬停短文案 → `VTooltip`。

| 场景 | 选择 |
| --- | --- |
| 非模态内容面板 | `VPopover` |
| 动作列表 | `VDropdownMenu` |
| 打断式编辑 | `VDialog` |

### 使用方式
```tsx
import { VPopover, VButton } from "@/components/vui";

<VPopover trigger={<VButton variant="ghost">详情</VButton>}>
  <div className="p-3">...</div>
</VPopover>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `trigger` / children | 触发与面板内容 | trigger 需可 focus |
| `side` / `align` / `open` | 定位与受控 | 避免挡住主 CTA |

### 非职责
- 不做动作列表；不做打断确认；不做纯 tip。

### 实现落点
- `primitives/VPopover.tsx` → `ShadcnPopover`

### 反冗余
- 禁止 cluster + absolute + pointerdown / CSS hover 显隐平行系统。
