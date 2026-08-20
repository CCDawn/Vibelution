# 开发提示词 · Python lifecycle 代码物理清理

> 把本文件全文作为首条消息投喂给开发 Agent。

---

你是 Vibelution 项目的资深开发 Agent，负责执行「Python lifecycle 代码物理清理」：Launcher 生命周期逻辑已全部迁入 Electron main（TS），仓库里退役的 Python lifecycle 写路径现在要物理删除。

## 第一步：按顺序通读（读完再动手）

1. `AGENTS.md`（根目录）——全局红线与工作流。
2. `docs/plans/2026-08-20-physical-retirement-of-python-lifecycle.md`——**唯一执行清单**。批次 A→B→C 顺序执行；批次 D（daemon workbench 切除）本轮不做，做完 C 就停。
3. `docs/adr/0009-launcher-control-plane-lives-in-electron-main.md`——架构裁决与 I6 增补。

## 硬规则

- 每个批次独立 worktree（`codex/<batch-slug>`），全绿后主动自审 diff 并 `git merge --ff-only` 合入本地 `main`，清理 worktree；远端 push/PR 需用户单独授权。
- 删除任何函数/常量前必须全仓 grep（core/ scripts/ tests/ web/ desktop/）确认零活引用；发现清单之外的引用立即停下上报，不擅自扩大手术面。
- 批次 A 有一个预期行为变化必须写进提交说明：浏览器直接打开工作台时，生命周期按钮会显示明确的 IPC 不可用错误（产品内 Electron 窗口不受影响，IPC 优先早已生效）。
- 每批次验收以清单为准；最后跑一次 Launcher 实测：stop → start → restart → `/api/health` 200，事件流无新增报错。

## 卡住时

用一段话报告精确 blocker（文件:行号 + 引用链 + 你尝试过什么），等待裁决；禁止 force 删除、禁止半途合入。

现在从批次 A（HTTP 生命周期命令面下线）开始。
