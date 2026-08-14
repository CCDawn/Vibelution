# Chat 路由单一权威实施规划

> 日期：2026-08-14
> 状态：方向已确认，待实施
> 模式：`COMPACT_PLAN`（一个主 owner，按可独立验收的阶段连续实施）
> 规划基线：local `main` `a52a903626`
> 适用范围：Workbench 全局路由与 Chat 会话、群聊、Project Agent Bus 选择
> 非现行规范：本文是实施规划；落地后的长期权威必须同步到 ADR、模块 README 和对话链路地图。

## 1. 摘要

当前异常不是“浏览器地址没有被及时修复”，而是 React Router URL、Zustand `activeSessionId`、localStorage 和后端 `active_conversation_id` 同时参与决定当前会话。`AppShell` 再通过 `browser.router_location_desync.recovered` 在窗口聚焦、页面重新可见、普通点击或 `pageshow` 时执行 `history.replaceState + navigate`，会把旧地址重新应用到 Router，形成非用户意图的会话切换。

本规划采用项目现有 React Router 7，不更换路由库、不新增依赖、不修改现有 `/chat?session=...` 深链接格式。目标是：

1. React Router 已提交的 URL 是当前页面、当前会话和当前群聊的唯一权威。
2. 后台任务、缓存刷新、窗口焦点、后端 viewing pointer 和本地持久化只能更新数据或偏好，不能导航。
3. 删除 `browser.router_location_desync.recovered` 及其所有恢复逻辑，不用另一种 recovery 事件或定时纠偏替代。
4. 所有 Chat 导航集中到一个 route-domain 控制器，异步结果使用 compare-and-swap，不能把用户拉回旧页面。
5. 保留现有 API、查询参数和 SQLite 字段作为兼容面；后端 `active_conversation_id` 降级为“上次查看偏好”，不再是某个窗口的实时页面权威。

## 2. 现状证据

### 2.1 AppShell 在 Router 之外直接纠偏

- [`web/src/app/AppShell.tsx`](../../../../web/src/app/AppShell.tsx) 定义 `routerLocationDesyncTarget` 和 `routerLocationDesyncRecoveryPlan`。
- `recoverRouterLocationDesync` 先用 `window.history.replaceState` 把地址恢复成 Router 旧值，再调用 `navigate(target, { replace: true })` 前往浏览器地址。
- recovery 由 `window_focus`、`pageshow`、`popstate`、`document_click`、`visibility_visible` 和 `app_shell_mounted` 触发。
- recovery 发出 `browser.router_location_desync.recovered`，但该事件本身无法证明目标地址来自用户意图。
- [`web/src/app/AppShellNavigationTelemetry.test.ts`](../../../../web/src/app/AppShellNavigationTelemetry.test.ts) 当前明确要求 recovery 存在；“不 monkey-patch history”测试只检查是否覆盖函数，没有禁止直接调用 `window.history.replaceState`。

### 2.2 Chat 同时维护多套 active selection

- [`web/src/store/chatWorkbenchStore.ts`](../../../../web/src/store/chatWorkbenchStore.ts) 保存 `activeSessionId` 和 `setActiveSession`。
- [`web/src/routes/chat/useChatWorkspaceActions.ts`](../../../../web/src/routes/chat/useChatWorkspaceActions.ts) 在会话点击时先 `setActiveSession`，再 `navigate('/chat?session=...')`，并同时调用后端 `/select`。
- [`web/src/routes/chat/chatSessionRouteSync.ts`](../../../../web/src/routes/chat/chatSessionRouteSync.ts) 为“store 已更新、Router 尚未更新”提供 2 秒 grace window。
- [`web/src/routes/chat/useChatSessionSelection.ts`](../../../../web/src/routes/chat/useChatSessionSelection.ts) 同时处理 URL → store、server bootstrap → store、first session → store、URL → `/select`。
- [`web/src/routes/chat/useChatSelectionPersistence.ts`](../../../../web/src/routes/chat/useChatSelectionPersistence.ts) 从 localStorage 恢复 store，并把 store 写回 localStorage。
- [`web/src/routes/chat/ChatCodingRouteWorkbench.tsx`](../../../../web/src/routes/chat/ChatCodingRouteWorkbench.tsx) 还有 pending self-evolution handoff、not-found fallback 等直接改写 active session 的 effect。

