---
name: vibelution-continuous-optimization-loop
description: >-
  Runs one evidence-driven Vibelution optimization iteration from the ROI backlog:
  pick one todo item, worktree isolate, implement, machine-verify, merge, update
  STATE. Use when the user starts /loop for project improvement, continuous
  optimization, or agent-dev ROI backlog work.
---

# Vibelution 持续优化 Loop

每轮 = **一次** ROI 迭代。禁止一轮多 item、禁止无验证宣称完成。

## 启动

- 固定节奏：`/loop 30m` + 本 skill
- 动态：`/loop` + 本 skill（自设 heartbeat；有 CI/log watcher 时优先事件唤醒）
- 读 `.runtime/loop/STATE.md`（无则创建）与 `docs/guides/agent-dev-roi-backlog.md`

## 红线（摘要）

- 根 `main` 只读；写入在 `.worktrees/<task-slug>` + `codex/<task-slug>`
- `AGENTS.md` → `docs/guides/loop.md` → `docs/standards/`
- FE 可见 UI 必须 VUI；改 `web/` 合入前 `npx tsc -b --pretty false`
- 无授权 push/PR；无可见控制台；合入门通过后主动 `git merge --ff-only` + cleanup

## 单轮顺序

1. **选 1 项** — backlog 最高 ROI 且 `Status=todo`（P0→P1→P2）；遵守热文件冲突表
2. **CLASSIFY** — FAST_PATCH | STANDARD_TASK | HIGH_RISK
3. **LOCATE** — `route.md` + `ownership.md` + 域 README + 测试
4. **ISOLATE** — STANDARD+ 开 worktree；多 Agent 时 claim
5. **IMPLEMENT** — 最小 diff，只改 owner surface
6. **VERIFY** — `select_tests.py --from-git main --commands-only` → 聚焦 pytest；FE 触面 + contract + `tsc -b`
7. **INTEGRATE** — 自审 → ff-only merge → cleanup
8. **RECORD** — 更新 backlog Status；append `.runtime/loop/STATE.md`

## 机器验证（backpressure）

Agent 不得自评通过。fail → **ITERATE**（同 ROI，最多 2 轮）→ 仍 fail → **BLOCKED**。

## 每轮输出

```text
Loop 轮次: <N>
ROI-ID: Rxx
决策: ADVANCE | ITERATE | BLOCKED | STOP
本轮结果: …
新证据: <命令 + pass/fail>
Agent 便利变化: …
merge: merged | not merged + 原因
下一动作: …
```

## STOP

满足任一时末尾输出 exact 字符串：

`<promise>VIBELUTION_LOOP_STOP</promise>`

- P0/P1/P2 无剩余 todo（或仅 blocked 且无新证据）
- 连续 3 轮 ITERATE/BLOCKED 无新证据
- HIGH_RISK 缺用户确认
- claim/diff 冲突无法协商

## 禁止

- 一轮多个 ROI
- 为 loop 写长文档而不改代码/门禁
- loopmaxxing（重复已通过项）

## STATE 模板

见 [state-template.md](state-template.md)

## 参考

- 执行环：`docs/guides/loop.md`
- 工作队列：`docs/guides/agent-dev-roi-backlog.md`
- Ralph / Loop Engineering：固定 prompt + 磁盘状态 + 独立 verifier + max iterations
