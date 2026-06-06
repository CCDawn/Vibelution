# Multi-Agent Worktree Collaboration

This document defines the default collaboration protocol for multiple Agents working on Vibelution in parallel.

## Roles

- `C:\Users\17533\Desktop\Vibelution` is the coordinator workspace. Use it for syncing `main`, merging, final validation, project-memory serialization, and publishing.
- Development Agents use task-specific worktrees under `C:\Users\17533\Desktop\Vibelution-worktrees\`.
- Each active task gets one worktree and one branch. Do not reuse an old task worktree for a new goal.

## Starting A Task

Create a task branch from the latest `origin/main`:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git fetch origin
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug> -b codex/<task-slug> origin/main
```

The task slug should describe one goal, for example `fix-ci-timezone-test` or `llm-protocol-routing`.

## Agent Responsibilities

Inside its own worktree, an Agent should:

- keep the task scope narrow;
- avoid unrelated refactors and broad formatting;
- check `git status --short --branch` before staging;
- stage only files that belong to the current task;
- run the narrowest useful validation;
- commit and push its task branch;
- report the worktree path, branch, commit SHA, changed files, validation result, Launcher refresh need, and project-memory update proposal.

## Coordinator Responsibilities

The coordinator should:

- keep the main workspace clean before each merge;
- merge one task branch at a time;
- run targeted validation after each merge;
- handle semantic conflicts instead of letting Agents resolve them blindly;
- push `main` after successful validation;
- serialize project-memory updates after code merges;
- clean merged task worktrees.

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

## User Involvement

The user should normally provide goals, not worktree instructions. Ask the user only for task authorization, product or architecture decisions, high-risk discard/overwrite approval, and Launcher active-work judgment.
