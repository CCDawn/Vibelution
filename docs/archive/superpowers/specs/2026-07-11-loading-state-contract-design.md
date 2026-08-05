# 前端统一加载状态契约设计

## 背景

当前工作台已经具备 `RouteLoadingShell`、`VStateSurface`、`VMetricStrip` 和若干页面级 skeleton，但不同路由对 React Query 状态的解释不一致：

- `/` 等待 `/api/config/public` 时直接返回 `null`，导致主内容空白；
- Agents、Git、Usage 在首包未返回时把缺失数据投影成真实的 `0`、`-` 或空列表；
- 页面级 loading、卡片级 loading、后台刷新和局部错误没有统一区分；
- 已有数据在后台刷新时有被空状态覆盖的风险。

运行审查中，Agents 页面先显示 `全部 Agent 0 / 可用 Agent 0 / 已归档 0`，随后才纠正为真实数量；Git 页面也会在 status 请求未完成时显示 `分支 - / 变化文件 0 / Worktree 0`。这会让用户把“尚未加载”误判为“确实没有数据”。

## 目标

建立并落地一套可复用的前端加载状态契约：

1. 页面壳、标题和全部关键卡片位置立即出现，不允许整页空白；
2. 首次请求未完成时，缺失值显示 spinner 或 skeleton，不显示假 `0`、`-` 或空状态；
3. 多个请求独立收敛，先完成的区域先展示，不等待全页所有数据；
4. 后台刷新保留最后一次成功数据，只显示低干扰的“同步中”；
5. 单个请求失败只替换其拥有的区域，并提供局部重试；
6. loading、empty、error、loaded 四种语义可由自动化测试区分；
7. 状态切换不改变关键卡片的占位尺寸，避免明显布局跳动。

## 非目标

本轮不处理：

- Agent 列表 DTO 与详情接口拆分；
- TeamsRoute 的串行查询瀑布；
- 全仓 React Query `AbortSignal` 接入；
- 全仓路由迁移到 React Router loader 或 Suspense data API；
- 后端接口缓存、数据库或持久化改造；
- 与 loading 无关的页面视觉重构。

## 方案比较

### 方案 A：逐页打补丁

直接在四个路由内分别添加条件判断。改动最少，但会继续复制 loading 判断、文案和占位样式，后续页面仍容易把 pending 投影成空值。

### 方案 B：复用 VUI，统一状态语义（采用）

复用现有 `RouteLoadingShell`、`VStateSurface`、`VMetricStrip` 和 Lucide loading 图标，只补充最小的共享表示能力。每个路由仍拥有自己的业务数据和错误文案，但遵循同一状态模型。

优点：范围可控、视觉一致、可渐进迁移、不会引入第二套组件系统。缺点：需要同时调整共享 VUI 契约和多个路由测试。

### 方案 C：全面迁移 Router loader/Suspense

由路由层统一等待和流式分发数据。长期边界更集中，但会扩大到绝大多数路由、错误边界和缓存策略，不适合作为本轮高 ROI 修复。

## 统一状态模型

每个独立数据区域按以下顺序派生状态：

1. `initial-loading`：`isPending` 且没有成功数据；保留容器，值区域显示 spinner/skeleton，设置 `aria-busy=true`；
2. `loaded`：存在成功数据；显示真实值，包括真实的零；
3. `refreshing`：存在成功数据且 `isFetching`；保留真实值，在标题或状态条显示“同步中”；
4. `error-with-data`：刷新失败但存在旧数据；保留旧数据，并显示非阻塞警告与重试；
5. `error-empty`：首次请求失败且没有数据；只替换该区域为 `VStateSurface tone="error"`；
6. `empty`：请求成功且集合确实为空；显示明确空状态。

禁止通过 `data ?? EMPTY_*` 在渲染前抹掉“尚未加载”和“真实为空”的区别。空值归一化只能在确认请求成功后发生。

## 共享表现契约

