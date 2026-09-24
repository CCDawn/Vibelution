# Component: 字号刻度 `text-vui-*`

> 设计基元（非组件）：本文件描述 VUI 的排版尺度契约，不新增 `V*` 导出。
> 权威：本文件 + [`../../design/tokens.css`](../../design/tokens.css)（尺度来源） + [`../../design/theme.tailwind.css`](../../design/theme.tailwind.css)（工具类暴露）。

## 字号刻度 `text-vui-*`

### 功能

给产品 UI 一套**唯一**的字号刻度：把 `tokens.css` 里已有的尺寸阶梯暴露成 Tailwind 工具类 `text-vui-*`，让“这行字应该多大”有唯一答案，而不是每个页面各写一个 `text-sm` 或 `text-[13px]`。

### 适用范围

- **适用**：`web/` 下所有产品 UI 的正文、标签、标题、按钮、表格、工具栏、菜单、对话输出等文字。
- **不适用**（改用 `…`）：代码块 / Diff / 终端等**内容型**渲染，保持各自的等宽字号设置；它们周围的控件、标签、页眉、元信息仍用 `text-vui-*`。

| 场景 | 选择 |
| --- | --- |
| 正文、列表、表格、菜单、工具栏文字 | `text-vui-md` / `text-vui-sm` / `text-vui-xs` |
| 对话可读正文 | `text-vui-chat` |
| 区块/路由标题 | `text-vui-title` |
| 罕见的页面级标题 | `text-vui-xl` |
| 密集元信息（少用） | `text-vui-2xs` |
| 代码 / Diff / 终端内容 | 该渲染器自带的等宽字号，不用 `text-vui-*` |

### 使用方式

```tsx
// 工具类由 design/theme.tailwind.css 的 @theme 注册，来自 tokens.css 的 --vui-font-*。
<p className="text-vui-md text-[color:var(--fg-primary)]">正文</p>
<span className="text-vui-xs text-[color:var(--fg-tertiary)]">元信息</span>
<h2 className="text-vui-title font-medium">区块标题</h2>
```

| Token | 取值（tokens.css） | 用途 |
| --- | --- | --- |
| `text-vui-2xs` | `--vui-font-2xs` (12px) | 密集元信息，少用 |
| `text-vui-xs` | `--vui-font-xs` (14px) | caption / chip / toolbar |
| `text-vui-sm` | `--vui-font-sm` (15px) | 控件 / 列表次要文字 |
| `text-vui-md` | `--vui-font-md` (16px) | 正文默认 |
| `text-vui-chat` | `--vui-font-chat` (17px) | 对话可读正文 |
| `text-vui-lg` | `--vui-font-lg` (18px) | 强调正文 / 空状态 |
| `text-vui-title` | `--vui-font-title` (19px) | 区块 / 路由标题 |
| `text-vui-xl` | `--vui-font-xl` (22px) | 页面标题，罕见 |

### 非职责

- 不负责行高、字重、字距：分别用已有的 `--vui-line-*` / `--vui-weight-*` / `--vui-tracking-*`（或语义角色 `--vui-type-*` 组合）。
- 不做字号缩放开关：`--vui-font-*` 目前是固定阶梯，不提供“外观设置改字号”的能力。
- 不接管代码 / Diff / 终端的内容字号。

### 视觉与状态

- 无交互状态；刻度是静态的。
- 语义角色（`--vui-type-caption/-label/-control/-body/-chat/-emphasis/-title/-display`）是“尺寸 + 行高”的组合，优先用于新 UI；需要精细控制时才直接用 `--vui-font-*`。

### 实现落点

- 尺度来源：`web/src/design/tokens.css`（`--vui-font-2xs…xl`、`--vui-line-*`、`--vui-weight-*`、`--vui-tracking-*`、`--vui-type-*`）。
- 工具类注册：`web/src/design/theme.tailwind.css`（`@theme inline` 的 `--text-vui-*`）。
- 机器门：`../vuiTypeScaleContract.test.ts`（VUI 目录禁止内置字号与任意字号，存量只减不增）。

### 反冗余

- 与 `--vui-font-*` 的边界：`--vui-font-*` 是 CSS 变量（值层），`text-vui-*` 是工具类（写法层），二者必须同源，禁止在 `@theme` 里写死 rem 值。
- 与语义角色 `--vui-type-*` 的边界：语义角色给“这类文字”（caption/label/body/…），`text-vui-*` 给“这一行字多大”；不要新建第二套 `--app-font-size-*`。
- 禁止再新建：`text-[13px]`、`text-sm`、`text-xs` 等内置/任意字号工具类（重命名或迁移到 `text-vui-*`）。
