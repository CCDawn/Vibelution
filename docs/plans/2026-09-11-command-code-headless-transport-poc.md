# Command Code Headless CLI 传输 PoC 设计稿

> 日期：2026-09-11
>
> 状态：USER-REQUESTED / PROPOSED FOR REVIEW（P0/P1 已执行，结果见 §7.1；G1 未测，无 GO/NO-GO 结论）
>
> 版本：V1.1（纳入 P0/P1 实测，并据实修订 G3 度量与 G4 判定）
>
> 文档用途：为「用 Command Code headless CLI 作为 Vibelution 的模型传输层」这一方向提供可执行的探针方案、量化 GO/NO-GO 判据，以及必须先裁决的架构阻碍清单，供决定是否进入集成设计。
>
> 当前完成范围：探针 P0（可执行体解析）与 P1（单次冒烟）已执行并留证，结果与两处判据修订见 §7.1。P2–P5 未执行，G1 的核心假说（坏窗口结构免疫）尚未验证，因此**本文不给出 GO/NO-GO 结论**。产品运行路径、operator config、provider 均未改动；探针脚本与原始证据只存在于会话临时目录。
>
> 证据性质：文中标注「实测」的条目为 2026-09-11 在本机直接观察所得；标注「官方文档」的条目来自 commandcode.ai 公开文档抓取；§7.1 为真实探针输出（P1 消耗 1 次真实模型调用）；其余均为待验证假设，不以推测充当结论。
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

**命名冲突（P0 已钉死）**：

- `shutil.which("cmd")` 解析到 `...\cmd.CMD`（Command Code 的 npm shim）。
- 但 `subprocess.run(["cmd", ...])` 在 Windows 上实际执行 `C:\Windows\System32\cmd.exe`：以 `/c echo PROBE_CMD_EXE` 判别，返回码 0、stdout 为 `PROBE_CMD_EXE`，即命中的是 Windows 命令解释器。
- 结论：**任何裸 `cmd` 的 spawn 都不会到达 Command Code**，且会启动被 §2 红线禁止的命令解释器。探针必须显式解析并调用确定的可执行体。
- P0 已给出可用替代路径，见 §7.1。

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

已执行，结果见 §7.1：第 1、2、3 种全部可用，且第 2 种完全不需要 shell 层。可执行体的「是否产生可见控制台」无法从会话内部目视确认，记录的是结构性事实（是否经过 shell 层）与所用 flags；产品化时仍须以 `no_window_subprocess_kwargs()` 为准并由人工目视复核一次。

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
| G2 | 冷启动可接受 | 受控同任务 A/B：`cmd -p` 端到端首字延迟 ≤ HTTP 路径 `ttftTotalMs` 的 2 倍 | 无收益，停止（除非仅用于后台批处理） |
| G3 | 上传量与首字延迟下降（**度量已修订，见 §7.1**） | 同一 ≥ 4 轮工具往返任务，客户端上传字节数显著低于 HTTP 全量重发，且 TTFT 不劣化 | 收益不足，重新评估动机 |
| G4 | 流式保真（**判定方式已修订，见 §7.1**） | 在数百 token 量级的长答案下，文本增量跨越数秒陆续到达，而非终态前一次性冲刷 | 降级为「仅非交互批处理可用」 |
| G5 | 会话连续与隔离 | 第 2 轮能答出仅第 1 轮存在的随机串；同 cwd 两个并发会话不串线 | 会话模型不可用于多会话产品 |
| G6 | 无可见控制台 | 全程零可见窗口 | 触碰 §2 红线，禁止进入产品路径 |
| G7 | 工具可观测 | 事件帧中能看到工具调用与结果 | 影响后续集成评估，不单独否决 |

判定组合：G1 失败即 NO-GO；G1 通过但 G2 失败为「无收益 NO-GO」；G1+G2 通过而 G4/G5 失败为「受限 GO」。

**HTTP 基线不新增测量代码即可获得**：`core/llm/ttft_breakdown.py` 已在真实回合产出 `llm.stream.ttft_breakdown` 场景事件（含 `ttftTotalMs` 与各分段），直接取最近 N 回合作对照分布。

### 7.1 已执行记录（P0 / P1，2026-09-11）

探针脚本与原始证据（`p0-result.json`、`p1-result.json`、`p1-stream.ndjson`）只存在于会话临时目录，不进产品树；本节只回填聚合数字与结论。所有 spawn 均经 `no_window_subprocess_kwargs()`。

**P0 可执行体解析**（不产生模型费用）：三条候选路径全部到达 CLI 并输出版本 `1.53.0`，唯裸 `cmd` 是反例。

| 路径 | 结果 | 耗时 |
| --- | --- | --- |
| `node.exe` + `dist\index.mjs` | 到达 CLI，**无 shell 层** | 1929ms |
| `<prefix>\cmd.cmd` | 到达 CLI（经 shell 解释） | 4057ms（进程内首次，含冷启动） |
| `cmd.exe /c <prefix>\cmd.cmd` | 到达 CLI（显式解释器） | 1654ms |
| `<prefix>\cmdc.cmd` | 到达 CLI（经 shell 解释） | 1489ms |
| 裸 `cmd`（对照） | 命中 `cmd.exe`，未到达 CLI | 30ms |

