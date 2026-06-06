# Multi-Agent Worktree Collaboration

This document defines the default collaboration protocol for multiple Codex sessions or sub-agents working on Vibelution in parallel.

## Roles

- `C:\Users\17533\Desktop\Vibelution` is the coordinator workspace. Use it for syncing `main`, sequencing merges, final validation, project-memory serialization, and publishing.
- Development Agents use task-specific worktrees under `C:\Users\17533\Desktop\Vibelution-worktrees\`.
- Each active development task gets one worktree and one branch. Do not reuse an old task worktree for a new goal.
- The user should normally provide goals and decisions, not per-worker Git instructions.

## Active Dispatch

The coordinator may actively dispatch work to other Codex sessions or sub-agents only when the user has asked for parallel work, delegation, or coordinator-driven task assignment.

Before dispatching, the coordinator must:

- state the main goal and the immediate local critical path;
- split only independent side tasks or bounded implementation slices;
- assign a disjoint write scope to every worker;
- keep hot shared files under coordinator sequencing unless one worker is explicitly made the single owner;
- decide what the coordinator will do locally while workers run;
- avoid delegating work that blocks the coordinator's very next action.

Use read-only explorer agents for narrow codebase questions. Use worker agents only for concrete implementation, verification, or repair tasks with clear ownership.

## Starting A Worktree Task

Create a task branch from the latest `origin/main`:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git fetch origin
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug> -b codex/<task-slug> origin/main
```

The task slug should describe one goal, for example `fix-ci-timezone-test` or `llm-protocol-routing`.

## Dispatch Packet

Every active-dispatch worker prompt should include:

- role: `explorer` or `worker`;
- objective: one concrete deliverable;
- ownership: exact modules, files, or responsibility slice;
- forbidden scope: files or behaviors the worker must not touch;
- coordination note: other agents may be editing nearby code, so do not revert or overwrite unknown changes;
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
- commit and push its task branch when the task is complete;
- report the worktree path, branch, commit SHA, changed files, validation result, Launcher refresh need, and project-memory update proposal.

## Coordinator Responsibilities

The coordinator should:

- keep the main workspace clean before each merge;
- dispatch only independent worker tasks and keep immediate blockers local;
- monitor worker results through structured handoff, commit SHA, and diff;
- review worker changes before integration;
- merge one task branch at a time;
- run targeted validation after each merge;
- handle semantic conflicts instead of letting workers resolve them blindly;
- push `main` after successful validation;
- serialize project-memory updates after code merges;
- close or clean completed worker agents/worktrees when no longer needed.

Do not treat worker final messages as the source of truth. Code facts come from Git status, commits, diffs, tests, and logs.

## Communication Channels

Use these channels in order of authority:

1. Git branch, commit, diff, and test output.
2. Structured handoff report.
3. Project-memory proposal queue for memory updates.
4. Agent inbox, thread message, or runtime private message for notifications only.

Inbox/thread messages are not authoritative for code state or final decisions. They should not replace commits, diffs, or validation evidence.

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

## Shared Files

Avoid concurrent edits to shared hot files unless the coordinator explicitly orders the work:

- `agent.py`
- `core/web/app.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `tests/test_web_app.py`
- `.docs/project-memory/*`
- `PROJECT_MEMORY.html`

Project memory is single-writer state. Parallel Agents should write append-only memory proposals or report lane/update payloads; the coordinator applies them after code merges.

## Cleanup

After a task has been merged into `main`, validated, pushed, and confirmed to have no uncommitted work, clean it up:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git worktree remove C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>
git branch -d codex/<task-slug>
git worktree prune
```

Delete the remote task branch only when it is no longer needed:

```powershell
git push origin --delete codex/<task-slug>
```

Do not auto-delete a worktree that is unmerged, dirty, failing validation, conflicted, or possibly still used by an active Agent. If a dirty worktree must be discarded, first save status, unstaged diff, staged diff, and untracked files as a backup.

## Failure Handling

- If a worker times out, the coordinator may continue local work and later resume or close the worker.
- If a worker changes out-of-scope files, do not merge blindly; ask it to produce a scoped correction or discard that branch after preserving evidence.
- If two workers conflict semantically, the coordinator chooses merge order and may request one worker to rebase or submit a follow-up branch.
- If validation fails after merge, stop the merge sequence and diagnose the latest failing evidence before merging more branches.
