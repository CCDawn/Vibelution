# Task 1 Report

## Scope

- Task: Backend observation prompt and run model
- Owned files only:
  - `core/web/services/self_evolution_control_service.py`
  - `tests/test_self_evolution_control_service.py`
- Out of scope and untouched:
  - Task 2+ routing, SSE, frontend surfaces
  - `VERSION`, `CHANGELOG.md`, `config.toml`, `config.example.toml`, operator config

## TDD Evidence

### Red

1. Prompt/boundary slice:
   - Command:
     - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_prompt or self_observation_boundary" -q`
   - Failure:
     - `AttributeError: module 'core.web.services.self_evolution_control_service' has no attribute 'build_self_observation_prompt'`

2. Observation start slice:
   - Command:
     - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py::test_start_self_observation_run_has_no_tools_no_worktree -q`
   - Failure:
     - `AttributeError: ... has no attribute '_run_self_observation_turn'`

### Green

1. Prompt/boundary slice:
   - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_prompt or self_observation_boundary" -q`
   - Result: `2 passed, 50 deselected`

2. Observation start slice:
   - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py::test_start_self_observation_run_has_no_tools_no_worktree -q`
   - Result: `1 passed`

3. Combined Task 1 slice:
   - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q`
   - Result: `3 passed, 49 deselected`

## Implemented Contract

### Prompt helpers

- Added `SELF_OBSERVATION_MIN_DURATION_SECONDS = 30`
- Added `SELF_OBSERVATION_MAX_DURATION_SECONDS = 3600`
- Added `_normalize_observation_duration(value)`
- Added `build_self_observation_prompt(goal, duration_seconds)`
- Added `detect_self_observation_boundary_violation(text)`

Behavior locked:
- autonomous observation prompt explicitly states no tools
- prompt forbids fake file/command/search/mutation claims
- prompt forbids tool requests/temporary authorization
- prompt requires `无法验证` when evidence is unavailable
- boundary detector classifies fake execution claims into stable reason codes

### Observation run model

- Added isolated in-memory observation run state:
  - `_OBSERVATION_RUN_STATE_LOCK`
  - `_OBSERVATION_RUNS`
  - `_ACTIVE_OBSERVATION_RUN_ID`
- Added snapshot builder:
  - `_build_self_observation_snapshot(...)`
- Added lifecycle helpers:
  - `get_active_self_observation_run()`
  - `get_self_observation_run_snapshot(run_id)`
  - `force_cancel_active_self_observation_runs_for_shutdown(reason="")`
  - `_run_self_observation_turn(context)` as current minimal placeholder
  - `start_self_observation_run(payload)`

Behavior locked:
- run snapshot uses `runKind="self_observation_run"`
- run snapshot uses `selfMode="observation"`
- `allowedTools=[]`
- `writeLeases=[]`
- `worktreeCreated=False`
- observation mode does not create a worktree
- observation mode does not request tool authorization
- active observation is single-run gated

## Test updates

- Added prompt contract test
- Added boundary violation detector test
- Added observation start snapshot test
- Updated autouse reset fixture to clear observation run state between tests

## Notes / Concerns

- `_run_self_observation_turn()` is intentionally minimal in Task 1 so this round only locks the prompt/boundary/start model contract.
- No routing, SSE streaming, or frontend wiring was added in this task.
- Existing guard script in this repo currently exposes `status/check/claim` rather than the `recommend/preflight` commands referenced in higher-level docs, so claim handling was adapted to the live script surface.

## Fix Review Findings

- Reviewer blocker 1 fixed: `_run_self_observation_turn()` no longer returns immediately. The default path now marks the run `running -> done`, writes a minimal no-tool observation report, stamps `finishedAt`, disables terminate action, and clears `_ACTIVE_OBSERVATION_RUN_ID` so later observation runs are not stuck behind a stale active slot.
- Reviewer blocker 2 fixed: `start_self_observation_run()` now rejects explicit tool/authorization/policy override fields with `SelfEvolutionRunValidationError` instead of silently ignoring them. Rejected fields include `allowedTools`, `tools`, `toolRequests`, `requestedTools`, `dynamicTools`, `temporaryAuthorization`, `temporaryToolAuthorization`, `toolPolicy`, `permissions`, `writeLeases`, `readScopes`, `writeScopes`, and `mutationAccess`.
- Reviewer blocker 3 fixed: added negative tests for forbidden tool fields, a synchronous minimal lifecycle test that proves the default observation turn reaches terminal state and releases the active slot, and duration normalization coverage for default/min/max clamp behavior.
- Verification:
  - `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q`
  - Result: `21 passed, 49 deselected`