包 `bin` 字段把 `cmd` / `cmdc` / `command-code` / `commandcode` 全部映射到同一入口 `dist/index.mjs`。**结论：可执行体解析不构成阻碍，B3 的红线冲突可规避**——直调 Node 入口不需要任何 shell 层。实现时应像 npm 生成 shim 那样在运行期读取 `package.json` 的 `bin` 字段解析入口，而不是硬编码路径，以免绑定包内部布局。

**P1 单次冒烟**（消耗 1 次真实模型调用）：一次 `-p` 调用，prompt 要求读取工作目录中的文件并回报内容，因此 CLI 内部产生 2 个上游回合（工具回合 + 最终回答回合），正是 HTTP 路径出问题的场景类别。

- 退出码 0，`subtype: "success"`，`stopReason: "end_turn"`；`finalText` 正确回报文件内容，工具往返完整成功。
- 35 行输出全部为合法 NDJSON，零解析失败；stdout 纯净，`--verbose` 的 session id 落在 stderr（验证了 §9 的既有约定判断）。
- 事件类型全清单（官方文档只给了一个示例，此处为探针补齐）：`run_start`、`turn_start`、`message_start`、`model_request_start`、`model_trace`、`message_update`、`model_request_end`、`message_end`、`tool_queued`、`tool_running`、`tool_completed`、`text_delta`、`turn_end`、`run_end`。
- 时间线：首个 NDJSON 帧 1699ms，末帧 8787ms；CLI 自报 `durationMs` 7262ms，差值约 1.5s 即 Node 进程启停开销。**7 个文本增量帧全部落在 8730–8742ms**。
- 用量：总 `inputTokens` 32383、`outputTokens` 78、`cacheReadTokens` 21248；分回合为 16139（缓存 5248）与 16244（缓存 16000）。
- 模型：CLI 自报 `deepseek/deepseek-v4.1-flash`，并显式携带 `effort: "max"`。与出问题的 HTTP 路径所用 `openai/deepseek/deepseek-v4.1-flash` 为同一模型，满足 §6.4 的模型对齐要求。
- `run_end` 携带 `result.nextState.messages`：完整结构化 transcript（含 `messageId`、`createdAt`、`tool_use` / `tool_result` 内容块与 `compaction` 状态），据此修订 §8 的 B1。

**两处判据必须据此修订**：

1. **G3 的度量选错了。** 实测显示 CLI 的计费 token 并不小（单次小任务 32k 输入、其中 21k 命中缓存）。服务端持有历史减少的是**客户端上传量与冷前缀重算**，不是账单 token 数。G3 应改为度量「客户端上传字节数」与「TTFT」，而非「累计输入 token ≤ HTTP 的 20%」。按原指标，一个真实收益会被判成失败。
2. **G4 未被本次采样证实。** 7 个 `text_delta` 集中在 8742ms 前后约 12ms 内，结果帧随即在 8787ms 到达。这既可能是上游一次性产出短答案（15 字符），也可能是 CLI 在终态前批量冲刷——观察窗口太短，不能据此判定流式保真。G4 需改用**长文本答案**（数百 token 量级）重测，观察文本是否跨越数秒陆续到达。

**HTTP 侧基线样本**（同一模型，取自 `llm.stream.ttft_breakdown`）：一个 118 条消息的真实回合为 `ttftTotalMs=18595ms`，分段 `queueWaitMs=1415`、`contextBuildMs=1899`、`streamOpenMs=4452`、`firstRawChunkMs=4656`、`firstProjectedChunkMs=15171`、`firstChunkMs=15203`。其中 `firstRawChunk` 到 `firstProjectedChunk` 约 10.5s 是思考内容的正常消耗，不是故障。**该样本与本探针工作量不可比**（118 条历史 vs 一次 2 回合小任务），只能作量级参考，G2 仍须受控对照。

## 8. 架构阻碍（Step 2 的准入问题，PoC 不解决）

以下问题不由探针解决，探针只提供判断数据。若第 8 节任一项无法回答，不得进入集成设计。

