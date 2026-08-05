# Shadcn-aligned VUI 全前端设计系统迁移方案

**Date:** 2026-07-23
**Status:** Wave 0–2 engineering close；Wave 3 见 `2026-07-24-vui-wave3-density-and-product-shell.md`（3A chrome density 开工）
**Owner:** `web-workbench-surface` / VUI design-system owner
**Mode:** `TASK_GRAPH`
**Risk:** `STANDARD_TASK`；共享 token、组件 API、主题与页面迁移属于串行契约工作
**Scope:** `web/src/design/**`、`web/src/components/vui/**` 及所有生产路由的视觉消费层
**Close condition:** 代表页面与迁移批次全部通过主题、视口、交互和构建验收；路由层不再派生任意表面透明度；兼容别名消费者清零并删除

## 0. 当前实施状态

### Wave 0–1（已完成，2026-07-24 基线）

- surface 语义 token；Reference Lab；`--vui-surface-*` 为唯一字面量源；legacy `--surface-*` **别名已删除**。
- `vuiSurfaceRecipes`（panel/row/glass/shell fill）与约 **147** 个 style map 接入；结构性 `surface+transparent` 大部收敛。
- 代表提交：`a09a28ff8`、`db3d90b4c`、`e2c3439a7`、`8059925ba` 等。

### 尚未完成

- 任意 `color-mix(...vui-surface...)` 的 **白名单契约**、代表页手测、状态 recipe、composition 示范路径。
- 全量 primitive anatomy/slot 收敛；页面仍大量直写长 Tailwind。

### 下一波 / 当前波

- Wave 2：`docs/superpowers/plans/2026-07-24-vui-wave2-alpha-whitelist-and-composition.md`（工程 close）
- Wave 3：`docs/superpowers/plans/2026-07-24-vui-wave3-density-and-product-shell.md`（密度 + product shell）
- 后续批次必须从当前主线继续，不能重新引入平行 token 或第二套组件 API。

## 1. 目标

以 shadcn/ui 的 Open Code、Composition、semantic theming、stable slots 和 progressive migration 思想为开发方法，把 Vibelution 当前“有 VUI 基础、业务页面仍各自决定视觉”的状态收敛为一个项目自有、可审查、可组合、可测试的前端设计系统。

完成后：

1. 同一语义角色在 Agent、配置、记忆库、团队、进化、对话和工具页面中具有一致的表面、前景色、边框、圆角与交互状态。
2. 页面通过 VUI product API、page recipe 和组合式 anatomy 搭建，不直接消费 renderer，也不复制 shadcn block。
3. 主题通过语义 token 换值；页面不能对基础表面 token 再计算任意百分比。
4. 控件通过有限的 `variant`、`size` / `density` 和 `state` 表达差异，普通页面不覆盖基础几何。
5. 每个迁移单元都可单独验证、提交、回滚，运行中应用持续可用。

## 2. Shadcn 复用决策

### 2.1 主决策：`ADAPT`

参考来源：

