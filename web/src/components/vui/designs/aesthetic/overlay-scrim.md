# Component: 遮罩层 `bg-vui-scrim-soft` / `bg-vui-scrim-strong`

> 设计基元（令牌，非组件）：本文件描述 VUI 的遮罩底色契约，不新增 `V*` 导出。
> 权威：本文件 + [`../../../design/tokens.css`](../../../design/tokens.css)（取值来源） + [`../../../design/theme.tailwind.css`](../../../design/theme.tailwind.css)（工具类暴露）。

## 遮罩层 `bg-vui-scrim-soft` / `bg-vui-scrim-strong`

### 功能

给弹窗、抽屉、破坏性确认等**覆盖式交互**提供唯一推荐的遮罩底色：一处定义、两档强度（soft / strong），避免每个组件各写一个 `bg-black/20`、`bg-black/35` 之类的一次性透明度值。

### 适用范围

- **适用**：模态对话框背景、抽屉/侧滑遮罩、危险操作确认层、任何需要"压暗场景"的覆盖层。
- **不适用**（改用 `…`）：普通容器背景（用 `bg-vui-surface-*`）、悬停/选中（用既有 hover/selected 类）、文本与图标颜色（用 `text-vui-fg-*` 语义色）。

| 场景 | 选择 |
| --- | --- |
| 常规模态/抽屉遮罩 | `bg-vui-scrim-soft` |
| 破坏性操作、需要强压暗的遮罩 | `bg-vui-scrim-strong` |
| 卡片、面板、页面底 | `bg-vui-surface-card` / `bg-vui-surface-panel` / `bg-vui-bg-canvas` |

### 使用方式

```tsx
// 工具类由 design/theme.tailwind.css 的 @theme 注册，取值来自 tokens.css 的 --vui-scrim-*。
<div className="fixed inset-0 bg-vui-scrim-soft" aria-hidden="true" />
```

| Token | 取值（tokens.css） | 用途 |
| --- | --- | --- |
| `bg-vui-scrim-soft` | `--vui-scrim-soft`（黑 20%） | 常规遮罩 |
| `bg-vui-scrim-strong` | `--vui-scrim-strong`（黑 35%） | 强压暗 / 破坏性 |

### 非职责

- 不负责模糊/毛玻璃效果：需要时用 `backdrop-filter`（按 reduced-motion 降级）。
- 不负责层级：遮罩的 `z-*` 由所在浮层决定。
- 不提供第三档强度：新增强度必须先改本文件与令牌，禁止组件内联新透明度。

### 视觉与状态

- 无交互状态；遮罩是静态的。
- 两档之外不要自造，`bg-black/20` 这类一次性透明度值视为设计系统缺陷。

### 实现落点

- 取值：`web/src/design/tokens.css`（`--vui-scrim-soft`、`--vui-scrim-strong`）。
- 工具类注册：`web/src/design/theme.tailwind.css`（`--color-vui-scrim-*`）。
- 机器门：`web/src/p0StyleContract.test.ts`（`alphaUtility` 基线为 0，`text/bg/border-white|black/N` 一律禁止）。

### 反冗余

- 与 `text-white/60`、`border-white/10` 的边界：这些一次性 alpha 工具类**禁止**，语义由既有令牌表达。
- 与 `--vui-surface-*` 的边界：surface 是不透明容器底色，scrim 是覆盖式半透明压暗，不可互换。
- 禁止再新建：`bg-black/…`、`--vui-overlay-*`、`--vui-mask-*` 等平行命名。
