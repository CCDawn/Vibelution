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
- On Windows, terminal-popup fixes must prove the full process chain, not just the first launcher layer. Inspect parent and child process command lines, visible window titles, launcher state, runtime-manager events, and any short-lived terminal hosts before deciding the root cause.
- Do not overfit terminal-popup diagnosis to the interpreter name. `pythonw.exe` can still be the correct no-console parent; visible Git, cmd, Windows Terminal, or OpenConsole windows may come from later runtime polling code. Verify the product-owned recursive process tree instead of global process churn from Codex, IDEs, or shell tooling.
- Avoid background runtime commands that depend on PATH wrappers when they can run from a no-console service or frontend polling path. Resolve the real executable, capture output, and apply the shared no-window startup policy instead of relying on a shell, `.cmd`, or wrapper binary.
- Git commands called by runtime services, UI polling, memory overview, restart backup, or evolution harnesses must use the shared Git process helper. Do not add new `subprocess.run(["git", ...])` runtime paths; Git for Windows may resolve to `cmd\git.exe` and surface visible terminals from background code.
- No-console Launcher entrypoints must not use `taskkill.exe` as the normal stale-process cleanup path. `taskkill.exe` can create its own console host even when called from `pythonw.exe`; prefer in-process `psutil`/WinAPI termination with focused tests that assert no `taskkill` subprocess is invoked.
- Source-bound CLI terminal attachment must not auto-resume a stale terminal state during page restoration or Launcher startup. Return the stale state for the UI to display, and require an explicit user start/reconnect action before spawning a new CLI process.
- Windows `.cmd` shim handling must inspect the real shim target. If the shim launches a native `.exe`, execute that `.exe` directly; only wrap JavaScript/no-extension CLI targets with `node.exe`.
- Launcher control-surface freshness signatures must include every source module that can run startup, polling, developer-mode, shutdown, or lifecycle logic behind the long-lived Launcher backend. When a terminal-popup or lifecycle fix touches such a module, add a regression test proving that editing that source changes the stored control signature; otherwise a stale backend can keep executing the old popup-producing code after the source fix is merged.
- Terminal-popup regressions need automated locks, not only documented lessons: add source or AST tests that forbid naked runtime Git subprocess paths, and add behavior tests for the no-console helper or source-signature freshness path that closed the bug.
- When a terminal-popup investigation finds interactive Git editor chains such as `git merge --continue -> sh -> vim .git/COMMIT_EDITMSG`, first verify repository state (`MERGE_HEAD`, `git status`) before killing anything. Treat stale editor processes as residual cleanup only after confirming no active merge or commit operation exists.

### 8.1 Rust Accelerator Boundary

Python remains the primary runtime for Vibelution business logic, Agent orchestration, web APIs, tests, and evolution workflows. Rust is allowed only as a bounded accelerator layer, not as a replacement for product semantics or the main Agent runtime.

Rust may be introduced only when all of these conditions are true:

- the task is deterministic and side-effect bounded;
- the interface is stable and callable through JSON, CLI, WASM, or a narrow FFI adapter;
- a Python fallback or compatibility path exists unless a separate architecture decision explicitly removes it;
- focused parity tests compare Rust output against Python expectations or stored fixtures;
- runtime logs, benchmarks, or SQLite/file forensics show a real bottleneck;
- the expected gain is at least 3x on representative local data, or the Rust helper removes a Windows lifecycle failure mode that Python/PowerShell cannot reliably close;
- the module does not own product semantics, Agent policy, LLM routing, persistence authority, or evolution selection decisions.

Recommended Rust areas:

- runtime-scene and JSONL indexing, filtering, timeline aggregation, and slow-event summaries;
- large file and directory scanning for reset summaries, memory overview inputs, workspace snapshots, and runtime package metadata;
- Git memory maintenance helpers, including worktree snapshot pruning plans, SQLite integrity checks, compact/vacuum preflight, and large-table statistics;
- Windows process-tree and port-owner probes for Launcher and Runtime Manager diagnostics;
- high-frequency text parsing, prompt segmentation, bounded diff scanning, and log redaction when the format is stable;
- WASM computation helpers for heavy visualization layout, graph math, or particle simulation data preparation;
- security-oriented path normalization, command classification, archive/media probing, and allowlist/denylist matching helpers.

