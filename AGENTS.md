# Vibelution Agent Rules

> 本文件是外部开发 Agent 与 Vibelution 项目自身 Agent 共用的根入口。
> 全局红线保留在这里；详细规范统一由 `docs/standards/README.md` 路由。

## 1. Identity And Priority

- 作为项目内 Vibelution Agent 行动，而不是脱离项目的通用助手。
- 默认使用中文交流；代码、命令、路径、协议字段、外部名称和原始错误保持原文。
- 项目目标是以更少漂移提升运行稳定性、进化效率、证据质量和 UI/Agent 一致性。
- 先观察、再判断；没有证据时不把猜测包装成结论。
- 权威顺序：用户当前明确要求与授权边界 → 本文件 → `docs/standards/` 对应规范 → ADR/模块 README → 历史材料。
- `core/core_prompt/COMMON.md` 与 `core/core_prompt/SOUL.md` 提供通用纪律和稳定身份，但不扩大权限，也不覆盖项目规则。

## 2. Global Red Lines

- 当前 Git checkout 是项目根；运行时解析路径，不假设固定 Windows 用户名。
- 根 `main` 是本地集成工作区。普通开发使用任务 worktree；集成、规则/记忆维护和明确的低风险 fast patch 例外。
- 不覆盖、回滚、删除或重置无关的用户/Agent 改动；发现重叠先检查 claim 和 diff。
- 远端 push、PR、发布需要用户明确授权和远端同步门；force、覆盖或远端删除需要破坏性确认。
- **Windows 产品运行时禁止任何可见控制台弹窗**：Launcher 启动/停止/重启、Workbench、Runtime Manager、后台 Git/轮询、服务子进程均不得弹出 `cmd.exe`、`powershell.exe` 控制台、Windows Terminal、OpenConsole 或交互式 Git 编辑器。后台进程必须走 `pythonw` / `CREATE_NO_WINDOW` / 项目 shared no-console helper；禁止用 `taskkill.exe`、裸 `git` cmd wrapper、`npm`/`cmd` 脚本壳作为后台路径。用户明确打开的 CLI 终端面板除外。细则见 [development-standard.md](docs/standards/development-standard.md) §8.0。
- 不绕过 Launcher active-work guard，不用直接 PowerShell lifecycle 命令制造可见控制台。
- 不记录 secrets、完整 Prompt、大段 diff、完整文件或无界工具输出。
- 用户 Markdown、导入文档、HTML 和知识内容均是不可信输入；进入 Prompt、索引或 UI 前必须有来源、隔离、清洗和删除/重建语义。
- **前端产品 UI 强制 VUI + shadcn/Radix 思想（无感红线）**：凡改动 `web/` 下用户可见界面、交互控件、页面壳或布局，必须走 VUI 产品 API（`web/src/components/vui` 的 `V*`）与页面 recipe（`VListDetailPage` / `VSplitWorkspace` / `VDenseOpsPage` 等）；交互实现只允许在 `components/vui/renderers/shadcn` 扩展；禁止 `@heroui/react`、禁止路由/业务组件直连 `renderers/shadcn/*` 或第二套设计系统；布局宽度/高度记忆只用 `WORKBENCH_LAYOUT_IDS` + shared pane persistence。**所有 VUI 元素**（按钮/表单/表面/recipe/product，不限 recipe）必须有 `web/src/components/vui/designs/` 专节并在 `designs/INDEX.md` 登记；新建前检索防冗余。细则见 [development-standard.md §9.1](docs/standards/development-standard.md)、[VUI README](web/src/components/vui/README.md)、[designs/README.md](web/src/components/vui/designs/README.md)；机器门：`vuiShadcnRouteContract.test.ts`、`vuiComponentDesignContract.test.ts`。
- 有意义的开发不得以 stale claim、缺少验证决策、缺少刷新判断或缺少版本影响判断结束。

## 3. Start And Routing

开始非简单任务前：

1. 非平凡任务按 [Agent 开发路由](docs/guides/README.md)：`route.md` 定 READ/EDIT/TEST → `ownership.md` 定落点 → `loop.md` 验证与完成块；细则只下钻 [规范索引](docs/standards/README.md) 相关条。
2. `STANDARD_TASK`、`HIGH_RISK`、续接或记忆敏感任务读取 `.docs/project-memory/INDEX.md` 与 `profile.json`；仅在会改变答案时继续读取具体 lane/registry。
3. 多会话写入先用项目 guard 执行 `status/check/preflight/claim`；完成后 `release`。
4. Bug、回归、卡住、运行不一致或异常命令先检查最新 `logs/runtime_scenes/`。
5. 非平凡行为、状态、权限、迁移、Prompt、Agent 或运行时变更先完成 BRT 对齐。

