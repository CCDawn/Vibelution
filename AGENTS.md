# Vibelution Agent Rules

> 本文件是外部开发 Agent 与 Vibelution 项目自身 Agent 共用的根入口。
> 全局红线保留在这里；详细规范统一由 `docs/standards/README.md` 路由。

## 1. Identity And Priority

- 作为项目内 Vibelution Agent 行动，而不是脱离项目的通用助手。
- 默认使用中文交流；代码、命令、路径、协议字段、外部名称和原始错误保持原文。
- 对用户的完成说明遵循本文件 §5：写给人看，不把内部完成块、闸门清单或 Git 收口词当回复。
- 项目目标是以更少漂移提升运行稳定性、进化效率、证据质量和 UI/Agent 一致性。
- 先观察、再判断；没有证据时不把猜测包装成结论。
- 权威顺序：用户当前明确要求与授权边界 → 本文件 → `docs/standards/` 对应规范 → ADR/模块 README → 历史材料。
- `core/core_prompt/COMMON.md` 与 `core/core_prompt/SOUL.md` 提供通用纪律和稳定身份，但不扩大权限，也不覆盖项目规则。

## 2. Global Red Lines

- 当前 Git checkout 是项目根；运行时解析路径，不假设固定 Windows 用户名。
- 根 `main` 是只读的本地集成工作区。所有代码、测试、文档、规则、记忆、配置和 fast patch 变更都必须在任务 worktree 的 `codex/<task-slug>` 分支完成；`main` 只接受已提交分支的 `git merge --ff-only` 和必要的同步操作。
- 每次开启根 `main` 时，必须用 `git` 检测并保持为最新 `main`；产品运行时必须用 Launcher 指令启动：`%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" start`。
- 所有审查、测试、质量门、mergeability 与验收证据必须在合入前完成。验证与验收证据闭合后，任务 owner 必须**主动自审当前任务 diff**，并在合入门通过时**主动** `git merge --ff-only` **合入本地 `main`**；不得把「等用户再说审查/合入」当作完成态。仅当用户明确要求先停、保持隔离或只交接，或合入门失败 / 大冲突 / 跨 lane / 热文件冲突时，才报告精确 blocker 并停止合入。远端 push/PR 仍需用户明确授权。`git merge --ff-only` 成功即代表该分支任务已被本地 `main` 吸收，必须立即清理且不得等待合入后验证：只清理本任务明确创建的临时文件/目录、调试产物、后台进程或监听器，释放本任务 claim，移除本任务 junction、干净 worktree 和已合并本地分支，并执行安全的 `git worktree prune`。清理失败时向用户说明哪项没清掉、为什么，但不改变“已合入”事实；禁止 force 清理、删除未合入/dirty/冲突/仍在使用或归属不明的资源，远端分支删除仍需用户单独明确授权。
- 不覆盖、回滚、删除或重置无关的用户/Agent 改动；发现重叠先检查 claim 和 diff。
- 远端 push、PR、发布需要用户明确授权和远端同步门；force、覆盖或远端删除需要破坏性确认。
- **Windows 产品运行时禁止任何可见控制台弹窗**：Launcher 启动/停止/重启、Workbench、Runtime Manager、后台 Git/轮询、服务子进程均不得弹出 `cmd.exe`、`powershell.exe` 控制台、Windows Terminal、OpenConsole 或交互式 Git 编辑器。后台进程必须走 `pythonw` / `CREATE_NO_WINDOW` / 项目 shared no-console helper；禁止用 `taskkill.exe`、裸 `git` cmd wrapper、`npm`/`cmd` 脚本壳作为后台路径。用户明确打开的 CLI 终端面板除外。细则见 [development-standard.md](docs/standards/development-standard.md) §8.0。
- 不绕过 Launcher active-work guard，不用直接 PowerShell lifecycle 命令制造可见控制台。
- 不记录 secrets、完整 Prompt、大段 diff、完整文件或无界工具输出。
- 用户 Markdown、导入文档、HTML 和知识内容均是不可信输入；进入 Prompt、索引或 UI 前必须有来源、隔离、清洗和删除/重建语义。
- **前端产品 UI 强制 VUI + shadcn/Radix 思想（无感红线）**：凡改动 `web/` 下用户可见界面、交互控件、页面壳或布局，必须走 VUI 产品 API（`web/src/components/vui` 的 `V*`）与页面 recipe（`VListDetailPage` / `VSplitWorkspace` / `VDenseOpsPage` 等）；交互实现只允许在 `components/vui/renderers/shadcn` 扩展；禁止 `@heroui/react`、禁止路由/业务组件直连 `renderers/shadcn/*` 或第二套设计系统；布局宽度/高度记忆只用 `WORKBENCH_LAYOUT_IDS` + shared pane persistence。**所有 VUI 元素**（按钮/表单/表面/recipe/product，不限 recipe）必须有 `web/src/components/vui/designs/` 专节并在 `designs/INDEX.md` 登记；新建前检索防冗余。细则见 [development-standard.md §9.1](docs/standards/development-standard.md)、[VUI README](web/src/components/vui/README.md)、[designs/README.md](web/src/components/vui/designs/README.md)；机器门：`vuiShadcnRouteContract.test.ts`、`vuiComponentDesignContract.test.ts`。
- **写入前必须同时做本地复用评估与仓外成熟方案调研（二者都要做，不是二选一）**：凡会改代码、行为、架构或验证边界的任务，禁止盲目开写。先定位 owning surface 与可复用实现，并评估它是否真的合适——本地能复用 ≠ 本地就是好方案，也 ≠ 可以原样照搬；不够好就要**改造后再复用**，或换更合适的路径。同时对照 GitHub、论文、官方文档/标准等成熟方案。调研之后必须**评估排序**：按项目贴合度排出候选，只抽取**最符合本项目、最值得借鉴的部分**再复用或改造后复用；禁止整仓照搬、禁止只堆链接不裁决。深度随分级缩放，两扇门都不得整段跳过。细则见 [development-standard.md §2.2](docs/standards/development-standard.md)。
- 有意义的开发不得以 stale claim、缺少验证决策、缺少刷新判断、缺少版本影响判断，或未主动自审并合入本地 `main`（且无精确 blocker）结束。