Avoid Rust for:

- Agent Turn orchestration, Tool Registry ownership, Tool Policy decisions, or permission governance;
- LLM invocation, prompt-cache policy, model routing, provider fallback, or message-shape adaptation;
- FastAPI route/service ownership, Pydantic DTOs, frontend API contracts, or React application logic;
- Self-Evolution, Supervised Evolution, Selection Policy, or any module whose product semantics are still actively changing;
- Launcher or Runtime Manager top-level lifecycle ownership unless a separate migration plan proves parity, fallback, logging, and rollback behavior.

Any Rust accelerator must report its integration path, fallback behavior, validation command, runtime refresh impact, packaging impact, and version-impact judgment before merge.

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

Detailed interaction geometry requirements, including button sizing, control choice, loading-state stability, and screenshot validation, live in section 23.10.

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

Process-level pytest parallelism is available, but it is opt-in. Use it to speed up focused, isolated suites after the relevant serial command or narrow subset is understood:

```powershell
python tests/test_runner.py --parallel --workers 4
python tests/test_runner.py --fast --parallel --workers 4
pytest tests/ -n 4 --dist loadfile -m "not serial"
```

Keep the default pytest path serial. Do not add `-n` to global pytest defaults unless a separate governance round approves it.

When using parallel pytest:

- use `pytest-xdist` process workers, not thread-level parallelism;
- prefer `--dist loadfile` so tests from the same file stay on the same worker;
- start with `--workers 2` or `--workers 4`; avoid `-n auto` until the suite has proved stable;
- exclude tests marked `serial`;
- mark a test `serial` when it touches real processes, fixed ports, shared global state, the real workspace, the external operator config, Launcher/runtime lifecycle, Git side effects, or non-isolated background services;
- if a broad parallel suite exposes unrelated baseline drift, keep the current task evidence focused and report the unrelated failure boundary explicitly.

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

Terminal popup issues during startup are Launcher/runtime lifecycle bugs until proven otherwise. Diagnosis must cover the desktop entry, VBS/PowerShell adapter, Python launcher and child interpreter, Node/npm/cmd wrappers, Git polling endpoints, Runtime Manager commands, and stale external processes. Closure requires live evidence that the original user action no longer creates visible `cmd.exe`, `WindowsTerminal.exe`, `OpenConsole.exe`, or interactive Git editor windows, plus focused tests for the no-console helper or launch policy that was changed.

## 13. Git Submission

Before staging or committing, inspect:

```powershell
git status --short --branch
```

Never use `git add .`. Stage only files belonging to the current task.

Run Git commands non-interactively in automation and agent workflows. Do not start `git commit`, `git merge --continue`, or similar commands in a way that can open an editor unless the user explicitly asked for interactive Git. Supply a message, use `--no-edit` when appropriate, or set a bounded non-interactive editor for scripted flows.

Do not revert unrelated user or Agent changes. If unrelated changes exist in files you must touch, read carefully and work with them instead of overwriting.

Treat `%USERPROFILE%\Documents\Vibelution\config\config.toml` as the operator config source of truth. Root `config.toml` / `config.example.toml` are deprecated and must not be used as migration input, template input, or active runtime config surface during integration.

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

Do not over-repeat root `config.toml` / `config.example.toml` cleanup state unless staging, validation, or config diagnosis depends on it. Prefer reporting the resolved external config path instead.

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

## 23. Functional Development Constraints

Functional development constraints are domain-triggered guardrails. They apply when a task touches the named product or architecture domain; they are not blanket rituals for every session.

Use this section to prevent high-cost drift in recurring Vibelution work. When a task triggers one of these constraints, follow the project's existing path first, and only introduce a new path when the old path is demonstrably unable to support the required behavior.

For each triggered constraint, a development round should be able to answer:

- which domain was triggered;
- which existing service, route, cache, registry, config, or lifecycle path was reused;
- why any bypass or new path is necessary;
- what validation proves the behavior still converges through the intended project mechanism.

### 23.1 LLM Invocation Chain

Trigger this constraint when adding or changing any model call, model routing, prompt execution, judge, summary, research step, evolution step, tool-planning step, or provider/model selection behavior.

Default rule: reuse the unified LLM invocation chain and its context objects before introducing direct provider calls.

