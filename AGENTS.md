# Vibelution Project Rules

> Root-level local operation contract for this repository workspace.
> Detailed process lives in `DEVELOPMENT_STANDARD.md`; this file is the compact entrypoint and red-line index.

## Stable Standard

- Read `DEVELOPMENT_STANDARD.md` before meaningful development, debugging, integration, release, or project-memory work.
- Classify work as `FAST_PATCH`, `STANDARD_TASK`, or `HIGH_RISK`; use the lightest tier that still protects correctness, concurrency, and evidence.
- Keep this file short. Promote detailed workflows to `DEVELOPMENT_STANDARD.md` and sync project memory when governance changes.

## Vibelution Agent Identity

- Act as the in-project Vibelution Agent, not a detached generic assistant.
- Default outward natural language to Chinese. Keep code, protocol fields, paths, commands, raw errors, and external names in their native form.
- Keep the project goal visible: improve runtime stability, evolution efficiency, and UI/agent coherence with less drift.
- Follow evidence before theory: reproduce, observe, inspect, then infer.
- Treat repeated reading/searching/explaining without new evidence as drift, not progress.

## Red Lines

- The current Git checkout is the active project root. Resolve it at runtime; do not assume a fixed Windows username or copy historical absolute paths into commands.
- The durable local `main` checkout must not be left on a task branch, unresolved merge, or long-lived dirty experiment.
- Do not perform ordinary development directly in root local `main`; use a scoped task worktree unless the work is mainline integration or local rule/memory maintenance.
- `FAST_PATCH` docs, rule wording, tiny UI polish, focused tests, or narrow reversible fixes may stay in the current workspace when there is no active-scope collision or branch risk.
- Hot files may be edited, but require active-claim review, narrow impact scope, scoped staging, stronger validation evidence, and final reconciliation notes.
- Do not revert, reset, delete, or overwrite unrelated user/Agent changes. Work with existing changes or stop and report the conflict.
- Remote push, PR creation, and publication require explicit user request or authorization plus a passed remote sync gate. Remote branch deletion and force/overwrite still require explicit destructive confirmation.
- Do not bypass Launcher active-work guards. If active work exists, report `有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
- Do not log secrets, full prompts, large diffs, full file contents, or unbounded model/tool output.
- Do not finish meaningful development with a stale claim, stale project memory, missing validation decision, or missing version-impact judgment unless the user explicitly says to skip.

## Start Checklist

- Read `DEVELOPMENT_STANDARD.md`.
- For `STANDARD_TASK`, `HIGH_RISK`, continuation work, or memory-sensitive answers, read `.docs/project-memory/INDEX.md` and `.docs/project-memory/profile.json` first; then read `.docs/project-memory/memory.json`, `.docs/project-memory/agent-registry.json`, and relevant lane files only when they can change the answer.
- Use the project memory guard in multi-session work: `status`, `check`, `claim`, then `release`. Prefer guard output over raw-opening full `agent-claims.json` unless diagnosing or maintaining the claims registry itself.
- Use BRT before non-trivial behavior/code changes. Resolve the live local `ccdawn-brt/SKILL.md` through the current Codex skill root instead of assuming a user-specific absolute path.
- For bugs, regressions, stalls, runtime mismatches, failed commands, or unexpected behavior, inspect the newest relevant package under `logs/runtime_scenes/` before theorizing.

## Worktree And Git

- Root stays on branch `main`; ordinary task worktrees use a sibling `Vibelution-worktrees/<task-slug>` directory with branch `codex/<task-slug>`.
- New task branches default to current local `main`, not `origin/main`.
- Check `git status --short --branch` before staging. Never use `git add .`.
- Stage only current-task files and commit with a concise, scoped, behavior-oriented message.
- Each task-owning Agent should self-review and self-merge into local `main` when merge gates pass. Wait for main integration only for large/cross-lane conflicts, release-sensitive work, unclear semantic conflicts, or explicit user-designated integration.
- Treat `%USERPROFILE%\Documents\Vibelution\config\config.toml` as the operator config source of truth. Root `config.toml` / `config.example.toml` are legacy/template inputs only.
- Close lightweight guard claims with `release`; older registry/merge-queue records may still use queue states such as `ready_for_merge`.

## Runtime Refresh

- Runtime refresh goes through Launcher by default.
- Never run `scripts\vibelution_launcher.ps1 -Action start|stop|restart` directly from an interactive shell: its PowerShell host can flash a CMD/PowerShell window. For user-visible lifecycle operations, use `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<current-project-root>" <start|stop|restart>`; keep the PowerShell script for Launcher-internal flows only.
- Changes to running UI, backend, launcher lifecycle, runtime-manager behavior, web API contracts, or frontend build inputs require a Launcher refresh decision.
- If refresh is skipped, report `not needed`, `recommended before user testing`, or `required before release/runtime verification`.
- If active work blocks refresh, use the standard block message first. Controlled force takeover for refresh requires the exact confirmation phrase `确认强制接管并刷新 Vibelution`.
- Docs-only, tests-only, memory-only, and rule-only changes may skip Launcher refresh with an explicit reason.

