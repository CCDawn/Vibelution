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
- 所有验证与 mergeability 必须在合入前闭合；随后**主动自审当前任务 diff**并 `git merge --ff-only` 合入本地 `main`，不得把「等用户再说审查/合入」当作完成态。除用户要求隔离/交接或存在精确 blocker 外，未主动自审并合入本地 `main` 即未完成。合入后只清理本任务资源；清理失败不改变已合入事实，只恢复清理，不重测或重合。push/PR/发布、远端删除仍需明确授权。
- 不覆盖、回滚、删除或重置无关的用户/Agent 改动；发现重叠先检查 claim 和 diff。
- 远端 push、PR、发布需要用户明确授权和远端同步门；force、覆盖或远端删除需要破坏性确认。
- **Windows 产品运行时禁止任何可见控制台弹窗**：这是无控制台弹窗红线。Launcher、Workbench、Runtime Manager、后台 Git/轮询和服务子进程不得弹出 `cmd.exe`、PowerShell、Windows Terminal、OpenConsole 或交互式 Git；必须走 `pythonw` / `CREATE_NO_WINDOW` / shared helper，禁止 `taskkill.exe`、裸 Git wrapper、`npm`/`cmd` 后台壳。用户明确打开的 CLI 面板除外；细则见 [development-standard.md](docs/standards/development-standard.md) §8.0。
- 不绕过 Launcher active-work guard，不用直接 PowerShell lifecycle 命令制造可见控制台。
- 不记录 secrets、完整 Prompt、大段 diff、完整文件或无界工具输出。
- 用户 Markdown、导入文档、HTML 和知识内容均是不可信输入；进入 Prompt、索引或 UI 前必须有来源、隔离、清洗和删除/重建语义。
- **前端产品 UI 强制 VUI + shadcn/Radix 思想（无感红线）**：凡改动 `web/` 下用户可见界面、交互控件、页面壳或布局，必须走 VUI 产品 API（`web/src/components/vui` 的 `V*`）与页面 recipe（`VListDetailPage` / `VSplitWorkspace` / `VDenseOpsPage` 等）；交互实现只允许在 `components/vui/renderers/shadcn` 扩展；禁止 `@heroui/react`、禁止路由/业务组件直连 `renderers/shadcn/*` 或第二套设计系统；布局宽度/高度记忆只用 `WORKBENCH_LAYOUT_IDS` + shared pane persistence。**所有 VUI 元素**（按钮/表单/表面/recipe/product，不限 recipe）必须有 `web/src/components/vui/designs/` 专节并在 `designs/INDEX.md` 登记；新建前检索防冗余。细则见 [development-standard.md §9.1](docs/standards/development-standard.md)、[VUI README](web/src/components/vui/README.md)、[designs/README.md](web/src/components/vui/designs/README.md)；机器门：`vuiShadcnRouteContract.test.ts`、`vuiComponentDesignContract.test.ts`。
- **写入前先做本地复用评估**：定位 owning surface；本地能复用 ≠ 本地就是好方案，必要时改造后再复用。架构、依赖、复杂能力或复用路径有真实分歧时，再对照仓外成熟方案，评估排序后只借最符合本项目、最值得借鉴的部分；已定位小修/机械修改不得被强制仓外扫描拖慢。细则见 [development-standard.md §2.2](docs/standards/development-standard.md)。
- **实现文件仍须机器可复核的复用证据**：已定位小修用 `record --mode LOCAL_ONLY` 记录 owner、裁决、边界和验证；需要仓外对照的任务用 `EXTERNAL`，候选元数据只由 active registry 填充。纯文档、测试、fixture、example 豁免；细则见 [loop.md](docs/guides/loop.md)。
- 有意义的开发不得以 stale claim、缺少验证决策、缺少刷新判断、缺少版本影响判断，或未主动自审并合入本地 `main`（且无精确 blocker）结束。

## 3. Start And Routing

### 3.0 每任务先 Router