### 路由加载壳

将当前 Router 内部的工作台加载壳提取到 `web/src/app/RouteLoadingShell.tsx`。`router.tsx` 与 `HomeRedirect.tsx` 都从该文件导入，避免 `HomeRedirect` 反向依赖 `router.tsx` 形成循环。`HomeRedirect` 在配置请求 pending 时渲染该壳，不再返回 `null`。

加载壳必须包含：

- `role="status"`；
- `aria-live="polite"`；
- `aria-busy="true"`；
- 稳定的最小高度；
- 明确的“正在确定默认工作台”文案。

### 卡片值占位

新增 `web/src/components/vui/display/VLoadingValue.tsx`。关键指标卡在 `initial-loading` 时保留标签和卡片尺寸，仅值区域渲染 `VLoadingValue`。该组件包含固定尺寸 `LoaderCircle`、`role="status"`、可读 label、`animate-spin` 与 `motion-reduce:animate-none`，不把 loading 编码成数字或字符串哨兵。

`VMetricStripMetric.value` 从 `string | number` 扩展为 `ReactNode`，允许 Agent 汇总条直接使用同一 `VLoadingValue`，不复制 spinner markup。

优先复用现有 VUI：

- 区域级状态使用 `VStateSurface`；
- 指标组继续使用 `VMetricStrip`；
- 图标使用 `VLoadingValue` 内的现有 `LoaderCircle`，动画和 `prefers-reduced-motion` 由 VUI 统一处理；
- 不新增独立的第三方 skeleton/spinner 依赖。

## 页面改动

### HomeRedirect

- pending 且无配置数据：显示工作台 loading shell；
- 配置成功：执行原有默认路由跳转；
- 配置失败：使用错误 surface，保留重试入口，不能静默跳到错误默认值。

### AgentsRoute

- 轻量列表的 loading/error 必须绑定 `agentSummaryQuery`；
- `workspaceQuery` 只负责按需加载完整配置，不能控制初始列表状态；
- Agent 汇总指标在 summary pending 时显示占位，不显示 `0`；
- summary 成功后才允许计算真实 `0`；
- workspace 详情加载不清空已经显示的 Agent 列表；
- summary 首次失败显示局部错误和重试，不允许无限 loading。

本轮不改变 `/api/agents?detail=summary` 的 DTO，也不改变选中 Agent 的业务规则。

### GitRoute

- status、commits、config 和 diff 按查询边界独立呈现；
- status pending 时，分支、变化文件、上游、领先/落后和 worktree 指标显示占位；
- commits 已完成时允许历史列表先展示，不等待 status；
- status 成功且数量为 0 时才显示真实 `0` 和 clean worktree；
- 刷新时保留已有 status 与 commits，不回退成空工作区。

### UsageRoute

- 保留 `TokenUsageRollup | undefined` 直到 summary 成功；
- 首次 pending 时所有指标卡保留结构并显示占位；
- 成功后使用真实 rollup，真实零值照常显示；
- 自动轮询时保留旧值，并在 header 状态条显示“同步中”；
- 首次失败显示区域级错误，刷新失败则保留旧数据并提示。

## 数据流

```text
React Query result
  -> derive initial-loading / loaded / refreshing / error-with-data / error-empty / empty
  -> route owns business copy and retry action
  -> VUI owns spinner/skeleton geometry and accessibility
  -> card/section renders without changing outer layout
```

不引入新的全局 store；React Query cache 继续作为服务器状态来源。路由只派生视图状态，不复制服务器数据。

## 错误与恢复

- 首次失败：局部 `VStateSurface tone="error"`，提供 `refetch`；
- 后台刷新失败：保留旧数据，显示警告，不把旧数据清空；
- 配置默认路由失败：停留在可见错误壳，不猜测跳转目标；
- 重试期间：错误 surface 转为 loading，但容器尺寸保持稳定；
- 任何错误文案不得泄露敏感配置、控制 token 或完整响应体。

