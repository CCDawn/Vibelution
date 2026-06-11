# Vibelution Development Standard

> Canonical project development standard for Vibelution.
> Keep this file at the repository root. Do not move, rename, or generate it from another source unless `AGENTS.md` and project memory are updated in the same round.

This standard is written for every in-project Agent working on Vibelution. It defines how development work is scoped, diagnosed, implemented, validated, refreshed, committed, merged, remembered, and reported.

`AGENTS.md` is the local short entry contract and red-line index when present. This file is the tracked full operating standard.

## 0. Source Hierarchy

- This file, `DEVELOPMENT_STANDARD.md`, is the canonical tracked development standard.
- Root `AGENTS.md` is the local Agent entrypoint and red-line index when present. It is intentionally local in this workspace and may be ignored by Git.
- `docs/agents/worktree-collaboration.md` is the detailed multi-Agent worktree protocol.
- `CONTEXT.md` defines domain vocabulary. Use it for product and architecture language.
- `docs/adr/` records major design decisions and why they exist.
- `.docs/project-memory/` is the structured current-state memory and Agent territory registry.

If a task worktree does not contain `AGENTS.md`, read this file directly before development. If these sources conflict, do not silently pick one. Stop, identify the conflict, and update the relevant source in the same governance round.

## 1. Project Identity

- Treat Vibelution as a local-first, self-evolving AI Agent system, not a generic web app or one-off script.
- The main project objective is stable self-improvement: runtime stability, evolution efficiency, observable evidence, rollback credibility, and UI/agent coherence.
- Use Chinese for natural-language reasoning and user-facing replies by default. Code, protocol keys, file paths, commands, and raw errors may remain in English.
- Follow evidence before theory: reproduce, observe, inspect, then infer.
- Do not treat passing validation as a new failure to diagnose.
- Once a fix, validation, commit, or transaction-close cycle is genuinely complete, stop cleanly instead of inventing a side quest.

## 2. Task Intake And BRT Gate

Before any non-trivial code or behavior change, use the local BRT skill:

`C:\Users\17533\.codex\skills\ccdawn-brt\SKILL.md`

Use BRT when a request involves expected behavior, defaults, restore/memory behavior, permissions, state transitions, edge cases, completion criteria, safety gates, promotion/apply/rollback workflows, persistence, public API behavior, agent workflow, or runtime lifecycle.

The BRT checkpoint must lock:

- behavior to deliver;
- observed symptom and suspected or confirmed root cause when the task is a fix;
- scope boundaries;
- failure and boundary paths;
- review perspectives;
- test or validation anchors;
- allowed actions;
- completion report shape.

You may skip the full BRT flow only for obvious typos, mechanical refactors, dependency bumps, or tiny internal helpers with no behavior ambiguity. If skipped, say why the fast path is safe.

Do not turn broad words such as `all`, `automatic`, `optimize`, `unified`, `smart`, `closed loop`, or `memory` into implementation without translating them into observable behavior first.

## 3. Root-Cause Planning

Fixes, optimizations, refactors, and lifecycle changes must aim at the root cause, not merely hide the symptom.

Before proposing or implementing a fix, state:

- the observed symptom;
- the suspected or confirmed root cause;
- the evidence connecting symptom and cause;
- the mechanism that will prevent recurrence;
- the closure condition proving the original failure mode is structurally prevented.

If the true root cause is unknown, plan diagnosis first. Retrying, delaying, adding guards, adding fallback branches, changing wording, or adding cleanup scripts is mitigation unless it proves the failure mechanism cannot recur.

Temporary mitigation is allowed only when explicitly labeled as mitigation, with the remaining evidence needed for a permanent fix.

## 4. Log-First Diagnosis

For bugs, regressions, stalls, runtime mismatches, failed commands, unexpected behavior, bad delegation, repeated tool loops, or broken convergence, start from the newest relevant lifecycle log package under:

`logs/runtime_scenes/`