| 编号 | 阻碍 | 说明 |
| --- | --- | --- |
| B1 | **历史权威转移**（**P1 后已修订描述**） | 探针确认 CLI 会在 `run_end.result.nextState.messages` 回吐完整结构化 transcript（`messageId`、`createdAt`、`tool_use` / `tool_result` 内容块，外加 `compaction` 状态），说明状态**可被镜像**；但输入侧仍只有单条 query + `--resume <sessionId>`，**没有注入结构化历史的入口**。因此历史权威仍落在 CLI 会话侧：产品的 `turn_journal` 只能降级为投影。与 checkpoint/rewind、`/tree`、fork、`conversation_invariant`、压缩策略的冲突不变，只是从「状态不可见」变成「状态可见但不可注入」。CLI 侧 `--fork-session` 可对应 fork，但 rewind/tree/checkpoint 是交互式 slash 能力，headless 明确不支持。这是最大阻碍。 |
| B2 | **工具执行归属** | headless 下读类工具仍由 CLI 自行执行，产品无法拦截审批、授权与证据链。若要把 Vibelution 的工具经 MCP 暴露给 CLI 以收回执行权，工具循环的控制权归属随即改变：谁拥有 loop、谁写 journal、谁做修复与回放，都需要重新定义。 |
| B3 | **无控制台红线**（**已解除，P0**） | P0 证明 `node.exe` + `package.json` 的 `bin` 指向的 `dist/index.mjs` 无需任何 shell 层即可到达 CLI，`cmd.cmd` 仅在需要 shell 时作为备选。剩余事项是实现期用运行期解析（读 `bin` 字段）代替硬编码入口路径，避免绑定包内部布局。 |
| B4 | **计费口径** | CLI 走计划额度，Provider API 走 API 计费，两套计量口径不同。§7.1 已确认 CLI 的计费 token 并不小，收益在客户端上传量与首字延迟；因此不能把「省上传」直接说成「省钱」，成本结论必须另有口径对齐。 |
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

| 阶段 | 产出 | 是否产生模型费用 | 状态 |
| --- | --- | --- | --- |
| P0 可执行体解析 | 可用调用形态与版本、控制台行为记录（§6.1） | 否 | **已完成**，见 §7.1 |
| P1 单发冒烟 | 一次调用的完整 NDJSON、事件类型清单、结果帧结构 | 是（1 次） | **已完成**，见 §7.1 |
| P2 会话连续与并发 | G5 证据：跨轮记忆、同 cwd 并发隔离 | 是（小样本） | 待授权 |
| P3 受控 A/B 采样 | G1/G2 证据：坏窗口连发 + 同任务 HTTP 对照 | 是（主要预算） | 待授权 |
| P4 多轮工具往返 | G3 证据：客户端上传字节数与 TTFT 对照 | 是 | 待授权 |
| P4b 长答案流式 | G4 证据：长文本下文本增量是否跨越数秒到达 | 是 | 待授权（§7.1 新增） |
| P5 结论回填 | 回填本文档聚合数字与 GO/NO-GO | 否 | 部分完成（P0/P1 已回填） |

P1 已完成，未触发「事件帧不携带增量文本」的提前终止条件：事件帧确实携带 `text_delta` 与 `message_update`；但文本到达的时间分布不足以判定 G4，故新增 P4b。

## 11. 授权边界与风险

- **费用**：P1–P4 会真实调用模型并计入计划额度。执行前必须由用户给出调用次数上限与时段，不设默认无限预算。
- **不触碰**：不执行 `/alpha/generate` 协议逆向（无公开文档）；不改 operator config；不新增 provider；不做 ZDR 决策。
- **风险登记**：

| 风险 | 处置 |
| --- | --- |
| 冷启动抵消收益 | 由 G2 量化判定，不凭感觉 |
| 判据度量选错，把真实收益判成失败 | 已发生一次（G3 原度量与收益无关），见 §7.1；小样本先行校验度量口径，再固定阈值跑主采样 |
| 短观察窗口导致误判 | 已发生一次（G4 用 15 字符答案无法判定流式），见 §7.1；判定类探针必须覆盖足够长的输出 |
| 双层 harness 语义漂移（CLI 自带工具循环叠加产品编排） | 由 B2 裁决；探针阶段不实现，只看事件可观测性 |
| 探针结论被误读为集成可行 | 本文档固定「探针 ≠ 集成设计」，GO 后另立文档 |
| 采样受时段影响，坏窗口不可复现 | 以「受控同任务 A/B」为核心方法，不做跨时段比较 |
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
- 证据形态：探针脚本与原始 JSON 属一次性证据，只留在会话临时目录，不进版本库；文档只回填聚合数字与结论。原始证据超出会话保留期后由本文档的聚合数字承接。

## 14. 下一步对齐

P0/P1 已完成（§7.1），其中 B3 已解除、B1 已获得更准确的描述、G3 度量与 G4 判定已按实测修订。仍未回答的核心问题是 **G1：坏窗口是否真的结构免疫**——这需要在坏窗口时段发起一轮采样，也是唯一能证伪整个方向的判据。

需要用户确认的事项：

1. 授权 P2 / P4b（小样本）与 P3（主要预算），并给出调用次数上限与可执行时段；P3 需要在已知坏窗口时段执行，时段由用户指定或由探针轮询等待。
2. 修订后的 §7 判据（G2 改为受控同任务 A/B，G3 改为上传字节数与 TTFT，G4 改为长答案重测）是否接受。
3. B2（工具执行归属）是否值得在 G1 通过后单独立项——它是集成设计里比传输替换更大的问题。

在 G1 有结论之前，不建议投入任何集成实现；§8 的 B1/B2 也仍未裁决。
