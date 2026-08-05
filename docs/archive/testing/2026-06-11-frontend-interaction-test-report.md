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
| Peripheral route contracts | Passed | Logs/Git/Tools/Skills/Reset/Evolution/Launcher/AppShell Vitest subset: 19 files, 177 tests passed; full Vitest: 81 files, 740 tests passed |
| Logs/Git/Tools backend routes | Passed | `tests/test_web_log_routes.py tests/test_web_git_routes.py tests/test_tool_registry_routes.py`: 34 passed |
| Reset live summary API | Fixed in follow-up | original live `GET /api/reset/summary` took about 64.7s; current-main service profile reproduced 59.759s before fix and completed in 4.453s after fix |
| Production frontend build | Passed with warnings | `npm --prefix web run build` passed; see Observations |

## Bugs And Fix Status

| ID | Status | Severity | Area | Finding | Reproduction / Evidence | Notes For Fix Agent |
| --- | --- | --- | --- | --- | --- | --- |
| VIB-FE-20260611-001 | Fixed / current-main verified | P2 | Evolution Workbench route/API contract | `terminal_bench_agent_judged` is a valid primary Evolution Workbench dataset; the original Workbench API contract test was stale and did not include the newer agent-judged dataset. | Original reproduction failed with extra `terminal_bench_agent_judged`. Current-main recheck in `codex/fix-reset-summary-current-main`: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state` passed 1/1; combined dataset/API regression passed 4/4. | No route filtering was applied because registry tests define `terminal_bench_agent_judged` as an `effective`, `primary`, selectable dataset with agent-judged evaluation semantics. Current task did not modify this fix. |
| VIB-FE-20260611-004 | Fixed | P2 | Reset page live load performance | The Reset page summary was slow because `get_reset_summary()` eagerly ran expensive filesystem discovery and deep size/file-count walks for every reset item. `python_test_caches` walked the whole project root, and `browser_profiles` recursively walked `.runtime` profile contents. | Reproduced on current main before fix with service profile against `C:\Users\17533\Desktop\Vibelution`: total 59.759s for 22 reset items; `browser_profiles` reported 9,943 files and `python_test_caches` 835 files. Verified after fix in `codex/fix-reset-summary-current-main`: same profile completed in 4.453s; targeted reset/API tests passed 7/7; full reset subset passed 19/19; dataset contract subset passed 4/4; `npm --prefix web run build` passed with existing warnings. | Fixed by narrowing Python cache discovery to bounded Python-bearing roots, replacing recursive `.runtime` profile discovery with shallow profile-directory discovery, using a single capped fast totals pass for summary, adding `scanTruncated` to the Reset summary DTO, adding `reset.summary.generated` runtime-scene timing logs, and adding regression tests for bounded cache/profile discovery plus summary logging. |
| VIB-FE-20260611-002 | Fixed | P2 | Team page navigation/list | Team page previously exposed evolution system teams in the ordinary custom Team list, which could pollute Team navigation and selection. | Fixed by commit `ca3ab98c` (`fix: hide evolution system teams from team list`). Current targeted checks passed: `web/src/routes/TeamsRoute.layout.test.ts` includes `visibleTeams` filtering; `tests/test_team_routes.py` passed 12 route tests. | Keep ordinary Team list filtered through `visibleTeams`; system teams such as `self-evolution-team` and `supervised-evolution-team` should remain out of the user-created Team list. |
| VIB-FE-20260611-003 | Fixed / guarded | P3 | Config page editable schema | Config workspace editable schema needed to keep Launcher-owned `runtime` and `workbench` startup settings visible in `publicConfig` but out of normal editable sections and editor metadata. | Guarded by `test_config_workspace_exposes_editor_schema_without_launcher_owned_startup_settings`; current config save subset passed 5/5. Related local commit: `6c6f88ef` (`test: align config workspace editor contract`) and merge `7abf45ae`. | Preserve the split: `runtime` and `workbench` may be shown as public config data, but should not appear in config page editable `editorSections`, `sections`, or `editorMeta` unless a Launcher-governed edit flow is deliberately introduced. |

## No New Bugs Found In This Round

- Config save flow: no new failure found in apply/save/stale-hash/deletion/pending-env scenarios.
- Chat/session send flow: no new failure found in create session, bind agent, send, edit-resubmit, async acceptance, or blank-message rejection scenarios.
- Agent/Team navigation flow: no new failure found in current layout contracts, route contracts, Team reference data, or HTTP route availability.
- Logs/Git/Tools/Skills/Evolution/Launcher/AppShell frontend contracts: no new Vitest failure found.

## Observations

| ID | Status | Area | Observation | Evidence | Suggested Follow-Up |
| --- | --- | --- | --- | --- | --- |
| VIB-FE-OBS-20260611-001 | Open | Build config | Build warns that both `esbuild` and `oxc` options are set; `oxc` wins and `esbuild` JSX options are ignored. | `npm --prefix web run build` warning: `Both esbuild and oxc options were set...` | Not a blocking bug. Clean up Vite build config when touching frontend build tooling. |
| VIB-FE-OBS-20260611-002 | Open | Bundle size | `three.module-DJYmThBH.js` is larger than Vite/Rolldown's 500 kB warning threshold after minification. | `npm --prefix web run build`: `three.module-DJYmThBH.js` around 722.74 kB. | Not a blocking bug. Consider dynamic import/code splitting for 3D-heavy routes if startup performance becomes a user-visible issue. |

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

```powershell
npm --prefix web run test -- src/routes/LogsRoute.layout.test.ts src/routes/logPackageIndex.test.ts src/routes/GitRoute.layout.test.ts src/routes/gitRouteLogic.test.ts src/routes/gitDiffView.test.ts src/routes/gitCommitUx.test.ts src/routes/ToolsRoute.layout.test.ts src/routes/SkillsRoute.layout.test.ts src/routes/ResetRoute.layout.test.ts src/routes/EvolutionRoute.layout.test.ts src/routes/evolutionLiveRun.test.ts src/routes/evolutionWorkspaceCache.test.ts src/routes/RuntimeScenesPane.layout.test.ts src/routes/runtimeScenePackageSections.test.ts src/routes/LauncherRoute.layout.test.ts src/app/AppShell.layout.test.ts src/app/workbenchContract.test.ts src/app/systemStatus.test.ts src/app/projectCloseGuard.test.ts
```

Result: 19 test files passed, 177 tests passed.

```powershell
npm --prefix web run test
```

Result: 81 test files passed, 740 tests passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_log_routes.py tests/test_web_git_routes.py tests/test_tool_registry_routes.py
```

