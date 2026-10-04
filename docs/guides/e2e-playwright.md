# Playwright E2E 手动车道（隔离分支实例）

针对真实分支实例（真实后端 + 真实前端产物 + headless/CDP 浏览器）的端到端测试车道。
当前覆盖：AppShell 全路由只读冒烟（`test_routes_smoke.py`）、主导航性能基线
（`test_perf_baseline.py`，只测量不断言阈值）、会话交互链路（`test_conversation_flow.py`，
发消息/终止/空态/hover 工具条/划词引用）、Agent 生命周期（`test_agent_lifecycle.py`，
三步向导建 Agent + 记忆设置关闭持久化）、快捷键改键（`test_shortcuts.py`，录键/
localStorage 覆盖/冲突抢占）与会话 SSE keep-warm 回归（`test_keep_warm.py`）。
交互与生命周期用例的 arrange 优先走实例 API（`helpers/agent_factory.py`，
POST /api/sessions、POST /api/agents 等，控制令牌同 GET 口径）。

## 车道与挂载约定

- pytest.ini **没有 `e2e` marker（已刻意删除，禁止重新注册）**。本目录所有模块
  使用现有 `serial` marker + `skipif` 环境门：未设 `VIBELUTION_E2E=1` 时逐条
  skip（退出码 0）。因此默认车道、serial 车道、closeout selector 收集到这些
  文件也只会跳过。注意不能用模块级 `pytest.skip(allow_module_level=True)`：
  那会「零收集」，closeout 选择器直跑本目录文件时 pytest 按退出码 5
  （NO_TESTS_COLLECTED）判失败。
- 环境变量：
  - `VIBELUTION_E2E=1`：启用本车道（唯一开关）。
  - `VIBELUTION_E2E_MODE=headless|cdp`：浏览器模式，默认 headless。
  - `VIBELUTION_E2E_LAUNCHER_TRANSPORT=native|desktop_ipc`：生命周期请求通道，
    默认 native。desktop_ipc 要求已运行且可发现的共享桌面壳；仅操作当前测试树的
    `codex/` 任务分支，通过唯一 Launcher 页的官方 bridge 发送请求。
  - `VIBELUTION_E2E_KEEP_DATA=1`：会话结束后保留实例数据目录并打印路径
    （默认清理，保证下一次运行回到空态）。
  - `VIBELUTION_E2E_ATTACH=1`：显式接管当前测试树已就绪的任务实例，不发 start。
    必须是当前 `codex/` worktree 且 registry 已就绪，随后仍校验 health 身份。
    默认 0；本次 pytest 仍负责正常 stop 与数据清理。用于启动响应丢失后的明确恢复，
    不自动启用，也不能把此前的 CLI/IPC 失败改记为通过。
- 测试代码与 fixture 一律 `CREATE_NO_WINDOW` 子进程，禁止 taskkill、禁止可见控制台。

## 运行前置

