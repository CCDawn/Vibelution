# P0-a 预览 · Tailwind 原生字号槽位接管（隔离预览）

本目录是「视觉统一 P0-a：把 Tailwind 原生 `--text-xs/sm/base/lg/xl` 槽位重定义指向 vui 字号变量」的**隔离预览**。
不注册生产 router、不进主 vite 图、**未改动任何生产文件**（`tokens.css` / `theme.tailwind.css` 仅只读引用，`src/tokens-preview-copy.css` 是快照副本）。

## 启动

```bash
cd web/preview/token-takeover
npm install
npm run dev          # http://127.0.0.1:5185/
```

截图回归（可选，需 python playwright + chromium）：

```bash
python tools/capture.py   # 输出 PNG 与 capture-report.json 到 ./screenshots
```

## 页面内容

- **A/B 对照**（左=现状原生槽位钉死，右=接管后槽位指向 vui 变量；class 完全相同）：
  - A 区：VButton/VInput 槽位复刻（buttonSlots/chipSlots 真实 class 串，故意用原生 text-sm/text-xs），每行实时计算值 `字号 / 行高`。
  - B 区：业务面板片段（ChallengeMvpProgressPanel 类排布复刻：text-lg 标题 / text-xs 元信息 / text-sm 数值 / text-base 摘要 / chips）。
  - C 区：密集 label/chip 混排，含 text-[10px] / text-[11px] / text-[0.62rem] / text-[0.92rem] 逃逸类（取自真实文件）。
- **D 区**：接管映射表（每档：原生默认 px/行高 → 目标变量 → vui 值 → 位移 → 存量用量）。
- **E 区**：行高分析（可勾选「行高配对模式」实测）与圆角槽位分析（仅分析）。
- 全页开关：`html[data-takeover]`（全页接管）与 `data-lh-pairing`（行高配对）、dark/light 主题切换。

## 接管机制（与集成阶段等价）

Tailwind v4 将 `text-sm` 编译为 `font-size: var(--text-sm); line-height: var(--tw-leading, var(--text-sm--line-height))`，槽位默认值发布在 `:root`。在更近祖先重定义同一自定义属性（本预览的 `.takeover-scope` / `html[data-takeover] body`）即等价于集成阶段在 `@theme inline` 重定义槽位，无需改任何 class。

## 映射表（P0 建议：视觉等价/最近档，size-only）

| 槽位 | 原生默认 | 原生行高 | 接管目标 | vui 值 | 位移 | 存量用量* |
| --- | --- | --- | --- | --- | --- | --- |
| text-xs | 12px | 1.3333 | `var(--vui-font-2xs)` | 12px | 0 | 45 |
| text-sm | 14px | 1.4286 | `var(--vui-font-xs)` | 14px | 0 | 36 |
| text-base | 16px | 1.5 | `var(--vui-font-md)` | 16px | 0 | 13 |
| text-lg | 18px | 1.5556 | `var(--vui-font-lg)` | 18px | 0 | 4 |
| text-xl | 20px | 1.4 | `var(--vui-font-title)` | 19px | **−1px（唯一变档）** | 3 |
| text-2xl | 24px | 1.3333 | 不接管 | — | — | 0 |

\* 本次精扫 `web/src`（.ts/.tsx，排除 `text-vui-*`），原生槽位共 101 处；审计口径 93 处为不同扫描范围。逃逸 `text-[Npx/rem]` 共 228 处，不经槽位、接管不影响，需另行治理。

**集成期更正（2026-09，实施时发现）**：`web/src/design/tailwind.css:55` 存在手写兼容规则 `.text-xs { font-size: var(--vui-font-xs); line-height: var(--vui-line-readable) }`（非分层，级联胜过分层 utility）——线上 text-xs 实际一直是 **14px/1.58**，并非本表所依据的 Tailwind 原生 12px。集成保留该规则：线上 text-xs 保持 14px（真实零位移），`@theme` 的 `--text-xs → var(--vui-font-2xs)` 仍按批准契约生效并守护，对无此规则的 route-css 分入口生效。本页 A/B 作为机制演示仍然有效；text-xs 行的「原生 12px」前提以此更正为准。

**行高关键结论**：原生行高是无单位 ratio（如 sm=calc(1.25/0.875)），跟随重定向后的字号等比缩放——四个零位移档行高像素级不变，text-xl 行高 28px→26.6px（比值 1.4 不变）。vui 的 `--vui-font-*` 本身不带配对行高（配对在 `--vui-type-*` 语义角色层），生产 `text-vui-*` 槽位也未配 `--line-height`。

**备选被否方案**：text-xl→`--vui-font-xl`（22px，+2px 更远）；「语义对齐」text-sm→`--vui-font-sm`（15px，36 处 +1px，违背零漂移目标）。

**圆角（仅分析）**：rounded-lg(8)→`--radius-control`(8)、rounded-xl(12)→`--vui-radius-panel-soft`(12) 可零位移接管；rounded(4)/md(6)/2xl(16) 无对应 vui 槽位（位移 +4/+2/−4px），建议维持原生；rounded-full 不经变量、不受影响。

## 截图（screenshots/）

- `01-overview-ab.png`：预览主界面（A 区原语 A/B + B 区面板 A/B）
- `02-dense-chips.png`：C 区密集标签布局（逃逸类两列一致）
- `03-mapping-table.png`：D 区映射表
- `04-global-takeover-on.png`：全页接管 + 行高配对开启状态
- `capture-report.json`：console/page 错误与行为断言报告（当前全部通过、零错误）

`tools/capture.py` 同时断言：native-scope 五档与 Tailwind v4 默认一致；takeover-scope 字号落在 vui 阶梯；全页接管时 body 级 text-xl=19px 而 native-scope 仍 20px；行高配对模式 text-sm 行高≈17.5px。

## 模拟项（非真实运行态）

- 组件为 VUI 槽位 class 串的静态复刻（buttonSlots/chipSlots/真实面板排布），非活体 React 组件挂载；颜色/几何 token 走同一 tokens.css 快照，字号行为与生产一致。
- 接管用 CSS 变量作用域覆盖模拟 `@theme inline` 槽位重定义（变量解析路径相同）。
- tokens 为快照副本（`src/tokens-preview-copy.css`），生产 tokens 变化时需刷新副本。
