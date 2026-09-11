# Command Code Headless CLI 传输 PoC 设计稿

> 日期：2026-09-11
>
> 状态：USER-REQUESTED / PROPOSED FOR REVIEW
>
> 版本：V1
>
> 文档用途：为「用 Command Code headless CLI 作为 Vibelution 的模型传输层」这一方向提供可执行的探针方案、量化 GO/NO-GO 判据，以及必须先裁决的架构阻碍清单，供决定是否进入集成设计。
>
> 当前完成范围：只在任务 worktree 内新增本文档与索引条目。未编写探针代码，未调用模型，未修改产品运行路径，未新增 provider，未改动 operator config。
>
> 证据性质：文中标注「实测」的条目为 2026-09-11 在本机直接观察所得；标注「官方文档」的条目来自 commandcode.ai 公开文档抓取；其余均为待验证假设，不以推测充当结论。
>
> 关闭条件：探针执行完毕并给出 GO / NO-GO 后更新状态。NO-GO 时回填证据并归档；GO 时另立集成设计，本文不就地改写为集成设计。

## 1. 问题定位

当前 Vibelution 的 `command_code` provider 走 Provider API 的 `/v1/chat/completions`，与 Command Code 官方 CLI 走的是两条不同协议路径：

| 维度 | 官方 CLI | Vibelution |
| --- | --- | --- |
| 端点 | `/alpha/generate`（私有代理协议，非公开文档） | `https://api.commandcode.ai/provider/v1/chat/completions`（官方公开文档） |
| 历史传法 | 只发当前用户消息 + `threadId`，对话状态由中转站服务端保存 | 每轮重发全部历史（含工具调用与思考内容） |
| 思考态回传 | 客户端从不回传 `reasoning_content` | 由客户端携带并回传 |

已完成的排除实验（来自 2026-09-10/11 的既有工作，本文不重复执行）：

- 失败时抓取并原样重放请求，每条都带 `reasoning_content` 仍被拒 → 不是载荷缺字段。
- 6.7 万 token 的 A/B 实验（裸发 / 加 `reasoning_effort: "max"` / 剥掉 `reasoning_content`，各 4 发）12 发全部 200 → 不是客户端参数问题。
- CLI 请求确实携带 `reasoning_effort: "max"`，但它不是成败开关。
- 坏窗口为时段性：上午 09:02–09:06 六连失败，前后正常。

结论：这是上游路由的时段性可用性问题，任何客户端参数都躲不开。本文评估的假说是——**换用 CLI 所在的那条通道能否在结构上绕开它，并顺带消除每轮重发大历史的成本**。

## 2. 官方能力与边界（公开文档）

来源：`https://commandcode.ai/docs/provider`、`https://commandcode.ai/provider`、`https://commandcode.ai/docs/headless-mode`（2026-09-11 抓取）。

- **Provider API 是无状态的**：文档全篇没有 threadId 或历史托管概念，两个端点均按标准请求体逐次自带头。CLI 的服务端历史能力**只存在于 `/alpha/generate`**，公开 API 不提供。
- **官方分工建议**：文档明确 "A direct API call gets you the model. The CLI gets you the whole harness."，自动化场景建议走 `cmd -p`。即官方认可的「CLI 当传输」路径真面目是 headless 模式。
- **计划门**：除 Go 计划外所有计划都有 API 访问；Go 调 Provider API 返回 `403 upgrade_required`。CLI 登录态与 API key 同源。
- **模型与端点绑定**：`/v1/messages` 只收 Anthropic 系，`/chat/completions` 只收非 Anthropic 系，错配返回 `400 invalid_request_error`。分类 400 时必须先排除这一类，不能误认成上游瞬时故障。
- **5xx 语义**：文档写明 5xx 的 body 携带上游 provider 的原始错误消息，可作为「网关 400（我们的问题）」与「上游故障（应 fallback）」的区分判据。
- **ZDR**：请求头 `x-cmd-zdr: 1`（等价 `CMD_ZDR=1`）只路由到支持零留存的上游，无可用上游时返回 `422 cmd_zdr_no_providers` 而非回退。本文不决策是否启用，仅登记为待决项。

## 3. headless 模式事实（公开文档）

