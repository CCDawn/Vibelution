# Multi-Agent Worktree Collaboration

This document defines the default collaboration protocol for multiple Agents working on Vibelution in parallel.

## Work Surfaces

- `C:\Users\17533\Desktop\Vibelution` is the durable local `main` development/integration workspace. Keep this path checked out on branch `main`; use it for local syncing, merging, final validation, project-memory serialization, and publishing only after the user explicitly authorizes a GitHub sync/release.
- If `C:\Users\17533\Desktop\Vibelution` is found on a non-main branch, preserve or migrate that work into `C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>` or a named stash, then restore the root path to `main` before continuing normal development or integration.
- Development Agents use task-specific worktrees under `C:\Users\17533\Desktop\Vibelution-worktrees\`.
- If that external worktree root is unavailable, use `.claude/worktrees\<task-slug>` or another explicit task worktree path and record the actual path in preflight/claim evidence.
- Each active task gets one worktree and one branch. Do not reuse an old task worktree for a new goal.

## Starting A Task

Create a task branch from the current local `main`:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug> -b codex/<task-slug> main
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
- commit locally; do not push to GitHub unless the user explicitly authorizes remote sync or publication;
- report the worktree path, branch, local commit SHA, changed files, validation result, Launcher refresh need, and project-memory update proposal.

## Main Integration Responsibilities

The session currently closing work into `main` should:

- keep the main workspace clean before each merge;
- refuse to merge any claim that is not in `ready_for_merge`;
- abort and restore `main` immediately if a blocked branch is accidentally merged and produces conflicts;
- merge one task branch at a time;
- run targeted validation after each merge;
- handle semantic conflicts instead of letting Agents resolve them blindly;
- keep successful merges on local `main`; do not push `main` after validation unless the user explicitly asks to sync GitHub or publish;
- serialize project-memory updates after code merges;
- clean merged task worktrees.

When a branch cannot merge cleanly, leave the task in its own worktree and mark the claim `blocked` with the conflicting files and next action. Do not keep conflict markers, staged partial resolutions, or an in-progress merge in the main integration workspace. The owning Agent should rebase/merge against the current local `main` or create a new conflict-resolved commit, then re-enter the queue as a fresh `ready_for_merge` claim. Use `origin/main` only when the user explicitly asks to align with GitHub.

## Cleanup

After a task has been merged into local `main`, validated, and confirmed to have no uncommitted work, clean it up:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git worktree remove C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>
git branch -d codex/<task-slug>
git worktree prune
```

Delete remote task branches only after the user explicitly authorizes GitHub cleanup:

```powershell
git push origin --delete codex/<task-slug>
```

Do not auto-delete a worktree that is unmerged, dirty, failing validation, conflicted, or possibly still used by an active Agent. If a dirty worktree must be discarded, first save status, unstaged diff, staged diff, and untracked files as a backup.

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
- `.docs/project-memory/*`
- `PROJECT_MEMORY.html`

Project memory is single-writer state. Parallel Agents should write append-only memory proposals or report lane/update payloads; the current memory-sync step applies them after code merges.

## Communication Channels

Use these channels in order of authority:

1. Git branch, commit, diff, and test output.
2. Structured handoff report.
3. Project-memory proposal queue for memory updates.
4. Agent inbox, thread message, or runtime private message for notifications only.

Inbox/thread messages are not authoritative for code state or final decisions. They should not replace commits, diffs, validation evidence, registry state, or runtime logs.

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
