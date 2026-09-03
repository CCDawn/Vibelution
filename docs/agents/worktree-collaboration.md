# Multi-Agent Worktree Collaboration

This document defines the default collaboration protocol for multiple Agents working on Vibelution in parallel.

## Work Surfaces

- `<project-root>` is the durable local `main` integration workspace. Keep this path checked out on branch `main`; use it only for local syncing, fast-forward merging, merge-result inspection, and publishing after the user explicitly authorizes a GitHub sync/release. All validation must finish before merge. Direct development writes and commits on `main` are forbidden.
- If `<project-root>` is found on a non-main branch, preserve or migrate that work into `<project-root>\.worktrees\<task-slug>` or a named stash, then restore the root path to `main` before continuing normal development or integration.
- Development Agents use task-specific worktrees under `<project-root>\.worktrees\`. Resolve the pool with `core.infrastructure.branch_workspace`; do not hardcode a username, Desktop, or sibling folder.
- The old sibling folder `<project-root-parent>\Vibelution-worktrees\` no longer exists on disk. The compatibility layer (`migrate_legacy_branch_workspaces` in `core.infrastructure.branch_workspace`) is kept only in case the folder reappears. Do not create new checkouts there; live legacy trees, if any ever resurface, can move with `migrate_legacy_branch_workspaces`.
- If the in-repo pool is unavailable, use `.claude/worktrees\<task-slug>` or another explicit task worktree path and record the actual path in `check`/`claim` evidence.
- Each active task, including `FAST_PATCH`, gets one task worktree and one `codex/<task-slug>` branch. `FAST_PATCH` may use a lighter validation path, but it may not stay in the `main` workspace. Do not reuse an old task worktree for a new goal.

## Starting A Task

For `STANDARD_TASK` and `HIGH_RISK`, create a task branch from the current local `main`:

```powershell
cd <project-root>
git worktree add .worktrees/<task-slug> -b codex/<task-slug> main
```

Use `git fetch origin` only as a read-only observation step unless the user explicitly asks to align with GitHub. Do not reset, rebase, or create task branches from `origin/main` by default.

The task slug should describe one goal, for example `fix-ci-timezone-test` or `llm-protocol-routing`.

## Active Dispatch

The current main integration session may actively dispatch work to other Codex sessions or sub-agents only when the user has asked for parallel work, delegation, or coordinator-driven task assignment.

Before dispatching, the main integration session must:

- state the main goal and immediate local critical path;
- split only independent side tasks or bounded implementation slices;
- assign a disjoint write scope to every worker;
- keep hot shared files under one explicitly named owner;
- decide what the main integration session will continue doing locally while workers run;
- avoid delegating work that blocks the main integration session's very next action.

Use read-only explorer agents for narrow codebase questions. Use worker agents only for concrete implementation, verification, or repair tasks with clear ownership.

## Dispatch Packet

Every active-dispatch worker prompt should include:

- role: `explorer` or `worker`;
- objective: one concrete deliverable;
- ownership: exact modules, files, or responsibility slice;
- forbidden scope: files or behaviors the worker must not touch;
- coordination note: other Agents may be editing nearby code, so do not revert or overwrite unknown changes;
- Git surface: worktree path and branch when using a full task worktree;
- validation: narrow commands or evidence expected;
- handoff: required final report fields;
- memory: project-memory updates must be reported as proposals, not applied directly.

Workers must stop and report if they discover their write scope overlaps a hot file or another active worker's scope.

## Agent Responsibilities

Inside its own worktree, an Agent should:

- keep the task scope narrow;
- avoid unrelated refactors and broad formatting;
- check `git status --short --branch` before staging;
- stage only files that belong to the current task;
- run the narrowest useful validation;
- let the quality gate resolve the integration worktree's read-only `.venv` when `requirements.txt` is byte-identical; do not create a task `.venv` junction. A dependency mismatch is an explicit toolchain blocker until a compatible environment exists;
- reuse a passed result when HEAD, command, and all relevant inputs are unchanged; do not rerun the final selector plan before managed closeout;
- commit locally;
- self-review the current-task diff and merge readiness without waiting for the user to request review;
- merge its own task branch into local `main` when the local merge gates pass, then immediately close its claim and clean only its task-owned resources without waiting for post-merge validation; waiting for the user to request merge is not done;
- invoke `scripts/task_closeout.py` from root local `main` as the single final entry. If a valid manifest exists or integration contention returns one, pass `--manifest`; never rerun selector tests for the same binding.
- hand off to the main integration session only for large conflicts, cross-lane conflicts, hot-file/active-claim conflicts, release-sensitive work, unclear semantic conflicts, or explicit user-designated integration;
- never push to GitHub unless the user explicitly authorizes remote sync or publication;
- report the worktree path, branch, local commit SHA, changed files, pre-merge validation result, Launcher refresh need, project-memory update proposal, whether it self-merged, and the resulting cleanup or exact `cleanup pending` residue.

## Main Integration Responsibilities

The session currently closing work into `main` should:

- keep the main workspace clean before each merge;
- expect task-owning Agents to self-review and self-merge routine clean branches before asking for integration help;
- accept covering development claims in `active` or `ready`; queue-only `ready_for_merge` semantics remain for explicit handoff/integration lanes;
- let the pre-commit guard reuse the registered worktree owner or automatically create one narrow claim for the staged paths; a real parent/child path overlap fails closed, while unrelated paths continue in parallel;
- abort and restore `main` immediately if a blocked branch is accidentally merged and produces conflicts;
- merge one task branch at a time;
- hold `integration/main` only for final manifest verification and fast-forward merge. Managed closeout binds a 60-second, exact old/new SHA permit to that lease; the `reference-transaction` hook rejects every other `main` ref update. Bounded contention returns the existing manifest; the only validation-under-reservation exception is a one-use token issued after `stale_main`;
- confirm each fast-forward merge succeeded and the target contains the merged task tip, then immediately clean that task's local resources;
- handle semantic conflicts instead of letting Agents resolve them blindly;
- keep successful merges on local `main`; do not push `main` after merge-result inspection unless the user explicitly asks to sync GitHub or publish;
- serialize project-memory updates after code merges;
- clean every successfully merged task's claim, temporary content, legacy junction if present, worktree, and local branch immediately. The integration worktree's shared `.venv` is not task-owned and must never be removed by task cleanup.

When a branch cannot merge cleanly, leave the task in its own worktree and mark the claim `blocked` with the conflicting files and next action. Do not keep conflict markers, staged partial resolutions, or an in-progress merge in the main integration workspace. The owning Agent should rebase/merge against the current local `main` or create a new conflict-resolved commit, then re-enter the queue as a fresh `ready_for_merge` claim. Use `origin/main` only when the user explicitly asks to align with GitHub.

Small conflicts contained entirely inside the owning Agent's claimed files should normally be fixed by that Agent in its task worktree, followed by a fresh commit, validation, and local self-merge attempt. Main integration waits for or takes over only when the conflict is large, cross-lane, active-claim blocked, semantically ambiguous, release-sensitive, or explicitly assigned by the user.

## Cleanup

All review, testing, quality gates, mergeability checks, and acceptance evidence belong before merge. The moment `git merge --ff-only <task-branch>` succeeds, the task is absorbed by local `main` and cleanup must start immediately; do not retain task resources while waiting for post-merge validation.

If managed closeout reports `merged_cleanup_pending`, do not run validation or merge again. From root `main`, call `--cleanup-only --branch <task-branch>` so the idempotent safety checks can finish only the remaining task-owned cleanup.

First remove only disposable files/directories, debug output, scratch artifacts, and background processes/listeners that are provably owned by the merged task. Use exact paths and exact process ownership; do not scan broadly or infer ownership. Then release only the task's claim, remove any legacy task-owned junction when present, and remove its clean worktree and merged local branch. Never create a junction merely to satisfy validation:

```powershell
cd <project-root>
git worktree remove .worktrees/<task-slug>
git branch -d codex/<task-slug>
git worktree prune
```

After cleanup, inspect Git/worktree/registry state only to prove the merge was absorbed and the task resources are gone; this inspection is not product validation. If any safe local cleanup fails, report `cleanup pending` with the exact residue and reason. Do not force deletion or reinterpret the successfully completed merge as unmerged.

Delete remote task branches only after the user explicitly authorizes GitHub cleanup:

```powershell
git push origin --delete codex/<task-slug>
```

Do not auto-delete a worktree that is unmerged, dirty, conflicted, possibly still used by an active Agent, or contains content whose ownership is unclear. If a dirty worktree must be discarded, first save status, unstaged diff, staged diff, and untracked files as a backup.

Do not retry a blocked merge directly from `main`. If a blocked worktree needs another integration attempt, first confirm its claim has been updated back to `ready_for_merge` with a new commit or explicit conflict-resolution note based on the current local `main`. Use `origin/main` only when the user explicitly asks to align with GitHub.

## Shared Files

Avoid concurrent edits to shared hot files unless the current main integration session has explicitly serialized the work:

- `agent.py`
- `core/web/app.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`
- inventory `activePaths.memory/**`
- Git common-dir coordination registry

Project memory is external single-writer state. Parallel Agents should write append-only memory proposals or report lane/update payloads; the current memory-sync step applies them after code merges. Live claim and territory ownership stays in the Git common-dir registry, not project memory.

## Communication Channels

Use these channels in order of authority:

1. Git branch, commit, diff, and test output.
2. Structured handoff report.
3. Project-memory proposal queue for memory updates.
4. Agent inbox, thread message, or runtime private message for notifications only.

Inbox/thread messages are not authoritative for code state or final decisions. They should not replace commits, diffs, validation evidence, registry state, or runtime logs.

## Disk vs Git worktree hygiene

Periodically reconcile **registered** worktrees with **disk** directories under `.worktrees/`:

```powershell
cd <project-root>
git worktree list
Get-ChildItem .worktrees -Directory | Select-Object -ExpandProperty Name
```

| 信号 | 含义 | 动作 |
| --- | --- | --- |
| 目录存在，`git worktree list` 无对应项 | 磁盘 orphan（常见：分支已删、merge 后未清目录） | **只读**标记；不删 dirty / 未验证内容 |
| `git worktree list` 有项，磁盘无目录 | 注册 stale | `git worktree prune`（安全） |
| orphan + 无 `codex/*` 分支 + 无 claim | 候选清理 | 确认目录内无未提交 WIP → 删目录 |
| orphan + 未知 WIP | 阻塞 | 保留；报告精确路径，等 owner handoff |

**2026-08-17 盘点（示例）：** 注册 4（含本任务）· 磁盘 15 · orphan 11（如 `session-list-bulk-remove`、`tray-restart-launcher-unified` 等，均无对应 `codex/*` 分支）→ **全部保留**，待 owner 确认无 WIP 后再清。

## Handoff Report

Every worker completion report should include:

```text
Task:
Worktree:
Branch:
Commit:
Changed files:
Validation:
Launcher refresh:
Project-memory proposal:
Risks / blockers:
Next recommended step:
```

If the worker did not commit, it must explicitly say why and list dirty files.

## User Involvement

The user should normally provide goals, not worktree instructions. Ask the user only for task authorization, product or architecture decisions, high-risk discard/overwrite approval, and Launcher active-work judgment.