- [shadcn/ui Introduction](https://ui.shadcn.com/docs)
- [shadcn/ui Theming](https://ui.shadcn.com/docs/theming)
- [shadcn/ui Button](https://ui.shadcn.com/docs/components/base/button)
- [shadcn/ui Card](https://ui.shadcn.com/docs/components/base/card)
- [shadcn/ui July 2026 Base UI migration guidance](https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default)
- [shadcn-ui/ui GitHub repository](https://github.com/shadcn-ui/ui)

吸收：

- 项目拥有组件源码，而不是依赖不可见的样式实现。
- anatomy 组合优于巨型 props API。
- CSS variables 使用语义背景/前景配对。
- `data-slot`、`data-size`、`data-state` 是稳定样式与测试接口。
- variant 有限、可预测；临时页面组合不升级为全局 variant。
- 逐组件、逐消费面迁移，行为差异显式记录。

不照搬：

- 不运行 `shadcn init` 覆盖现有 Vite/Tailwind/VUI 配置。
- 不新建与 VUI 平行的 `components/ui` 产品 API。
- 不把官方 dashboard/block 复制进路由。
- 不为模仿官方实现而新增 `class-variance-authority`、registry 或其他依赖；现有 variant map 能满足契约时继续复用。
- 不把 Radix 迁移到 Base UI。现有 Dialog/Tooltip 工作正常，官方也明确现有生产项目无需迁移。
- 当前不建立内部 registry；只有出现第二个真实消费仓库时再评估分发需求。

### 2.2 依赖影响

- 默认无新增依赖。
- 保留 React 19、Tailwind CSS 4、Radix Dialog/Tooltip 和项目本地 renderer。
- 若未来新增复杂交互 primitive，先比较原生 HTML、现有 Radix 依赖和 shadcn 官方源码，再单独形成复用决策。

## 3. 保护边界

- 不改变后端 API、DTO、缓存、权限、Agent 状态和业务流程。
- 不借设计系统迁移重做 AppShell 信息架构。
- 不强制所有页面采用双栏、三栏或卡片墙。
- 不改变用户已批准的 Agent 页面信息层级；Agent 专项计划作为本方案的代表消费面和第一迁移批次。
- 不把 route-specific domain shell 强行抽成通用 primitive。
- 不让 renderer 兼容参数无限增长；旧 API 兼容必须标注消费者和退出条件。
- 不在一次提交中同时改变基础 token、多个 primitives 和全部路由。

## 4. 事实源

| 契约类别 | 唯一事实源 | 消费者 |
|---|---|---|
| 物理主题值 | `web/src/design/tokens.css` | theme/provider |
| Tailwind 语义映射 | `web/src/design/vui-provider-theme.css` | VUI、route style maps |
| 交互 primitive 实现 | `web/src/components/vui/renderers/shadcn/**` | 仅 VUI primitive |
| 产品级组件 API | `web/src/components/vui/primitives/**`、`forms/**`、`layout/**`、`display/**` | routes、product components |
| 稳定 slots/variants | VUI 组件源码和 `renderers/shared/**` | CSS、测试、组合组件 |
| 领域组合 | `web/src/components/vui/product/**` | 对应产品路由 |
| 页面视觉组合 | 同名 `*.styles.ts` | 单个 route/panel |
| 迁移约束 | `web/src/components/vui/vui*Contract.test.*` 与 route aesthetic contracts | CI/build |

禁止新增第二事实源：

- 路由不能定义新的基础颜色、圆角、阴影、控件高度。
- route style map 可以定义布局和局部组合，但不能重新实现 primitive。
- renderer 只能由 VUI primitive 导入。

## 5. 目标语义模型

### 5.1 表面与前景配对

保留现有物理值作为迁移输入，在语义层收敛为：

| 语义角色 | 用途 |
|---|---|
| `workspace` / `workspace-foreground` | 工作区画布与默认内容 |
| `region` / `region-foreground` | 一级功能区域、rail、detail、inspector |
| `card` / `card-foreground` | 独立内容单元 |
| `inset` / `inset-foreground` | 卡片内部事实、元数据、列表行 |
| `control` / `control-foreground` | 输入、选择、低强调按钮 |
| `popover` / `popover-foreground` | Dialog、Popover、Menu、Tooltip |
| `muted` / `muted-foreground` | 辅助信息和低强调状态 |
| `accent` / `accent-foreground` | hover、selected、active |
| `destructive` / `destructive-foreground` | 危险操作与错误强调 |
| `border`、`input`、`ring` | 分隔、表单边界和键盘焦点 |

最终名称可保留 `--vui-*` 前缀，但语义必须稳定，不携带百分比或具体颜色。

### 5.2 状态叠加

`default`、`hover`、`focus-visible`、`active`、`selected`、`disabled`、`loading`、`error` 不再通过新建表面层表达。组件选择一个基础语义角色，再由有限状态覆盖边框、前景或轻量 accent。

### 5.3 密度

正式保留两档：

- `compact`：高密度操作台、列表、行内动作。
- `normal`：表单、对话框、主操作和阅读型详情。

密度统一决定控件高度、横向 padding、图标尺寸和内部 gap。页面不得只覆盖其中一个参数。

## 6. 组合式组件 Anatomy

### 6.1 Surface

扩展现有 `VSurface`，不新建平行 Card：

```tsx
<VSurface role="card" size="sm">
  <VSurfaceHeader>
    <VSurfaceTitle />
    <VSurfaceDescription />
    <VSurfaceAction />
  </VSurfaceHeader>
  <VSurfaceContent />
  <VSurfaceFooter />
</VSurface>
```

规则：

- anatomy 子组件提供结构、slots 和默认节奏，不理解 Agent、Memory 等业务。
- `VSurface` 使用 `data-slot="surface"`、`data-role`、`data-size`。
- spacing 由组件级变量统一，例如 `--vui-surface-spacing`，不让 header/content/footer 分别硬编码。
- 只有至少两个真实消费者需要时才增加新的全局 anatomy。

### 6.2 Button 和控件

- `VButton` 保持产品入口，renderer 使用 `data-slot="button"`。
- 图标使用 `data-slot="button-icon"` 与位置属性，不由页面手工调整 gap。
- `variant` 保留有限集合：`primary`、`secondary`、`ghost`、`danger`。
- `density` 保留 `compact`、`normal`；图标按钮由 `VIconButton` 表达。
- 链接保持链接语义，不用 button role 模拟。
- Input、Select、Textarea、Checkbox 补齐一致的 slot、invalid、disabled、density 契约。

### 6.3 页面 Recipe

继续复用：

- `VListDetailPage`
- `VSettingsFormPage`
- `VDenseOpsPage`
- `VSplitWorkspace`

新增 recipe 的门槛：

- 至少两个页面拥有相同滚动所有权、header/toolbar/content 结构和响应式降级。
- 只共享视觉相似度但行为不同，不新增 recipe。

## 7. Task Graph

### Task 0：基线审计与参考矩阵

- **Owner/Boundary:** design-system owner；只读扫描 `web/src` 和运行页面。
- **Dependency:** 无。
- **Mode:** `SIMPLE`。
- **Output:** surface/token/geometry 使用清单；关键页面基线截图；已知例外表。
- **Verification/Stop:** 所有生产路由归入迁移批次；记录当前任意 surface alpha 消费数和 VUI 覆盖率。

### Task 1：Shadcn-aligned VUI Reference Lab

- **Owner/Boundary:** design-system owner；新增隔离的开发预览，不修改生产 route。
- **Dependency:** Task 0。
- **Mode:** `SIMPLE`。
- **Output:** 展示全部语义表面、anatomy、按钮、表单、列表行和状态的 HTML/React reference lab。
- **Verification/Stop:** light、dark、自定义背景三种环境与 compact/normal 两档密度通过人工审批。

### Task 2：语义 token 与兼容映射

- **Owner/Boundary:** design-system owner；`design/tokens.css`、theme mapping 和 token contracts。
- **Dependency:** Task 1 审批。
- **Mode:** `BDD_TDD`，因为共享主题契约会影响全部页面。
- **Output:** 背景/前景语义配对、边框/input/ring、旧 token 兼容映射和退出清单。
- **Verification/Stop:** 新 token 在 light/dark/custom background 下可读；旧消费者视觉不意外改变；契约测试先失败再通过。

### Task 3：Primitive 与 Anatomy

- **Owner/Boundary:** VUI owner；`primitives/**`、`forms/**`、`renderers/**`、`renderers/shared/**`。
- **Dependency:** Task 2。
- **Mode:** `BDD_TDD`，因为公开组件 API、交互和无障碍语义存在回归风险。
- **Output:** Surface anatomy、完整 `data-slot`、有限 variants/density、统一 focus/disabled/invalid 状态。
- **Verification/Stop:** primitive tests、键盘交互和 renderer import boundary 通过；无新增 route renderer import。

### Task 4：页面 Recipe 与三类试点

- **Owner/Boundary:** VUI owner + 对应 route owner；只迁移 Agent overview、Config overview、Chat session workspace 三个代表切片。
- **Dependency:** Task 3。
- **Mode:** `SIMPLE`；若试点暴露交互回归，再对具体组件升级为 `BDD_TDD`。
- **Output:** 高密度列表、配置表单、长内容工作区各一个完整样板。
- **Verification/Stop:** 三类页面证明同一契约能覆盖，不新增临时全局 variant；用户视觉验收通过。

### Task 5A：管理型页面迁移

- **Owner/Boundary:** Agent/Config/Memory route owners；不修改共享 token。
- **Dependency:** Task 4。
- **Mode:** `SIMPLE`。
- **Output:** Agent、配置、记忆库、提示词、工具、技能页面迁移。
- **Verification/Stop:** 对应 layout tests、route tests、视觉矩阵和无溢出检查通过。

### Task 5B：工作流页面迁移

- **Owner/Boundary:** Teams/Research/Evolution route owners；不修改共享 token。
- **Dependency:** Task 4；可与 5A 并行，但共享 hot file 必须串行。
- **Mode:** `SIMPLE`。
- **Output:** 团队、科研、自进化、监督进化和 Research Flow 迁移。
- **Verification/Stop:** 阶段卡、候选项、检查器、控制条和状态面板遵守相同 anatomy/slot 契约。

### Task 5C：Shell 与复杂工作区迁移

- **Owner/Boundary:** Chat/AppShell/operational route owners；不改变会话和运行时行为。
- **Dependency:** Task 4；可与 5A/5B 按文件边界并行。
- **Mode:** `SIMPLE`。
- **Output:** 对话、Git、Kernel、日志、Launcher、Usage 等页面迁移。
- **Verification/Stop:** 滚动、流式内容、Overlay、状态 rail 与长内容布局无回归。

### Task 6：防漂移约束和兼容层退出

- **Owner/Boundary:** design-system owner；contracts、旧 token 别名和迁移 allow-list。
- **Dependency:** Task 5A、5B、5C 全部完成。
- **Mode:** `BDD_TDD`。
- **Output:** 路由 surface 派生禁令、renderer import 禁令、控件几何禁令；删除零消费者兼容别名。
- **Verification/Stop:** 路由层对 surface token 的任意百分比混合为 0；allow-list 为 0 或仅保留带删除条件的真实例外。

### Task 7：全局验收、集成与发布判断

- **Owner/Boundary:** Integration Owner；只整合已通过各批验证的提交。
- **Dependency:** Task 6。
- **Mode:** `SIMPLE`。
- **Output:** 最终验证记录、浏览器截图、回滚点、版本影响与 Launcher 刷新证据。
- **Verification/Stop:** focused tests、完整 web build、主题/视口矩阵和运行页面浏览器检查全部通过。

## 8. Critical Path 与并行边界

Critical Path：

```text
Task 0 → Task 1 → Task 2 → Task 3 → Task 4
       → Task 5A/5B/5C → Task 6 → Task 7
```

- Task 2、3、6 修改共享契约，必须串行。
- Task 5A、5B、5C 只有在 scope/claim 不重叠且不修改共享 VUI 时才能并行。
- `ChatCodingRoute.styles.ts`、`TeamsRoute.styles.ts` 等热点文件按单 owner 串行编辑。
- route owner 若发现共享契约缺口，提交给 design-system owner，不在路由内创造替代 primitive。

## 9. 验收契约

### 9.1 自动化

- `vuiThemeFoundation`
- `vuiPrimitives`
- `vuiForms`
- `vuiLayoutTemplates`
- `vuiImportBoundary`
- `vuiDesignCssContract`
- `routeAestheticContract`
- 各迁移页面的 `*.layout.test.*`
- `npm --prefix web run build`

在 Windows 上 focused Vitest 优先使用：

```powershell
node web/node_modules/vitest/vitest.mjs run <focused-test-files>
```

### 9.2 浏览器矩阵

| Viewport | 用途 |
|---|---|
| 390×844 | 手机窄屏 |
| 768×900 | 平板/窄屏 |
| 1280×720 | 小型桌面 |
| 1440×900 | 常规桌面 |
| 1920×1080 | 大屏与自定义背景 |
| 2560×1440 | 超宽大屏 |

每个代表页面检查：

- light / dark；
- 默认背景 / 自定义背景；
- default / hover / focus / active / selected / disabled / loading / error；
- 长名称、长文本、空状态、加载状态；
- 键盘 Tab 顺序、focus ring、ARIA；
- 无导航覆盖、横向溢出、按钮挤压和双滚动容器。

### 9.3 量化退出条件

- 路由层 surface token 任意百分比派生：当前基线降至 0。
- 路由直接导入 shadcn renderer：保持 0。
- 新增基础控件局部实现：0。
- 同一 semantic role 的 computed background/border/radius 在同主题下完全一致。
- 按钮高度和图标尺寸只由 density/size 契约决定。
- 旧 token/API 兼容项均有消费者、退出条件和删除状态；最终消费者为 0。

## 10. 回滚与发布

- Task 2 先新增语义映射，不立即删除旧 token。
- 每个 primitive、代表切片和 route wave 独立提交，可按批次回滚。
- 发现行为差异时回滚消费面，不在共享 token 中加入页面特例。
- 只有消费者清零后才删除兼容映射。
- 视觉/token/组件迁移不新增业务 runtime log；使用静态审计、测试和浏览器证据。
- 最终系统级迁移建议按 `minor` 版本影响评估；单个不改变 API 的 route wave 可按 `patch`。
- 生产用户验收前必须通过 Launcher 刷新；仅完成计划或隔离 reference lab 时不需要刷新。

## 11. 与 Agent 专项计划的关系

`2026-07-23-agent-management-frontend-optimization.md` 继续拥有 Agent 的信息架构、滚动所有权、响应式降级和业务页面验收。

本方案拥有：

- 语义 token；
- VUI primitive/anatomy；
- variants、density、slots；
- 跨页面迁移顺序；
- 全局防漂移约束。

Agent 专项计划不得自行新增共享 token 或 primitive；全局方案也不得推翻已批准的 Agent 页面结构。

## 12. 第一实施单元

先完成 Task 0 和 Task 1：

1. 固化现有 surface/geometry 基线。
2. 创建隔离的 `Shadcn-aligned VUI Reference Lab`。
3. 同屏展示六种语义表面、组合 anatomy、按钮、表单、列表、状态与三种背景环境。
4. 使用正式浏览器地址打开，按真实 1920×1080 比例验收。
5. Reference Lab 通过后，才允许修改共享 token 和 VUI primitive。
