# Schema v2 Migration Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make legacy loopback model services migrate as `local_runtime` and make Config recover from stale migration previews.

**Architecture:** Keep Schema v2 validation strict and fix classification at the migration source by deriving service class from both legacy kind and normalized endpoint. Keep UI recovery deterministic through a pure error-classification helper, while `ConfigRoute` owns state reset and localized copy.

**Tech Stack:** Python 3.12, pytest, React 19, TypeScript 5.9, Vitest, TanStack Query.

## Global Constraints

- Operator config source of truth remains `C:\Users\17533\Documents\Vibelution\config\config.toml`.
- Never print or persist API Key values in repository files or `config.toml`.
- Do not relax localhost Provider validation.
- Do not rename Provider IDs, model IDs, upstream IDs, or compatibility aliases.
- Use TDD: each task must show a focused failing test before production edits.
- No remote push, PR, version bump, or unrelated refactor.

---

### Task 1: Loopback-aware migration classification

**Files:**
- Modify: `config/model_config_migration.py`
- Test: `tests/test_model_config_migration.py`

**Interfaces:**
- Consumes: normalized Provider `base_url` already produced by `normalize_legacy_service_root(...)`.
- Produces: `_service_class(provider: dict[str, Any], base_url: str = "") -> str`, returning `local_runtime` for explicit local kinds or loopback endpoints.

- [ ] **Step 1: Write the failing regression test**

Add a test that builds a legacy model with `provider.kind = "relay"` and `http://127.0.0.1:8080/v1`, previews migration, and asserts `preview.providers[0]["service_class"] == "local_runtime"`. Apply the preview against a temporary config with `reload_config` monkeypatched and assert the persisted config reaches `schema_version = 2`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_model_config_migration.py -k 'loopback_relay' -q
```

Expected: FAIL because the preview currently reports `service_class == "relay"` or Apply raises the localhost/non-local validation error.

- [ ] **Step 3: Implement minimal endpoint-aware classification**

Use `ipaddress.ip_address(host).is_loopback` plus the literal `localhost` after parsing the normalized endpoint with `urlsplit`. Pass the normalized `base_url` into every `_service_class(...)` call used to build or compare Provider groups. Do not classify RFC1918/LAN addresses as local automatically.

- [ ] **Step 4: Verify GREEN and migration regressions**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_model_config_migration.py -q
```

Expected: 48 tests pass with zero failures.

- [ ] **Step 5: Commit the task**

Stage only `config/model_config_migration.py` and `tests/test_model_config_migration.py`, then commit `fix(config): classify loopback migration providers`.

### Task 2: Clear stale Config migration previews

**Files:**
- Modify: `web/src/routes/configRouteLogic.ts`
- Modify: `web/src/routes/configRouteLogic.test.ts`
- Modify: `web/src/routes/ConfigRoute.tsx`

**Interfaces:**
- Produces: `shouldResetMigrationPreview(error: unknown) -> boolean`.
- Consumes: `Error.message` emitted by `fetchJson`, including JSON details with `migration_request_rejected` or `migration_state_conflict`.

- [ ] **Step 1: Write failing pure-logic tests**

Add assertions that `shouldResetMigrationPreview(new Error('{"detail":{"code":"migration_request_rejected"}}'))` and the state-conflict equivalent return `true`, while an unrelated network error returns `false`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
npm test -- src/routes/configRouteLogic.test.ts
```

Expected: FAIL because `shouldResetMigrationPreview` is not exported.

- [ ] **Step 3: Implement the minimal helper and route recovery**

Implement the helper by reading `Error.message` or `String(error)` and matching only the two migration codes. In `handleApplyMigration` catch, clear `migrationPreview` and show localized “预览已失效，请重新生成” / “The migration preview expired. Generate a new preview.” copy when the helper returns `true`; retain existing error handling otherwise.

- [ ] **Step 4: Verify GREEN and frontend contract**

Run:

```powershell
npm test -- src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts
npm run build
```

Expected: both test files pass and Vite build succeeds.

- [ ] **Step 5: Commit the task**

Stage only the three frontend files, then commit `fix(web): recover stale config migration previews`.

### Task 3: Integrate, migrate, and verify runtime settings

**Files:**
- Modify outside Git: `C:\Users\17533\Documents\Vibelution\config\config.toml`
- Generated outside Git: migration backup manifest and before/after payloads under the operator config backup directory.
- Modify after successful evidence: `.docs/project-memory/lanes/llm-model-config-alignment.json`

**Interfaces:**
- Consumes: Task 1 migration behavior and Task 2 recovery behavior.
- Produces: applied Schema v2 operator config, rollback migration ID, Launcher-refreshed settings UI evidence.

- [ ] **Step 1: Rebase/reconcile against current local main and run focused tests**

Verify both task commits remain isolated and rerun Python tests, frontend tests, and build. Stop on any overlap with active claims.

- [ ] **Step 2: Merge the task branch into local main**

Use a non-interactive local merge after gates pass. Keep root on `main` and stage no unrelated files.

- [ ] **Step 3: Generate and apply a fresh migration preview**

Through the authenticated local Config API, assert `READY`, 6 Providers, 110 live references, 8 historical references, zero conflicts, and matching workspace `baseHash`; immediately Apply within the same backend process.

- [ ] **Step 4: Verify disk and rollback evidence**

Assert Schema v2, 6 Providers, 7 models, compatibility aliases, no unresolved live alias references, changed file hash, and an `applied` migration manifest with before/after backups. Do not expose secrets.

- [ ] **Step 5: Refresh Launcher and perform browser QA**

Use the normal Launcher path. Verify Model Center exposes existing models, `relay_gpt_5_6_luna`, Provider grouping, API Key password input/environment-variable storage guidance, and stable desktop plus 390x844 layouts. Confirm Agent binding still resolves through the compatibility alias.

- [ ] **Step 6: Close governance state**

Sync project memory through the project memory skill, release both active claims with evidence, remove the task worktree after integration, and report version impact as `none` unless runtime code versioning policy requires otherwise.
