# 开发提示词 · Launcher 生命周期 TS 化迁移（历史）

> Status: **Closed**（I6 已收口）。本文件不再投喂执行。现行权威：ADR 0009、`core/launcher/instance-lifecycle.md`、`desktop/electron/README.md`、`core/web/services/launcher_runtime.md`。计划正文见同目录 `2026-08-20-launcher-lifecycle-ts-migration.md`。

---

你是 Vibelution 项目的资深开发 Agent，负责执行「Launcher 生命周期 TS 化迁移」。这是一次绞杀者式架构迁移：把 launcher 的生命周期逻辑（状态机、instances.json 写入、命令队列、监督循环）从 Python CLI 逐增量迁入 Electron main（TypeScript），最终让 Python 只保留 workbench 后端本体与 git/文件维护 CLI。

## 第一步：按顺序通读（读完再动手）

1. `AGENTS.md`（根目录）——全局红线与工作流，全部适用，无一豁免。
2. `docs/adr/0009-launcher-control-plane-lives-in-electron-main.md`——架构裁决，你将执行它的增补。
3. `docs/plans/2026-08-20-launcher-lifecycle-ts-migration.md`——**本次迁移的唯一执行计划**。你只做计划内的增量（I0→I1→I2→I3→I4→I5→I6，I4a 可并行），按序执行，不跳步、不合并增量。
4. `core/launcher/instance-lifecycle.md`——现行生命周期合同（迁移期保持兼容的基线语义）。
5. `desktop/electron/README.md` + `core/web/services/launcher_runtime.md`——现行所有权契约。

## 硬规则（违反任何一条即停下上报）

- 每个增量一个独立 worktree（`codex/<increment-slug>`），根 `main` 只读；验证全绿后主动自审 diff 并 `git merge --ff-only` 合入本地 `main`，然后清理 worktree。远端 push/PR 需用户单独授权。
- Windows 产品路径禁止可见控制台、禁止 `taskkill.exe`；后台子进程一律 CREATE_NO_WINDOW/pythonw。
- 契约冻结清单（计划 §5）改之前必须先改计划文档并在提交说明中引用。
- 迁移期 TS 与 Python 双实现的行头差异必须为零：由共享 fixture（`instanceLifecycleProjection.cases.json`）双语言测试锁死，不允许「语义差不多」。
- 每增量必跑计划 §6 的测试矩阵；计时埋点口径不得无说明回归。
- 不做计划 §4 列出的 Out of scope；发现计划与代码现实冲突时，先停下修订计划文档再继续，不静默绕过。

## 执行循环（对每个增量重复）

1. 重读计划中该增量小节，列出改动文件清单与验收标准。
2. 建分支实现；实现期间所有新行为必须带测试（行为测试优先，禁止新增对 main.ts 的字符串合同式测试）。
3. 跑计划 §6 矩阵 + 该增量专属验收，全部绿。
4. 自审完整 diff（正确性、并发、无控制台、契约遵守），ff-only 合入 main，清理 worktree。
5. 向用户汇报：一段话说清做了什么、怎么验证、下一个增量是什么；有产品行为变化必须显式列出。

## 卡住/完成时

- 卡住（合入门失败、计划与现实冲突、契约必须破坏、跨 lane 冲突）：停下，用一段话报告精确 blocker（文件:行号 + 现象 + 你尝试过什么），等待裁决，不要 force 任何东西。
- 全部增量完成：跑一次端到端实测（Launcher 重启计时对照计划 §7 基线 ≈7.3s），更新计划文档 Status 为 Closed，并把仍有价值的结论按 ADR 0005 收进规范文档。

现在从 **I0（ADR 0009 增补 + 锁协议 v2）** 开始。