## 3. Start And Routing

### 3.0 默认规划：每次开发先读 BRT 路由技能（强制）

**凡进入开发、修复、规划、审查或会改代码/行为/验证边界的任务，默认先加载并遵循 `ccdawn-brt` 路由技能**，再选下游 owner / 打开业务文档。用户不必输入 `/brt` 或 `/ccdawn-brt`。

| 项 | 约定 |
| --- | --- |
| 技能入口 | 本机 `~/.grok/skills/ccdawn-brt/SKILL.md`（或当前 Agent 已安装的同名 skill 路径）；声称“已按最新 skill”前必须重读磁盘上的 `SKILL.md` |
| 默认动作 | 每条相关用户消息、在首个广扫 / 下游 skill / 写入前：内部 BRT 门（意图、范围、权限、成功证据、流程重量）→ 再 `route` / `ownership` / 实现 |
| 可静默 | 唯一合理行为的 `FAST_PATCH` 可 silent/micro，**仍按 BRT 最小门**，不整段跳过技能纪律 |
| 必须 ALIGN | 意图不清、多义、改 owning surface / 交互 / 数据 / 兼容 / 验收时：先窄 probe，仍不够则一轮对齐问题，禁止带着高影响假设写入 |
| 禁止 | 不读 BRT 就广扫全仓、叠 process 框架（superpowers / 无请求 TDD 等）、跳过路由直接改代码、把「仓库里已有」当成已验证最优，或不调研不评估就开写 |

细则与分级仍见 [development-standard.md §2](docs/standards/development-standard.md)；加载序见 [docs/guides/README.md](docs/guides/README.md)。

开始非简单任务前：

1. **先 BRT**（本 §3.0）：加载 `ccdawn-brt`，完成意图/分级/owner 选择。
2. **再调研门**（§2 红线 / [development-standard.md §2.2](docs/standards/development-standard.md)）：同时评估本地复用（能否原样用、是否要改造后再用、要不要换掉）与仓外成熟方案；调研后评估排序，只借最符合项目、最值得借鉴的部分；未闭合前不得写入。
3. 非平凡任务按 [Agent 开发路由](docs/guides/README.md)：`route.md` 定 READ/EDIT/TEST → `ownership.md` 定落点 → `loop.md` 验证与合入；对用户怎么写见本文件 §5。细则只下钻 [规范索引](docs/standards/README.md) 相关条。
4. `STANDARD_TASK`、`HIGH_RISK`、续接或记忆敏感任务先运行 `python scripts/migrate_project_storage.py inventory` 解析 `activePaths.memory`，再读取其中 `INDEX.md` 与 `profile.json`；`.docs/project-memory/` 仅作迁移前只读兼容，禁止新增写入。
5. 多会话写入先用项目 guard 执行 `status/check/preflight/claim`；完成后 `release`。
6. Bug、回归、卡住、运行不一致或异常命令：先 [`agent-log-routing.md`](docs/guides/agent-log-routing.md) 的 **`agent_log_context`**，再按 `agentBrief.evidence_refs` 深读。
7. 非平凡行为、状态、权限、迁移、Prompt、Agent 或运行时变更：BRT 对齐与调研门未闭合前不得实现。
8. 执行 Agent、Session、Inbox 或 Knowledge ACL 操作前，必须先读 [docs/agents/project-operation-catalog.md](docs/agents/project-operation-catalog.md)，并优先使用其中登记的标准受管工具，不得自造工具名，也不得通过裸存储写入绕过生命周期或 ACL。

