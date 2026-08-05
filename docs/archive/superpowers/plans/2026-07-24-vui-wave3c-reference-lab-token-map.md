# VUI Wave 3C：Reference Lab ↔ 生产 Token / Recipe 映射

**Date:** 2026-07-24
**Status:** complete
**Owner:** `web-workbench-surface` / VUI design-system
**Depends on:** Wave 0–2 surface 契约；Wave 3A chrome recipes；Wave 3B Chat composition
**Contract test:** `web/src/design/vuiWave3cLabTokenMapContract.test.ts`

## 0. 目的

把 `web/vui-reference-lab.html` 里的**语义角色**锁定到正式生产入口，避免 Lab 与路由再长出第二套命名或透明度。

- Lab 继续是**隔离预览**（不进生产路由）。
- 生产只消费：`tokens.css` 变量 + `vuiSurfaceRecipes` / `vuiChromeRecipes` + VUI page recipes。
- 本表是 Wave 3 收口条件「Lab 映射文档存在」的权威源。

## 1. 表面语义（Lab §01 SURFACES）

| Lab 角色 | Lab CSS 变量 | 生产 token | 生产 recipe / 用法 | 不透明度规则 |
|---|---|---|---|---|
| workspace | `--lab-workspace` | `--vui-surface-base` / `--vui-surface-workspace` | `vuiWorkspaceFillClass` | 实底页面画布 |
| region | `--lab-region` | `--vui-surface-rail` / `--vui-surface-region` | `vuiRailFillClass` | 侧栏 / 区域容器实底 |
| card | `--lab-card` | `--vui-surface-panel` / `--vui-surface-card` | `vuiOpaquePanelClass` / `vuiElevatedPanelClass` / `vuiFlatPanelClass` | **内容卡默认不透明** |
| inset | `--lab-inset` | `--vui-surface-row` / `--vui-surface-inset` | `vuiOpaqueRowClass` / `vuiDenseRowClass` / `vuiInsetFillClass` | 内嵌列表行/井 |
| control | `--lab-control` | `--vui-control-muted` / `--vui-surface-control` | chrome recipes 的 `bg-[var(--vui-control-muted)]`；控件 fill | 控件底，非结构板 |
| popover | `--lab-popover` | `--vui-surface-glass` / `--vui-surface-popover` | `vuiGlassPanelClass` | **唯一允许玻璃/浮层** |

### 补充生产角色（Lab 未单独命名，路由需要）

| 生产角色 | Token | Recipe | 备注 |
|---|---|---|---|
| chat board | `--vui-surface-chat` | `vuiChatFillClass` | 对话中区；禁止 soft wash 透壁纸 |
| toolbar strip | `--vui-surface-toolbar` | `vuiToolbarFillClass` | 模块条 |
| row hover | `--vui-surface-row-hover` | `vuiOpaqueRowHoverClass` | 交互行 hover |
| overlay scrim | `--vui-surface-overlay` | 对话框遮罩 | 非内容卡 |

## 2. 边框 / 文字 / 强调

| Lab 角色 | Lab CSS | 生产 token |
|---|---|---|
| ink | `--lab-ink` | `--fg-primary` |
| muted | `--lab-muted` | `--fg-secondary` |
| soft | `--lab-soft` | `--fg-tertiary` |
| line | `--lab-line` | `--vui-border-subtle` |
| line strong | `--lab-line-strong` | `--vui-border-strong` |
| accent | `--lab-accent` | `--accent-cool` |
| danger | `--lab-danger` | `--state-error` |

## 3. 控件几何与密度（Lab §02–03 + 紧凑开关）

| Lab / 产品语义 | 生产 token | Chrome recipe | 推荐组件 |
|---|---|---|---|
| 紧凑控件高 | `--vui-control-height-sm`（= compact 30px） | `vuiControlQuietClass` / `vuiControlQuietChromeClass` / `vuiControlIconSmClass` | `VButton` density compact / `VIconButton` |
| 舒适控件高 | `--vui-control-height-md`（= comfortable 34px） | （默认按钮高度） | `VButton` default |
| 圆角 control | `--radius-control`（8px） | 含于 chrome / surface recipes | 输入与按钮 |
| 圆角 panel | `--radius-panel` | `vuiOpaquePanelClass` | 卡片 |
| pill | `--radius-pill` / full | `vuiControlPillClass` | 状态 chip |
| 字号 xs / sm / md | `--vui-font-xs` … | chrome 默认 xs | 路由禁止 `text-[var(--vui-font-*)]`（用 `[font-size:…]`） |