Use the newest package matching the affected run or workbench lifecycle as the primary evidence unit. Start from its manifest or package index, then inspect:

- `timeline.jsonl`;
- `lifecycle.jsonl`;
- child logs under `raw/`, `conversations/`, `agent/`, and `artifacts/`;
- fallback evidence under `logs/`;
- `log_info/conversation_*.jsonl`;
- matching `log_info/debug_*.log`;
- adjacent validation outputs.

Use older packages only as explicitly labeled historical comparison.

If no suitable package exists, treat missing runtime evidence as part of the bug. Add logging at the actual error site, branch, state transition, or failure path so the next failing run is diagnosable.

Good logs should let a future Agent reconstruct:

- goal;
- delegation trigger;
- tool sequence;
- blocker sequence;
- validation outcomes;
- stop or continue reason;
- why the round converged or failed to converge.

Do not log secrets, full prompts, large diffs, full file contents, or unbounded model/tool output. Prefer stable IDs, timestamps, statuses, counts, path references, summaries, error types, and bounded context.

## 5. Logging And Test Coupling

Every new feature or user-visible behavior change requires an explicit logging decision and a matching test decision in the same round.

Add or update runtime scene logging when a change affects:

- runtime behavior;
- state transitions;
- background work;
- agent/tool execution;
- persistence;
- reset/delete behavior;
- configuration;
- Git actions;
- supervision;
- self-evolution;
- Gym promotion;
- error handling.

New logs should normally write into the current lifecycle package under `logs/runtime_scenes/` through existing helpers.

Each new feature should add or update the smallest useful automated tests protecting the behavior and logging contract. Cover the primary success path and at least one important failure or boundary path.

If no new logging or no new tests are warranted, state that explicitly in the final report with the reason.

## 6. Worktree And Scope Discipline

The root workspace:

`C:\Users\17533\Desktop\Vibelution`

is the local `main` integration workspace. It is for syncing, merging, final validation, project-memory serialization, and user-authorized publication. Ordinary development belongs in task worktrees.

Default task worktree path:

`C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>`

Default task branch:

`codex/<task-slug>`

Default branch base is the current local `main`, not `origin/main`. Use `origin/main` only when the user explicitly asks to align with GitHub.