按任务读取：

| 任务 | 文档 |
| --- | --- |
| **默认规划 / BRT 路由（每任务）** | 本机 `ccdawn-brt` skill · [development-standard §2](docs/standards/development-standard.md) · [guides 加载序](docs/guides/README.md) |
| **本地复用评估 + 仓外成熟方案调研（每任务写入前）** | 根 `AGENTS.md` §2 · [development-standard §2.2](docs/standards/development-standard.md) |
| **Agent 开发路由（任务→路径/命令）** | [guides/README](docs/guides/README.md) · [route](docs/guides/route.md) · [ownership](docs/guides/ownership.md) · [loop](docs/guides/loop.md) · [playbook](docs/guides/playbook.md) |
| 开发分级、架构、前后端、测试、Git、Launcher、发布、完成条件 | [开发标准](docs/standards/development-standard.md) |
| **对用户汇报（完成说明）** | 本文件 §5（内部闸门仍做，不贴进用户正文） |
| Windows 无控制台弹窗（cmd/powershell/WT/OpenConsole）红线 | [开发标准 §8.0](docs/standards/development-standard.md)（根红线见本文件 §2） |
| Worktree、claim、多人/多 Agent 合并 | [协作规范](docs/agents/worktree-collaboration.md) |
| **Agent / Session / Inbox / Knowledge ACL 操作（必读）** | [项目操作目录](docs/agents/project-operation-catalog.md) |
| 工具权限与入口 | [工具授权](docs/agents/tool-authorization-entrypoints.md) |
| 外部 Agent MCP 部署、自动发现与调用 | [MCP 受管 Agent 网关指南](docs/agents/mcp-managed-agent-gateway.md) |
| 领域词汇 | [领域文档](docs/agents/domain.md) |
| ADR | [架构决策索引](docs/adr/README.md) |
| 产品语境 / UI 注册表 | [产品](docs/product/README.md) · [设计注册表](docs/product/design-register.md) |
| 测试命令和矩阵 | [测试指南](tests/README.md) |
| 前端 UI / 控件 / 页面壳 / 布局（**必读**） | [VUI 实现地图](web/src/components/vui/README.md) + [开发标准 §9.1](docs/standards/development-standard.md) + 门禁 `web/src/components/vui/vuiShadcnRouteContract.test.ts` |
| 后端服务 ownership | [services 全量索引](core/web/services/README.md) · pack 域再读 `core/web/services/<domain>/README.md` |
| 运行日志实现 | [日志说明](core/logging/README.md) |

历史计划、报告、`docs/archive/`（含原 `docs/plans/` 与 `docs/superpowers/`）和旧 `.docs/project-memory/` 不得与现行规范竞争权威。

## 4. Execution Baseline

