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
- 不绕过 Launcher active-work guard，不用直接 PowerShell lifecycle 命令制造可见控制台。
- 不记录 secrets、完整 Prompt、大段 diff、完整文件或无界工具输出。
- 用户 Markdown、导入文档、HTML 和知识内容均是不可信输入；进入 Prompt、索引或 UI 前必须有来源、隔离、清洗和删除/重建语义。
- 有意义的开发不得以 stale claim、缺少验证决策、缺少刷新判断或缺少版本影响判断结束。

## 3. Start And Routing

开始非简单任务前：

1. 读取 [规范索引](docs/standards/README.md)，再只读取与任务相关的专项文档。
2. `STANDARD_TASK`、`HIGH_RISK`、续接或记忆敏感任务读取 `.docs/project-memory/INDEX.md` 与 `profile.json`；仅在会改变答案时继续读取具体 lane/registry。
3. 多会话写入先用项目 guard 执行 `status/check/preflight/claim`；完成后 `release`。
4. Bug、回归、卡住、运行不一致或异常命令先检查最新 `logs/runtime_scenes/`。
5. 非平凡行为、状态、权限、迁移、Prompt、Agent 或运行时变更先完成 BRT 对齐。

按任务读取：

| 任务 | 文档 |
| --- | --- |
| 开发分级、架构、前后端、测试、Git、Launcher、发布、完成条件 | [开发标准](docs/standards/development-standard.md) |
| Worktree、claim、多人/多 Agent 合并 | [协作规范](docs/agents/worktree-collaboration.md) |
| 工具权限与入口 | [工具授权](docs/agents/tool-authorization-entrypoints.md) |
| 领域词汇 | [领域文档](docs/agents/domain.md) |
| ADR | [架构决策](docs/adr/) |
| 测试命令和矩阵 | [测试指南](tests/README.md) |
| 前端 VUI | [VUI 实现地图](web/src/components/vui/README.md) |
| 后端服务 ownership | 对应 `core/web/services/<domain>/README.md` |
| 运行日志实现 | [日志说明](core/logging/README.md) |

历史计划、报告、`docs/archive/`、`docs/superpowers/` 和 `.docs/project-memory/` 不得与现行规范竞争权威。

## 4. Execution Baseline

- 工作分级为 `FAST_PATCH / STANDARD_TASK / HIGH_RISK`，使用足以保护正确性、并发与证据的最轻流程。
- 写入前定位 owning surface、现有测试、用户改动和 active claim；根 `main` 上的 development 写入收到 `ISOLATION_REQUIRED` 时转任务 worktree。
- 前端使用 TypeScript、Tailwind-first、VUI `V*` 产品 API 和 shadcn/Radix renderer；HeroUI 已移除。
- 后端 route 保持薄层，公共 DTO 明确，业务与来源权威归 service/pack；projection 不得成为第二写入者。
- 优先小范围验证；用户可见行为必须有测试与日志决策，关键运行/Agent/工具/配置路径需要可诊断 runtime-scene 证据。
- 活跃 operator config 是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`；仓库根 config 只作 legacy/template。
- Launcher 刷新使用 `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" <start|stop|restart>`；若 active work 阻止刷新，报告：`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`

## 5. Completion Evidence

完成有意义的任务时至少说明：

- 实际改变了什么，以及没有改变什么；
- 运行了哪些验证，结果与未覆盖边界；
- Launcher/runtime refresh：`not needed / recommended before user testing / required before release`；
- project-memory 与 version impact 决策；
- worktree、branch、claim 和 Git 状态；
- 若包含 fallback、degraded、partial 或 compatibility 路径，明确原因、范围、可信部分和剩余修复信号。

规则冲突、链接失效或本地事实与文档不一致时，不静默选择旧路径；先保留现场、定位唯一权威，再在同一治理轮修正文档与守卫。