### 2.3 后端 viewing pointer 与窗口路由边界不一致

- [`core/web/routes/sessions.py`](../../../../core/web/routes/sessions.py) 暴露 `GET /api/sessions/active` 与 `POST /api/sessions/{session_id}/select`。
- [`core/web/services/conversation_service.py`](../../../../core/web/services/conversation_service.py) 在 Chat bootstrap 中返回 `activeSessionId`。
- [`docs/agents/conversation-flow-map.md`](../../../agents/conversation-flow-map.md) 当前把 `active_conversation_id` 定义为“操作者正在看的会话”。该定义无法表达同一项目的两个窗口分别查看不同会话。
- 后端已有 `tests/test_session_viewing_pointer.py` 证明后台 submit 和子会话创建不应改写 pointer；该保护应保留，但 pointer 需要改名或重新定义为 last-viewed preference。

## 3. 外部成熟模式与复用结论

### 3.1 参考

- [React Router State Management](https://reactrouter.com/explanation/state-management)：URL search params 是可路由 UI 状态的自然归属；同时维护 React state 和 URL 会引入同步代码和同步错误。
- [React Router createBrowserRouter](https://reactrouter.com/api/data-routers/createBrowserRouter)：浏览器 History 由 Router 管理。
- [React Router useSearchParams](https://reactrouter.com/api/hooks/useSearchParams)：修改 search params 本身就是 Router navigation。
- [MDN Working with the History API](https://developer.mozilla.org/en-US/docs/Web/API/History_API/Working_with_the_History_API)：`pushState`、`replaceState` 与 back/forward 具有明确的历史栈语义；应用不应在 Router 之外建立第二套历史控制面。

### 3.2 复用决策

- 决策：`ADAPT`。
- 复用点：现有 `react-router-dom`、`createBrowserRouter`、`useSearchParams`、`chatSelectionProjection.ts`、React Query 按 session ID 分区的 cache。
- 依赖影响：无新增依赖。
- 不采用：迁移 TanStack Router；切换库不能自动消除业务层重复 authority。
- 不采用：把 `/chat?session=` 全量迁成 `/chat/:sessionId`；当前大量工作流深链接、后端 DTO 与测试依赖查询参数，正确性收益不足以覆盖兼容成本。
- 不采用：继续增加 desync recovery 条件；这只会把“谁覆盖谁”的规则变得更复杂。

## 4. 目标状态与单一权威表

| 信息 | Canonical source | 允许的派生/缓存 | 禁止成为第二权威 |
| --- | --- | --- | --- |
| 当前 Workbench 页面 | React Router `location` | shell telemetry | `window.location` recovery timer、localStorage |
| 当前 direct session | `?session=<id>` | `activeSessionId` 局部派生变量 | Zustand active ID、server active pointer |
| 当前 group room | `?room=<id>` | `activeGroupRoomId` 局部派生变量 | React local state active room |
| Project Agent Bus | `?room=__project_agent_bus__` | 特殊 surface projection | 裸 `/chat` + 本地 sentinel |
| 当前 session 内容 | backend detail/journal + React Query cache | SSE/live overlay | route selection side effect |
| 每 session 工作区 | Zustand `sessionWorkspaces[sessionId]` | open tabs、active inner tab、draft | 全局 active session |
| 上次查看偏好 | localStorage + backend `active_conversation_id` 兼容字段 | 裸 `/chat` 初始化候选 | 已 canonicalize 页面上的导航输入 |
| 后台运行状态 | runtime/SSE/query cache | busy、完成、未读提示 | `navigate`、`setSearchParams` |

## 5. 路由行为契约

### 5.1 允许导航的来源

只有以下事件可以改变页面：

1. 用户点击顶部标签、会话列表、群聊、Agent、通知或明确的返回入口。
2. 浏览器 back/forward 产生的 Router `POP`。
3. 用户打开明确 deep link。
4. 用户创建、删除、归档、清空历史等操作成功后的必要 route transition。
5. 裸 `/chat` 对当前 location entry 做一次默认路由 canonicalization。
6. 明确的 workflow/self-evolution handoff route，而不是仅仅存在一条 pending handoff 缓存。

### 5.2 禁止导航的来源

以下事件只能更新数据、缓存、状态标记或 telemetry：

- `focus`、`visibilitychange`、`pageshow`、普通 document click。
- 后台 session 开始、完成、失败、排队或 recency 改变。
- SSE、轮询、React Query invalidation/refetch。
- session index 排序变化。
- localStorage 在页面打开后的变化。
- 后端 `active_conversation_id` 在其他窗口发生变化。
- 过期的 `/select`、create、delete、archive、reset 请求返回。
- pending handoff、通知或后台工作仅被创建但没有用户点击。

### 5.3 History 语义

- direct session 标签切换保持当前产品语义：`replace: true`，不为每次标签点击增加历史记录。
- group room 进入保持当前产品语义：`replace: false`。
- 临时 ID → 真实 ID、删除当前项后的替代项、裸 `/chat` canonicalization 使用 `replace: true`。
- `POP` 完全由 React Router 处理；业务代码不监听 `popstate` 做导航修复。
- AppShell 可以被动记录 `POP` telemetry，但不得从 telemetry handler 调用 `navigate`。

### 5.4 显式无效路由

- `/chat?session=<missing>`、已归档 session、冲突参数（同时存在 session 与普通 room）保持原 URL并显示错误/不可用 surface。
- 不自动打开第一条 session，不应用后端 pointer，不读取 localStorage 覆盖显式 URL。
- 用户可通过明确按钮返回会话列表或选择其他 session。
- 用户主动删除/归档当前 session 成功后的跳转不属于“静默 fallback”，但必须满足 compare-and-swap 条件。

## 6. 推荐架构

```text
User intent / Router POP / explicit deep link
                    |
                    v
        useChatRouteSelection (sole writer)
                    |
                    v
      React Router committed location.search
          |                         |
          v                         v
 active session/room derivation   passive effects
          |                    local preference write
          |                    backend last-viewed write
          v                         |
 React Query cache by id            +-- must never navigate

Background SSE/query/runtime ------> cache, busy, unread only
Window focus/visibility -----------> polling policy/telemetry only
```

### 6.1 Route selection type

在 `web/src/routes/chat/` 中建立一个明确的 discriminated union，可复用并收敛 `chatSelectionProjection.ts`：

```ts
type ChatRouteSelection =
  | { kind: "session"; sessionId: string }
  | { kind: "room"; roomId: string }
  | { kind: "project_bus" }
  | { kind: "bare" }
  | { kind: "invalid"; reason: string };
```

`activeSessionId`、`activeGroupRoomId` 只允许从该 selection 派生，不进入 Zustand 或独立 `useState`。

### 6.2 唯一写入口

新增 `useChatRouteSelection.ts`（最终命名可按模块惯例调整），只暴露：

```ts
selection
openSession(sessionId, options?)
openRoom(roomId, options?)
openProjectBus(options?)
canonicalizeBareRoute(target)
replaceIfStillViewing(expectedSelection, nextSelection)
```

除该模块外，`web/src/routes/chat/` 不得直接拼接并 `navigate('/chat?session=...')` 或 `navigate('/chat?room=...')`。预取函数不持有 navigate capability。

### 6.3 异步 compare-and-swap

所有可能晚到的 mutation 使用同一规则：

```text
request started while route = expected
        |
response arrives
        |
current route still equals expected ?
        | yes                         | no
        v                             v
apply explicit transition      update cache only
```

异步结果不得读取 backend fallback 后无条件导航。

## 7. 详细实施阶段

### 阶段 1：回归门禁与 AppShell containment

目标：先移除已确认会自动切页的恢复路径，同时保留 Electron shell link 的 SPA 导航保护。

修改：

- `web/src/app/AppShell.tsx`
  - 删除 `routerLocationDesyncTarget`、`routerLocationDesyncRecoveryPlan`。
  - 删除 recovery delay、timer、refs、`recoverRouterLocationDesync`。
  - 删除 recovery 专用 focus/pageshow/popstate/click/visibility listeners。
  - 删除 `browser.router_location_desync.recovered`。
  - 保留 shell navigation anchor 的 capture-phase `preventDefault + navigatePrimaryNav`，把它从 recovery effect 中独立出来。
- `web/src/app/AppShellNavigationTelemetry.test.ts`
  - 删除要求 recovery 存在的断言。
  - 新增源码/AST 断言：不存在 desync recovery symbol/event。
  - 新增源码/AST 断言：AppShell 不调用 `window.history.pushState/replaceState`。
  - 保留全局导航不整页 reload、Chat preload 和 shell click telemetry 契约。

停止条件：任何 Electron shell anchor 必须依赖 recovery 才能避免整页 reload。若出现，先把 anchor interception 独立成稳定 Router adapter，不恢复 desync 逻辑。

### 阶段 2：Chat route selection 核心

目标：建立 URL 单一读取面和唯一写入口，但暂不一次性改动所有下游视图。

修改：

- 扩展 `web/src/routes/chat/chatSelectionProjection.ts`：
  - 解析 session/room/project bus/bare/invalid。
  - 保留无关 query params，例如 `focusTask`、`focusTurn`、`returnTo`、`returnLabel`。
  - 提供纯序列化与 compare-and-swap helper。
- 新增 `web/src/routes/chat/useChatRouteSelection.ts`：
  - 绑定 `useLocation`/`useSearchParams`/`useNavigate`。
  - 提供唯一 route action API。
- 在 `ChatCodingRouteWorkbench.tsx` 中把 `activeSessionId` 和 `activeGroupRoomId` 改为 route-derived values。
- 现有大部分下游组件继续接收相同 props，避免无关 UI 重构。
- 新增 route write boundary contract，禁止 Chat 其他模块新增直接 URL writer。

停止条件：某个选择状态无法被 URL 表达。必须先扩展 `ChatRouteSelection`，不能退回第二份 active state。

### 阶段 3：移除 Zustand active session 与双向同步

目标：删除 URL/store 双写和为双写服务的 grace/recovery 代码。

修改：

- `web/src/store/chatWorkbenchStore.ts`
  - 删除 `activeSessionId`、`setActiveSession`。
  - `removeSession/resetSessions` 只操作 `sessionWorkspaces`。
- `web/src/store/chatWorkbenchStore.test.ts`
  - 删除 active focus 断言。
  - 保留 workspace hydrate/open/close/reset 行为。
- `web/src/routes/chat/useChatWorkspaceActions.ts`
  - `handleOpenDirectSession`：prefetch 后只调用 `openSession`。
  - `handleOpenGroupRoom`：只调用 `openRoom`。
  - `handleOpenProjectAgentBus`：进入显式 project bus URL。
- `web/src/routes/chat/useChatSessionSelection.ts`
  - 删除 URL → store、server → store、first session → store effect。
  - 将后端偏好写入拆为 committed-route passive effect，必要时重命名为 `useChatSessionPreferenceSync.ts`。
- `web/src/routes/chat/chatSessionRouteSync.ts`
  - 删除 `SESSION_ROUTE_INTENT_GRACE_MS`、`shouldDeferUrlSessionSync`、`shouldCanonicalizeUrlSessionSelection`。
  - 只保留 not-found/retirement 等纯 route transition policy，或合并进 route selection model。
- 删除 `latestDirectSessionSelectionAtRef` 和仅为 URL/store 顺序服务的 generation/intent 分支；网络去重仍可保留独立 generation，但不能影响路由。

停止条件：仍存在 effect 根据 `activeSessionId !== requestedSessionId` 主动互相同步。

### 阶段 4：一次性 bootstrap 与持久化降级

目标：localStorage 与后端 pointer 只帮助裸 `/chat` 选一次默认值。

裸 route 初始化优先级：

1. 有效 localStorage last-viewed session。
2. 有效 backend last-viewed session。
3. 第一条可见 direct session。
4. 无可用 session 时保持 bare route 并显示空状态。

规则：

- 每个 bare `location.key` 最多 canonicalize 一次。
- 只有 session directory 已成为 authoritative 后才能验证 local/server 候选。
- 显式 session/room/project bus URL 永远跳过 bootstrap。
- canonical URL 提交后，localStorage 只被动写入，不再读取驱动当前页面。
- `GET /api/sessions/active` 只作为 bare bootstrap hint。
- `POST /api/sessions/{id}/select` 只记录 last-viewed preference，并可返回/缓存该 session detail；响应不得导航。
- 快速 A→B 时，A 的晚到响应最多更新 `queryKeys.session(A)`，不能改变 B。

兼容决策：

- 当前阶段不删除 endpoint，不改变 SQLite schema。
- 保留 `activeSessionId` JSON 字段作为兼容字段，但在文档和类型注释中明确其 last-viewed hint 语义。
- 未来若需要清理命名，可另案新增 `lastViewedSessionId`，先双读单写迁移；不纳入本缺陷修复。

### 阶段 5：生命周期与所有切换边界

#### 会话点击与通知

- 用户点击 session：`openSession` 是唯一导航动作。
- hover/focus prefetch：只预取，不能导航。
- desktop notification click：调用同一 `openSession`，属于明确用户意图。
- notification 创建/更新：不能导航。

#### 新建临时 session

- onMutate 缓存 `temp-session-*` detail，并进入 `?session=temp-session-*`。
- onSuccess：先缓存真实 ID；仅当当前 URL 仍是该 temp ID 时 `replace` 为真实 ID。
- 用户已离开：保留当前页面，只把新 session 加入目录。
- onError：保留 temp failure surface，提供“重试”和“返回”；不自动恢复旧 active session。
- temp route 不调用 `/select` 或真实 detail API。

#### 删除、归档、清空历史

- mutation pending 时保留当前 route，可显示 pending 状态。
- 成功后仅当当前 URL 仍指向被操作 ID，才替换到明确计算的 next ID 或 bare route。
- 用户已切走时只修复缓存，不应用 server fallback。
- mutation 失败保持原 route，不执行回滚导航。
- 后台 index 刷新发现 session 缺失时保持 URL并显示 unavailable surface。

#### Self Evolution / workflow handoff

- 只有明确 URL anchor 或用户点击的 handoff action 能导航。
- `loadPendingSelfEvolutionHandoff()` 仅可为当前明确目标 session 填充 draft。
- pending handoff 存在但 URL 没有目标时，不能选择 `matchedSession || active || first`。

#### 群聊与 Project Agent Bus

- `activeGroupRoomId` 从 route selection 派生。
- 新建群聊成功属于明确用户操作，可进入新 room route；若用户在请求期间已离开创建 surface，需要 compare-and-swap。
- Project Agent Bus 使用显式 `?room=__project_agent_bus__`，不再使用裸 `/chat` 加本地 sentinel。

### 阶段 6：被动 telemetry、长期文档与防回归门禁

可保留纯观察事件，例如：

```text
browser.route.committed
```

字段只包含：

```text
pathname
search
navigationType: PUSH | REPLACE | POP
intentSource: primary_nav | session_click | room_click | notification_click |
              explicit_deep_link | initial_canonicalization | lifecycle_result | history_pop
```

要求：

- 事件在 React Router location 已提交后发送。
- telemetry handler 没有 `navigate`、History API 或 selection setter capability。
- 不新增任何“detected/recovered/reconciled 后自动导航”的事件处理器。

长期文档：

- 新增 `docs/adr/0009-chat-route-is-window-local-authority.md`，记录窗口局部 URL authority、后端 pointer 降级和不采用双模式 feature flag 的原因。
- 更新 `docs/agents/conversation-flow-map.md` 的 viewing pointer SSOT 表。
- 更新 `web/src/routes/chat/README.md` 的 selection ownership。
- 若新增源文件，更新相应 route contract/ownership map；不需要新增 VUI primitive 或 design registry 项。

## 8. 任务图与执行边界

Critical Path 串行执行。共享写入面集中在 Chat route selection，不建议把阶段 2–5 并行给不同 owner。

### Task 1：AppShell 不再执行路由恢复

- Owner/Boundary：App shell；只改 `AppShell.tsx` 和对应 navigation telemetry test。
- Dependency：无。
- Mode：`BDD_TDD`。
- Verification/Stop：focus/visibility/pageshow 不产生 navigate；Electron shell link 仍为 SPA navigation。

### Task 2：Chat URL 成为唯一 route selection

- Owner/Boundary：Chat route-domain model/hook、Workbench wiring、Zustand active selection removal。
- Dependency：Task 1 regression gate。
- Mode：`BDD_TDD`。
- Verification/Stop：不存在 URL/store 双向同步；Chat route writer 只有一个。

### Task 3：异步生命周期不能抢页面

- Owner/Boundary：Chat workspace actions、lifecycle、archive retirement、handoff、notification open adapter。
- Dependency：Task 2 route API。
- Mode：`BDD_TDD`。
- Verification/Stop：所有晚到响应通过 compare-and-swap；用户已离开时路由不变。

### Task 4：后端 pointer 语义与长期文档收口

- Owner/Boundary：session route/service compatibility tests、ADR、conversation flow map、Chat README。
- Dependency：Task 2 committed-route preference effect。
- Mode：`SIMPLE`，现有后端 invariant 测试必须保留。
- Verification/Stop：API/schema 无破坏变更；文档不再声称 project-global pointer 是窗口实时页面 SSOT。

### Task 5：整体验收与 runtime 证据

- Owner/Boundary：前端集中测试、后端兼容测试、production build、Launcher 真实窗口验收。
- Dependency：Task 1–4。
- Mode：`SIMPLE`。
- Verification/Stop：自动化矩阵全绿，真实窗口在后台任务与恢复焦点后保持用户当前页面。

## 9. 自动化验收矩阵

| 场景 | 初始 route | 事件 | 预期 route |
| --- | --- | --- | --- |
| 窗口恢复 | session A | focus / visible / pageshow | A |
| 后台任务 | session A | session B busy → idle | A |
| 后端 pointer | session A | server active becomes B | A |
| local preference | session A | localStorage becomes B | A |
| 列表排序 | session A | B recency becomes newest | A |
| stale select | A→B | A `/select` response arrives last | B |
| 用户点击 | session A | click B | B |
| 通知生成 | session A | B completion notification appears | A |
| 通知点击 | session A | click B notification | B |
| browser history | any | Router POP | history target |
| 显式不存在 | missing ID | directory authoritative | missing ID + unavailable surface |
| bare bootstrap | `/chat` | directory + preference ready | exactly one canonical target |
| temp create success | temp T | response real R, still on T | R via replace |
| temp create late | temp T → user B | response real R | B |
| temp create failure | temp T | request fails | T + failure surface |
| delete current | A | delete A succeeds, still on A | explicit next/bare |
| delete late | A → user B | delete A succeeds | B |
| archive refresh | A | background data says A archived | A + archived surface |
| clear history replacement | old A | success R, still on A | R via replace |
| clear history late | A → user B | success R | B |
| pending handoff | A | unrelated pending handoff B appears | A |
| multi-window | W1=A, W2=B | W2 persists pointer B | W1=A, W2=B |

## 10. 测试与验证命令

### 10.1 前端聚焦测试

```powershell
cd web
npm test -- --run `
  src/app/AppShellNavigationTelemetry.test.ts `
  src/app/router.test.ts `
  src/routes/chat/chatSelectionProjection.test.ts `
  src/routes/chat/chatSessionRouteSync.test.ts `
  src/routes/chat/useChatSelectionPersistence.test.ts `
  src/store/chatWorkbenchStore.test.ts
```

新增或扩展的 integration test 应使用 `createMemoryRouter`/RouterProvider 或等价 Router harness，真实证明 committed location 不变；不能只断言纯 helper 返回值。

### 10.2 前端结构与交付门禁

```powershell
cd web
npm test -- --run `
  src/routes/ChatCodingRoute.layout.test.ts `
  src/routes/chat/chatHandTestSubstitute.test.ts `
  src/components/vui/vuiShadcnRouteContract.test.ts `
  src/api/fullStackApiBoundary.test.ts

npx tsc -b --pretty false
npm run build
```

约束：

- route 写入边界测试必须证明 Chat 其他模块没有新增直接 route writer。
- AppShell AST test 必须证明没有直接 History API 调用。
- `fullStackApiBoundary` 预算不得上升；若拆出偏好 API adapter，应降低或保持既有债务预算。
- 本任务不新增可见控件；若 failure surface 需要按钮，复用现有 VUI，不新增 renderer 或第二套设计系统。

### 10.3 后端兼容测试

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_session_viewing_pointer.py `
  tests\test_web_session_routes.py -q
```

必须继续证明：

- background submit 不改 last-viewed pointer。
- child session 默认不改 pointer。
- session list 不把 pointer pin 到第一位。
- `/select` 只写目标 preference，不影响其他 session 数据。
- API 兼容响应仍满足现有调用者。

### 10.4 Launcher 真实窗口验收

所有前端 tests、`tsc -b` 和 build 通过后，使用受管 Launcher refresh；不得使用裸 PowerShell lifecycle 或任何可见控制台路径。

真实验收步骤：

1. 打开 session A，记录地址和选中标签。
2. 让 session B 在后台执行并完成，确认仍停留 A。
3. 最小化/恢复窗口、切换其他应用后回来，确认仍停留 A。
4. 快速点击 A→B→A，等待全部 `/select` 返回，确认最终仍为 A。
5. 点击通知打开 B，确认只有这次明确点击切换到 B。
6. 创建临时 session 后立刻切到其他 session，等待创建成功，确认不被拉回。
7. 在两个 Workbench 窗口分别打开 A/B，分别触发 pointer 写入，确认互不切页。
8. 检查 runtime scene：不存在 `browser.router_location_desync.recovered`；若保留 `browser.route.committed`，其 source 与真实用户动作/POP 一致。

## 11. 风险与保护边界

### 11.1 主要风险

1. **临时 session 之前依赖 store 提前绘制。** 解决方式是把 temp ID 也放进 URL，并继续从按 ID 分区的 Query cache 绘制。
2. **删除/归档当前项之前依赖 store fallback。** 解决方式是 route compare-and-swap，非用户后台缺失改为 unavailable surface。
3. **Project Agent Bus 当前用裸 `/chat` + local sentinel。** 必须先给它显式 route，才能彻底移除 active room local state。
4. **Self Evolution handoff effect 可能隐式选择 session。** 需要区分“明确 handoff route”和“只有 pending payload”。
5. **AppShell recovery 与 Electron anchor interception 写在同一 effect。** 删除 recovery 时必须保留并单测 anchor interception。
6. **当前源码 contract 测试大量使用字符串断言。** 关键 route 行为必须补 Router integration test，不能只改字符串断言让测试变绿。

### 11.2 明确不做

- 不更换 React Router。
- 不引入 TanStack Router 或另一套路由状态库。
- 不把 search param 迁成 path param。
- 不修改数据库 schema。
- 不删除兼容 endpoint。
- 不重排 Chat UI、不重做标签视觉、不修改 VUI 设计系统。
- 不借机重构整个 `ChatCodingRouteWorkbench.tsx`；只抽出 route-domain responsibility。
- 不添加新 feature flag 同时运行旧、新两套 authority。
- 不执行远端 push、PR 或发布，除非用户另行授权。

## 12. 回滚与发布策略

- 每个 Task 形成独立、可验证的本地提交；Task 2–3 共享 route contract，按顺序合入。
- 不使用运行时双模式 feature flag。双模式会重新引入两套 authority，无法作为可靠回滚手段。
- 回滚以提交为单位：若 Task 2–3 未完成，不把半迁移状态合入 `main`。
- 无数据库迁移，因此回滚不需要数据恢复。
- 后端 pointer 与现有 endpoint 保留，旧版本仍可读取。
- 前端改动完成且 build 通过后，Launcher refresh 为 `recommended before user testing`；正式发布前必须完成真实窗口验收。
- 版本影响：行为修复，建议 patch version；无需协议 major/minor bump。

## 13. 完成定义

只有以下条件全部满足，才可声称问题解决：

- `browser.router_location_desync.recovered` 及 recovery 代码从产品源码和测试契约中删除。
- AppShell 不直接调用 History API。
- React Router URL 是 direct session、room、project bus 的唯一 active authority。
- Zustand 不保存 `activeSessionId`，Chat 不保存独立 active room state。
- localStorage 和后端 pointer 只参与 bare route 初始化与被动偏好写入。
- 所有异步生命周期导航都有 compare-and-swap，晚到响应不能抢页面。
- 显式 missing/archived route 不自动 fallback。
- 自动化矩阵、后端兼容测试、`tsc -b`、production build 全绿。
- Launcher 真实窗口验收覆盖后台任务、焦点恢复、快速切换、通知、临时创建和多窗口。
- ADR、conversation flow map 和 Chat README 已同步，不再保留互相冲突的 SSOT 描述。

## 14. 实施入口

后续实现应创建新的独立任务 worktree，并在写入前 claim 以下准确 scopes；本文档 worktree 不承担业务实现：

- `web/src/app/AppShell.tsx`
- `web/src/app/AppShellNavigationTelemetry.test.ts`
- `web/src/routes/chat/chatSelectionProjection.ts`
- `web/src/routes/chat/useChatRouteSelection.ts`（新增）
- `web/src/routes/chat/useChatSessionSelection.ts`
- `web/src/routes/chat/useChatSelectionPersistence.ts`
- `web/src/routes/chat/useChatWorkspaceActions.ts`
- `web/src/routes/chat/useChatWorkspaceLifecycle.ts`
- `web/src/routes/chat/useChatArchivedAgentRetirement.ts`
- `web/src/routes/chat/chatSessionRouteSync.ts`
- `web/src/routes/chat/ChatCodingRouteWorkbench.tsx`
- `web/src/store/chatWorkbenchStore.ts`
- 对应 focused tests、ADR 与 ownership 文档

下一步建议：从 Task 1 开始，用失败回归测试固定“focus/visibility/pageshow 不导航”，随后删除 AppShell desync recovery，并在同一提交中保留 Electron shell anchor 的 SPA 导航保护。