- 入口：`cmd -p "<query>"`，或 `echo "..." | cmd -p` 读管道输入；stdin 有 30 秒超时。
- 输出：`--output-format json` 输出 NDJSON，每行一个对象。事件帧形如 `{"type":"event","event":{"type":"tool_running",...}}`，最后一行为唯一的结果帧 `{"type":"result","subtype":"success|error|max_turns","sessionId":...,"stopReason":...,"usage":{...},"durationMs":...,"finalText":"..."}`。文档只给了一个事件帧示例，**事件类型全集未文档化**，并要求消费者对未知 `event.type` 保持前向兼容。
- 会话：每次运行落盘 session 记录；`--continue`（或 `-c`）续当前目录最近一次 headless 会话；`--resume <sessionId>` 精确续接；`--verbose` 把 session id 打到 **stderr**（stdout 保持洁净）。headless 会话单独打标，不出现在交互式 `/resume` 列表中。
- 权限：headless 默认**阻断**文件写入与 shell 命令，读类工具仍允许；`--yolo` 才放开。`--tools-all` / `--tools-enable` 可按名开启被 headless 屏蔽的工具。
- 退出码结构化：`0` 成功、`3` 未认证、`4` 权限拒绝、`5` 限流、`6` 网络、`7` 服务端 5xx、`8` 触顶 max-turns、`9` 无响应、`10` 余额不足、`130` 中断。
- headless 明确**不支持 slash 命令**；会话生命周期命令（如 `/clear`、`/reload`）在一次性模式下没有意义。
- CLI 选项中有 `--fork-session`（配合 `--resume`/`--continue` 把会话分叉，原会话不动）。

## 4. 本机环境实测（2026-09-11）

| 项 | 实测结果 |
| --- | --- |
| CLI 版本 | `command-code` 1.53.0 |
| npm 全局 prefix | `%LOCALAPPDATA%\BossAI\runtimes\node-v24.15.0-win-x64` |
| 可用 shim | `cmd` / `cmd.cmd` / `cmd.ps1`、`cmdc` / `cmdc.cmd` / `cmdc.ps1`、`command-code*`、`commandcode*` |
| 登录态 | `%USERPROFILE%\.commandcode\auth.json` 存在；`providers.json` 不存在（未配置 BYOK provider） |
| 产品侧通道 | operator config `[llm.providers.command_code]` → `base_url = "https://api.commandcode.ai/provider/v1"`、`driver = "openai"`、`protocols.default = "chat_completions"` |

**命名冲突（必须在探针第一步钉死）**：

- `shutil.which("cmd")` 解析到 `...\cmd.CMD`（Command Code 的 npm shim）。
- 但 `subprocess.run(["cmd", ...])` 在 Windows 上实际执行 `C:\Windows\System32\cmd.exe`：以 `/c echo PROBE_CMD_EXE` 判别，返回码 0、stdout 为 `PROBE_CMD_EXE`，即命中的是 Windows 命令解释器。
- 结论：**任何裸 `cmd` 的 spawn 都不会到达 Command Code**，且会启动被 §2 红线禁止的命令解释器。探针必须显式解析并调用确定的可执行体。

**无控制台红线约束**：即使探针是开发期工具，也应复用 `scripts/windowless_subprocess.py` 的 `no_window_subprocess_kwargs()`（`CREATE_NO_WINDOW` + 隐藏 `STARTUPINFO`），与产品侧同一策略，避免验证出一套与产品不同的启动行为。

## 5. PoC 定位与范围

**这是一次外部探针，不是产品集成。**

- 探针独立于产品运行路径：不改 `core/llm/`、不改 config、不新增 provider、不写产品数据目录。
- 探针只回答「CLI 通道是否值得进一步投入」，不回答「如何集成」。
- 探针产生的原始证据写任务专属临时目录（Git common-dir 任务目录或系统临时目录），不回填产品树；文档只回填聚合数字与结论。

原因：第 8 节的架构阻碍（历史权威、工具执行归属）在探针阶段无法消除，若先做集成再发现阻碍，成本无法回收。先用最小代价验证假说。

## 6. 探针设计

### 6.1 可执行体解析（P0，不产生模型费用）

按优先级尝试并记录哪一种实际可用：

1. 显式路径 shim：`<npm-prefix>\cmd.cmd`；
2. Node 直调：`node <npm-prefix>\node_modules\command-code\<入口脚本>`；
3. 显式 `cmd.exe /c <shim>`。

每种方式都要记录：是否成功启动、是否产生可见控制台、版本输出是否与 1.53.0 一致。**若唯一可行方式是第 3 种，本文将其记为潜在红线冲突**（产品路径禁止命令解释器后台壳），并在 GO 结论中单列，不得静默接受。

### 6.2 调用形态

- 探测命令：`<exe> -p "<query>" --output-format json --skip-onboarding -t`
  - `--skip-onboarding` 用于自动化运行；
  - `-t/--trust` 跳过项目信任提示，避免 headless 挂起；
  - **不使用** `--yolo`：探针依赖 headless 默认的「禁写 + 禁 shell」语义；
  - stdin 置 `DEVNULL`，规避 30 秒管道超时。
- **cwd 设为隔离空目录**，避免 CLI 的读类工具误读项目文件、污染证据。
- sessionId 只从结果帧的 `sessionId` 字段读取；`stdout_regex` 那条既有约定（见第 9 节）不适用于 `cmd -p --verbose`，因为 session id 走 stderr。