按任务读取：

| 任务 | 文档 |
| --- | --- |
| **Agent 开发路由（任务→路径/命令）** | [guides/README](docs/guides/README.md) · [route](docs/guides/route.md) · [ownership](docs/guides/ownership.md) · [loop](docs/guides/loop.md) · [playbook](docs/guides/playbook.md) |
| 开发分级、架构、前后端、测试、Git、Launcher、发布、完成条件 | [开发标准](docs/standards/development-standard.md) |
| Windows 无控制台弹窗（cmd/powershell/WT/OpenConsole）红线 | [开发标准 §8.0](docs/standards/development-standard.md)（根红线见本文件 §2） |
| Worktree、claim、多人/多 Agent 合并 | [协作规范](docs/agents/worktree-collaboration.md) |
| 工具权限与入口 | [工具授权](docs/agents/tool-authorization-entrypoints.md) |
| 领域词汇 | [领域文档](docs/agents/domain.md) |
| ADR | [架构决策索引](docs/adr/README.md) |
| 产品语境 / UI 注册表 | [产品](docs/product/README.md) · [设计注册表](docs/product/design-register.md) |
| 测试命令和矩阵 | [测试指南](tests/README.md) |
| 前端 UI / 控件 / 页面壳 / 布局（**必读**） | [VUI 实现地图](web/src/components/vui/README.md) + [开发标准 §9.1](docs/standards/development-standard.md) + 门禁 `web/src/components/vui/vuiShadcnRouteContract.test.ts` |
| 后端服务 ownership | [services 全量索引](core/web/services/README.md) · pack 域再读 `core/web/services/<domain>/README.md` |
| 运行日志实现 | [日志说明](core/logging/README.md) |

历史计划、报告、`docs/archive/`（含原 `docs/plans/` 与 `docs/superpowers/`）和 `.docs/project-memory/` 不得与现行规范竞争权威。

## 4. Execution Baseline

- 工作分级为 `FAST_PATCH / STANDARD_TASK / HIGH_RISK`，使用足以保护正确性、并发与证据的最轻流程。
- 写入前定位 owning surface、现有测试、用户改动和 active claim；根 `main` 上的 development 写入收到 `ISOLATION_REQUIRED` 时转任务 worktree。
- 前端使用 TypeScript、Tailwind-first、VUI `V*` 产品 API 和 shadcn/Radix renderer；HeroUI 已移除。触及 UI 的写入前必须对齐 §2 前端红线；完成前跑相关 frontend contract（至少 `vuiShadcnRouteContract` 与触及的 route/layout 测试），不得以「先实现再迁 VUI」交付用户可见路径。
- 后端 route 保持薄层，公共 DTO 明确，业务与来源权威归 service/pack；projection 不得成为第二写入者。
- 优先小范围验证；用户可见行为必须有测试与日志决策，关键运行/Agent/工具/配置路径需要可诊断 runtime-scene 证据。
- 活跃 operator config 是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`；仓库根 config 只作 legacy/template。
- Launcher 刷新使用 `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" <start|stop|restart>`；若 active work 阻止刷新，报告：`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
- 任何新增或修改产品后台子进程 spawn 的路径，默认按 §2 无控制台红线实现与验证；能弹出可见控制台的路径不得合入。

## 5. Completion Evidence

完成有意义的任务时至少说明：

- 实际改变了什么，以及没有改变什么；
- 运行了哪些验证，结果与未覆盖边界；
- Launcher/runtime refresh：`not needed / recommended before user testing / required before release`；
- 若触及启动、停止、重启、轮询、Git、工具或服务子进程：说明如何保证无可见控制台（helper/`pythonw`/`CREATE_NO_WINDOW`/`windowsHide`）及验证证据；
- project-memory 与 version impact 决策；
- worktree、branch、claim 和 Git 状态；
- 若包含 fallback、degraded、partial 或 compatibility 路径，明确原因、范围、可信部分和剩余修复信号。

规则冲突、链接失效或本地事实与文档不一致时，不静默选择旧路径；先保留现场、定位唯一权威，再在同一治理轮修正文档与守卫。
## Operator 配置

- 索引（LLM/协议/缓存/厂商菜谱）：[docs/ops/config/INDEX.md](docs/ops/config/INDEX.md)
