# Task 2 Report

## Summary

Implemented Task 2 for self-evolution dual modes in the owned backend files only:

- added self-observation start/detail/events/action routes under `/api/evolution/self/observation-runs*`
- added `execute_self_observation_action` with `terminate` / `stop` / `cancel` support for queued and running observation runs
- added `stream_self_observation_run_events` SSE polling helper
- updated route-test isolation fixture to clear observation state between tests
- added focused route and service tests for the new observation flow

No frontend/types/snapshot field expansion was added. No real observation conversation chain was added.

## Scope Check

Touched owned files only:

- `core/web/services/self_evolution_control_service.py`
- `core/web/routes/evolution.py`
- `tests/test_self_evolution_control_service.py`
- `tests/test_web_evolution_routes.py`

Did not modify:

- `VERSION`
- `CHANGELOG.md`
- `config.toml`
- `config.example.toml`
- operator config

## TDD Notes

Red phase:

- `tests/test_web_evolution_routes.py -k "self_observation"` failed with `405 Method Not Allowed` before the new routes existed.
- `tests/test_self_evolution_control_service.py -k "self_observation"` failed because `execute_self_observation_action` did not exist.

Green phase:

- implemented the missing routes and service helpers
- reran the same targeted slices until both passed

## Implementation Details

### Route surface

Added:

- `POST /api/evolution/self/observation-runs`
- `GET /api/evolution/self/observation-runs/{run_id}`
- `GET /api/evolution/self/observation-runs/{run_id}/events`
- `POST /api/evolution/self/observation-runs/{run_id}/actions`

Behavior:

- start returns `202`
- missing run returns `404`
- invalid action or invalid payload returns `422`
- action against a non-active observation run returns `409`

### Observation actions

`execute_self_observation_action`:

- normalizes run id and action
- accepts `terminate`, `stop`, `cancel`
- only allows action on `queued` / `running` snapshots
- marks the run `terminated`
- clears the active observation slot
- disables terminate action state
- preserves a minimal report if the run was stopped before a final report existed

### Observation SSE

`stream_self_observation_run_events`:

- emits the initial snapshot immediately when provided
- polls current snapshot state
- stops when the run becomes non-active or disappears

### Test isolation

`tests/test_web_evolution_routes.py` autouse fixture now clears:

- `_OBSERVATION_RUNS`
- `_ACTIVE_OBSERVATION_RUN_ID`

This prevents active observation state from leaking between tests.

## Validation

Commands run with the required interpreter:

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py -k "self_observation" -q
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q
```

Results:

- route slice: `2 passed, 63 deselected`
- service slice: `24 passed, 49 deselected`

## Concerns

- Observation SSE currently polls at 1 second intervals and emits raw run snapshots only; this is enough for Task 2 but still intentionally minimal before Task 5 conversation-chain work.
- Route coverage in this task focuses on start and terminate behavior; 404/409/422 handling is implemented in the route layer but not exhaustively expanded into more route tests in this round.

## Commit

Planned commit message:

`feat: expose self-observation run routes`

## Fix Review Findings

- Fixed reviewer blocker: operator-triggered `terminate` now wins over later worker lifecycle writes.
- Added `_self_observation_has_operator_terminal_state(...)` guard so `_set_self_observation_terminal_state(...)` returns the existing snapshot unchanged when the observation run is already in an operator terminal state such as `terminated`.
- Added the same guard at `_run_self_observation_turn(...)` entry so a queued run that is terminated before the worker starts cannot be moved back to `running` and later to `done` or `failed`.
- Added service regression tests covering both post-terminate overwrite paths:
  - direct `_set_self_observation_terminal_state(...)` call after terminate keeps `terminated`
  - delayed `_run_self_observation_turn(...)` call after terminate keeps `terminated`
- Added route regression coverage for the non-active action path: a second terminate action against the same observation run now returns `409` through the route layer.

### Fix Validation

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py -k "self_observation" -q
```

Results:

- service slice: `26 passed, 49 deselected`
- route slice: `3 passed, 63 deselected`

### Fix Commit

Planned fix commit message:

`fix: preserve terminated self-observation runs`