### 6.3 采集项

| 类别 | 采集内容 |
| --- | --- |
| 时序 | spawn→stdout 首字节（冷启动）、spawn→首个 NDJSON 帧、spawn→结果帧、总耗时 |
| 用量 | 结果帧 `usage`（输入/输出/缓存命中），与 HTTP 路径同任务对照 |
| 事件 | 事件帧 `event.type` 全量清单与计数；未知类型必须记录而非丢弃 |
| 失败 | 退出码、stderr 签名，区分 `reasoning_content` 400 / 5xx / 限流 / 超时 |
| 保真 | 中文往返是否损坏；stdout 是否被非 JSON 内容污染（管道纯净度） |
| 控制台 | 全程是否出现可见窗口 |

### 6.4 对照控制

模型必须对齐，否则结论不可比：探针用 `--list-models`（或 `GET /provider/v1/models`）确认 CLI 侧模型 id，并核对与 HTTP 路径所用模型为同一上游条目。两侧模型不一致时，本次采样作废。注意产品配置中的 `upstream_id` 为 `openai/deepseek/deepseek-v4.1-flash`，与文档示例的拼写风格不同，需以线上目录为准。

## 7. GO / NO-GO 判据

初始阈值如下，执行前可调整，但必须在采样前固定并写入证据文件。

| 编号 | 判据 | 阈值 | 失败含义 |
| --- | --- | --- | --- |
| G1 | 结构免疫 | 在已知坏窗口时段连发 ≥ 20 次，`reasoning_content` 400 次数为 0，整组成功率 ≥ 95%（同期 HTTP 基线作对照） | 假说被证伪，直接停止本方向 |
| G2 | 冷启动可接受 | spawn→首个文本增量帧 ≤ 同期 HTTP `ttftTotalMs` P50 的 2 倍 | 无收益，停止（除非仅用于后台批处理） |
| G3 | 历史成本下降 | 同一 ≥ 4 轮工具往返任务，累计输入 token ≤ 当前 HTTP 模式的 20% | 收益不足，重新评估动机 |
| G4 | 流式保真 | 能增量获得文本输出，而非仅在终态得到全文 | 降级为「仅非交互批处理可用」 |
| G5 | 会话连续与隔离 | 第 2 轮能答出仅第 1 轮存在的随机串；同 cwd 两个并发会话不串线 | 会话模型不可用于多会话产品 |
| G6 | 无可见控制台 | 全程零可见窗口 | 触碰 §2 红线，禁止进入产品路径 |
| G7 | 工具可观测 | 事件帧中能看到工具调用与结果 | 影响后续集成评估，不单独否决 |

判定组合：G1 失败即 NO-GO；G1 通过但 G2 失败为「无收益 NO-GO」；G1+G2 通过而 G4/G5 失败为「受限 GO」。

**HTTP 基线不新增测量代码即可获得**：`core/llm/ttft_breakdown.py` 已在真实回合产出 `llm.stream.ttft_breakdown` 场景事件（含 `ttftTotalMs` 与各分段），直接取最近 N 回合作对照分布。

## 8. 架构阻碍（Step 2 的准入问题，PoC 不解决）

以下问题不由探针解决，探针只提供判断数据。若第 8 节任一项无法回答，不得进入集成设计。

| 编号 | 阻碍 | 说明 |
| --- | --- | --- |
| B1 | **历史权威转移** | `cmd -p` 只接受单条 query，公开文档未提供注入结构化历史（含工具轮次）的入口。用 CLI 传输即意味着历史权威落在 CLI 会话侧，与 `turn_journal` 权威、checkpoint/rewind、`/tree`、fork、`conversation_invariant`、压缩策略正面冲突。CLI 侧有 `--fork-session` 可对应 fork，但 rewind/tree/checkpoint 是交互式 slash 能力，headless 明确不支持。这是最大阻碍，不是实现细节。 |
| B2 | **工具执行归属** | headless 下读类工具仍由 CLI 自行执行，产品无法拦截审批、授权与证据链。若要把 Vibelution 的工具经 MCP 暴露给 CLI 以收回执行权，工具循环的控制权归属随即改变：谁拥有 loop、谁写 journal、谁做修复与回放，都需要重新定义。 |
| B3 | **无控制台红线** | 若唯一可行调起方式必须经 `.cmd` shim 或命令解释器，将与 §2 红线（禁止 `cmd` 后台壳）冲突。替代方案是直调 Node 入口，但那依赖未公开的包内部布局，稳定性自负。此项必须在 GO 之前有结论。 |
| B4 | **计费口径** | CLI 走计划额度，Provider API 走 API 计费，两套计量口径不同。G3 的「省 token」若不同时对齐成本口径，不能直接推断为省钱。 |
| B5 | **会话身份** | headless 会话单独打标，`--continue` 以 cwd 定位「最近一次」。产品多实例、多会话、并发回合场景需要显式 sessionId 管理，不能依赖 cwd 隐式定位。 |

