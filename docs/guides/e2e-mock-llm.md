# E2E 模拟 LLM 服务商（aimock 车道）

针对真实分支实例的端到端测试中，用 [`@copilotkit/aimock`](https://www.npmjs.com/package/@copilotkit/aimock)
充当可控的 OpenAI-compatible LLM 服务商：产品配置中心会话级注册 `e2e-mock`
provider，Agent 对话真实走 litellm → aimock，从而在不依赖真实供应商的前提下
验证对话链路、限流重试、思考阶段与前端渲染鲁棒性。车道代码在
`tests/e2e/mock_llm/`，入口用例 `test_mock_llm_flow.py`（2026-09-25 全量实测）。

## 架构

```
pytest (VIBELUTION_E2E=1)
  └─ e2e_instance fixture（父级 conftest：Launcher 分支实例，见 e2e-playwright.md）
       └─ mock_llm fixture（tests/e2e/mock_llm/conftest.py，会话级）
            1. ensure_aimock_installed()  # %LOCALAPPDATA%\Vibelution\e2e\aimock，stamp 防重装
            2. start_aimock(script=runner.mjs)
               # runner 模式（产品车道默认）：node 直跑 scenarios/runner.mjs，
               # 程序化注册剧本并按「完整 messages」做标记路由（见下节）；
               # AIMOCK_INSTALL_ROOT 环境变量传安装根给脚本解析包
            3. ConfigCenterSession.snapshot()/register()
               # GET /api/config/workspace → POST /config/draft/providers → PUT /config/apply
               # provider: id=e2e-mock, base_url=http://127.0.0.1:<port>/v1,
               #           chat_completions, local_runtime（127.0.0.1 仅允许 local 类）,
               #           auth_kind=none, 模型列表与剧本对齐
            4. 测试：API 建 Agent（dialogue 绑 e2e-mock/<model>）→ UI 发消息 → 断言
            5. teardown（逆序）：restore_and_verify()（unpin 模型 → 删 provider →
               apply → 与注册前快照精确核对）→ AimockServer.stop()（terminate→wait→
               kill→wait，杀不死报错；禁 taskkill）→ 父级 fixture 停实例
```

职责边界：

- `aimock_runtime.py`：安装、空闲端口、node 子进程生命周期、`/health` 就绪轮询、
  journal/reset 控制面封装；`AimockServer(script=...)` 双模式（runner / fixtures）。
- `config_center.py`：配置中心 draft→apply 链（控制令牌头）、provider 条目构造、
  快照/恢复核对。**apply 写的是共享 operator config**
  （`%USERPROFILE%\Documents\Vibelution\config\config.toml`），因此注册前深拷贝
  快照 provider 列表，恢复后逐键核对，不一致即报错保现场；apply 409（并发页面/
  实例改配置）限次重读重试。
- `scenarios/runner.mjs`：**产品车道默认剧本入口**。为什么必须程序化路由（实测）：
  产品主聊天调用的末条 user 消息是 "## Turn Status Bar" 遥测尾巴（composer 正文在
  更早的 user 消息里），而 aimock JSON fixture 的 `match.userMessage` 只匹配**末条**
  user 消息文本——JSON 剧本永远路由不到主调用。runner 对**完整 messages** 做
  `fullUserText.includes(marker)` 谓词路由，并用 `isTitleCall`（末条 user 以
  "用户消息："开头）把标题生成等辅助调用排除在主剧本之外；标题类辅助调用由
  catch-all 兜底。
- `scenarios/fixtures/`：同一批剧本的 JSON 形态，仅供 `fixtures` 模式
  （`AimockServer.start_aimock(dir)` 不带 `script`，等价 CLI `--fixtures`）直接
  研究 aimock 行为或只喂辅助调用时使用；**产品车道不加载该目录**。
- 每条用例 autouse `reset_mock_llm_journal`：`POST /__aimock/reset/journal` 只清
  journal 条目，**保留 fixture 与 sequence 计数**。

## 运行前置

1. 与 `e2e-playwright.md` 相同的前置：项目 venv 装 Playwright、前端产物由
   `e2e_instance` fixture 自动构建（stamp 命中即跳过）。
2. **Node.js ≥ 20.15**（aimock 要求）。`aimock_runtime.py` 依次查找
   `VIBELUTION_E2E_NODE` 环境变量与 PATH 中的 `node`。
3. 首次运行需要网络安装 aimock（固定 `@copilotkit/aimock@1.43.0`，MIT）；安装产物
   落 `%LOCALAPPDATA%\Vibelution\e2e\aimock\`，stamp 命中后零网络。离线机器请预装：

   ```bash
   npm install --prefix "%LOCALAPPDATA%\Vibelution\e2e\aimock" @copilotkit/aimock@1.43.0
   ```

4. 一条命令跑法（Git Bash）：

   ```bash
   VIBELUTION_E2E=1 ./.venv/Scripts/python.exe -m pytest tests/e2e/mock_llm -m serial
   ```

   未设 `VIBELUTION_E2E=1` 时全部 skipif 逐条跳过、退出码 0（与 e2e-playwright
   车道同一环境门口径，`serial` marker + `skipif`，禁模块级 skip）。

## 剧本目录结构与扩写指南

```
tests/e2e/mock_llm/scenarios/
├── runner.mjs                     # 产品车道默认：predicate/动态 response 程序化剧本
└── fixtures/                      # fixtures 模式（--fixtures）用 JSON 形态，车道不加载
    ├── normal_stream.json         # reasoning+markdown、多轮 turnIndex、plain
    ├── incident_signatures.json   # 429/400 抖动、malformed、断流、stall、格式泄漏
    ├── tool_calls.json            # 参数多分片、tool-first 交错
    └── timing.json                # 长思考（thinking 窗口）、慢速流（低 tps）
```

扩写规则（aimock 语义实测于 2026-09-25，spike 证据见
`%LOCALAPPDATA%\Temp\aimock-spike\`）：

- **新增主调用剧本进 `runner.mjs`**：`mock.addFixture({ match: { predicate:
  makeScenarioPredicate("E2E-MOCK-<家族>-V<n>") }, response, ... })`，谓词在完整
  user 文本上做 `includes(marker)` 且自动排除标题调用。每条用例用独立标记，跨用例
  互不串扰——这是不 `POST /__aimock/reset` 的前提下最稳的隔离手段。
- 「首发命中后重试成功」族在 runner 里用**工厂 response + 计数器**（第 N 次请求
  返回不同剧本），等价于 JSON 的 `sequenceIndex`，且计数天然按标记隔离。
- 历史故障签名写法：
  - 429/Retry-After：`{ error: {...}, status: 429, retryAfter: <秒> }`；
  - 确定性畸形 JSON：fixture 级 `chaos: { malformedRate: 1 }`（每次命中必畸形）；
  - 中途断流：`truncateAfterChunks: <n>`，**必须配 `streamingProfile.tps` pacing**
    （否则 Windows 上 RST 先于在途字节到达，客户端收不到任何帧）；
  - stall：`streamingProfile: { ttft: 8000, tps: 10 }`（大 ttft = 首帧前停顿）；
  - 时间断流：`disconnectAfterMs`（同样要配 pacing）。
- 时序剧本：`streamingProfile: { ttft, tps, jitter }`；`tps` 越低流越长。
- provider 侧模型对齐：`config_center.MOCK_PROVIDER_MODELS` 的 `upstream_id`
  即产品发送的 `model` 字段；新增模型家族时同步补 pin（`e2e-mock-chat` 走
  reasoning 合同、`e2e-mock-tools` 走 tool 合同，`model_protocol` 必须显式
  `openai_chat_tools`，否则协议解析兜底成 no-tools 合同、绑工具时 fail-fast）。

## journal 断言口径

- `GET /__aimock/journal`（封装 `AimockServer.journal(path=..., status=...)`）返回
  请求条目：`{method, path, body:{model, stream, messages}, response:{status,
  fixture, interrupted?}}`。条目只在 **aimock 自己**收到的请求上累积。
- **主调用请求体通常不进 journal**：journal 单条 body 上限 64KB，主调用带完整
  系统提示与遥测尾巴会超限，条目里 `body` 为空（`model`/`messages` 取不到）。
  因此「主调用命中剧本」的产品侧证据是**时间线正文**与 llmUsage（provider=local、
  model=e2e-mock-*），journal 侧可断言的是条目数与状态码序列。
- 「本轮只打了 mock」的可断言口径：用例前 `reset/journal` 清条目 → 用例内断言
  ①`path=/v1/chat/completions` 条目非空；②所有请求 `model ∈ {e2e-mock-chat,
  e2e-mock-tools, ""}`（空 model 为辅助调用）。注意标记 200 命中可由标题调用
  满足（其末条 user content 为"用户消息：<正文>"含标记），主调用证据仍以上屏
  正文为准；「无真实调用」由「Agent 绑定的是 e2e-mock 模型 + journal 全量命中
  断言」联合保证。
- 429 重试链：journal 中同剧本应同时出现 `status=429`（首发）与 `status=200`
  （重试），即产品重试链路的真实证据。

## 已知缺口与产品实测事实（勿当 bug 反复试）

- **UI 投影滞后**：thread 转 idle（`data-agent-thread-status=idle`）时助手正文
  的 DOM 投影可能落后一拍，即时读 `inner_text` 会拿到没有正文的时间线；用例统一
  用 `wait_thread_text(page, needle)` 轮询等文本上屏后再断言。
- **thread 容器文本含 composer 常驻件**：`thread_text` 会带出权限档按钮
  （"请求批准"）、模型 pill、上下文占用（"13%"）等 composer chrome，属正常，
  不是审批卡片。
- **格式泄漏渲染吞字**：`<think>`/`<summary>` 等原始 HTML 标签连同标签内文本被
  渲染器丢弃，且紧随其后无空行的明文段也会被并入 HTML 块丢弃；只有纯文本行上屏。
  泄漏用例闸门只锁「原始行可见 + 不炸 + 收口」。
- **流式 markdown 偶发丢代码块**：增量渲染在 ``` fence 的 chunk 边界上不稳定，
  同一内容偶发整块代码块不渲染（非流式复现可正常渲染）；正文硬断言只锁标题、
  列表与行内代码，代码块仅打印事实。
- **提交偶发冻结在乐观态**：同一实例连续跑多个用例后，偶发提交停在
  「已发送 · 0s」乐观态、服务端未起 turn（journal 为空）；用例统一走
  `wait_turn_started`（等 stage 条或 journal 出现请求，超时重发一次）。
- **tool_calls 对未绑工具 Agent**：mock 返回 tool_calls 后产品 turn 以
  runtime_error（`turn_journal_replay_failed`，"Seeded chat history does not
  match ConversationLedger reconstruction"）失败，时间线出「请求错误/重试」内联
  卡片——未声明工具却收到 tool_calls 应优雅降级，这是产品缺陷嫌疑（2026-09-25
  记录）；车道闸门只锁「到达 mock + 收口 + 页面存活」。
- **同实例第 6 个 Agent 的 turn 被静默丢弃**：同一实例连续建/用/删 5 个 Agent 后，
  第 6 个 Agent 的对话 turn 会停在各阶段之前被静默丢弃（thread 回 idle、乐观态
  行冻结在「已发送 · 0s」、无错误面、主调用不发向 LLM；重发同样被丢）。产品
  turn 调度缺陷嫌疑（2026-09-25 记录）；因此 `test_tool_calls_turn_closes_without_crash`
  排在套件首位（全新实例上稳定），其余用例由 `complete_turn` 的「主调用未到
  mock 则整轮重发一次」兜底。
- **进程零残留口径**：正常会话由 `AimockServer.stop()`（terminate→wait→kill→wait）
  收口，teardown 断言 `assert_stopped()`；若诊断脚本/会话在 stop 前崩溃，aimock
  node 进程会成为孤儿（无 job object 托管）。核查与清理（只匹配本车道安装路径）：

  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like '*Vibelution*e2e*aimock*' }
  # 确认后 Stop-Process -Id <pid> -Force
  ```
- **无 `[Done]` 开关对本栈无意义**：litellm 对缺失 `[DONE]` 的 clean FIN 兼容
  （spike L4 实测），产品不暴露该开关位，剧本不需要覆盖。
- **chaos 原始字节不进 journal**：`malformedRate` 畸形的原始响应体不会出现在
  journal 条目里（journal 记录的是 fixture 意图与状态），畸形断言只能落在产品侧
  （turn 失败形态/页面存活）。
- **`POST /__aimock/reset` 会清空全部 fixture**（源码 `clearFixtureQueue:
  fixtures.length = 0`，runner 模式下清掉的是程序化注册的剧本）：测试间严禁使用；
  隔离只靠 `reset/journal` + 用例级唯一标记。
- 400 网关抖动签名（`E2E-MOCK-400-V1`）已入库为剧本；当前产品对 400 的分类若为
  不可重试，该签名仅供演练与回放，不进产品级用例。
- aimock 进程日志写系统临时目录（`aimock-e2e-*.log`），排查启动失败时先看它
  （runner 模式下 aimock 请求日志未接 console，文件通常只有启动行）。

## 与 e2e-playwright.md 车道的关系

本车道是 e2e-playwright 手动车道的**下沉**：实例生命周期、控制令牌、页面锚点
约定全部复用父级口径（`tests/e2e/conftest.py` 的 `e2e_instance`/`page` fixture，
本目录零复制）；唯一新增的是可控 LLM 后端这一层。两份文档互为引用但不合并：
e2e-playwright.md 覆盖全路由冒烟/性能基线，本文只覆盖 mock LLM 对话链路；
本文互链改动留给后续任务（不修改对方文件）。