**规则：** style map 里重复的 quiet 按钮串优先改为 chrome recipe；新 TSX 优先 VUI 组件，不复制 Lab 的 `.lab-button-*` 类名。

## 4. 列表与状态（Lab §04 ROWS）

| 语义 | 生产 recipe | 固定 alpha（禁止路由再发明 %） |
|---|---|---|
| 默认密集行 | `vuiDenseRowClass` | 不透明 row |
| 选中（cool） | `vuiStateSelectedRowClass` / `vuiStateSelectedRowFillClass` | cool border 34% / wash 10% |
| 选中（warm，Agents） | `vuiStateSelectedWarmRowClass` | warm 34% / 9% |
| 危险板 | `vuiStateDangerPanelClass` | error 22% border / 4% wash |
| 警告板 | `vuiStateWarningPanelClass` | warning 固定 wash |
| 成功/危险 soft chip | `vuiStateSuccessSoftClass` / `vuiStateDangerSoftClass` | 见 recipe 字面量 |

Alpha 策略由 `vuiSurfaceAlphaPolicy` 守卫；结构板禁止 soft wash 透壁纸。

## 5. Product shell 搭页（Wave 3 搭页层）

| 场景 | Recipe id (`data-vui-recipe`) | 组件 | 何时用 |
|---|---|---|---|
| 列表 + 详情 | `list-detail-page` | `VListDetailPage` | 通用双栏运维/目录 |
| 设置表单 + sticky footer | `settings-form-page` | `VSettingsFormPage` | Config / 偏好类 |
| 高密度运维表 | `dense-ops-page` | `VDenseOpsPage` | Tools / 日志类 |
| 工作台列壳 | （VWorkbenchPage 默认） | `VWorkbenchPage` | 多列 workbench |
| **Chat 领域壳** | `chat-session-workbench` | Chat 路由 composition | **不**硬套 list-detail；见 Wave 3B |

示范页状态：

| 路径 | 状态 |
|---|---|
| Chat `chat-session-workbench` | ✅ Wave 3B + `vuiWave3ChatCompositionContract.test.ts` |
| Config `config-settings-workbench` + 主栏 `settings-form-page` | ✅ 3B-alt + `vuiWave3ConfigCompositionContract.test.ts` |
| Tools `dense-ops-page` | ⏳ 可选 3B-alt2 |

## 6. 决策锁定（自 Lab 引入生产）

以下已在 Wave 2–3 生产契约中落地，Lab 仅作对照：

1. **内容卡默认不透明**（panel / row / chat board）。
2. **glass 仅浮层与临时覆盖**（`vuiGlassPanelClass`）。
3. **状态 tint 只走 recipe**，禁止 style map 新造 `color-mix(... surface ... NN%)` 结构洗底。
4. **控件高度**走 `--vui-control-height-sm|md` + chrome recipe。
5. **字号**走 `--vui-font-*` 的 font-size 写法。

## 7. 开发者消费顺序

```text
1. 能用 VUI 组件 / page recipe → 直接用
2. style map 填色 / 边框 → vuiSurfaceRecipes
3. quiet / icon / pill 控件壳 → vuiChromeRecipes
4. 仍缺语义 → 先扩 recipe，再改路由（禁止路由发明 token 透明度）
5. Lab HTML/CSS → 只评审，不 import 到生产
```

## 8. 验证

```powershell
npm --prefix web run test -- src/design/vuiWave3cLabTokenMapContract.test.ts src/design/vuiWave3ChatCompositionContract.test.ts src/design/vuiSurfaceAlphaPolicy.test.ts
```

## 9. 非目标

- 不把 Lab 接入 App router。
- 不引入 cva / `components/ui` / shadcn init。
- 不在本文件重开 surface 透明度产品争论；变更须改 recipe + policy 测试。