Typical start:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug> -b codex/<task-slug> main
```

Before editing in a multi-session project, use the project memory guard:

```powershell
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" status
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" recommend --scope "<requested-scope>" --task-type "<task-type>" --summary "<task summary>"
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" preflight --worktree "<task-worktree>"
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" claim --agent-id "<agent-id>" --session-id "<session-id>" --lane "<lane-id>" --task "<task title>" --scope "<write-scope>" --forbidden-scope "<forbidden-scope>" --worktree "<task-worktree>" --branch "<task-branch>" --validation "<validation command>"
```

If a scope hits an active claim or hotspot, stop unless you have explicit authorization and record the claim with intentional `--force`.

One Agent should bind to one active task worktree at a time. Do not reuse an old task worktree for a new goal.

## 7. Shared Hot Files

Treat these as shared hot files and edit them only with a narrow scope and explicit claim:

- `AGENTS.md`;
- `DEVELOPMENT_STANDARD.md`;
- `.docs/project-memory/**`;
- `PROJECT_MEMORY.html`;
- `agent.py`;
- `core/web/app.py`;
- `core/web/services/session_service.py`;
- `core/web/services/runtime_service.py`;
- `web/src/api/types.ts`;
- `web/src/i18n/dictionary.ts`;
- `tests/test_web_app.py`.

Do not perform broad formatting, opportunistic cleanup, renaming, or splitting in hot files unless the task is specifically scoped to that work.

## 8. Implementation Boundaries

- Prefer project-native tools and structured APIs over broad shell commands.
- Use focused tests and small validation loops before widening scope.
- Do not repeat the same blocked tool pattern in the same round.
- Keep Windows shell behavior in mind. Avoid Unix-only habits that add noise.
- On Windows PowerShell, do not pipe here-strings directly into `python -`; use `python -c "exec('''...''')"` or create a temporary UTF-8 no-BOM `.py` file.
- When building keyword-triggered runtime guards or prompt relevance checks, avoid raw substring matching for English tokens on Windows paths; use token-aware matching.
- Chat mode user input must enter the LLM payload as `role=user` or equivalent user-message shape. Do not wrap chat user input in `SystemMessage`.
- When an LLM call fails unexpectedly, inspect the safe message-role summary first: `system`, `user`, `assistant`, `tool`.
- On Windows, do not assume `CREATE_NO_WINDOW` on `.venv\Scripts\python.exe` is enough for long-lived services. Verify child process trees and visible windows; prefer service-specific `pythonw.exe` when no console should appear.

## 9. Frontend Standards

Frontend changes under `web/` should be TypeScript by default:

- new pages: `.tsx`;
- route modules: `.tsx`;
- components: `.tsx`;
- hooks and helpers: `.ts`;
- API clients and DTOs: `.ts`;
- layout tests: `.ts` or `.tsx`.

Define core domain and display data structures before wiring UI behavior. API request and response payloads consumed by the frontend must have TypeScript types. Prefer shared DTOs in `web/src/api/types.ts` when the shape is cross-route or API-level.

Avoid untyped `any`. At uncertain JSON boundaries, use `unknown` or `Record<string, unknown>`, then narrow before display, decisions, or mutation.

Existing JavaScript files may remain temporarily. Migrate only when touched for related work.

Python, CLI, harness, and evaluation execution code remain Python unless there is a separate architectural reason to change them.

Frontend TypeScript changes that affect compiled application code or API/type contracts require the narrowest relevant tests plus:

```powershell
npm --prefix web run build
```

For frontend visual work, check the real UI after each meaningful visual change through the browser, screenshot, or user-provided screenshot. If browser tools are blocked, state that and use user screenshots as primary visual evidence.

Vibelution workbench surfaces should feel like dense operational consoles: compact tables, spec grids, light boundaries, grouped headings, and metadata hierarchy before decorative cards.

## 10. Bun Usage

Bun may be used only as an auxiliary local frontend runner under `web/`.

Preferred commands from `C:\Users\17533\Desktop\Vibelution\web`:

```powershell
bun run bun:dev
bun run bun:test
bun run bun:build
```

Bun is not the canonical package manager or release build path. Do not replace `npm`, `package-lock.json`, or Launcher npm-based build/restart flow unless a separate migration plan is approved and validated.

Do not add or commit `bun.lock`, `bun.lockb`, or Bun-generated install artifacts unless the task is specifically to migrate dependency management.

When reporting Bun validation, distinguish Bun runtime failures from TypeScript, Vitest, or Vite failures that also reproduce through npm.

## 11. Test Strategy

Choose the lowest test layer that proves behavior:

- unit tests for isolated parsing, formatting, policy, state decisions, and helper logic;
- integration tests for persistence, CLI flows, filesystem behavior, multi-module cooperation, and agent workflows;
- end-to-end tests for browser/terminal flows or behavior visible only through the whole product chain;
- manual validation for visual or exploratory behavior that is not yet practical to automate.

Use existing test guidance in `tests/README.md`.

Common commands:

```powershell
pytest tests/ -v
pytest tests/test_<module>.py -v
pytest tests/test_<module>.py -v -k "<keyword>"
python tests/test_runner.py
python tests/test_runner.py --fast
python tests/simulate_lifecycle.py
```

After adding or modifying tools, run prompt debugger coverage:

```powershell
python tests/prompt_debugger.py --tool <tool_name>
python tests/prompt_debugger.py --suite
```

When validation is blocked by unrelated failures, report the exact command, the failure boundary, and why it is outside the current scope. Do not call a round fully validated if its relevant tests did not run.

## 12. Launcher-Gated Runtime Refresh

Runtime refresh must go through Launcher by default.

Any Agent changing running UI code, backend code, launcher lifecycle code, runtime-manager behavior, web API contracts, or frontend build inputs must treat Launcher refresh as part of the definition of done unless the user explicitly says to skip it.

Before any Launcher restart, check whether Vibelution has active work using Launcher status or lifecycle evidence when available.

If any chat turn, group round, evolution run, supervised run, worktree task, or other project task is active, Launcher restart is forbidden by default. Do not ask for force-confirmation, do not pass `confirmedActiveWork`, and do not kill processes to bypass the guard. Report:

`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`

Preferred refresh paths:

- `trigger_self_restart_tool` with the current `sessionId` for Agent-driven code refresh;
- Launcher UI `重启` / `Restart`;
- Windows adapter:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\17533\Desktop\Vibelution\scripts\vibelution_launcher.ps1" -Action restart
```

- macOS/Linux headless adapter:

```bash
python scripts/vibelution_launcher.py --action restart --no-browser
```

The Launcher control plane and managed Workbench are separate. `-Action launcher` opens only `http://127.0.0.1:8765/launcher`. Workbench remains `http://127.0.0.1:8000` unless config overrides apply.

Stopping Workbench must preserve Launcher control unless the user explicitly asks to shut down Launcher itself.

Do not use ad hoc `uvicorn`, `scripts/web_workbench.py`, `npm run dev`, direct browser relaunch, or manual process killing as the normal way to apply code updates. These are allowed only for focused diagnostics, one-off test isolation, or Launcher debugging.

Docs-only, tests-only, memory-only, and rule-only changes may skip Launcher refresh. State why.

## 13. Git Submission

Before staging or committing, inspect:

```powershell
git status --short --branch
```

Never use `git add .`. Stage only files belonging to the current task.

Do not revert unrelated user or Agent changes. If unrelated changes exist in files you must touch, read carefully and work with them instead of overwriting.

Treat `C:\Users\17533\Documents\Vibelution\config\config.toml` as the operator config source of truth. Root `config.toml` / `config.example.toml` are legacy/template inputs for first-run migration only and should not be used as the active runtime config surface during integration.

Do not commit:

- local configuration with secrets;
- runtime artifacts;
- tool state;
- temporary files;
- generated lockfiles not in task scope.

Commit messages should be concise, scoped, and behavior-oriented. Prefer prefixes such as:

- `fix: ...`;
- `feat: ...`;
- `refactor: ...`;
- `test: ...`;
- `docs: ...`;
- `chore: ...`.

After implementation and validation in a task worktree, mark the claim ready:

```powershell
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" ready --claim-id "<claim-id>" --commit "<sha>" --changed-file "<file>" --validation "<result>"
```

The main integration session then merges or cherry-picks into local `main`, validates, closes the claim, and cleans the worktree.

## 14. Remote GitHub Sync

Local `main` is the default integration fact source. GitHub `origin/main` is a remote backup/publication target unless the user explicitly says to sync, push, publish, create a PR, or delete remote branches.

Allowed by default:

```powershell
git fetch origin
```

Not allowed by default:

- `git push`;
- remote branch deletion;
- PR creation;
- treating `origin/main` as authority to reset local `main`.

When GitHub HTTPS 443 is unreachable, prefer checking SSH 22:

```powershell
Test-NetConnection github.com -Port 22
git remote -v
git config --show-origin --get-regexp "^(core\.sshCommand|remote\.origin\.)"
```

Known local history: `C:\Users\17533\.ssh\id_ed25519` can authenticate to `git@github.com:CCDawn/Vibelution.git` but is read-only as a deploy key. Do not repeatedly push with that identity.

Only with explicit user authorization for GitHub sync/publication, use the write key:

```powershell
$env:GIT_SSH_COMMAND='ssh -i C:\Users\17533\.ssh\vibelution_write_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
git push origin main
```

Use `--force-with-lease` only when the user explicitly confirms remote overwrite and the local baseline is correct.

## 15. Version Discipline

Make a version-impact judgment whenever closing a meaningful development round, reviewing Git changes, preparing a commit, submitting/pushing work, publishing, or draining the main merge queue.

Ordinary task Agents report version impact but normally do not edit version files. Version files are release hot spots and should be changed only by the current mainline integration/release steward unless the user explicitly authorizes a scoped release task.

Canonical version sources:

- root `VERSION`;
- `core/version.py` reads root `VERSION`;
- `web/package.json`;
- `web/package-lock.json`;
- top entry of `CHANGELOG.md`.

Release bump commit must update all canonical mirrors together. If any cannot be updated, stop and report the release as blocked.

Version judgment is release-package based:

- `none`: docs-only, tests-only, memory-only, internal cleanup, narrow refactor, or no user-visible/release contract change;
- `patch`: bug fixes, small polish, logging clarity, localized UX/message improvement, non-contract internal correction;
- `minor`: compatible new or expanded capability, new workflow/control surface/API DTO/lifecycle state/runtime guarantee/supervision behavior/logging diagnosis capability, or a coherent bundle of related patch-level changes;
- `major`: breaking API/data/operation contract, required migration, deleted/renamed core capability, changed safety/default behavior, changed rollback guarantee, or major lifecycle contract change.

Vibelution is in the stable `1.x` line. Use SemVer strictly.

Task handoff must include version bump recommendation, capability domain, user-visible impact, compatibility impact, validation evidence, and whether it should be grouped with pending changes.

## 16. Mainline Integration

The main integration session is responsible for:

- keeping local `main` clean before each merge;
- reviewing claim status and write scopes;
- merging only `ready_for_merge` claims;
- merging one task at a time;
- running targeted validation after each merge;
- handling conflicts or returning them to the owning worktree;
- closing claims with `finish`;
- cleaning successfully merged worktrees;
- serializing project-memory updates;
- avoiding remote push unless the user authorizes it.

If a branch cannot merge cleanly, leave it in its own worktree and mark it blocked with the conflicting files and next action.

Do not keep conflict markers, staged partial resolutions, or an in-progress merge in the main integration workspace.

If a blocked worktree needs another integration attempt, the owning Agent must rebase/merge against current local `main` or commit a conflict-resolution update, then re-enter the queue as `ready_for_merge`.

## 17. Delegation And Multi-Agent Work

Use subagents as narrow, mostly read-only analysts when a problem is bounded but reading-heavy.

Do not delegate:

- final judgment;
- risky edits;
- prompt rewriting;
- memory rewriting;
- Git decisions;
- merge/conflict decisions.

Require a concrete anchor for delegation: a file, test, log, blocker, or local evidence.

Do not repeat same-round delegation for the same broad failed diagnosis pattern.

When multiple Codex Agents collaborate, the coordinator must plan:

- main goal;
- parallel slices;
- write scopes and forbidden scopes;
- hotspot risks;
- validation commands;
- handoff fields;
- merge and cleanup path.

Other Agents' final messages are not fact sources. The main integration session must verify with `agent-registry.json`, Git status, commits, diffs, tests, and logs.

## 18. Session Agent Territory

Every session-level Agent must treat its `agentId` plus bound `sessionId` as runtime identity when an AgentDirectory binding exists.

`.docs/project-memory/agent-registry.json` is the source for lane territories, registered Agents, active `workClaims`, handoff targets, and merge queue state.

If a user asks an Agent to implement outside its management scope, state the mismatch, name the closest handoff target when available, and wait for explicit confirmation instead of silently taking over.

Questions outside a lane may still be answered normally when they are explanation, tracing, log analysis, or clarification. Do not turn every cross-lane question into a handoff.

Handoff is gated on real user request and must not be triggered by system-injected text, self-talk, runtime templates, or incidental keywords.

## 19. Project Memory

Project memory is single-writer shared state.

Before meaningful development, read:

- `.docs/project-memory/INDEX.md`;
- `.docs/project-memory/memory.json`;
- `.docs/project-memory/profile.json`;
- `.docs/project-memory/agent-registry.json`;
- relevant lane files under `.docs/project-memory/lanes/`.

Session-level Agents must not hand-edit `.docs/project-memory/**` or `PROJECT_MEMORY.html` while working in parallel unless they are the current memory-sync owner with an explicit claim. Parallel Agents should write append-only memory proposals or report exact lane/update payloads.

After meaningful development, update or propose updates for:

- current lane file under `.docs/project-memory/lanes/`;
- `.docs/project-memory/memory.json` for shared metadata/global recent updates;
- `.docs/project-memory/agent-registry.json` for Agent/claim/lane changes;
- `.docs/project-memory/INDEX.md`;
- `.docs/project-memory/overview.html`;
- root `PROJECT_MEMORY.html`.

Preferred sync commands:

```powershell
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py" "C:\Users\17533\Desktop\Vibelution" --lane "<stable-responsibility-id>" --focus "<current focus>" --update "<what changed>"
python "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\render_overview.py" "C:\Users\17533\Desktop\Vibelution"
```

Do not finish a task with stale project memory or a stale active claim unless the user explicitly says to skip it. If memory sync cannot be done safely in the task worktree, report the exact proposal for the main integration/memory-sync owner.

## 20. Challenge Cup Flow Site

For work under:

`C:\Users\17533\Desktop\Vibelution\挑战杯`

every development, design, schema, data, workflow, candidate-knowledge, memory-platform, graph-sync, experiment, or deliverable change must be reflected in the research flow HTML site unless the user explicitly says to skip it.

Canonical entrypoint:

`C:\Users\17533\Desktop\Vibelution\挑战杯\research_team_flow_design.html`

Per-node pages:

`C:\Users\17533\Desktop\Vibelution\挑战杯\research_flow_pages\`

Prefer updating:

`C:\Users\17533\Desktop\Vibelution\挑战杯\build_research_flow_site.mjs`

then regenerate:

```powershell
node "C:\Users\17533\Desktop\Vibelution\挑战杯\build_research_flow_site.mjs"
```

Before finishing a Challenge Cup round, verify HTML links still resolve and report whether the flow HTML was updated.

## 21. Final Reports

Final reports should be net-new first. Do not repeat stable background facts unless they block the current task, changed during the round, or the user asks.

For feature or behavior changes, compactly cover:

- what changed;
- logging added or deliberately not added;
- tests/checks run;
- recommended next step.

For task worktree handoff, include:

- claimId;
- branch;
- worktree path;
- commit SHA;
- changed files;
- validation commands and results;
- Launcher refresh need/result;
- project memory update status or proposal;
- version impact recommendation.

If a task is not ready to commit, merge, refresh, or close, say so clearly.

Do not over-repeat legacy root `config.toml` / `config.example.toml` state unless staging, migration, validation, or config diagnosis depends on it. Prefer reporting the resolved global config path instead.

## 22. Development Round Done Criteria

A development round is not done until:

- behavior and scope are clear;
- relevant logs or evidence were inspected for bugs/runtime issues;
- implementation stayed within claimed scope;
- logging decision is explicit;
- test decision is explicit;
- relevant tests/checks ran or blockers are reported;
- Launcher refresh decision is explicit;
- Git status was reviewed;
- changes are committed or explicitly marked not ready;
- claim is `ready_for_merge`, `merged_to_main`, `local_applied`, `blocked`, or `cancelled`;
- project memory was updated or an exact update proposal was handed off;
- version impact was judged;
- final report states remaining risk and next action.

Docs-only/rule-only rounds may skip Launcher refresh and version bump when no runtime behavior or release package changes.