1. 项目 venv 安装 Playwright（版本与已缓存内核对齐）：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install playwright==1.62.0
   ```

   浏览器内核已在本机缓存（`playwright install` 的产物随 1.62.0 分发），无需重复下载。
2. web 前端产物不需要手工构建：`e2e_instance` fixture 会自动执行
   `tests/e2e/helpers/ensure_web_build.py` —— 用 junction 把根 checkout 的
   `web/node_modules` 映射进 worktree，`npm run build` 一次并写 stamp 到
   `%LOCALAPPDATA%\Vibelution\e2e\build-stamps\<worktree哈希>.json`（仓外，
   不污染 git status；HEAD 未变且 `dist/index.html` 在场时跳过重建）。
   根 checkout 定位用 `git rev-parse --git-common-dir`，不假设固定路径。

## 一条命令跑法

```bash
# Git Bash / pytest 直跑
VIBELUTION_E2E=1 ./.venv/Scripts/python.exe -m pytest tests/e2e -m serial
```

```powershell
# PowerShell
$env:VIBELUTION_E2E = "1"; .\.venv\Scripts\python.exe -m pytest tests/e2e -m serial
```

会话流程：自动构建前端（stamp 命中则跳过）→ Launcher 启动本 worktree 分支实例 →
轮询 `%LOCALAPPDATA%\Vibelution\instances.json` 直到 `desiredState=="open"`、
`status/phase=="steady"`、`spawnPid!=0`、`portLeaseStatus=="held"` → `GET /api/health`
核对 `routesReady==true`、`workspaceRoot==worktree`、`serving.frontend.builtFromCommit`
非空 → 跑测试 → Launcher `stop`（优雅 `POST /api/runtime/shutdown`）→ 断言 registry
`desiredState=="closed"`、`status=="closed"`、`spawnPid==0`、端口租约退出 `held`
（实测 `phase` 停留为 `"steady"` 表示无在飞迁移，与 `core/launcher/service.py` 投影
语义一致）。stop 被在飞 chat turn / work run 挡住时，测试报告并保留现场，不 force-stop。

实例数据目录（registry 条目 `dataHome`）默认在会话结束时清理以回到空态；
`VIBELUTION_E2E_KEEP_DATA=1` 时保留并打印路径。

已运行桌面壳时，可在任务 worktree 用 IPC 通道执行无模型回归。根 checkout 的
Python 路径应由实际 Git common-dir 解析，不要求任务树自带 `.venv`：

```powershell
$root = Split-Path (git rev-parse --path-format=absolute --git-common-dir)
$env:VIBELUTION_E2E = "1"
$env:VIBELUTION_E2E_MODE = "headless"
$env:VIBELUTION_E2E_LAUNCHER_TRANSPORT = "desktop_ipc"
& "$root\.venv\Scripts\python.exe" -m pytest tests/e2e/test_composer_drafts.py tests/e2e/test_finance_focus.py tests/e2e/test_composer_upload_recovery.py -m serial
```

IPC 与浏览器模式独立，headless 默认隐藏分支窗口。IPC 受理后仍须通过上述
registry/health 就绪与关闭核对；失败直接报告，不自动切换 native 或重试生命周期
请求，不聚焦、导航或关闭共享壳。IPC 成功不能作为原生 CLI 通道通过的证据。

## 后端 API 访问口径（控制令牌）

`/api/*` 的 GET（除 `/api/health`、`/api/control-token`）要求携带控制令牌头
`X-Vibelution-Control-Token`（`core/web/control.py`）。令牌经免鉴权引导端点
`GET /api/control-token` 获取（前端 `web/src/api/client.ts` 同口径）。直连实例
后端做断言时必须先 bootstrap 令牌再带头访问，否则得到 403；
`tests/e2e/helpers/instance_registry.py` 的 `fetch_json` 已封装（403 自动刷新重试）。

## 架构：隔离分支实例 + headless/CDP 双模式

- 生命周期归属官方 Launcher（`%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe
  --project "<worktree>" start|stop`，或显式 desktop_ipc 的官方 `launcherInvoke`），
  registry 是运行权威，语义见
  [launcher-branch-development.md](launcher-branch-development.md)。
- **headless（默认）**：函数级 `page` fixture 启动 Playwright 自带 chromium
  （1440x900、zh-CN），指向实例 URL，等 route-header h1 或状态面离开 loading。
- **CDP（`VIBELUTION_E2E_MODE=cdp`）**：用 `scripts/desktop_debug.py --project "<worktree>"`
  发现共享桌面壳，`connect_over_cdp` 后按「页面 URL 端口 == 实例端口」定位分支工作台
  真实窗口（bridge 角色校验优先，端口回退）。实测（2026-09-25）：共享壳对分支窗口
  origin 拒绝 `getDesktopShellSummary` 的 IPC（"blocked ipc sender origin:
  http://127.0.0.1:<branch-port>"），`currentWindow` 在分支页不可得，产品侧若放开
  该 IPC 可恢复角色校验。红线：不 `bringToFront`、不对共享壳发 `Browser.close`；
  `connect_over_cdp` 连接对象的 `close()` 仅断开客户端（官方约定）。
  CDP 发现与窗口身份判定封装在 `tests/e2e/helpers/desktop_cdp.py`。

## 危险按钮禁区（冒烟严禁点击）

纯 `goto`/读取 DOM 是安全面。以下按钮点击即产生副作用，冒烟与基线一律不点：

| 路由 | 危险动作 |
| --- | --- |
| `/logs` | 清理日志 |
| `/launcher`、`/launcher/tools` | 重启/关闭进程 |
| `/agents` | 归档/清除/重置 Agent |
| `/memory/cleanup` | 清理记忆 |
| `/git` | commit / discard |
| `/chat` composer | Enter/发送会创建会话与 turn（冒烟不提交） |
| `/teams` | 已有 meeting round 数据时 auto-draft（空实例安全，仍不点） |

唯一允许的点击面：**主导航** `a[data-vui="route-link-button"][data-chrome="shell-nav"][href="…"]`
（纯路由跳转，性能基线用）。

## 锚点约定速查

无统一 data-testid；约定 = `data-vui` + 原生 ARIA。以下可见性结论实测于
2026-09-25（分支实例 head=23ecd0c3d9d3，headless chromium 1440x900 zh-CN）：

- **主锚点 = 页面根 `data-vui-domain-recipe`**：29 条 AppShell 路由中 27 条带
  该属性且可见（如 `/chat`=chat-session-workbench、`/agents`=agents-management-workbench、
  `/git`=git-workbench、`/config`=config-settings）。仅 `/usage`、`/reset` 无该属性
  （实测豁免，登记于 `test_routes_smoke.py` 路由表）。
- **route-header h1 只对部分路由可见**，按路由逐项断言（同文件路由表带豁免理由）：
  - 可见：`/supervised-evolution/review`、`/memory*` 全部、`/kernel`、`/git`、
    `/usage`、`/logs`、`/pet`、`/reset`、`/config`；
  - 不存在（chat/evolution 工作台布局没有 route-header h1）：`/chat`、`/companions`、
    `/supervised-evolution`、`/supervised-evolution/runs`、`/supervised-evolution/library`、
    `/self-evolution`；
  - 存在于 DOM 但 pane 隐藏（空态布局事实）：`/agents`、`/agents/prompts`、
    `/agents/tools`、`/agents/skills`、`/teams`。
  产品若改动这些布局，对应路由的冒烟会红——此时先复核 DOM 再更新路由表。
- 状态面：`section[data-vui="state-surface"][data-tone="loading|empty|unavailable|error|info"]`；
  加载完成 = 等 recipe 锚点/h1 或 tone 离开 loading。
- URL 断言用前缀匹配：`/chat` 会自动补 `?session=<id>`（自动选中最近会话）。
- 主导航：`nav[data-shell-group="navigation"][aria-label="主导航"]`；项定位
  `a[data-vui="route-link-button"][data-chrome="shell-nav"][href="…"]`；禁用项渲染为
  `span[aria-disabled="true"]`。二级路由（`/agents/*`、`/memory/*`、`/git|/usage|/logs`）
  不在主导航，直接 goto。
- 守卫：`WorkbenchDomainRoute`/`WorkbenchModeRoute` 按配置 302 回 home。断言 URL 前
  先 `GET /api/config/public` 读 `domainAvailability`/`modeAvailability`（语义同
  `web/src/app/workbenchContract.ts`）；smoke 的守卫判定与 home 解析在
  `test_routes_smoke.py`。
- 对话/交互面（后续用例用）：
  - composer 输入框 `aria-label="发送消息"`（placeholder 动态，禁止用 placeholder 定位）；
    发送按钮 aria-label「发送/发送中」；Enter 提交、Shift+Enter 换行。
  - 消息容器 `div[data-agent-thread-message-count]`（免模型断言利器）。
  - 生成中 `role="status"` + `data-active-turn-stage`（user_submit/model_request/
    thinking/responding）+ `data-active-turn-elapsed-seconds`；停止按钮 aria-label「终止」。
  - 会话树 `<nav aria-label="对话索引">`，激活项 `aria-current="true"`。
  - Agent 创建入口 `#agents-create-trigger`（三步向导，成功标题「Agent 已创建」）。
  - 记忆开关：`/agents` config pane「记忆设置」checkbox（`data-vui="checkbox"`），
    保存断言用面板 pill「未保存→已同步」。
  - 快捷键：`/config?section=workbench-interface&page=workbench-shortcuts`
    （`?section=` 是设置分组 id、`?page=` 是页面 id，见 ConfigRoute.tsx）；命令行
    testid `shortcuts-row-<id>` / `shortcuts-modify-<id>` / `shortcuts-recording-strip`，
    状态 chip「默认/已覆盖」，冲突 banner `shortcuts-banner` +「抢占并绑定」；
    命令面板 Ctrl+K、会话搜索 Ctrl+P，覆盖存 localStorage
    `vibelution.shortcuts.overrides`（canonical 串如 `CmdOrCtrl+Shift+l`）。
    VDialog 锚点已透传（2026-09-25 修复 668cfa8c1）：命令面板/会话搜索打开后
    `data-vui="global-command-palette"` / `"global-session-search"` 锚点在 DOM，
    可直接定位；未传自定义值的对话框（如 Agent 创建向导）仍统一
    `[data-vui="dialog-content"]`。
  - hover 工具条 `span[data-conversation-hover-actions="1"]`（断言可见性而非存在性）；
    划词引用菜单 `data-conversation-selection-menu="1"`。
- 空态：全新实例全部路由有空态兜底；`/` 配置读取失败显示「工作台配置读取失败」，
  可当后端不健康的反信号。

## keep-warm 网络断言口径

- 依据 `web/src/routes/chat/sessionStreamWarmRegistry.ts`：会话 SSE 端点
  `GET /api/sessions/:id/events?initial=none`；离开 `/chat` 后连接保留
  `SESSION_STREAM_WARM_MS = 30_000` ms。
- 断言口径：在 `/chat` 打开会话（记录 `/api/sessions/*/events` 请求数）→ 切走
  （如 `/agents`）→ 30 秒内切回同一会话：**`/events` 不应出现第二次请求**。
- DOM 备选（无网络计数环境）：切回后不应出现 `sessionTranscriptLoading` 的
  「正在加载会话消息…」加载骨架。

## 性能基线口径

`test_perf_baseline.py` 对主导航 8 项（`/chat` `/companions` `/supervised-evolution`
`/self-evolution` `/teams` `/kernel` `/memory` `/agents`）各采集：

- `gotoMs`：`page.goto` → 目标页 `[data-vui-domain-recipe]` 锚点可见；
- `clickNavMs`：从静态中转页 `/reset` 点击主导航项 → URL 到达目标 + recipe 锚点可见；
- `window.performance`：DOMContentLoaded/load、资源数、JS 堆；
- 遥测事件计数（拦截 `POST /api/runtime/browser-telemetry` 放行并统计）：
  `browser.route.changed`、`browser.chat_route.chunk_load_started/loaded`。

只测量、不断言阈值（阈值在积累数据后另行评定）。结果 JSON 落
`C:\vtmp\vibelution-e2e\perf_baseline_<时间戳>.json`，stdout 打印简表。

## 只读轮询本底（解读性能数字时扣除）

`/chat` 目录轮询+会话 SSE；`/logs` 5s/10s；`/git` 6s+30s；`/usage` 10s；
evolution 30s+条件快询；`/agents` 15s（activity 12-20s）；`/companions` 30s；
AppShell「进行中」120s runtime summary。全局每次路由变化有
`POST /api/runtime/browser-telemetry`。

## 排障

- 实例起不来/停不干净：fixture 失败信息自带 registry 条目快照与 launcher 日志目录
  线索（`%LOCALAPPDATA%\Vibelution\projects\*\instances\<slotId>\runtime\launcher\`）；
  不要盲目重试，先核对 `instances.json`。
- 前端白屏或锚点超时：确认 stamp 与 HEAD 一致（删除
  `%LOCALAPPDATA%\Vibelution\e2e\build-stamps\` 下对应 worktree 的 stamp 强制重建），
  或用 `GET /api/health` 的 `serving.frontend.builtFromCommit` 核对实例
  服务的产物身份。
- 路由守卫改判（302）导致 URL 不符：先看 `/api/config/public` 的可用性字段，再核对
  `test_routes_smoke.py` 的路由表与 `workbenchContract.ts` 是否仍一致。