## 9. 复用与不复用

| 对象 | 裁决 | 理由 |
| --- | --- | --- |
| `scripts/windowless_subprocess.py` | **复用** | 产品级无控制台 spawn 策略，探针必须同源，避免验证出与产品不同的启动行为 |
| `core/llm/ttft_breakdown.py` 的分段语义 | **复用** | 保证 TTFT 口径与现状可比，无需为对照另建计量 |
| `core/web/services/cli_agent_service.py` 的运行记录/超时/输出裁剪约定 | **参考，不复用** | 该服务是阻塞式 `subprocess.run` + 输出预览 + 截断，面向「委派任务返回结果」，不是流式回合传输；直接用会把流式保真（G4）判死 |
| `core/web/services/cli_agent_service.py` 的 `sessionId.source = "stdout_regex"` 约定 | **不适用** | `cmd -p --verbose` 的 session id 走 stderr；应改用结果帧 `sessionId` 字段 |
| `core/web/services/cli_agent_task_kernel.py` 的终端屏捕获语义 | **不适用** | 面向 `pty_agent` 交互终端，与 NDJSON 流无关 |
| `core/llm/client.py` 的 canonical 契约 `stream_events(...) -> TurnOutcome` | **Step 2 的唯一正确插入点，PoC 阶段不实现** | 下游 journal、SSE、UI 均消费该契约；任何传输替换都必须合成同一组协议事件与终态，不得另建并行通路 |

## 10. 实施顺序

| 阶段 | 产出 | 是否产生模型费用 |
| --- | --- | --- |
| P0 可执行体解析 | 可用调用形态与版本、控制台行为记录（§6.1） | 否 |
| P1 单发冒烟 | 一次调用的完整 NDJSON、事件类型清单、结果帧结构 | 是（1 次） |
| P2 会话连续与并发 | G5 证据：跨轮记忆、同 cwd 并发隔离 | 是（小样本） |
| P3 坏窗口对照采样 | G1 证据：坏窗口时段 ≥ 20 连发 + 同期 HTTP 对照 | 是（主要预算） |
| P4 多轮工具往返 | G3 证据：同任务累计输入 token 对照 | 是 |
| P5 结论回填 | 回填本文档聚合数字与 GO/NO-GO | 否 |

P1 若发现事件帧不携带增量文本（G4 直接失败），可提前终止，不必进入 P3。

## 11. 授权边界与风险

- **费用**：P1–P4 会真实调用模型并计入计划额度。执行前必须由用户给出调用次数上限与时段，不设默认无限预算。
- **不触碰**：不执行 `/alpha/generate` 协议逆向（无公开文档）；不改 operator config；不新增 provider；不做 ZDR 决策。
- **风险登记**：

| 风险 | 处置 |
| --- | --- |
| 冷启动抵消收益 | 由 G2 量化判定，不凭感觉 |
| 双层 harness 语义漂移（CLI 自带工具循环叠加产品编排） | 由 B2 裁决；探针阶段不实现，只看事件可观测性 |
| 探针结论被误读为集成可行 | 本文档固定「探针 ≠ 集成设计」，GO 后另立文档 |
| 采样受时段影响，坏窗口不可复现 | 以「同期 HTTP 对照」为核心方法，不做跨时段比较 |
| 中文或编码损坏被忽略 | 纳入 §6.3 保真采集项，损坏即记为失败 |

## 12. 非目标

- 不做 `/alpha/generate` 协议适配或逆向。
- 不实现产品侧传输替换，不改 `core/llm/` 任何文件。
- 不评估「用 CLI 替代 Vibelution 编排」这一产品方向，那是 B2 的下游决策。
- 不把本探针的结论当作科学或竞赛方向的证据。

## 13. 验证与收口

本文档为纯文档变更：

- 验证方式：文件差异、章节交叉引用与索引链接一致；不新增测试。
- 刷新判断：`not needed`（不进运行时，无产品版本影响）。
- 证据形态：探针原始 JSON 留在任务专属临时目录，文档只回填聚合数字与结论。

## 14. 下一步对齐

需要用户确认的事项：

1. 是否授权执行探针（P0–P4），以及调用次数上限与可执行时段；
2. §7 的阈值是否按本稿固定，特别是 G2 的 2 倍与 G3 的 20%；
3. 若 P0 发现唯一可行调起方式必须经 `.cmd` shim，是否愿意为此在 B3 上单独立项裁决。

上述确认后，先执行 P0/P1（成本最低、信息量最大），再决定是否进入 P3 的坏窗口采样。
