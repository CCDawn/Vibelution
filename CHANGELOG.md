# Changelog

## Unreleased

## 3.5.2 - 2026-11-24
- fix: 生效状态按前端、后端、桌面壳三层分层给出，只改文档、测试或版本账本时不再提示需要重启后端。
- feat: 仅前端变更时不必重启后端，即可在校验通过后直接切换到新界面（`POST /runtime/frontend/switch`）。

## 3.5.1 - 2026-11-24
- fix: 个人助理派遣在首次提交前失败后，同参数重试不再卡在无可用凭据，可以正常提交

## 3.5.0 - 2026-11-24
- 修复宽屏展开对话右侧栏后，主聊天标签栏与正文的左边缘错位及重复左上圆角。
- 个人助理模型选择器把"缺少服务商开关字段"按未启用处理：只有明确返回已开启的服务才出现在候选和「已启用的服务」列表里，避免旧运行时或旧数据把全部服务误列成已启用。

## 3.4.3 - 2026-11-24
- feat: 个人助理模型弹窗新增「已启用的服务」列表，直接列出当前可用的服务商并一键跳到模型设置；未启用服务的模型不再出现在厂商分组里。

## 3.4.2 - 2026-11-24
- fix: 个人助理的模型选择器不再列出未启用服务商的模型，只保留当前正在使用的那一行；列表为空时提示去模型设置开启服务。

## 3.4.1 - 2026-11-24
- `web/src/routes/chat/useChatComposerTurnMutations.ts`：guidance onMutate 从会话缓存解析
- `web/src/components/conversation/conversationGuidanceSegments.test.ts`：新增乐观行归位用例，
- `npx vitest run conversationGuidanceSegments.test.ts ConversationView.test.tsx`：165 用例通过。
- `npx tsc -b`：无类型错误。

## 3.4.0 - 2026-11-24
- fix: 个人助理的助理状态、派遣任务、团队任务三类读取失败时各记录一条浏览器遥测（操作名、失败序号、是否有缓存、错误摘要），同一失败只记一次，便于下次定位「暂时查不到任务进度」的真实原因。

## 3.3.4 - 2026-11-24
- Split the session tab band into a center surface and a rail surface when the
- The band keeps its single-surface shape whenever the rail is closed or shown

## 3.3.3 - 2026-11-24
- Reverted the transparent/gradient tab strip band: the gradient depended on a pane-width
- Restored the solid tab surface; the leading 12px corner stays.

## 3.3.2 - 2026-11-23
- 消息内联编辑恢复即时输入：编辑框直接订阅会话草稿存储，不再等 400ms 草稿镜像才显示字符；同时去掉输入框与卡片的双层边框/底色，编辑区按内容自适应高度，只保留一层编辑态描边。

## 3.3.1 - 2026-11-23
- feat: 个人助理模型选择器在长目录下新增「可用模型」「最近使用」两个跨厂商分组，打开菜单即可直接选当前可用的模型，不必逐个展开厂商分组；搜索时仍只显示厂商分组，避免重复行。

## 3.3.0 - 2026-11-23
- Let the chat tab strip show the same pane gutter as the panes below it, so the

## 3.2.4 - 2026-11-23
---

## 3.2.3 - 2026-11-23
- 修正 composer 图片排队提示的措辞：原句 "图片会随这条消息一起排队，本轮结束后自动发送" 让人以为贴图即自动发出，实际必须点发送后消息才进队列，图片会一直留在附件区等待。
- 新句写明"图片会随发送一起排队，点发送后本轮结束即自动发出"，英文同步；纯文案，不改排队与上传行为。

## 3.2.2 - 2026-11-23
- perf: 图片附件进 tray 即后台上传，发送时不再等图；粘贴后无需等待即可发出

## 3.2.1 - 2026-11-23
- fix: 发送到 running 标记之间点停止会真正取消排队 turn，不再静默返回状态

## 3.2.0 - 2026-11-23
- feat: 服务厂商改为默认关闭，模型选择器只把已显式开启的厂商当作可用；操作者在模型设置里勾选需要的服务后再选模型，未启用的服务会在列表里标注原因而不是静默消失。
- feat: 服务商改为默认全部关闭，模型选择器里所有厂商初始都是未启用状态，由用户主动在模型设置中逐个开启；onboarding 主动新增的厂商即时可用。

## 3.1.4 - 2026-11-23
- perf: 排队 turn 停止先返回 stopping，中断快照改后台落盘

## 3.1.3 - 2026-11-23
- The top bar now names the frontend release this page is actually running plus when the backend started, and marks a stale pointer or a legacy-tree fallback instead of leaving both to a log line.

## 3.1.2 - 2026-11-23
- feat: 个人助理模型选择器把当前绑定模型与可用模型排到所属服务分组顶部，打开菜单即可确认当前选择，不必在长列表里滚动查找。

## 3.1.1 - 2026-11-23
- 个人助理重启后按原派单回执继续跟进，避免重跑已经派单的对话和产生额外模型用量。
- Codex 等支持 MCP 的外部 Agent 可与 Launcher 个人助理双向发起消息、回复并核对原请求回执。