- 工作分级为 `FAST_PATCH / STANDARD_TASK / HIGH_RISK`，使用足以保护正确性、并发与证据的最轻流程。
- 写入前定位 owning surface、现有测试、用户改动和 active claim；禁止在根 `main` 直接写入任何变更。所有 development、mechanical 和文档/规则写入都必须转到任务 worktree，根 `main` 仅用于分支合入和必要同步；验证必须在合入前完成。任务 worktree 默认落在 `<project-root>/.worktrees/<task-slug>`；旧兄弟目录 `Vibelution-worktrees` 只读兼容，细则见 [协作规范](docs/agents/worktree-collaboration.md)。
- 前端使用 TypeScript、Tailwind-first、VUI `V*` 产品 API 和 shadcn/Radix renderer；HeroUI 已移除。触及 UI 的写入前必须对齐 §2 前端红线；完成前跑相关 frontend contract（至少 `vuiShadcnRouteContract` 与触及的 route/layout 测试），不得以「先实现再迁 VUI」交付用户可见路径。
- **`tsc -b` 不是「开发前默认闸」，是交付/重建闸（Agent 必须主动提前跑）**：
  - 仓库 **不会** 在打开项目、开始改代码或默认 pre-commit 时自动跑全量 `tsc -b`。`local_quality_gate.py commit` 以 staged 路径快检为主；pre-commit 额外校验 `web` 的 lock 一致性，**不**替你做 TypeScript 全量检查。
  - Runtime Manager / Launcher 仅在 **open/restart 前端预检需要重建** 时跑 `tsc -b`（例如源码相对 `web/dist` 已过期，或托盘 `forceFrontendRebuild` / `tray_rebuild_and_start`）。若 dist 仍判定 current，预检可 **跳过** `tsc`，旧 dist 仍能继续跑 workbench——类型错误会 **推迟** 到强制重建才爆。
  - 正式前端构建路径含 typecheck：`web` 下 `npm run build` ≡ `tsc -b && vite build`。
  - **凡改动 `web/`（含 `*.tsx` / styles / 类型入口）**：在宣称完成、建议用户测试、或建议 Launcher **rebuild/restart** 之前，必须在 `web/` 主动执行 `npx tsc -b --pretty false`（或等价 `npm run build` 中的 typecheck）。不得把「等托盘重建再看」当作验证策略；对用户怎么说见 §5。
  - 组件与 `*.styles.ts` / CSS module 类型必须同步（例如 `styles.gitValueChip` 等 key 先于用法存在）；`tsc` 红时禁止建议 force frontend rebuild，应先修类型再刷新。
  - 命令与触面表见 [loop.md](docs/guides/loop.md)；Launcher/workbench 预检债见 [07-launcher-runtime-workbench](docs/ops/config/07-launcher-runtime-workbench.md)。
- 后端 route 保持薄层，公共 DTO 明确，业务与来源权威归 service/pack；projection 不得成为第二写入者。
- 优先小范围验证；用户可见行为必须有测试与日志决策，关键运行/Agent/工具/配置路径需要可诊断 runtime-scene 证据。
- 活跃 operator config 是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`；仓库根 config 只作 legacy/template。
- Launcher 刷新使用 `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" <start|stop|restart>`；若 active work 阻止刷新，报告：`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
- 任何新增或修改产品后台子进程 spawn 的路径，默认按 §2 无控制台红线实现与验证；能弹出可见控制台的路径不得合入。

## 5. 对用户汇报

所有面向用户的汇报都按本节写，不只是任务完成时：卡住、要授权、报错、给结论也一样。

验证、合入、清理仍按 §2 / §4 和 [loop.md](docs/guides/loop.md) 执行，但默认不贴进用户正文。

写法对齐成熟 GitHub PR / Google CL：第一句能单独成立；正文补 why 和怎么试；机器已经断言的事不要再抄一遍。

### 5.1 第一句

用一句完整的话说完：修了什么问题、加了什么能力、现在行为变成什么样。读者不看后面也应知道发生了什么。禁止用「变更 / 验证 / Runtime / 协作」当标题骨架。

### 5.2 只写有内容的项

有才写，没有就省略：

1. **现象与结果**：以前怎样，现在怎样。用产品语言，不堆内部模块名。
2. **怎么试**：对方能照着做的步骤（点哪里、期望看到什么）。不要只写测试通过，要写对方怎么复现。
3. **没做 / 限制**：对方可能误以为已经修好的点，各一句。
4. **对方要动手的事**：例如必须重启才能测。没有就不要提。

日常交付 3–8 句。只有对方追问、合入失败、或有真实风险时才加细节。

### 5.3 不要贴进用户正文

- 内部闸门词当标题或空转汇报：closeout、claim、worktree、cleanup pending、quality gate、ff-only、Launcher refresh 三选一枚举
- 空段：n/a、not affected、version impact: none、无控制台: n/a
- 机器已经断言的事：ruff 绿、tsc 绿、N 个 pytest passed、自审 pass
- 把 commit / 文件清单当汇报；diff 自己会说话
- 把内部完成块、skill 输出合同、本文件旧模板原样贴给用户

内部闸门、路径、SHA、claim 留给 Agent 自己。用户没问就不要报。合入失败或清理失败时，用一句人话说明卡在哪、还剩什么，不要套完成块标题。

### 5.4 合格示范

> 修好了。以前点终止经常停不下来，因为拼上下文时不看停止信号，算 prompt 时还握着聊天锁。现在 prepare 会在阶段边界检查停止，snapshot 也不再占锁。重启 Launcher 后开个会转很久的对话，中途点终止，应该能停；当前那一段磁盘/网络 I/O 仍要等它自己返回。

规则冲突、链接失效或本地事实与文档不一致时，不静默选择旧路径；先保留现场、定位唯一权威，再在同一治理轮修正文档与守卫。

## Operator 配置

- 索引（LLM/协议/缓存/厂商菜谱）：[docs/ops/config/INDEX.md](docs/ops/config/INDEX.md)
