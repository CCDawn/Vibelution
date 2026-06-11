# 2026-06-11 Vibelution Frontend Interaction Test Report

## Scope

- Target: Vibelution Web Workbench frontend interaction surfaces.
- Focus areas:
  - Config page save flow.
  - Chat/session create and send flow.
  - Agent and Team page navigation flow.
  - Workbench route/API smoke checks.
- Limitation: direct in-browser click/input automation against the local Workbench was blocked by the available Browser tool URL policy in this session. This report therefore uses Vitest interaction/layout contracts, pytest API interaction contracts, and HTTP smoke checks as the primary evidence.

## Summary

| Area | Result | Evidence |
| --- | --- | --- |
| Config save flow | Passed | `tests/test_web_app.py -k "config_workspace_apply"`: 5 passed |
| Chat/session send flow | Passed | targeted `submit_session_message` / session binding pytest subset: 6 passed |
| Agent/Team navigation contracts | Passed | targeted Vitest subset: 9 files, 218 tests passed |
| Team routes and references | Passed | `tests/test_agent_config_workspace_service.py::test_agent_config_workspace_api_route tests/test_team_routes.py`: 13 passed; targeted `tests/test_team_service.py`: 3 passed |
| Workbench route smoke | Passed | `/`, `/config`, `/agents`, `/teams`, Launcher, and key APIs all returned HTTP 200 |
| Production frontend build | Passed with warnings | `npm --prefix web run build` passed; see Observations |

## Bugs And Fix Status

| ID | Status | Severity | Area | Finding | Reproduction / Evidence | Notes For Fix Agent |
| --- | --- | --- | --- | --- | --- | --- |
| VIB-FE-20260611-001 | Fixed | P2 | Evolution Workbench route/API contract | `terminal_bench_agent_judged` is a valid primary Evolution Workbench dataset; the Workbench API contract test was stale and did not include the newer agent-judged dataset. | Reproduced before fix: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state` failed with extra `terminal_bench_agent_judged`. Verified after fix: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state tests/test_web_app.py::test_workbench_dataset_list_backfills_new_builtin_datasets` passed 2/2; `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_dataset_registry.py::test_default_dataset_registry_lists_builtin_and_swe tests/test_dataset_registry.py::test_materialize_terminal_bench_agent_judged_uses_agent_scoring` passed 2/2. | Fixed by updating `tests/test_web_app.py` API contract expectations to include `terminal_bench_agent_judged` and assert `agent_harness_ready`, `evaluationMode=agent_judged`, `officialVerifierStatus=not_required`, and non-official score semantics. No route filtering was applied because registry tests already define it as `effective`, `primary`, and selectable. |
| VIB-FE-20260611-002 | Fixed | P2 | Team page navigation/list | Team page previously exposed evolution system teams in the ordinary custom Team list, which could pollute Team navigation and selection. | Fixed by commit `ca3ab98c` (`fix: hide evolution system teams from team list`). Current targeted checks passed: `web/src/routes/TeamsRoute.layout.test.ts` includes `visibleTeams` filtering; `tests/test_team_routes.py` passed 12 route tests. | Keep ordinary Team list filtered through `visibleTeams`; system teams such as `self-evolution-team` and `supervised-evolution-team` should remain out of the user-created Team list. |
| VIB-FE-20260611-003 | Fixed / guarded | P3 | Config page editable schema | Config workspace editable schema needed to keep Launcher-owned `runtime` and `workbench` startup settings visible in `publicConfig` but out of normal editable sections and editor metadata. | Guarded by `test_config_workspace_exposes_editor_schema_without_launcher_owned_startup_settings`; current config save subset passed 5/5. Related local commit: `6c6f88ef` (`test: align config workspace editor contract`) and merge `7abf45ae`. | Preserve the split: `runtime` and `workbench` may be shown as public config data, but should not appear in config page editable `editorSections`, `sections`, or `editorMeta` unless a Launcher-governed edit flow is deliberately introduced. |

## No New Bugs Found In This Round

- Config save flow: no new failure found in apply/save/stale-hash/deletion/pending-env scenarios.
- Chat/session send flow: no new failure found in create session, bind agent, send, edit-resubmit, async acceptance, or blank-message rejection scenarios.
- Agent/Team navigation flow: no new failure found in current layout contracts, route contracts, Team reference data, or HTTP route availability.

## Observations

| ID | Status | Area | Observation | Evidence | Suggested Follow-Up |
| --- | --- | --- | --- | --- | --- |
| VIB-FE-OBS-20260611-001 | Open | Build config | Build warns that both `esbuild` and `oxc` options are set; `oxc` wins and `esbuild` JSX options are ignored. | `npm --prefix web run build` warning: `Both esbuild and oxc options were set...` | Not a blocking bug. Clean up Vite build config when touching frontend build tooling. |
| VIB-FE-OBS-20260611-002 | Open | Bundle size | `three.module-CzzXn1T9.js` is larger than Vite/Rolldown's 500 kB warning threshold after minification. | `npm --prefix web run build`: `three.module-CzzXn1T9.js` around 722.74 kB. | Not a blocking bug. Consider dynamic import/code splitting for 3D-heavy routes if startup performance becomes a user-visible issue. |

## Commands Run

```powershell
npm --prefix web run test -- src/routes/ConfigRoute.layout.test.ts src/routes/configRouteLogic.test.ts src/routes/ChatCodingRoute.layout.test.ts src/components/conversation/ConversationView.test.tsx src/routes/AgentsRoute.layout.test.ts src/routes/TeamsRoute.layout.test.ts src/routes/TeamsRoute.logic.test.ts src/routes/AgentSessionTabStrip.test.tsx src/routes/SessionContextMenu.test.tsx
```

Result: 9 test files passed, 218 tests passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -k "config_workspace_apply"
```

Result: 5 passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -k "submit_session_message_runs_turn_and_persists_reply or submit_session_message_prefer_async_returns_lightweight_acceptance or submit_session_message_rejects_blank_message_without_mutating_session or edit_resubmit_session_message_truncates_following_history_and_starts_turn or create_session_persists_new_active_empty_conversation or update_session_agent_id_persists_as_primary_binding"
```

Result: 6 passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_config_workspace_service.py::test_agent_config_workspace_api_route tests/test_team_routes.py
```

Result: 13 passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_team_service.py::test_team_detail_uses_lightweight_agent_references_for_member_repair tests/test_team_service.py::test_team_graph_references_skip_linked_room_hydration_and_repair tests/test_team_service.py::test_agent_config_workspace_includes_team_reference
```

Result: 3 passed.

```powershell
npm --prefix web run build
```

Result: passed with the two warnings listed in Observations.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state
```

Result: failed; see `VIB-FE-20260611-001`.

## Fix Agent Follow-Up Commands

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state
```

Result before fix: failed; extra dataset in actual API payload was `terminal_bench_agent_judged`.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state tests/test_web_app.py::test_workbench_dataset_list_backfills_new_builtin_datasets
```

Result after fix: 2 passed.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_dataset_registry.py::test_default_dataset_registry_lists_builtin_and_swe tests/test_dataset_registry.py::test_materialize_terminal_bench_agent_judged_uses_agent_scoring
```

Result after fix: 2 passed.

## Handoff Recommendation

`VIB-FE-20260611-001` has been fixed by treating `terminal_bench_agent_judged` as a valid Evolution Workbench dataset and updating the API contract tests. No Not fixed bug remains in the Bugs And Fix Status table at this point.