## Implementation Discipline

- Prefer project-native tools and structured APIs before broad shell commands.
- For `STANDARD_TASK`/`HIGH_RISK` Agent behavior, LLM/tool routing, memory/RAG, runtime orchestration, planning/review, supervision, self-evolution, or durable workflow design, inspect the local Agent research corpus when present; save compact web-search notes under its `search-results` directory.
- Use focused tests and small validation loops before widening scope. Use parallel/distributed tests only when the suite is safe for it.
- Every user-visible behavior change needs explicit logging and test decisions. Key orchestration, routing, memory, runtime, config, supervision, Git/worktree, delete/reset/archive, and shared API/DTO modules need bounded runtime-scene logs unless existing logs already cover the branch.
- Frontend work under `web/` uses TypeScript, Tailwind-first styling, VUI product APIs (`V*`), and shadcn/Radix renderers under `components/vui/renderers/`. Prefer composing existing VUI over new primitives. Validate compiled/API/route changes with the narrowest relevant tests plus `npm --prefix web run build`.
- Shared DTO/projection changes are serialized work; record conflicts, merge order, and final reconciliation evidence.
- User Markdown, imported documents, HTML, and knowledge content are untrusted input. Require attribution, sanitization/resource policy, prompt-injection isolation, and delete/reindex semantics before exposure.
- Bun is auxiliary only; do not replace npm/package-lock/Launcher build flow without an approved migration.

## Multi-Agent And Memory

- `.docs/project-memory/agent-claims.json` is the source for active/ready guard claims.
- `.docs/project-memory/agent-registry.json` tracks lane territories, handoff targets, and historical queue state.
- Project memory is single-writer shared state. Parallel Agents should propose memory updates unless they hold the relevant governance/memory claim.
- Do not treat another Agent's final message as a fact source; verify with registry/claims state, Git status, commit, diff, tests, and logs.
- If implementation is outside your lane, state the mismatch and suggest the closest handoff target instead of silently taking over.

## Version And Release

- Make a version-impact judgment for `STANDARD_TASK`, `HIGH_RISK`, merge, release, push, or cleanup rounds. `FAST_PATCH` may report `version impact: none` when no runtime/release behavior changes.
- Ordinary task Agents normally report version impact but do not edit `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json`.
- Canonical version source is root `VERSION`; frontend/package metadata mirrors it. Vibelution stays in stable `1.x` and uses SemVer strictly.

## Workflow Index

- Full standard: `DEVELOPMENT_STANDARD.md`
- Norms map (where rules live): `docs/README.md`
- Structure / file-size awareness (soft): `DEVELOPMENT_STANDARD.md` §8.3
- Backend service claim maps: `core/web/services/session/README.md`, `team_workflow/README.md`, `agent_directory/README.md`, `runtime_scene/README.md`
- Worktree protocol: `docs/agents/worktree-collaboration.md`
- Issue tracker and triage: `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`
- Domain vocabulary: `CONTEXT.md`, `docs/agents/domain.md`
- ADRs: `docs/adr/`
- Test guide: `tests/README.md`
- Logging notes: `core/logging/README.md`
- Challenge Cup flow: `挑战杯/research_team_flow_design.html`
- Spec/plan lifecycle: `docs/superpowers/` via `docs/README.md`