## 可访问性与布局

- loading 容器使用 `aria-busy`；
- spinner 带可读状态文本，装饰图标使用 `aria-hidden`；
- `aria-live` 只用于状态摘要，避免每个卡片同时播报；
- reduced-motion 环境停用连续旋转，保留静态图标与文本；
- placeholder 与最终数字使用相同值槽高度；
- 桌面和移动端均不得因 loading 文案造成横向溢出。

## 测试策略

### 单元与组件测试

对共享状态表示或纯派生 helper 覆盖：

- pending 且无数据 -> initial loading；
- pending/fetching 且有数据 -> 保留数据并 refreshing；
- error 且无数据 -> blocking local error；
- error 且有数据 -> stale data + warning；
- 成功空集合 -> empty；
- 成功零值 -> loaded zero。

### 路由行为测试

- HomeRedirect pending 时存在可见 loading shell，禁止 `return null`；
- Agents 使用 `agentSummaryQuery` 控制列表和汇总状态；
- Git status pending 不显示真实零；
- Usage pending 不通过 `EMPTY_ROLLUP` 伪造零值；
- 后台 refetch 不移除已经显示的数据。

### 集成验证

- 聚焦 Vitest；
- `npm --prefix web run build`；
- 浏览器验证 `/`、`/agents`、`/git`、`/usage`；
- 桌面与移动宽度检查；
- 人工或可控延迟下验证卡片独立收敛；
- 浏览器 console 无新增 error/warning。

## 并行实施策略

为利用多核并减少冲突，实施分为三个阶段：

1. 串行基础阶段：完成共享状态契约及其测试；
2. 并行页面阶段：
   - Lane A：HomeRedirect + Usage；
   - Lane B：Git；
   - Lane C：Agents；
3. 串行收口阶段：合并页面结果、运行全量聚焦测试、生产构建、浏览器验证和最终审查。

并行 lane 不同时编辑共享 VUI 文件、query keys、全局样式或测试基础设施。共享基础必须先形成稳定提交，再分发给页面 lane。

## 影响面

预计涉及：

- `web/src/app/RouteLoadingShell.tsx` 与 `web/src/app/router.tsx`；
- `web/src/components/vui/display/VLoadingValue.tsx`、VUI export 与 `VMetricStrip.tsx`；
- `web/src/routes/HomeRedirect.tsx`；
- `web/src/routes/AgentsRoute.tsx` 与相关 Agent panel；
- `web/src/routes/GitRoute.tsx`；
- `web/src/routes/UsageRoute.tsx`；
- `web/src/routes/GitRoute.styles.ts` 与 `web/src/routes/UsageRoute.styles.ts` 的固定值槽样式（仅在现有卡片无法保持尺寸时修改）；
- `web/src/components/vui/vuiLayoutTemplates.test.tsx`；
- `web/src/app/router.test.ts` 与四个目标路由的现有测试文件。

最终文件清单由实施计划在只读复查后确定；不得为统一风格顺手改动其他路由。

## 成功标准

- `/` 首次加载时主内容区域始终可见；
- Agents、Git、Usage 首包未到时不显示假 `0`、`-` 或空列表；
- 页面卡片从 loading 独立过渡到 loaded，不等待无关查询；
- 后台刷新保留最后成功数据；
- 首次失败和刷新失败均有正确、局部、可重试的表现；
- 聚焦测试、生产构建和浏览器验证通过；
- 不改变本轮排除项的接口、缓存或查询拓扑。

## Launcher、版本与日志判断

- 本轮属于用户可见前端行为变化，合并后需要 Launcher refresh 才能做最终运行验收；
- version impact：`patch`；
- 不新增后端运行日志；前端失败继续使用现有 API failure telemetry 和 route error boundary；
- 若实现引入新的加载状态 helper，仅通过测试证明状态转换，不记录用户数据或响应体。