## 3.1.0 - 2026-11-23
- tools：新增 agent_directory 工具，一次列出可发现的 Agent 及其对应会话，不必先知道 session id 才能联系对方。
- fix: Agent 会话的中断 turn 也写入续跑标记，重启后自动接上
- 个人助理重启后继续核对原任务回执，CLI 子任务补发已完成结果，已授权的项目 Agent 可查询联系人、发送消息并在原会话收取回复。
- 修复 Windows CLI Agent 的终端启动竞态，命令启动前先纳入终端进程组，关闭时统一结束子进程。
- 个人助理的派单工具可正常使用，工具策略里尚未注册的可选救援工具不再阻塞已有权限。
- **自动压缩倒计时对齐真实触发档**：面板原先把 `contextCompression.strategy.levels` 的最低档（`light`，0.6）当作自动压缩线，但 `light` 只参与策略分级、不执行任何压缩，导致 256K 窗口用到 155K（61%）就显示「0%」；现在绑定后端 `_should_automatically_compress` 实际使用的 `standard` 档（0.8），同一状态显示约 19%（≈50K），仅在档位集合缺少 `standard` 时回退到最小正阈值。图例文案同步更新。
- 压缩诊断补上 JSONL 与 Markdown 两个通道：`compress_turn_messages` 现在把压缩前/后/节省 token、级别、原因、是否生效一并写进 conversation 日志与回放文档，排查压缩问题时不必再跨到 turn_journal 关联。
- closeout now publishes a fresh frontend release when the merged diff touches web/, so the next restart serves the merged UI instead of the pre-merge build.
- closeout no longer leaves a silent publish gap on pending merged results: when cleanup fails and publish did not run (or was not requested), the result now carries explicit ``versionSync``/``push`` skipped markers and a ``next_action`` that names the ``--cleanup-only --publish`` recovery rerun.
- A guidance insert now clears the staged images and references it just consumed instead of leaving them in the composer.
- Guided inserts now hand image and reference attachments back to the composer, so the same message no longer appears in both the transcript and the input box.
- A guide submitted after its turn ended is no longer re-queued, so one input can no longer appear as two rows.
- A drained guidance receipt and the agent scene log now name the injected model message, so a later reader can tell which request already carried the steer.
- 引导消息不再永久停在「等待纳入」：本轮无法纳入时明确显示「已转下一轮」，会话空闲时提交的引导直接进入下一轮。
- 历史里由已结束回合遗留的引导行，会在该会话下一次回合结算时被清扫到下一轮队列。
- A guided insert now carries one client submission id from composer to journal, so the optimistic row is claimed by id instead of guessed by text.
- 撤销「结算时自动把未纳入引导重新入队」，避免同一条引导在时间线里出现两条、输入框又显示一遍排队提示
- A mid-turn guide now splits its turn at the guide sequence instead of lifting the row above work that ran earlier.
- `splitTurn` 在引导被消费后会保留一个空的 running tail shell，等待下一步工作；这个 tail 原先继承 turn 在引导之前的 `queued` stage，导致刚插入的引导下方显示"排队中"，读起来像是引导还在排队。
- 现在空 tail shell 固定用 `running` stage：引导已纳入当前轮，tail 表达的是"继续处理"，不是"还在排队"。有内容的 segment 行为不变。
- 验证：`conversationGuidanceSegments.test.ts` 与 `ConversationView.test.tsx` 163 项通过；`npx tsc -b` 通过。
- A turn that ends in a session you are not viewing now stops its spinner and status immediately instead of waiting for you to open that session.
- 修复思考栏只显示一两行：进度解说不再吞掉更长的思考内容，跨通道重叠仅在近似重复（较短一侧达到较长一侧 90%）时才去重。
- Session rail rows now carry the settled status patch for background sessions, so a turn finishing outside the open session updates the list in place instead of forcing a full index re-read; the rail also keeps polling while the index stream is disconnected instead of freezing until the session is opened.
- 工具结果不再把同一段摘要写两遍进会话 journal：`tool_result` 只保留 `result`，工具预览仍由 `tool_call_started` 承载，读取侧统一回退到 `result`。大型会话因此少存约 3.49 MB/会话，打开和回放更快。
- fix: hot restarts now write the restart-resume marker so startup recovery auto-resumes interrupted sessions, excluding the requester own turn.
- fix: 关闭阶段的空快照不再清空重启续跑标记
- Launcher 个人助理会话现在默认挂载开发工具（shell、文件编辑、测试、Git 读取），以会话工作区为边界走正常审批；无任务授权或伪造来源仍被拒绝。
- 个人助理工具调用预算默认改为无上限（maxCallsPerTurn=0），配置读取也把 0 当作显式无限制而不是回落到 16。
- Rail completion badges now light for a settle the index stream delivered while the operator was on another session: the "never read" silence in `sessionActivityIndicator` only suppresses first-paint history, and a live settle arriving through `/api/sessions/events` outranks it until the row is actually read. Starting a new turn on that row drops the mark again.
- 日志补齐 LLM 往返耗时、响应侧模型快照、请求配对序号与错误堆栈兜底，并在会话结束时写入条数与失败计数自检摘要，让「慢在哪、响应错配、日志残缺」可以直接从落盘 JSONL 读出，而不是靠时间戳猜。
- Runtime scene 保留窗口从 30 个包收紧到 10 个，配合字节预算进一步压低单机日志占用上限
- fix: 日志保留补上两处容量缺口——会话清理同时回收孤儿 payload 目录，runtime scene 在 30 个包之外增加 1 GiB 总字节上限。
- fix: CLI 发起的工作台重启现在按「操作员明确要求」处理，会中断正在运行的任务而不是排队等空闲；Runtime Manager 自动转发仍保持保护，被中断的任务沿用既有落盘记录，续跑语义不变。
- signature 来自既有的 `session_conversation_events_signature`，包含文件路径、
- 进缓存和出缓存都做深拷贝，因为调用方会把 message metadata 合并进拿到的 items。
- 缓存有界（4096 项），按访问顺序淘汰。
- Projection now bounds `reasoning.text` (400 chars) and `tool_call.input` /
- `GET /api/sessions/{id}/turns/{turnId}/items/{itemId}` re-projects one turn at
- The web transcript passes the canonical item id down to the reasoning cell and
- feat: 核心提示词新增「完整掌握再动手」纪律，禁止丢三落四式碎片完成
- web：左栏左上角改为 12px 圆角，与中栏卡片一致；右栏开关与其余三角保持不变。
- 打开右侧面板时不再改动中栏形状：删除 `centerPaneMeetsRail` 把中栏右上角压平的规则与条件类，右栏停靠只影响它自己的那一列。
- fix: 右栏停靠与浮层形态统一恢复 12px 圆角，左右面板各自成卡片；撤销此前的接缝压平，中栏右上角恢复圆角。
- 重启不再因控制回复丢失而报「重启未确认」：请求期间连接断开时继续等待新工作台就绪并自动重载，只有真正等不到才提示重启超时。
- fix: 重启标记里的会话在存储打开后立即恢复，不再等首帧预热门（实测拖到 10 分钟以上）
- fix: 重启续跑快速通道写入结构化场景事件，可从日志确认是否命中
- fix: 重启标记里的会话先于 journal 尾部判定恢复，被中断的会话不再等完整扫描
- **健康检查暴露产物陈旧信号**：`/api/health` 现在同时返回 `servingRelease`（进程启动时 pin 的产物）与 `activeRelease`（当前 `active.json` 指针），并用 `releaseStale` 标记两者不一致。重建前端后若未重启后端，可直接从 health 读出“需要重启”，不必再手动比对两份数据。
- 会话切换时，大型会话（约 30MB journal）首次打开更省一次解析开销：turn journal 逐行解析改用可选的 orjson 加速器，缺失时自动回退标准库 json，解码结果完全一致。
- Opening a long chat now returns its first page much faster: the transcript no longer rebuilds assistant timelines for every turn in the session before rendering the visible window (cold read on a 30MB session dropped from ~2.1s to ~1.7s, with byte-identical detail payload).
- Settled index hydration no longer escapes into turn finalization: a projection failure while publishing the settled rail patch now degrades to the bare "this row moved" frame instead of raising from the turn-completion path, so a finished turn can never be reported as a crashed worker because its rail row could not be hydrated.
- Publish a running status patch to the session index stream when a session starts running, and apply index patches to the per-Agent tab cache so the rail updates without opening the session.
- 修复 Agent 目录工具缺少元数据导致整个工具目录加载失败、会话回到「需要继续」的问题。
- 内置工具注册改动自动验证完整目录。共享集成目录必须保持在 `main`，本地推送无法绕过验证流程更新 `main`。
- 修复会话初始化时无法调用附加工具策略合并函数的问题，恢复正常回合执行。
- Keep incremental codebase-map updates working when a file tool reports an absolute path outside the project; normalize to project-relative paths and ignore foreign paths.
- Round the session tab strip leading corner so it stops reading as a square block above the conversation card.
- Problem: the tab strip painted one white band across the centre pane and the
- Change: the strip background is transparent and a gradient paints only the
- Owner: web/src/routes/ChatCodingRoute.styles.ts, web/src/design/workbench-frame.css
- Verification: closeout frontend contract; visual check after restart.
- 会话切换后时间线不再上下闪动：两处滚动容器关闭浏览器 overflow-anchor，恢复位置改为等实测行高连续稳定后再停，而不是固定补一帧。
- 顶栏任务数改为单一数据源：`/api/runtime/summary` 的同一次快照同时携带 workRuns 与运行中 runtime task 卡片，前端只读这一个来源，不再把两个独立轮询的结果相加。
- 移除主壳里第二个 `/api/runtime-tasks` 轮询（15 秒节奏、无后台刷新），任务开始或结束时不会再出现数字与自身下拉菜单对不上的那一个轮询间隔。
- `/aux` 的任务面板仍走原有 `/api/runtime-tasks` 接口，行为不变。
- 契约测试同步：`AppShell.layout.test.ts` 断言单一读取源，`AppShell.startup.test.tsx` 不再期望后台拉 `/api/runtime-tasks`。
- fix: 重启续跑标记统一由停止入口写入，任何关闭路径都不会再漏记被中断的会话
- Keep the virtual timeline host out of the browser's scroll anchoring so a
- 前端静态资源改为按内容哈希长缓存，并只对 /assets/* 启用 gzip，缩短首屏与路由切换的加载时间
- 用户主动发起的重启现在以 operator-restart 身份中断正在运行的会话，而不是以 forwarded 身份无限排队；被中断的会话仍按既有重启恢复逻辑续跑，self-evolution 的“空闲再重启”保持不变。

## 3.0.3 - 2026-11-19
- fix: 上下文面板的「距自动压缩还剩」改为绑定后端 `standard` 档真实触发线；此前取最低档 `light`（只是策略分级、不执行压缩），61% 的 256K 窗口就显示 0%，现在同一状态显示约 19%（≈50K）。
- fix: 会话分组标签同时常驻运行中与已完成两个计数，数字放在彩色圆点内，为 0 时保留占位不再隐去，切换任务时标签宽度不跳动。
- 右栏停靠展开时中栏右上角改为直角，消除两栏接缝处的圆弧缺口；右栏收起后恢复圆角。
- feat(agents): Agent 可在共享工具包之上追加额外策略包的允许工具，追加只增不减、被 blocked 的工具永不进入结果、基础包已授予的工具不会被追加包移除；未配置该字段的 Agent 生效权限完全不变。

- feat: 会话内「已从重启中恢复」提示改为两行安静卡片，任务名不再被截断，时间右对齐，整块内容自适应宽度。
- 右栏停靠展开时，中栏与右栏接缝处的圆角真正压平（此前被 workbench-frame 的 important 简写覆盖，类名生效但视觉无变化）。
- 停靠态右栏展开时中栏右上角改为直角，消除两栏交界处的圆弧缺口；右栏收起后恢复圆角。
- 右栏顶部工具栏改为透明并加下边框，圆角不再被浅灰底吃掉；停靠态左栏去掉永远用不上的滚动条预留，右侧不再留 9px 灰带。
### Fixed
- fix: 切换分组会话时先切路由再清理右栏，避免当前会话在两个分组之间来回闪。
- fix: 分组标签的运行中/已完成计数移到名称右侧，两个数字与总数并排在同一侧。
- fix: 打开工作台时把 Launcher 控制面端口一并登记进实例表；此前只记后端端口，Launcher 重启时找不到可发命令的控制端点，于是静默返回成功而不重启。
- fix: 会话分组标签不再保留 6px 色点，组色只由标签底色承载，腾出横向空间。
- fix(chat): 分组色点不再被基础灰底覆盖，组色在分组标签上稳定生效
- fix: 实例清单写入中途留下的孤儿临时文件（`.<hex>.instances.json`）会在启动协调前被清理，不再无限堆积
- fix: 打开工作台时把实例登记进 launcher 清单，`restart` 不再找不到运行中的后端；写入中途失败的临时文件也会在下次启动时被清理
- fix(chat): 引导 chip 只在等待/未确认时显示，纳入或转入下一轮后回到普通消息行；被转入下一轮的引导不再在时间线上重复出现。
- fix: 引导回执只属于提交它的会话和仍在运行的 turn，turn 结束或切换会话后不再留下「已插入当前 turn」的持续提示。
- fix: 切换会话不再整表重测行高，消除切换时的主线程卡顿与首访白屏
- fix: 恢复扫描先续跑被中断的会话，再摊开空闲历史
- fix: 会话分组标签的底色改由组色浅染承载，不再因包含选中会话而整块变蓝
- 对话输入框在引导回执旁边不再重复提示排队；同一条引导输入只显示一行，未获服务端确认时不再标成「已接收」；被单行截断的工具命令悬停可看全文。

- fix: `npm run build:release` 走 Launcher 同一套锁、BuildKey 与原子发布，手动构建不再只刷新 web/dist 而落不到工作台所服务的 release
- fix: 会话索引流重连后重新读取一次会话列表，断连期间丢掉的 turn 完成帧不再需要手动切换会话才补上。

## 2.5.2 - 2026-11-17


### Changed
- fix: keep inline message edit keystrokes in the composer draft store
- fix: refresh the frontend release before rebuilding the desktop shell
- fix: 未确认发送提示回到输入框上方并放宽发送准入预算
- fix(git): require a live integration claim before moving main
- fix(launcher): wait for packaged Electron processes before replacing shell
- test(runtime): isolate launcher open tests from live backend freshness
- fix(launcher): ignore chat snapshots owned by exited processes
- fix(launcher): recover crashed chat turns through guarded CLI restart
- perf(claims): keep dependency trees out of the dormancy scan
- fix(launcher): recover workbench when a live package directory is locked
- fix(chat): spin the session indicator for a fresh optimistic turn
- test(session-archive): assert the archive wiring at its workbench owner
- fix(workbench): reload the window when a newer frontend release lands
- fix: resume interrupted turns after a requester-less hot restart
- fix(tone): carry optimistic running into directory, index and browser rows
- fix(platform-version): keep the version badge readable beside the update bar
- fix(platform-version): drop the extra pending dot and lift the badge contrast
- refactor(tools): stop re-embedding the shell dialect rules in tool schemas
- feat(authorization): tell the model why a visible tool cannot run this turn
- feat(chat): make guidance insert paint immediately and report where it landed
- feat(chat): show group status counts and drop the neutral dot
- feat(platform-version): keep the version on one quiet line beside the update banner
- fix(chat): separate session tabs from group chips by shape
- feat(chat): persist guidance delivery and settle undrained steers
- feat(guard): require an Unreleased line for product commits


## 2.0.1 - 2026-11-16

### Added
- 平台版本按本地演进节奏自动推进：每次带 Unreleased 声明的合入结算一个小版本，满 5 个进中版本，满 10 个进大版本；\`/platform-version\` 页面实时展示当前版本、build、档位进度与结算记录。

## 2.0.0 - 2026-10-03

### Breaking

- Persisted LLM operator config must be schema v2. Recognizable schema v1 files, including `role_bindings`, are upgraded in place by a one-shot upgrader. Inputs that cannot be upgraded leave the original file unchanged and are not read at runtime.

### Added

- 炒股智能体 opens from the specialist menu or `/finance` into its own chat. The first visit creates a general agent, an empty report library, and a session without calling a model. Public news in that chat is reference only and is not filed. The assistant does not collect accounts, holdings, or amounts, and it cannot place orders.
- An agent can bind the virtual-human life plugin. Only an explicitly enabled binding keeps a schedule, mood, memory, and proactive messages. Other agents stay unchanged.

### Changed

- Chat panel widths are stored only in `paneLayouts.chat`. A leftover `shell.chatPanelWidths` value is copied once when the canonical value is missing, then dropped.
- Agent log diagnosis now leads with the scene summary, how many times it repeated, and the primary reason. The default result names the evidence files to open.

### Removed

- The workbench no longer redirects `/chat-rooms`, `/agents/teams`, `/agents/memory/*`, or `/evolution`. Use `/chat`, `/teams`, `/memory/*`, `/supervised-evolution`, or `/self-evolution`.

### Notes

- Old compatibility paths now follow `docs/standards/development-standard.md` §25.
- This product version is 2.0.0. The desktop shell package version remains 1.0.16.
- These notes cover the user-visible changes recorded since 1.1.2. They do not list internal launcher, startup, and test fixes.
- Restoring the 1.1.2 label does not rewrite an operator config that has already been upgraded to schema v2.

## 1.1.2 - 2026-08-06

Five-wave structure pass:

1. **Teams SC phase island** — `TeamsWorkbenchWithScPhase` lazy-loads SC composition (Mid/Tail + compose + shell surfaces). Eager `TeamsRoute` ~110 KiB; SC phase ~261 KiB secondary chunk.
2. **Foundation bag hygiene** — `buildTeamsScLayerInput` + launch-guard ref for late SC flags.
3. **Chat** — `conversationTurnRowMemo` extracted from `ConversationView`.
4. **CliAgent** — pure terminal presentation helpers extracted (panel already route-lazy).
5. **Backend** — `session/projection_codex_transcript.py` extracted from `session/projection.py` (~480 lines).

## 1.1.1 - 2026-08-06

- Teams: SC inject wrappers and workflow stage modules mount panels via `teamLazyPanels` / dynamic import so workspace packs leave the eager `TeamsRoute` graph.
- Teams: memory index and standalone SC stage panel no longer static-import into the route bag.
- Bundle: `TeamsRoute` ~396 → ~383 KiB residual; SC pack lands as secondary `teamSourceCollectionPanels` chunk.

## 1.1.0 - 2026-08-06

Public baseline after the post-1.0.16 workbench stretch. Version number and this note catch up to code that already shipped on `main`.

### Product surfaces

- Teams research home: flow strip + organization canvas as the default workspace (stage board for stage work).
- Chat: harder turn/projection paint path, SessionTurnItem as the UI projection source, companion rail i18n, create-session optimistic shell fixes.
- Shell: status chips alignment; browser close/refresh guard uses a stable `beforeunload` bind (workbench + launcher) plus a one-shot unload pass (memory + sessionStorage) so intentional refresh does not flash a dead dialog.
- Source-collection / experiment stage chrome: command-bar step chips, search brief layout, stage advance gates.
- VUI: shadcn-aligned primitives (dialog, popover, dropdown, tabs, selects) rolled across shell, chat, config, and teams.

### Engineering

- Large-route extracts: ChatCoding workbench, Teams spines / SC stage modules, Config and Evolution workbench slices, conversation session scroll memory module.
- LLM: native wires, Anthropic prompt-cache alignment, agent-kernel related wiring on main.
- Docs: living vs archive authority; open-source packaging (MIT, CONTRIBUTING, SECURITY, issue/PR templates); README rewritten in plain product language.

### Notes

- Still a local-first workbench: operator config stays outside the git tree.
- GitHub Actions CI remains manual (`workflow_dispatch`) to limit minutes; local hooks / quality gate remain the default gate.

## 1.0.16 - 2026-06-12

- Added a Challenge Cup source-collection search execution API that runs metadata-only query batches from existing assignments.
- Wrote automated search results into DataRecords and imported them as source_manifest candidates without formal Team Knowledge, RAG, or official graph writes.
- Added a Teams knowledge-collection action for executing the next search batch and showing search/writeback/import events in the conversation-style trace.
- Updated the Challenge Cup flow HTML to M6.17 and documented the metadata-only boundary before full webpage/PDF retrieval is added.

## 1.0.15 - 2026-06-11

- Made Challenge Cup knowledge-collection start/continue visibly reuse active source-collection runs instead of appearing idle.
- Returned continued source-run context from research stage startup so the Teams page can show run id, records, open assignments, query count, and external-search boundary.
- Updated the Challenge Cup flow HTML to M6.16 and clarified that the current search stage is still contract/writeback-only until a real external search executor is connected.

## 1.0.14 - 2026-06-09

- Slimmed ordinary short chat turns by skipping heavy runtime context and tool binding only when the message is clearly low-intent dialogue.
- Hardened lightweight chat intent detection with token-aware English markers so incidental substrings do not disable the lightweight path.
- Added server-registry support to the local model monitor so operators can switch monitored model hosts with `-ServerId`.
- Documented the local model monitor registry shape and replaced the example local-model entries with portable server A/B placeholders.
- Added regression coverage for monitor script parsing, registry resolution, and personal-path hygiene.

## 1.0.13 - 2026-06-09

- Recovered supervised-evolution harness evidence so run summaries include task, command, output, and workspace artifacts even when evidence tables are initialized late.
- Hardened Git memory transaction-table initialization so missing evidence containers are recreated without misclassifying existing state.
- Added regression coverage for supervised harness evidence recovery and Git memory transaction table repair.

## 1.0.12 - 2026-06-09

- Densified the Memory workbench layout so operational memory panels use tighter spacing, better clipping, and verified layout coverage.
- Improved prompt cache hit stability by preserving history-before-volatile-context ordering and reusing fresh Memory overview section cache entries when signatures remain unchanged.
- Added regression coverage for prompt-cache ordering, Memory overview cache reuse, and Memory route layout density.

## 1.0.11 - 2026-06-09

- Changed Config apply to merge only the fields changed from the setting page's original baseline, preventing stale drafts from overwriting unrelated current settings.
- Added path-level conflict detection so concurrent edits to the same config field are blocked while unrelated current changes are preserved.
- Added config apply logs for apply mode, changed paths, and touched model IDs, plus regression coverage for patch merge behavior and ConfigRoute apply payload baselines.

## 1.0.10 - 2026-06-09

- Guarded supervised worktree candidate cleanup so discard actions only remove owned candidate worktrees or legacy harness temp worktrees, never arbitrary development worktree paths.
- Added cleanup audit evidence for skipped or failed candidate deletion into the run snapshot and runtime-scene logs.
- Added regression coverage for owned candidate deletion, unowned path skip behavior, and legacy harness temp-path bounds.

## 1.0.9 - 2026-06-09

- Extended the Launcher runtime-manager restart wait window so guarded rebuild/close/open transactions can finish without the outer `-Action restart` call timing out near completion.
- Added Launcher regression coverage for the explicit `restart_workbench` wait timeout and forwarded command flags.

## 1.0.8 - 2026-06-08

- Coalesced duplicate Launcher close requests so repeated stop clicks join the in-flight close instead of queueing extra shutdowns.
- Skipped residual process cleanup for already-closed clean Workbench observations while preserving strict cleanup for manager shutdowns and real residual evidence.
- Added segmented Launcher shutdown timing evidence to runtime-scene and control logs so slow stops identify the backend, port wait, browser, or closure-snapshot phase.

## 1.0.7 - 2026-06-08

- Made the Challenge Cup research team surface show one selected workflow node at a time, with Source Collection, Coordination, Ingestion, Candidate Graph, Candidates, Discussion, and Canvas separated behind the team-level index.
- Unified the synced research team display name to `ai科学研究团队` and kept the canvas as an auxiliary view instead of the default right-panel content.
- Bound source-collection run assignments to functional team Agents from the Team canvas when available, while preserving the contract-only boundary with no external search, formal Team Knowledge, RAG, or official graph writes.

## 1.0.6 - 2026-06-08

- Switched the backend ready wait loop to a direct HTTP ready probe instead of full backend liveness scans on every startup poll.
- Tightened Launcher backend ready polling from 500ms to 250ms while still requiring a successful Workbench HTTP response before reporting the runtime scene ready.
- Added Launcher regression coverage for the faster HTTP-ready wait contract.

## 1.0.5 - 2026-06-08

- Removed the startup-ready-path browser process memory snapshot so opening the managed Workbench window no longer waits on an unsupported multi-second process scan.
- Changed Launcher backend readiness checks to probe the Workbench root URL first, with `/api/health` retained as a fallback, reducing startup wait time while preserving API health semantics.
- Added Launcher regression coverage for the non-blocking browser memory evidence path and root-first readiness probe.

## 1.0.4 - 2026-06-08

- Marked managed Workbench sessions ready before attaching the desktop supervisor so Launcher restart/open commands finish after the backend and window are live.
- Started supervisor attachment as a non-blocking hidden background step with runtime-scene evidence for ready, attach-started, and attach-failed paths.
- Added launcher regression coverage for the ready-before-supervisor lifecycle order and preserved full Launcher script test coverage.

## 1.0.3 - 2026-06-08

- Prevented the PowerShell Launcher frontend dependency and build paths from invoking npm `.cmd` wrappers, avoiding transient Windows cmd flashes during startup.
- Switched Launcher frontend build execution to direct Node.js package entrypoints for TypeScript and Vite while preserving runtime-scene build logs.
- Added launcher regression coverage so frontend build and dependency flows cannot silently return to cmd shim execution.

## 1.0.2 - 2026-06-08

- Blocked direct Launcher and Workbench window closes while the managed project is still running, using browser beforeunload confirmation plus lifecycle telemetry.
- Preserved controlled Launcher stop/restart flows by sharing a short-lived lifecycle-operation marker with the Workbench window.
- Added regression coverage for running, partial, closed, and controlled lifecycle close-guard states.

## 1.0.1 - 2026-06-08

- Fixed supervised-evolution judge marker extraction so prompt examples cannot override the real final judge response.
- Hydrated referenced conversation payload files before summarizing supervised Agent judgments, preserving real PROMOTE/HOLD decisions and scores in persisted reports.
- Added regression coverage for referenced LLM responses and prompt-example marker noise.

## 1.0.0 - 2026-06-08

- Promoted Vibelution to the stable 1.0.0 line across the canonical backend version source and frontend package metadata.
- Recorded the stable mainline contract after the Launcher lifecycle, runtime-scene diagnostics, supervised evolution surfaces, and multi-agent worktree workflow became inspectable as one product baseline.
- Kept this release bump scoped to version metadata and changelog documentation; no runtime behavior, API contract, or evaluation harness code changed in this release commit.

## 0.12.1 - 2026-06-08

- Added the Challenge Cup AI research team source-collection execution panel to the Teams surface, with run startup, assignment/query visibility, and manual result writeback into candidate source records.
- Kept the source-collection UI on the candidate side of the knowledge boundary: no external search execution, no formal Team Knowledge writes, no RAG writes, and no official graph publication.
- Hardened Launcher/workbench state reconciliation and supervised-evolution transaction closure so merged development rounds refresh and close more reliably.

## 0.12.0 - 2026-06-08

- Added lightweight runtime-manager live-control probes for evolution control surfaces, reducing expensive process inventory work during polling while preserving lifecycle evidence.
- Added agent-judged Terminal-Bench-style supervised evaluation support with explicit non-official score labeling, limited bundle materialization, and judge-artifact tests.
- Split heavy shell surfaces into lazy AppShell utility/status panels and tightened topbar responsive behavior for dense launcher/workbench layouts.
- Added chat-review candidate detail loading and self-evolution overview caching so review and evolution surfaces stay responsive.
- Switched the default Workbench window mode to fullscreen across product defaults, example config, and launcher-facing tests.

## 0.11.5 - 2026-06-08

- Kept Workbench shell and Chat startup data loading alive while the managed window is hidden, using a bounded startup warmup instead of permanent high-frequency background polling.
- Allowed Chat session streams to connect during startup warmup and logged warmup state in browser telemetry.
- Adjusted managed Edge launch flags to avoid background networking and timer throttling during startup.

## 0.11.4 - 2026-06-08

- Added a traceable Challenge Cup data-search plan contract to source-collection run startup, including query seeds, planned queries, role assignment inputs, and result writeback boundaries.
- Extended `/api/teams/{team_id}/workflow-orchestration/source-collection-runs` with query seed, language, source type, and max-results inputs while keeping the slice contract-only with no external search execution.
- Updated the Challenge Cup flow HTML to show M6.5 data-search planning as the next step in the source-collection Agent workflow.
- Fixed permanent Agent deletion so active Agents can be purged directly, including solo chat-room cleanup and direct-session tombstone preservation.
- Preserved deleted-Agent session history without allowing session repair to recreate purged Agents.
- Kept unresolved current LLM bindings visible in Agent model slot selectors and preserved structured `llmBindings` in runtime scene child logs.
- Added management-center safeguards for bulk Agent purge, generated-tool deletion, and prompt-template reset/deactivation, while making Skill bulk edit/delete visibly read-only.

## 0.11.3 - 2026-06-07

- Added a Team workflow source-collection run launcher that creates a generic DataProcessing run plus functional collection assignments for the AI research team.
- Exposed `/api/teams/{team_id}/workflow-orchestration/source-collection-runs` so the research coordinator can start a traceable source batch before DataRecord import.
- Updated the Challenge Cup flow HTML to show source-collection run startup as the entry into the data-gathering Agent workflow.

## 0.11.2 - 2026-06-07

- Removed archived Team member Agents from extra group rooms during Team archive cascade, while preserving the existing linked Team room deletion behavior.
- Added Team archive cleanup evidence with removed room ids and per-Agent room cleanup mapping in runtime scene events.
- Refreshed Team archive frontend caches for Agents, mode bindings, chat rooms, sessions, conversations, config workspace, and project bus state.

## 0.11.1 - 2026-06-07

- Added a Team workflow bridge that imports generic DataProcessing records into Challenge Cup `source_manifest` candidates while preserving run, record, quality, and collection-trace metadata.
- Exposed the bridge through `/api/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_id}/records/{record_id}/source-candidate` with idempotent duplicate handling.
- Updated the Challenge Cup flow HTML to mark DataRecord-to-source-manifest import as the handoff from generic collection to the AI research team candidate workflow.

## 0.11.0 - 2026-06-07

- Added the generic data-processing substrate with profiles, runs, records, collection assignments, collection outputs, and status APIs under `/api/data-processing`.
- Persisted data-processing runs under `workspace/data_processing/runs/<runId>` so agent-driven source collection can be tracked before any domain-specific knowledge publication.
- Recorded safe runtime scene events for data-processing run, record, assignment, and output activity while keeping raw source content out of lifecycle logs.
- Updated the Challenge Cup flow HTML to position data processing as the generic source-collection layer feeding the AI research team workflow.

## 0.10.46 - 2026-06-07

- Added bulk selection bars to the Agent, Prompt Template, Tool, and Skill management pages.
- Added safe bulk actions for Agent prompt assignment/archive, prompt category/reset/deactivate, and generated-tool enable/disable/delete while preserving existing per-item protection rules.
- Kept the Skill library read-only while adding bulk command copy and disabled edit/delete controls with explicit read-only guidance.
- Hardened supervised-evolution startup with runtime-manager source freshness checks and safer active-work probe failures.
- Added guarded restart frontend build preflight and Launcher desktop-entry validation before closing a running workbench.
- Improved supervised evaluation environment handling, memory detail surfaces, and related workbench UI affordances.

## 0.10.45 - 2026-06-07

- Added read-only communication briefs to the Challenge Cup workflow coordination status API, mapping queue items to target functional Agent roles and suggested delivery channels without sending messages automatically.
- Surfaced coordination brief targets and channel hints in the Teams research workflow panel while keeping transfer, approval, and formal-knowledge writes disabled.
- Updated the Challenge Cup flow HTML to document coordination briefs as the bridge between workflow queues and later team communication dispatch.

## 0.10.44 - 2026-06-06

- Optimized Agent Center loading by reusing repaired Agent registry snapshots, batching Agent API hydration and runtime history reads, and logging slow `list_agents` hydration breakdowns.
- Added Agent creation tool packages in the Web Agent Center, while keeping per-tool policy tuning available after creation.
- Hardened direct-session Agent indexing, archive/purge cleanup, team-linked chat room cleanup, and runtime LLM binding diagnostics with focused lifecycle evidence.
- Removed stale legacy `llmConfigId` flow-canvas persistence from the frontend contract and aligned visible copy around Agent model slots.

## 0.10.43 - 2026-06-06

- Added a read-only Challenge Cup workflow coordination status API that groups pending transfers, rework candidates, stewardship items, blocked candidates, and active work for the research team.
- Surfaced the coordination queue in the Teams research workflow panel without adding automatic transfer, approval, or formal-knowledge write controls.
- Updated the Challenge Cup flow HTML to show the coordination queue as the team organization layer for research review and knowledge-governance handoff.

## 0.10.42 - 2026-06-06

- Collapsed low-frequency Chat/Coding session diagnostics behind a compact context diagnostics disclosure while keeping status, LLM input, token speed, current task, and prompt-cache facts visible.
- Kept previous-turn context/cache composition and compression details available inside the diagnostics disclosure instead of occupying the default left rail.
- Renamed ordered execution-trace expansion copy from tool-call language to execution-detail language so mixed thought/status/tool chains are labeled truthfully.

## 0.10.41 - 2026-06-06

- Added a Teams workspace knowledge-ingestion status panel for the Challenge Cup research team, showing staged source/candidate/steward/review/official-sync progress from the read-only status API.
- Surfaced action items and official Knowledge/RAG/Graph boundaries in the research workflow panel without adding approval or write controls.
- Updated the Challenge Cup flow HTML to mark the Teams status funnel as the visible coordination entry for the knowledge ingestion process.

## 0.10.40 - 2026-06-06

- Added a read-only Challenge Cup knowledge-ingestion status API for Team workflows, summarizing CandidateStore progress, candidate validation, candidate graph health, Team Knowledge proposal/item counts, and official sync boundaries.
- Returned staged action items for source collection, candidate screening, steward-pack review, and official graph sync without creating KnowledgeItems, writing RAG content, or generating new candidate graph snapshots.
- Updated the Challenge Cup flow HTML to mark the knowledge-ingestion status view as landed and document the pending-review versus official-sync boundary.

## 0.10.39 - 2026-06-06

- Added a shared Agent Turn Runtime facade for chat, self-evolution, and supervised-evaluation runs, producing common runtime metadata and prompt-cache partitions.
- Wired self-evolution executor turns to record safe `turnRuntime` diagnostics in lifecycle logs without changing run-state, carryover, or transaction semantics.
- Propagated supervised Agent runtime metadata through harness child-process environment variables so baseline and candidate runs keep isolated cache scopes while reusing the shared turn contract.
## 0.10.38 - 2026-06-06

- Split prompt-cache usage observation into cache read hits, cache writes, and uncached input tokens across LLM logs, session detail APIs, and the Chat/Coding status UI.
- Added stable per-agent/per-session/per-model prompt cache partitioning for chat turns so automatic cache keys no longer drift per turn.
- Recorded safe prompt-cache key hashes and cache composition diagnostics without logging raw cache keys or prompt text.

## 0.10.37 - 2026-06-06

- Added the Challenge Cup review rework/rejection closure path: transfer decisions can now return candidates to the smallest upstream revision node or archive rejected candidates in `metadata.rejectionArchive`.
- Candidate graph snapshots now exclude rejected/archive candidates from the active graph while reporting `archivedCandidateCount`.
- Updated the Teams research workflow graph stats and Challenge Cup flow HTML/technical plan to show the closed rework/rejection behavior.

## 0.10.36 - 2026-06-06

- Added a Candidate Graph panel to the Team workspace research workflow view, reading latest `candidate_graph` snapshots and rendering candidate nodes, evidence-direction edges, missing links, unreviewed nodes, and candidate-only boundary status.
- Added a Team workflow graph refresh action that reuses the existing candidate-only graph builder without writing formal Team Knowledge, RAG, or the official knowledge graph.
- Updated the Challenge Cup flow HTML and technical plan to mark Teams candidate graph visualization as landed.

## 0.10.35 - 2026-06-06

- Fixed Launcher `status` so it remains read-only: it now reports missing or incomplete Python dependencies without creating `.venv` or running `pip install`.
- Added an explicit `repair-deps` Launcher action for Python dependency bootstrap and kept mutating start/restart flows on the existing dependency repair path.
- Added pip install override support through `VIBELUTION_PIP_INDEX_URL`, `PIP_INDEX_URL`, and `VIBELUTION_PIP_EXTRA_ARGS`, with structured dependency status logging.

## 0.10.34 - 2026-06-06

- Added a read-only Research Workflow panel to the Team workspace for `research-team` / research-organization teams, showing workflow stage, CandidateStore totals, active workflow items, validation summary, and recent candidate states.
- Wired the panel to the existing TeamWorkflowOrchestration and candidate list APIs without adding transfer, approval, Team Knowledge, RAG, or graph write actions.
- Updated the Challenge Cup flow HTML and technical plan to mark the Team workspace workflow panel as landed.

## 0.10.33 - 2026-06-06

- Removed legacy `profileCards` and `profileCount` from the config workspace API contract, keeping Model Library access through `modelOptions`.
- Hid the legacy Tools config editor section from the Config page so tool-specific configuration stays with Agent/tool management surfaces.
- Changed direct Agent session renaming to update the Agent Directory display name, while child-session renaming updates only the task title and leaves Agent identity unchanged.

## 0.10.32 - 2026-06-06

- Added lazy-loaded Memory Graph node details through `/api/memory/knowledge-graph/node-detail`, returning full formal knowledge bodies only for the selected node and within Team Knowledge ACL boundaries.
- Updated the Memory graph detail panel to fetch and render selected node knowledge content with loading and truncation states while keeping the main graph payload body-free.
- Added runtime-scene diagnostics for node-detail views without logging knowledge content.

## 0.10.32 - 2026-06-06

- Changed Launcher and runtime stop/restart requests to reject active project work with `409 active_work_*_blocked` instead of queuing or silently stopping chat, group, evolution, or worktree runs.
- Added blocked active-work lifecycle evidence for runtime and launcher stop/restart paths, preserving active task state for later diagnosis.
- Updated Launcher copy so active work is presented as a hard stop/restart guard, with legacy deferred restart queue text marked as historical diagnostics rather than an automatic action.

## 0.10.31 - 2026-06-06

- Added a Challenge Cup paper-note autodraft API that turns a completed local PDF `sourceExtraction` into a `paper_note_draft` local-model invocation.
- Reused the existing Local Research Worker Model and CandidateStore recording path, preserving source refs, page-anchor evidence refs, validation, and source-candidate draft trace metadata.
- Updated the Challenge Cup flow HTML and technical plan to mark the first source-extraction to paper-note bridge as landed while keeping long-document splitting pending.

## 0.10.30 - 2026-06-06

- Added the Challenge Cup source-extraction API for local PDF `source_manifest` candidates, computing `sha256`, extracting page anchors and excerpts, and writing traceable `metadata.sourceExtraction` evidence back to CandidateStore.
- Kept source extraction inside the candidate boundary: failed extraction leaves the source in `source_needs_confirmation`, and no formal Team Knowledge, RAG, or official graph writes happen.
- Added `pypdf` as the runtime PDF text extraction dependency and updated the Challenge Cup flow HTML and technical plan to mark local PDF page-anchor extraction as landed while keeping automatic `paper_note` generation pending.

## 0.10.29 - 2026-06-06

- Fixed OpenAI-compatible `tool_chat` protocol routing so Xiaomi MiMo and similar providers with `compat_mode = "openai"` resolve to `openai_chat_tools` instead of falling back to `basic_chat_no_tools`.
- Preserved Qwen thinking and local runtime special routes while adding regression coverage for Xiaomi `tool_chat` tool support.

## 0.10.28 - 2026-06-05

- Expanded `officialResearchGraph` into the read-only Memory Graph when requested, adding formal research reference nodes and `official_*` edges while preserving the default high-level graph.
- Updated the Memory page to request `include=officialResearchGraph`, so formal Challenge Cup research trace edges are visible in the graph canvas without exposing full knowledge bodies.
- Updated the Challenge Cup flow HTML and technical plan to mark Memory Graph canvas expansion as landed.

## 0.10.27 - 2026-06-05

- Added official Challenge Cup research graph trace syncing on steward-pack approval, storing `officialResearchGraph` on the formal KnowledgeItem and `officialSyncRecord`.
- Translated steward-pack `sourceTrace` and `candidateIds` into formal `supports`, `maps_to`, `inspires`, and `approved_for_ingestion` edges without promoting candidate graph drafts directly.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 formal graph trace metadata as landed, leaving only Memory Graph canvas expansion for a later slice.

## 0.10.26 - 2026-06-05

- Migrated approved Challenge Cup steward-pack proposal rating suggestions into formal KnowledgeItem pending rating reviews without auto-applying the score.
- Recorded `ratingSuggestionMigration` in `officialSyncRecord` and `knowledgeIngestion` metadata so approval, skipped, and failed migration outcomes are traceable.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 rating suggestion migration as landed while keeping fine-grained formal graph edges for later.

## 0.10.25 - 2026-06-05

- Added the Challenge Cup steward-pack ingestion approval gate API, approving pending steward packs into formal Team Knowledge or rejecting them back to revision.
- Recorded `officialSyncRecord` evidence on steward candidates, including proposal, batch, KnowledgeItem, reviewer, RAG, and graph status boundaries.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 approval-gate behavior as landed while leaving rating migration and fine-grained graph edges for later.

## 0.10.24 - 2026-06-05

- Fixed Agent Center runtime status so current direct-session cards ignore stale run snapshots from old direct sessions, while preserving those runs as historical diagnostics.
- Surfaced unresolved Agent dialogue model references as blocking health issues and showed the raw model ID in Agent Center instead of a misleading `-`.
- Kept Agent reset replacement direct sessions synchronized back to AgentDirectory so Agent Center and the Chat/Coding session list stay aligned.
- Added the Challenge Cup steward-pack knowledge-ingestion API, submitting valid `steward_pack_draft` candidates to Team Knowledge as a `SourceArtifact` plus pending `RefinementProposal`, with optional pending rating suggestion.
- Moved submitted steward packs into `steward_pending_knowledge_review` while keeping official `KnowledgeItem`, RAG, and graph writes blocked until the approval gate.
- Updated the Challenge Cup research-flow HTML and technical plan to show the M5 pending-review bridge and remaining official-sync work.

## 0.10.23 - 2026-06-05

- Added the Challenge Cup `steward_pack_draft` CandidateStore gate for knowledge-governance ingestion drafts, requiring traceable candidate IDs, target domain, source trace, proposal payload, rating suggestion, risk summary, and `approvalRequired=true`.
- Blocked ingestion drafts that try to write official Team Knowledge, RAG, or graph state before the approval gate.
- Updated the Challenge Cup research-flow HTML and technical plan to show M5 steward pack behavior and remaining official-ingestion work.
- Fixed Chat/Coding session deletion so deleting an Agent direct session clears the Agent's `directSessionId` instead of creating a replacement direct session that makes the conversation appear restored.
- Kept the Agent active in Agent Center after its direct conversation is deleted, while removing the deleted session from the chat index.
- Changed last-session deletion fallback to create a plain empty "新会话" conversation without Agent binding.

## 0.10.22 - 2026-06-05

- Added a unified Model Library test control: choose one saved model and run a text connection test from that single button.
- Extended `/api/config/test-llm` to accept `modelId`, using the selected model library entry and its unique key binding through a temporary probe profile.
- Kept per-row Model Library actions focused on edit, image capability check, and delete, with model test diagnostics now logging the tested model ID.

## 0.10.21 - 2026-06-05

- Fixed Agent Center debug reset pending state so only the Agent being reset shows "resetting", while other Agent detail views remain usable.
- Added Agent reset requested/failed runtime-scene diagnostics at the API boundary, complementing the existing completed event so reset crashes and validation failures are traceable.
- Restored resetToolPolicy behavior for work-session Agents to the session default tool package instead of an empty default policy.

## 0.10.20 - 2026-06-04

- Surfaced live Chat/Coding model status while streamed LLM calls retry, fail, or fall back to non-streaming invoke, so the assistant output area no longer appears idle during retry backoff or fallback work.
- Added safe `llm:status` breadcrumbs with session/turn context and lifecycle logging for retry, fallback-started, fallback-succeeded, and failed states.
- Preserved fallback non-streaming assistant replies in the live session stream when the final result is otherwise only a control marker.
- Added the Anthropic thinking request contract for Claude Opus 4.7 via ATPify, including `thinking_type` / `thinking_display` model fields, payload injection, and safe runtime-scene diagnostics for requested and observed reasoning.

## 0.10.19 - 2026-06-04

- Added `conversation_log_inspect_tool`, a read-only JSONL conversation log inspector that summarizes candidate logs, event counts, LLM/token usage, tool-call sequences, errors, repeated calls, and large-result inefficiency signals without shell execution or raw full-log expansion.
- Added the new log inspector to the built-in tool registry and the 会话 Agent 基础包, with safe fixed-argument registry testing.
- Changed work-session Agent defaults so new and repaired chat/session Agents receive a private read-only session tool policy that includes `conversation_log_inspect_tool`; Agent Center work-session creation now lets the backend default policy apply instead of requiring a manual tool package.

## 0.10.18 - 2026-06-04

- Reduced Chat/Coding background polling while a direct session SSE stream is connected, pausing session, conversation, and team index polling until the stream disconnects or the user switches surfaces.
- Added low-noise `session.detail_snapshot.published` runtime-scene telemetry for active SSE subscribers, including snapshot publish latency, subscriber count, delivery/drop counts, message count, and current phase.
- Updated focused backend and ChatCodingRoute layout tests for the stream-backed polling and telemetry contract.

## 0.10.17 - 2026-06-04

- Clarified Chat/Coding context indicators so session message history estimates and runtime context compression estimates are displayed as separate scopes.
- Added `source`, `scope`, `tokenBasis`, and `limitBasis` metadata to runtime `contextCompression` payloads so the UI can explain why compression percentages differ from session history usage.
- Expanded Chat/Coding provider-failure notices with safe user-facing reason summaries such as quota exhaustion, deprecated sampling parameters, authentication failure, context limit, timeout, and upstream gateway failure.
- Updated Chat/Coding layout tests and runtime summary tests for the new context-scope contract.

## 0.10.16 - 2026-06-04

- Rebuilt `code_symbol_tool` as the native project code context graph tool, replacing the old Python-only outline/entity/definition/hover contract with status/index/search/explore/inspect/references/impact/affected_tests/files modes.
- Added a local cache-backed project index for code, frontend, docs, config, and workspace prompt assets while excluding runtime-history noise.
- Updated agent guidance, tool metadata, reading strategy, runtime observations, and focused tests for the new graph-based code navigation contract.

## 0.10.15 - 2026-06-04

- Added per-turn `llmUsage` to chat session details, sourced from provider usage metadata only.
- Changed Chat/Coding status display so "本轮真实输入" shows provider-observed input tokens, while missing provider usage is shown as unavailable instead of estimated.
- Kept session history context as a separate estimate and added runtime-scene events for recorded versus missing LLM usage.

## 0.10.14 - 2026-06-04

- Increased Launcher route information density by replacing repeated lifecycle cards with a compact lifecycle matrix.
- Consolidated control-plane evidence, recent command results, recent events, and guardian responsibilities into tighter console tables.
- Fixed narrow viewport Launcher layout so panels keep natural height and no longer visually overlap.

## 0.10.13 - 2026-06-04

- Changed the desktop launch chain so Start Menu / desktop entry opens the Launcher control surface first instead of directly starting the full workbench lifecycle.
- Added a `launcher_control_surface` session role so runtime and launcher status distinguish Launcher-only backend/control UI from a started project bundle.
- Hardened launcher stale-state cleanup by ignoring tracked backend PIDs whose command line no longer matches a launcher-managed backend.

## 0.10.12 - 2026-06-04

- Restored provider-agnostic LLM reasoning capture for OpenAI-compatible/local providers by centralizing reasoning field aliases and explicit `<think>` / `<thinking>` tag extraction.
- Kept hidden reasoning out of visible assistant content, including streamed think tags split across chunks.
- Added runtime-scene reasoning diagnostics with source and character-count summaries for invoke, stream, and stream fallback paths.

## 0.7.5 - 2026-06-01

- Added `/api/memory/usage-contract` as the cross-system contract for how Agent private memory, Team knowledge, Team chat, self evolution, supervised evolution, and external artifacts use the memory platform.
- Visualized the usage contract in `/agents/memory/knowledge`, including system domains, allowed read/write paths, prompt defaults, current contract state, and forbidden actions.
- Locked the evolution boundary in tests: evolution evidence may register sources and proposals, but it cannot directly create formal Team knowledge without reviewer confirmation.
- Logged contract reads through `memory.usage_contract.viewed`.

## 0.7.4 - 2026-06-01

- Added knowledge operations health APIs, Agent tools, and UI panels that surface orphan sources, pending proposals, pending rating suggestions, and unrated formal items without mutating knowledge.
- Added read-only governance plan APIs, Agent tools, and Memory Library visualization with explicit `planOnly` boundaries and recommended next tools.
- Added `exact` / `semantic` / `hybrid` knowledge search mode support with lightweight local token-overlap scoring and visible match reasons.
- Logged health and governance plan reads through `knowledge.operations.health.viewed`, `knowledge.governance.plan.viewed`, `knowledge.tool.operations_health.queried`, and `knowledge.tool.governance_plan.queried`.

## 0.7.3 - 2026-06-01

- Added the Knowledge Steward workbench API at `/api/knowledge/steward/workbench`, aggregating steward identity, open governance tasks, read-only recommendations, staged next actions, and acceptance checklist evidence.
- Added ToolPolicy-gated `knowledge_steward_workbench_tool` for the protected Knowledge Steward Agent so Agents can inspect the unified governance workflow without applying, deleting, changing ACLs, or bypassing reviewers.
- Visualized the steward workbench in `/agents/memory/knowledge`, including governance stages, next actions, and the review-safe acceptance checklist.
- Logged workbench reads through `knowledge.steward.workbench.viewed` and tool reads through `knowledge.tool.steward_workbench.queried`.

## 0.7.2 - 2026-06-01

- Allowed `terminal_bench_core` to run through the Vibelution custom harness as a non-official Terminal-Bench evaluation, while keeping Harbor/Docker official verifier status pending.
- Marked dataset, bundle, case, decision, proposal, API, and UI payloads with `evaluation_mode=custom_harness`, `official_verifier_status=harbor_pending`, `official_score=null`, and a Vibelution custom score label.
- Kept explicit official-mode launches blocked until the Harbor/Docker `/app` sandbox and official verifier are wired in.
- Logged custom-harness Terminal-Bench starts through `supervised_run.preflight.custom_harness_non_official` for later diagnosis.

## 0.7.1 - 2026-06-01

- Tightened supervised evolution real-run selection so `terminal_bench_core` is marked as requiring the official Harbor/Docker Terminal-Bench `/app` sandbox and verifier, hidden from the primary picker, and blocked during start/retry preflight.
- Kept `terminal_bench_smoke` as the currently runnable multi-step ReAct harness option for closed-loop validation while official Terminal-Bench runner integration remains pending.
- Preserved harness evidence for failed or cancelled supervised runs before temporary worktrees are removed, including conversation/debug logs, payloads, and runtime-scene lifecycle traces.
- Fixed supervised evolution request payload roles so user task input is sent as provider `user` content instead of drifting into a system message.
- Clarified supervised retry control flow by separating the local retry implementation from the runtime-manager wrapper and covering official-environment retry blocking with tests.

## 0.7.0 - 2026-05-31

- Added Memory Platform P1 for team knowledge bases: JSON/JSONL persistence for knowledge bases, source artifacts, refinement proposals, batches, formal items, and audit records under each team workspace.
- Added knowledge APIs for accessible overview, team knowledge-base creation/listing, source registration, proposal submission, review/apply, item listing, and rating updates with team role/ACL enforcement.
- Extended Agent memory policy with readable/proposable/reviewable knowledge-base boundaries and exposed those controls in Agent Center.
- Added ToolPolicy-gated Agent tools `knowledge_query_tool` and `knowledge_proposal_tool` so Agents can read reviewed team knowledge or submit source-backed candidates without directly writing formal knowledge.
- Integrated Team Knowledge into `/agents/memory/knowledge` with source registration, refinement proposal review, formal item inspection, and rating controls while keeping formal knowledge tool-readable and out of prompt by default.

## 0.6.2 - 2026-05-31

- Tightened Agent Center management around setup tasks: added per-Agent management readiness, next-action guidance, task-oriented filters for missing persona/task/tools/team/inbox/maintenance gaps, effective tool capability previews, and a dedicated maintenance intro for reset/archive/purge actions.
- Reduced Agent detail top-level tabs from Overview / Base config / Policies / Membership / Activity to Overview / Config / Activity, with tool, memory, and membership controls progressively disclosed inside Config.
- Reduced overlap between Tools and Agent Center: Tools now stays focused on tool catalog, scope visibility, runtime testing, and lightweight Agent test-boundary summaries, while Agent Center remains the configuration source for Agent ToolPolicy and tool package editing.

## 0.6.1 - 2026-05-31

- Fixed supervised worktree merge analysis so untracked files that already existed before candidate creation, such as local `.codex/visual-checks` artifacts, are kept as baseline noise instead of counted as candidate changes or merge overlaps.
- Kept true candidate edits visible in `candidateWorktree.changedFiles`, allowing the Terminal-Bench smoke closed loop to finish with a clean `mergeAnalysis.ready` result when only the candidate marker changes.

## 0.6.0 - 2026-05-31

- Added a local Terminal-Bench-style supervised dataset adapter with two multi-step terminal/ReAct smoke cases that materialize into `terminal_bench_smoke_v1`.
- Added `multi_step_react` as a supervised harness mode alias that preserves benchmark metadata while launching through the existing single-turn prompt runner.
- Hid empty, missing-source, and external-harness datasets from the supervised workbench's primary dataset picker while keeping their status visible through API metadata.
- Merged the supervised launch dataset/bundle controls into one evaluation-source picker with compact source counts and inline terminology guidance.
- Exposed dataset `visibility`, `selectable`, and `noiseLevel` fields from the evolution workbench API for cleaner benchmark selection.

## 0.5.3 - 2026-05-31

- Added Agent Center tool package presets for fast ToolPolicy setup, including core, research, coding, collaboration, memory/context, media, and operations bundles.
- Exposed `toolBundles` from `/api/tools` with tool counts, preferred-tool counts, high-risk counts, explicit-allow counts, and risk tags.
- Added compact Agent Center controls to merge a tool package into the current draft or reset the draft exactly to that package while keeping manual per-tool allow/block editing.
- Persisted `preferredTools` from the Agent Center tool-policy editor so package priorities are not lost on save.

## 0.5.2 - 2026-05-30

- Added configuration-stage image input capability checks for model library entries and profile-derived models through `/api/config/draft/check-model-capabilities`.
- Persist image input capability metadata including `supports_image_input`, `capability_status`, `capability_source`, `capability_checked_at`, and `capability_error`.
- Added model-center actions to check one model or all models for image input support and display the resulting capability status.
- Marked DeepSeek V4 Pro/Flash presets as unsupported for image input, kept Xiaomi MiMo V2.5 multimodal as supported, and made the profile/model-center badges use conservative `supports_image_input` evidence.
- Moved Agent binding edits out of the Config page: LLM config now keeps read-only Agent usage summaries and links to Agent management instead of duplicating Agent bindings, prompt/session/workspace edits, and mode slot/pool assignment controls.
- Restored recent image attachments for contextual retry messages such as “你再试试” when the active task is image comparison or prompt refinement.

## 0.5.1 - 2026-05-30

- Added AgentDirectory-backed `taskProfile` fields for mission, task types, responsibilities, preferred and avoided tasks, success criteria, deliverables, constraints, and handoff notes.
- Added Agent Center editing for task profiles and exposed the profile through `/api/agents` plus `/api/agents/config-workspace`.
- Injected non-empty task profiles into Agent runtime context as descriptive task-fit guidance without automatic recommendation, routing, permission, or scheduling behavior.
- Logged task profile updates through `agent.task_profile.updated` and covered API/context/UI contracts with focused tests.

## 0.5.0 - 2026-05-30

- Added AgentDirectory-backed `personaProfile` fields for gender, age, pronouns, personality, communication style, background, expertise, collaboration preference, and identity notes.
- Added Agent Center editing for persona profiles and exposed the profile through `/api/agents` plus `/api/agents/config-workspace`.
- Injected non-empty persona profiles into Agent runtime context as descriptive collaboration guidance, while explicitly keeping age/gender out of capability or permission logic.
- Logged persona profile updates through `agent.persona_profile.updated` and covered API/context/UI contracts with focused tests.

## 0.4.33 - 2026-05-29

- Added one-shot route chunk recovery for stale lazy-loaded assets after a frontend rebuild, preventing the default React Router error screen when a managed window still holds an older entry bundle.
- Covered dynamic import fetch failure detection and reload loop prevention with focused frontend tests.

## 0.4.32 - 2026-05-29

- Renamed the top-level Research navigation entry to Team and mounted the Team workspace at `/teams`.
- Kept `/research` and `/agents/teams` as compatibility redirects to `/teams`, preserving selected team query links.
- Moved Team out of the Agent management subnavigation while keeping Agent Center as the member binding source.

## 0.4.31 - 2026-05-29

- Added Agent Center avatar editing from the detail avatar: upload a new PNG/JPG/WebP, choose an existing `workspace/avatars` image, or restore the Agent role default.
- Added Agent avatar management APIs under `/api/agents/{agent_id}/avatar`, `/api/agents/{agent_id}/avatar-image`, and `/api/agents/avatar-options`.
- Logged avatar updates/uploads through AgentDirectory runtime-scene events while preserving text-avatar fallback behavior.

## 0.4.30 - 2026-05-29

- Added AgentDirectory-backed default avatars sourced from `workspace/avatars`, exposed through `/api/agents/avatar-image/{filename}` and `avatarImageUrl` fields.
- Render Agent avatars in Agent Center and Chat/Coding Agent reference surfaces while keeping text-initial fallbacks for missing images.
- Persisted default avatar assignments for existing Agents and logged `agent.avatar_defaults_assigned` during directory repair.

## 0.4.29 - 2026-05-29

- Tightened Research Flow Canvas communication-edge routing so dense bidirectional team organization edges stay close to their Agent nodes instead of expanding into large overlapping arcs.
- Added a focused ResearchFlowCanvas geometry regression for the three-Agent research team layout with six communication lines.
- Render Chat/Coding generated-image Markdown as real inline image previews, links, and compact tables instead of exposing raw `![...](...)` syntax after image2 tool calls.
- Suppress stale interrupted-turn runtime notices after a real follow-up message arrives, and show at most one active runtime notice in the Chat/Coding status strip.

## 0.4.28 - 2026-05-29

- Tightened `list_sessions()` into a read-only lightweight index path: session list loading no longer creates missing session workspaces, materializes legacy Agents, or hydrates each Agent through full detail serialization.
- Kept AgentDirectory-only direct sessions visible in the list through compact Agent state, while moving legacy chat-state repair to detail/interaction paths such as `get_session_detail`.
- Added `session.list.loaded` runtime-scene timing metadata so future diagnostics can verify the lightweight read path.
- Moved interrupted-turn recovery notices out of Agent assistant replies and into `runtimeNotices`, rendered as a separate Chat/Coding status strip while filtering legacy notice messages from the conversation timeline.

## 0.4.27 - 2026-05-29

- Sped up Agent Center configuration workspace loading by switching team and group-room references to compact read paths that avoid session scans, participant repair, linked-room hydration, and canvas reads during the first aggregate load.
- Added `loadModes` timing metadata to `agent_config.workspace.loaded` so future runtime-scene logs show when compact workspace reads are active.

## 0.4.26 - 2026-05-29

- Simplified Chat/Coding auxiliary message rendering: “思考过程” and “心智模型” now render as compact dedicated panels instead of duplicated operation-timeline rows.
- Expanded the mental model panel so mood, cognitive state, source, confidence, samples, timestamp, feeling, summary, whisper, and intervention can be inspected from the conversation itself.

## 0.4.25 - 2026-05-29

- Fixed Chat/Coding thought visibility: captured assistant `thought` text now appears as a folded summary on the “思考过程” row, and the same text is available as the thought operation detail instead of being stored but visually empty.

## 0.4.24 - 2026-05-29

- Added permanent purge for already archived Agents: Agent Center now exposes a separate irreversible delete action for archived Agents, backed by `DELETE /api/agents/{agent_id}/purge`.
- Purging removes the AgentDirectory record, unreferenced private tool/memory policies, stale mode/group-room references, and the Agent private workspace while logging `agent.purged`; active and protected Agents remain blocked from physical deletion.
- Group-room cleanup now repairs legacy session-only participants before Agent removal, so archived/direct-session Agents cannot slip past unique-member guards because of stale participant shape.

## 0.4.23 - 2026-05-29

- Retired the duplicate `/chat-rooms` group-chat workspace route and kept it as a compatibility redirect into `/chat`.
- Preserved `/chat-rooms?room=...` deep links by redirecting them to `/chat?room=...`, so Chat/Coding remains the single group-chat user surface while `/api/chat-rooms` stays as the backend contract.

## 0.4.22 - 2026-05-29

- Bound the Research Flow Canvas to the stable `research-team` Team entity while keeping `research_organization` as the live organization source.
- Added research-Team synchronization from the active organization graph so Team members, Team canvas nodes, and communication edges stay aligned with the locked research canvas.
- Pruned unresolvable active Research Organization nodes during canvas repair so embedded stale Agent snapshots cannot drift the locked canvas away from AgentDirectory.

## 0.4.21 - 2026-05-29

- Added a Teams inspector task kickoff form that starts the linked Chat/Coding group-room round directly from a selected Team, carrying `source=team_workspace` and `teamId` metadata.
- Blocks task kickoff until the Team has a linked room, active members, and no busy linked-room round, then refreshes team, chat-room, and conversation caches with an open-group-chat handoff link.

## 0.4.20 - 2026-05-29

- Closed archived-Agent execution gaps across edit-resubmit, queued chat workers, chat-room speakers, and ContextEngine context lookup so AgentDirectory active Agents remain the runtime source of truth.
- Fixed chat-room speaker reservation order so a waiting group speaker reserves the Agent execution slot before expensive context preparation, preventing later direct turns from cutting ahead.

## 0.4.19 - 2026-05-29

- Tightened AgentDirectory as the Agent availability source: archived or missing Agents now block chat turn scheduling and inbox wake delivery instead of being runnable through stale direct-session references.
- Split silent ensure from explicit restore semantics: `ensure_agent_for_session` no longer reactivates archived Agents, while fixed supervised/self-evolution role bootstrap uses explicit `agent.reactivated` diagnostics.

## 0.4.18 - 2026-05-29

- Linked Agent Center Teams to Chat/Coding group rooms: teams with active Agent members now create and maintain a linked group chat, and canvas member changes sync that room's participants.
- Added a Teams page control to open or sync the linked group chat, plus `/chat?room=...` deep-link support so team, canvas, Agent members, and group-chat execution share one navigation path.

## 0.4.17 - 2026-05-29

- Fixed Chat/Coding direct session deletion so deleted Agent-bound session ids no longer reappear from the AgentDirectory direct-session index.
- Rebind the active Agent to a fresh empty direct session after deleting its old conversation record, while keeping the Agent active and adding `session.delete.agent_rebound` lifecycle diagnostics.

## 0.4.13 - 2026-05-29

- Reworked Agent Center filters into status, runtime mode, and reference sections so active Agents, archived records, mode membership, group-chat references, and team references are no longer mixed in one flat list.
- Changed the default Agent Center filter to active Agents so archived records no longer inflate the primary available-Agent view.

## 0.4.12 - 2026-05-29

- Made direct chat session deletion diagnosable by logging requested, busy-blocked, and deleted lifecycle events into runtime scene conversation logs.
- Show a visible busy-delete reason in the Chat/Coding session list when a direct session is still running or stopping instead of relying only on a disabled delete button.

## 0.4.11 - 2026-05-29

- Added QQ-like blue clickable `@` mentions in the Chat/Coding project bus and group-chat timelines, resolving active Agent code/name/id mentions to their direct conversation index and `@全体成员`/`@all` to the project bus index.
- Added focused mention tokenization coverage so unknown mentions remain plain text while recognized Agent mentions preserve the original message content around them.

## 0.4.10 - 2026-05-29

- Added read-only research organization context to persistent Research Agent turns so a CEO/advisor/steward can see connected team members, Agent IDs/codes, roles, responsibilities, communication edges, allowed message types/intents, and wake policy before using `agent_message_tool`.
- Filtered the runtime organization context to the current Agent's connected communication subgraph so stale historical research nodes do not pollute the member list.

## 0.4.9 - 2026-05-29

- Added the project Agent bus and Agent Teams workspace so project-wide and team-scoped broadcasts can target active Agents, wake or interrupt them, appear in the shared bus timeline, and be revoked through the UI.
- Routed research-organization Agent messages through the organization graph policy layer and locked the Research Flow Canvas to the live organization graph, including read-only Agent/communication-line rendering and stale/archived Agent safety fixes.
- Tightened Agent Center pages into a compact console layout across Agents, Prompt Templates, Tools, Skills, and Memory, while exposing team references, archived/protected Agent counts, and safer archive semantics.
- Reduced frontend API failure telemetry noise by suppressing pagehide-adjacent background GET cancellations without hiding normal foreground failures.

## 0.4.8 - 2026-05-29

- Fixed AgentDirectory-only direct sessions in Chat/Coding so selecting or sending to an active Agent direct session materializes it into chat state instead of returning "Session not found."
- Added lifecycle logging and regression coverage for materializing active Agent direct sessions from Agent Center metadata before detail, attachment, delete, or message submission flows.

## 0.4.7 - 2026-05-28

- Clarified Agent Center archive semantics for protected core research Agents: active CEO/advisor/steward cards now show a neutral archive-protection panel instead of the destructive safe-archive zone.
- Added the archived Agent count to the Agent Center summary so protected active Agents and truly archived Agents are visibly separate.
- Locked the research flow canvas to the live research organization graph so it shows active project Agents, person-name/function tags, and communication edges from the same project-bound source.

## 0.4.6 - 2026-05-28

- Aligned Chat/Coding conversation indexes with Agent Center as the authoritative Agent source: direct conversations now carry Agent primary mode, role key, and prompt template metadata, and active Agent Directory direct sessions can appear in the conversation list even when chat state lacks a matching conversation entry.
- Updated Chat/Coding grouping so research organization members classify under the Research Agent group from Agent Center metadata instead of brittle session titles or legacy profile labels.

## 0.4.5 - 2026-05-28

- Routed `agent_message_tool` messages involving research organization Agents through the organization graph policy layer, so CEO, organization advisor, capability steward, and recruited research members honor communication edges, message type/intent rules, supervision gates, inbox delivery, wake rules, and audit logging.
- Added regression coverage for allowed CEO-to-capability-steward delivery, blocked advisor-to-CEO task delivery, and blocked outsider-to-core Agent delivery through the real tool executor path.

## 0.4.4 - 2026-05-28

- Exposed restricted tool permission metadata in the tool registry so Agent management can distinguish default-inherited tools from explicit-allow tools.
- Updated the Agent tools workbench to show the research knowledge query tool as requiring explicit Agent allow-list permission before it becomes visible or callable.

## 0.4.3 - 2026-05-28

- Added the protected research Capability Steward Agent as the third default core role beside CEO and organization advisor.
- Assigned role-specific tool policies, memory read/write groups, and graph communication edges so prompt, tool, and memory governance can start from a minimal ordered team.
- Restored the built-in capability steward prompt template and updated the default research flow canvas to show the graph-shaped three-role opening structure.

## 0.4.2 - 2026-05-28

- Changed the default research team entry to CEO Agent plus organization advisor only; specialist research Agents are now explicitly activated or created through CEO/advisor organization proposals instead of being auto-seeded.
- Updated the research flow canvas default to the CEO-to-advisor organization entry while preserving explicit worker flow execution support and regression coverage.

## 0.4.1 - 2026-05-28

- Fixed Research AgentInstance sync so archived or missing Research Agents are replaced before mode binding updates, preventing repeated `research.mode_binding.sync_failed` runtime-scene errors from stale Agent ids.
- Added lifecycle logging for stale Research Agent replacement and regression coverage for archived Research mode binding references.

## 0.4.0 - 2026-05-28

- Added Impeccable product/design context for Vibelution frontend visual work.
- Unified Agent management routes around Agent Center navigation, prompt templates, tools, skills, memory, runtime evidence, and responsive `/agents` behavior.
- Added a read-only Skill Library plus `/skill` slash-command routing into chat turns with bounded runtime context and lifecycle logging.
- Added missing-Agent placeholders and safer delete/reference cleanup so sessions, rooms, bindings, and research canvases can surface invalid Agent content without crashing.
- Streamlined research theme discovery onto Agent-only flow-canvas nodes and updated related route/tests.
- Refined the Agent management surface with a denser control-room layout, stronger runtime/status hierarchy, and polished operational navigation.

## 0.3.0 - 2026-05-27

- Added the unified Agent configuration foundation across AgentInstance, PromptTemplate, ModeBinding, and ContextEngine boundaries.
- Expanded Agent settings APIs for prompt templates, mode bindings, inbox messages, and recent Agent run history.
- Migrated chat, research, supervised evolution, and self-evolution paths toward Agent-based runtime resolution.
- Improved the research flow canvas with Agent bindings, stricter contract validation, and corrected default routing contracts.
- Refined the workbench settings and chat surfaces for Agent configuration, role bindings, and cross-Agent messaging.

## 0.2.1 - 2026-05-27

- Fixed a startup overlay false positive where non-blocking lifecycle proof items could mark an already running workbench as failed.
- Kept advisory runtime source freshness signals visible in lifecycle proof without blocking open/steady workbench sessions.

## 0.2.0 - 2026-05-27

- Added multi-agent conversation and chat room foundations, including persistent agent registry, conversation APIs, and group context handling.
- Expanded the research workspace with configurable research agents, knowledge-base backed research flow, richer canvas editing, and additional validation coverage.
- Improved the web workbench surface across chat, memory, config, self-evolution, and runtime status views.
- Strengthened tool execution, shell safety, LLM routing/configuration, and runtime scene observability.
- Added focused backend and frontend regression coverage for the new workbench, research, agent, and tool behaviors.