Prefer:

- existing `core/llm` entrypoints and adapters;
- `LLMInvocationContext` or the current equivalent context carrier;
- the configured model library and operator config as the source of model/provider truth;
- the normal session, agent, role, runtime-scene, and audit context attached to the call;
- existing test doubles and provider probes.

Avoid:

- new ad hoc OpenAI-compatible clients inside feature services;
- hard-coded model names, base URLs, API keys, timeouts, or provider priority;
- prompt/model calls that cannot be tied back to a session, agent, runtime scene, or config source;
- duplicating retry, fallback, timeout, redaction, or logging behavior already owned by the LLM layer.

Allowed exception: bounded provider health checks, model discovery, config validation, or migration probes may call a provider-specific path when they are isolated, redacted, logged, and not used as the normal feature execution path.

Validation anchor: trace the call path from the feature entrypoint to the shared LLM layer, and add or update focused tests around routing, context propagation, fallback, and failure logging when behavior changes.

### 23.2 Agent, Session, Team, And ChatRoom Lifecycle

Trigger this constraint when creating, deleting, archiving, restoring, listing, routing, binding, or displaying Agents, Teams, Sessions, Conversations, or ChatRooms.

Default rule: lifecycle changes must converge through the owning service path, and related indexes must be repaired in the same behavior round.

Prefer:

- `agent_directory_service` for Agent identity, status, archive, purge, mode binding, and display metadata;
- `session_service` for chat session creation, ownership, and conversation state;
- `chat_room_service` for room membership, participant repair, room sessions, and room run behavior;
- `team_service` for Team membership, linked room behavior, and Team-to-Agent cascade semantics;
- existing conversation and workspace projections instead of parallel UI-only state.

Avoid:

- orphan Agents with no Team/category path when product semantics require a binding;
- archived Agents left in active rooms, participants, mode bindings, or UI indexes;
- Team deletion or archive paths that update only the Team record but skip member Agent and linked room cleanup;
- frontend-only removal that is not reconciled with backend lifecycle state;
- direct JSON/file edits to lifecycle state unless they are part of an approved migration or repair tool.

Validation anchor: lifecycle work should include focused service or route tests for the state transition, plus cache invalidation or optimistic rollback coverage when the UI changes.

### 23.3 Runtime Scene Evidence Chain

Trigger this constraint when changing runtime execution, workbench activity, task orchestration, tool execution, error handling, repair flows, Launcher integration, or any path where future debugging depends on evidence.

Default rule: behavior that can fail, stall, branch, retry, or repair must leave a bounded runtime-scene evidence trail at the real decision point.

Prefer:

- existing runtime-scene services and package structure under `logs/runtime_scenes/`;
- structured fields for state transitions, identifiers, duration, result status, and failure class;
- redacted summaries instead of raw prompts, secrets, large outputs, or unbounded diffs;
- focused logging at the cause site rather than broad wrapper logs.

Avoid:

- silent fallback branches;
- success-only logs for behavior that can fail;
- logs that cannot be correlated to Agent, Team, Session, worktree, task, claim, or runtime lifecycle;
- dumping prompts, secrets, provider payloads, or full tool output into logs.

Validation anchor: when changing runtime behavior, inspect or create the smallest relevant runtime-scene evidence and confirm a future Agent can reconstruct the branch, failure, or repair without guessing.

### 23.4 Launcher And Runtime Manager Lifecycle

Trigger this constraint when changing startup, shutdown, restart, refresh, health checks, backend/frontend process control, browser launch, environment loading, or runtime-manager behavior.

Default rule: runtime lifecycle operations should go through Launcher or Runtime Manager paths, not one-off shell process control.

Prefer:

- `scripts/vibelution_launcher.ps1` or `scripts/vibelution_launcher.py` for local runtime restart decisions;
- runtime-manager APIs and existing process registry behavior for UI-controlled lifecycle actions;
- explicit refresh decisions in final reports: `not needed`, `recommended before user testing`, or `required before release/runtime verification`;
- active-work guards before restarting when work is running.

Avoid:

- raw `uvicorn`, `npm`, process-kill, or port-kill flows as the normal refresh mechanism;
- restarting Vibelution while Launcher active-work guards report an active task;
- hiding skipped refresh decisions in final reports.