Result: 34 passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -k "test_spa_route_still_falls_back_to_index_html or test_skills_api_lists_read_only_skill_library or test_skills_api_returns_skill_detail or test_reset_summary_shape"
```

Result: 4 passed.

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/reset/summary" -UseBasicParsing -TimeoutSec 120
```

Result: HTTP 200 after about 64.691 seconds; see `VIB-FE-20260611-004`.

```powershell
.\.venv\Scripts\python.exe -c "exec('''...timed reset_service._reset_items() summarization...''')"
```

Result: slowest reset summary work was `python_test_caches` about 37.9s, then `browser_profiles` about 8.6s.

## Fix Agent Follow-Up Commands

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state
```

Result on current main before this task's reset fix: 1 passed. `VIB-FE-20260611-001` is already fixed on current main.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -c "import time; from pathlib import Path; from core.web.services import reset_service as r; r.PROJECT_ROOT=Path(r'C:\Users\17533\Desktop\Vibelution'); r.get_web_language=lambda:'zh'; t=time.perf_counter(); p=r.get_reset_summary(); total=time.perf_counter()-t; picked=[(i['id'], i.get('fileCount'), i.get('sizeBytes')) for i in p['items'] if i['id'] in {'python_test_caches','browser_profiles'}]; print('total=%.3fs items=%d' % (total, len(p['items']))); print(picked)"
```

Result before `VIB-FE-20260611-004` fix on current main data: total 59.759s for 22 reset items; `browser_profiles` and `python_test_caches` were the slow high-count items.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_reset_service.py::test_reset_summary_includes_memory_as_optional_item tests/test_reset_service.py::test_reset_summary_records_timing_event tests/test_reset_service.py::test_browser_profile_cleanup_protects_current_profile tests/test_reset_service.py::test_browser_profile_collection_uses_shallow_runtime_discovery tests/test_reset_service.py::test_python_cache_collection_uses_bounded_code_roots tests/test_reset_service.py::test_reset_routes_expose_preview_and_execute tests/test_web_app.py::test_reset_summary_shape
```

Result after fix in `codex/fix-reset-summary-current-main`: 7 passed.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -c "import time; from pathlib import Path; from core.web.services import reset_service as r; r.PROJECT_ROOT=Path(r'C:\Users\17533\Desktop\Vibelution'); r.get_web_language=lambda:'zh'; t=time.perf_counter(); p=r.get_reset_summary(); total=time.perf_counter()-t; picked=[(i['id'], i.get('fileCount'), i.get('sizeBytes'), i.get('scanTruncated')) for i in p['items'] if i['id'] in {'python_test_caches','browser_profiles'}]; print('total=%.3fs items=%d' % (total, len(p['items']))); print(picked)"
```

Result after fix in `codex/fix-reset-summary-current-main`: total 4.453s for 22 reset items; `browser_profiles` summary is capped with `scanTruncated=true`, and `python_test_caches` no longer walks runtime/workspace/log trees.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_reset_service.py tests/test_web_app.py::test_reset_summary_shape
```

Result after fix in `codex/fix-reset-summary-current-main`: 19 passed.

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py::test_evolution_workbench_route_exposes_dataset_choices_and_saved_state tests/test_web_app.py::test_workbench_dataset_list_backfills_new_builtin_datasets tests/test_dataset_registry.py::test_default_dataset_registry_lists_builtin_and_swe tests/test_dataset_registry.py::test_materialize_terminal_bench_agent_judged_uses_agent_scoring
```

Result after fix in `codex/fix-reset-summary-current-main`: 4 passed.

```powershell
npm --prefix web run build
```

Result after fix in `codex/fix-reset-summary-current-main`: passed with the existing `esbuild`/`oxc` and large `three.module` warnings.

## Handoff Recommendation

`VIB-FE-20260611-001` is fixed on current main, and `VIB-FE-20260611-004` is fixed in `codex/fix-reset-summary-current-main`. No Not fixed bug remains in the Bugs And Fix Status table at this point.