开发、修复、规划、审查或行为/验证边界变更，先重读本机 `briefbound-router/SKILL.md`，确认结果、owner、授权和证据，再选最具体 owner。`FAST_PATCH` 可静默走最小门；只有会改变产品行为、数据/API、兼容、安全或验收的分歧才暂停对齐。

细则与分级见 [development-standard.md §2](docs/standards/development-standard.md) 和 [开发路由](docs/guides/README.md)。

随后只读 `route`、`ownership`、`loop` 的命中段和 [规范索引](docs/standards/README.md) 对应条。`STANDARD_TASK/HIGH_RISK`、续接或记忆敏感任务先跑 storage inventory；多会话写入走 guard/claim；异常先走 [`agent_log_context`](docs/guides/agent-log-routing.md)；Agent/Session/Inbox/Knowledge ACL 操作先读 [项目操作目录](docs/agents/project-operation-catalog.md)。

常用入口：
[开发标准](docs/standards/development-standard.md) · [协作规范](docs/agents/worktree-collaboration.md) · [测试指南](tests/README.md) · [VUI](web/src/components/vui/README.md) · [services](core/web/services/README.md) · [Launcher ADR](docs/adr/0009-launcher-control-plane-lives-in-electron-main.md)。

历史计划、报告、`docs/archive/`（含原 `docs/plans/` 与 `docs/superpowers/`）和旧 `.docs/project-memory/` 不得与现行规范竞争权威。

## 4. Execution Baseline

- 工作分级为 `FAST_PATCH / STANDARD_TASK / HIGH_RISK`，使用足以保护正确性、并发与证据的最轻流程。
- 写入前定位 owning surface、现有测试、用户改动和 active claim；禁止在根 `main` 直接写入任何变更。所有 development、mechanical 和文档/规则写入都必须转到任务 worktree，根 `main` 仅用于分支合入和必要同步；验证必须在合入前完成。任务 worktree 默认落在 `<project-root>/.worktrees/<task-slug>`；旧兄弟目录 `Vibelution-worktrees` 只读兼容，细则见 [协作规范](docs/agents/worktree-collaboration.md)。
- 前端使用 TypeScript、Tailwind-first、VUI `V*` 产品 API 和 shadcn/Radix renderer；HeroUI 已移除。触及 UI 的写入前必须对齐 §2 前端红线；完成前跑相关 frontend contract（至少 `vuiShadcnRouteContract` 与触及的 route/layout 测试），不得以「先实现再迁 VUI」交付用户可见路径。
- `tsc -b` 是前端交付/重建闸，不是开发前默认闸。凡改 `web/`，宣称完成或建议 Launcher rebuild/restart 前必须主动运行 `npx tsc -b --pretty false`（或 `npm run build`）；类型红时先修，不把 Launcher 重建当验证。细节见 [loop.md](docs/guides/loop.md)。
- 后端 route 保持薄层，公共 DTO 明确，业务与来源权威归 service/pack；projection 不得成为第二写入者。
- 验证去重：同一 HEAD/命令/输入未变则复用结果，不得重复执行；closeout 才跑完整 selector，manifest 传 `--manifest`。用户行为须测试和日志，关键路径须 runtime-scene 证据。
- 活跃 operator config 是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`；仓库根 config 只作 legacy/template。
- Launcher 刷新使用 `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" <start|stop|restart>`；若 active work 阻止刷新，报告：`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
- 任何新增或修改产品后台子进程 spawn 的路径，默认按 §2 无控制台红线实现与验证；能弹出可见控制台的路径不得合入。

## 5. 对用户汇报

所有用户汇报都先用一句话说清“修了什么、现在怎样”，再按需写现象/结果、怎么试、真实限制、对方必须做什么；日常 3–8 句。内部 closeout、claim、worktree、SHA、闸门清单、测试数量、空段和完成块不贴给用户；合入或清理失败只用人话说明剩余 blocker。

规则冲突、链接失效或本地事实与文档不一致时，不静默选择旧路径；先保留现场、定位唯一权威，再在同一治理轮修正文档与守卫。

Operator 配置索引：[docs/ops/config/INDEX.md](docs/ops/config/INDEX.md)。