Validation anchor: lifecycle changes require a launcher/runtime-manager test, smoke check, or explicit reason why runtime verification is deferred.

### 23.5 Memory, Knowledge, And RAG Boundaries

Trigger this constraint when changing project memory, Team knowledge, candidate knowledge, RAG retrieval, vector/index writes, formal memory promotion, or generated memory views.

Default rule: transient, candidate, formal, and project-governance memory must stay in their owned layers.

Prefer:

- project-memory guard and sync scripts for `.docs/project-memory/**`;
- `memory_service`, `team_knowledge_service`, and existing knowledge promotion paths for runtime knowledge;
- candidate knowledge or proposal records before formal memory when confidence, ownership, or source quality is uncertain;
- generated views rebuilt by their owning scripts instead of hand-edited HTML snapshots.

Avoid:

- direct writes to formal memory, RAG indexes, or generated memory views from feature code;
- mixing Challenge Cup research memory, runtime Agent memory, and project governance memory without an explicit boundary;
- treating another Agent's final report as primary evidence without checking files, logs, commits, registry state, or tests.

Validation anchor: memory work should show the source, target layer, promotion condition, and sync/render result or exact handoff proposal.

### 23.6 Frontend State, Optimistic UX, And Cache Coherence

Trigger this constraint when changing visible UI state, optimistic actions, list/detail caches, React Query keys, workspace projections, or frontend/backend DTO contracts.

Default rule: the UI may respond optimistically, but it must reconcile through backend source-of-truth state and project cache helpers.

Prefer:

- existing query keys, cache helpers, and route-level workspace cache utilities;
- optimistic removal or patching for obvious slow operations, with rollback or invalidation on failure;
- narrow cache updates for known entities, followed by invalidation of related indexes when relationships change;
- TypeScript DTO updates that match backend route/service contracts.

Avoid:

- UI-only deletion/archive states that survive backend failure;
- updating a list cache while leaving detail, conversation, room, Agent, or Team indexes stale;
- broad cache clears when a targeted helper already exists;
- adding new DTO shapes without route tests, type checks, or generated/static type alignment.

Validation anchor: frontend behavior changes need the narrowest relevant unit tests plus `npm --prefix web run build` unless the task is docs-only or the user explicitly accepts deferred validation.

### 23.7 Tool Invocation And Permission Governance

Trigger this constraint when adding or changing tools, agent tool routing, command execution, permission checks, tool descriptions, capability discovery, or tool-result handling.

Default rule: tool behavior should go through the Tool Registry, policy checks, and existing executor/result contracts.

Prefer:

- registered tool descriptors with clear input, side effect, permission, and failure semantics;
- explicit routing rules for automatic command recognition;
- bounded outputs and redaction for tool results;
- tests that cover both allowed and denied paths.

Avoid:

- feature-specific direct shell/network/file operations that bypass the tool registry when the behavior is a user-facing tool capability;
- vague tool descriptions that make routing depend on guessing;
- tools that cannot explain their side effects, permission requirement, timeout, or rollback behavior;
- logging raw secrets, prompts, credentials, or unbounded command output.

Validation anchor: tool changes should include descriptor review, routing/permission tests where practical, and a manual or automated smoke result for the main path.

### 23.8 Config And Model Source Of Truth

Trigger this constraint when changing config loading, model/provider selection, defaults, credentials, feature flags, environment resolution, or operator-facing settings.

Default rule: use the configured source of truth and preserve local-first operator control.

Prefer:

- `C:\Users\17533\Documents\Vibelution\config\config.toml` as the active operator config source during integration;
- root `config.toml` and `config.example.toml` only as legacy/template surfaces unless an approved migration says otherwise;
- existing public config APIs and model library services for frontend-visible config;
- redacted diagnostics for missing, invalid, or partial config.

Avoid:

- hard-coded runtime defaults that compete with operator config;
- exposing secrets or provider credentials through UI, logs, runtime scenes, or test fixtures;
- treating root template config as active integration state;
- introducing a second source of model/provider truth.

Validation anchor: config changes should test precedence, missing/invalid values, redaction, and the UI/backend contract for any setting exposed to users.

### 23.9 Delete, Archive, Reset, And Data Retention

