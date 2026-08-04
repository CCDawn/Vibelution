# Feedback（反馈与浮层）

## VChip

### 职责
状态/标签小片：过滤、状态、计数。

### 非职责
- 不做可点击主操作（用按钮）

### 何时使用
- 列表元信息、状态徽章（非紧急）

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 强调状态条 | `VStatusChip` / `VStateSurface` |
| 指标键值 | `VMetricChip` |

### 实现落点
- `primitives/VChip.tsx` → `ShadcnChip`

### 反冗余
- 与 aesthetic `VStatusChip` / `VMetricChip` 分工：Chip 通用；后两者绑定工作台美学

---

## VTooltip

### 职责
悬停/焦点解释：非关键说明外置。

### 非职责
- 不做必须先读完才能操作的主文案（应内联）

### 何时使用
- 图标按钮释义、截断字段全文、次要 hint

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 错误阻断说明 | `VErrorSummary` / 字段 error |
| 持久帮助 | `VContextualHint` 或内联说明 |

### 实现落点
- `primitives/VTooltip.tsx` → `ShadcnTooltip` (Radix)

### 反冗余
- 禁止手写 `title=` 作为唯一无障碍解释（可并存，但不能替代）

---

## VContextualHint

### 职责
上下文帮助触发器（问号/信息），常与 header 标题配对。

### 非职责
- 不做通用 tooltip 替代一切 hover

### 何时使用
- 面板标题旁的「这是什么」

### 实现落点
- `primitives/VContextualHint.tsx`

### 反冗余
- 不新建 `VHelpIcon` / `VInfoTip`

---

## VDialog

### 职责
模态对话框容器。

### 非职责
- 不做抽屉/非模态 popover（另议）

### 何时使用
- 需打断主流程的确认/编辑

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 仅 yes/no 危险确认 | `VConfirmDialog` |
| 非模态提示 | `VTooltip` / toast（若项目有） |

### 实现落点
- `primitives/VDialog.tsx` → `ShadcnDialog`

### 反冗余
- 禁止 route 内 `fixed inset-0` 手写遮罩（实现落在 `ShadcnDialog` 即可）

### 已迁业务面（对齐收口）
- `AgentCreateWizardDialog`、`AgentModelPicker`
- `CacheDetailDialog`、`ConversationImagePreviewDialog`
- Config 未保存离开守卫（`ConfigRoute` leave guard）

### Intentional keep（不要硬套 VDialog）
| 面 | 原因 |
| --- | --- |
| `ChatToolApprovalDialog` | banner/inline 会话内确认，非模态栈 |
| Chat `overlayBackdrop` | 响应式侧栏遮罩（`VButton` 关侧栏） |
| design preview tooltips | 非产品 chrome |

门禁：`components/vui/vuiOverlayAlignmentGate.test.ts`

---

## VConfirmDialog

### 职责
标准确认对话框（危险/普通确认）。

### 非职责
- 不做复杂多步表单（用 `VDialog` + 自建 body）

### 何时使用
- 删除、归档、不可逆操作确认

### 实现落点
- 与 `VDialog` 同文件族

### 反冗余
- 禁止每个域一个 `XxxConfirmModal`

---

## VDropdownMenu

### 职责
下拉菜单 / 右键锚定菜单（Radix DropdownMenu / shadcn 风格）。

### 非职责
- 不做路由级导航（菜单项里的跳转由调用方 `onSelect` 处理）
- 不做多级树（未暴露 Sub）

### 何时使用
| 模式 | 用法 |
| --- | --- |
| 按钮触发 | `trigger={...}` + `items` |
| 右键/坐标锚定 | `position={{ x, y }}` + 受控 `open` / `onOpenChange` |

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 分段浏览 | `VTabs` |
| 表单单选 | `VSelect` / `VStringSelect` |
| 复杂命令面板 | 域内实现或后续 `VCommand` |

### API 要点
- `items: { id, label, icon?, disabled?, danger?, title?, onSelect? }[]`
- `position` 时使用 1px 虚拟 Anchor + Portal Content
- `contentClassName` / `itemClassName` / `dangerItemClassName` 允许域几何

### 实现落点
- `primitives/VDropdownMenu.tsx` → `renderers/shadcn/ShadcnDropdownMenu.tsx` → `@radix-ui/react-dropdown-menu`

### 反冗余
- 禁止再写 `role="menu"` + `fixed` 坐标面板平行系统；Agent/Session 上下文菜单应消费本组件

---

## VPopover

### 职责
非模态浮层面板（Radix Popover / shadcn 风格）：trigger + 任意内容。

### 非职责
- 不做动作列表（用 `VDropdownMenu`）
- 不做打断主流程的确认（用 `VDialog` / `VConfirmDialog`）
- 不做纯文案 tip（用 `VTooltip`）

### 何时使用
- 工具菜单、状态说明、短表单浮层、可滚动内容面板

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 纯操作列表 | `VDropdownMenu` |
| 模态编辑 | `VDialog` |
| 悬停短文案 | `VTooltip` |

### API 要点
- `trigger`（forwardRef 子节点）+ `children`
- `open` / `onOpenChange` / `side` / `align` / `sideOffset` / `modal?`

### 实现落点
- `primitives/VPopover.tsx` → `renderers/shadcn/ShadcnPopover.tsx` → `@radix-ui/react-popover`

### 已迁业务面
- AppShell 顶栏工具菜单（click，替代 hover 手写面板）
- AppShell 进行中详情（active-work）
- AppShell 系统状态指南（status guide）
- Composer：`AgentPermissionPresetControl`、`ConversationInferenceControl`

### 反冗余
- 禁止再写 cluster + absolute + pointerdown / CSS hover 显隐平行系统