Trigger this constraint when changing destructive, reversible, archival, reset, purge, repair, or cleanup behavior.

Default rule: destructive semantics must be explicit, cascades must be intentional, and user-visible state must not leave unclassified or unreachable entities.

Prefer:

- archive before purge unless the product behavior explicitly requires irreversible deletion;
- service-level cascade helpers that repair related indexes, rooms, bindings, sessions, caches, and projections;
- clear distinction between `delete`, `archive`, `purge`, `reset`, `detach`, and `hide`;
- tests for partial failure and already-archived/already-deleted inputs.

Avoid:

- deleting a parent while leaving children active and unclassifiable;
- frontend disappearance without backend convergence or failure rollback;
- cleanup scripts as the only enforcement of a lifecycle invariant;
- irreversible operations without explicit product intent and validation.

Validation anchor: every lifecycle removal should prove the parent, child records, indexes, UI caches, and user-visible lists converge to the same semantic state.

### 23.10 Frontend Interaction Design And Layout Fit

Trigger this constraint when adding or changing visible controls, buttons, action groups, panels, cards, tables, forms, drawers, modals, loading states, empty states, or responsive layouts.

Default rule: UI geometry must match the action's content, intent, scope, and container semantics. A control should not become large merely because its parent layout has available space.

Prefer:

- buttons sized to their label and icon content with consistent padding, stable height, and bounded min/max width;
- icon-only square buttons for familiar tool actions, with accessible labels and tooltips;
- short visible labels for actions, fields, badges, and status rows; keep supplemental explanation in hover and keyboard-focus tooltips instead of inline prose;
- terse visible page copy that preserves the current object, state, value, and next action; move meaning, source, formula, scope, or rationale into a tooltip, details disclosure, drawer, or help surface;
- full-width buttons only when the whole row or block is intentionally the action target, such as a mobile primary action, a form submit row, or a single CTA inside a constrained panel;
- segmented controls, tabs, checkboxes, toggles, selects, menus, or dropdowns for modes and option sets instead of long stacks of button-like choices;
- action groups aligned near the object they affect, with primary, secondary, and destructive actions visually separated;
- compact operational layouts that prioritize scanning, comparison, and repeated use over marketing-style hero/card composition;
- tooltips that are concise, accessible by hover and focus, and limited to local explanation; longer guidance belongs in an expandable detail panel rather than a tooltip;
- reserved dimensions, skeletons, or stable placeholders so loading content does not pop in below the viewport or shift the surrounding layout after data arrives;
- responsive constraints such as `minmax`, `fit-content`, `max-content`, `max-width`, `aspect-ratio`, and fixed icon-button dimensions for fixed-format controls;
- designs checked against the longest realistic Chinese and English labels, empty values, loading labels, error text, and permission-disabled states;
- clear focus, hover, active, disabled, busy, and failure states for every interactive element.

Avoid:

- short-label buttons stretched across a wide container, leaving large empty clickable areas;
- using `width: 100%` on buttons inside dense panels, toolbars, lists, or cards unless the full row is the intended target;
- button text that wraps awkwardly, clips, overflows, or visually floats in excessive whitespace;
- controls whose hover, loading, badge, or label states resize the surrounding layout;
- explanatory sentences that permanently occupy dense operational surfaces when the same meaning can live in a tooltip, title, focus hint, details disclosure, or contextual help icon;
- hiding complete errors, destructive consequences, permission blockers, secret-handling warnings, or irreversible-operation risks behind a tooltip; critical blocking information must remain directly visible;
- nested cards, decorative card walls, or large empty bands on operational pages;
- using buttons as generic pills for filters, binary settings, mode switches, or multi-choice inputs when a standard control communicates the intent better;
- loading states where key rows, actions, or bottom content are hidden until the request finishes without a stable placeholder;
- mobile layouts that require horizontal scrolling for normal controls or let fixed buttons cover content.

Validation anchor: frontend visual work should include a browser screenshot or equivalent visual check at the relevant desktop and mobile widths. Before finishing, confirm that buttons hug their content or have an explicit full-width reason, text fits, controls do not overlap, non-critical explanatory copy is not permanently consuming primary UI space, tooltip/focus explanations are reachable, and loading-to-loaded transitions do not create disruptive layout shifts.
