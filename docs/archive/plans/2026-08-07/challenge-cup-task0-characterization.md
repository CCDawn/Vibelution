# Task 0 · Characterization Evidence

Status: **Locked 2026-08-07**

Branch: `codex/challenge-workflow-impl` @ planning base `b6a41e3e` + this commit

## 1. Baseline identity

| Item | Value |
| --- | --- |
| Planning commit | `b6a41e3ec` (ADRs 0006/0007 + implementation plan + disposition) |
| Main at planning | ancestor of planning branch |
| Implementation worktree | `Vibelution-worktrees/challenge-workflow-impl` |
| Claim | `claim-c3ea7d7d348e` / lane `research-workflow` |

## 2. Dual SSOT (production writers)

| Surface | Function | Source of truth today |
| --- | --- | --- |
| GET `/api/research/flow-canvas` | `get_research_flow_canvas` | **Organization graph** via `_research_organization_flow_canvas()`; `locked: true` |
| Saved file `flow_canvas.json` | `_get_saved_research_flow_canvas` | Disk worker/pipeline canvas (may differ from GET) |
| POST `/api/research/flow-canvas/execute` | `execute_research_flow_canvas_node` | **Saved** canvas only (`_get_saved_research_flow_canvas`) |
| PUT `/api/research/flow-canvas` | `save_research_flow_canvas` | Writes disk; GET still re-projects org for display |

### Characterization tests

- `tests/test_challenge_cup_workflow_task0_characterization.py`
  - GET ≠ saved worker node ids
  - execute uses saved worker node ids
  - no third runtime route yet
- Existing coverage (keep):
  - `test_research_flow_canvas_is_locked_to_research_organization_graph`
  - `test_research_flow_canvas_executes_next_ready_node_and_routes_successors`

### Third writer search

- Only `core/web/routes/research.py` exposes `/research/flow-canvas/execute`.
- No `research_runtime.py` LangGraph route exists yet.
- **No third production execute writer found.** Migration risk is dual (GET org vs execute saved), not triple.

## 3. Router / page inventory

| Entry | Reachable? | Disposition (from plan) |
| --- | --- | --- |
| `/teams` | yes | KEEP → canonical workflow default |
| `/research` | yes → `LegacyTeamsRedirect` | REDIRECT |
| `/research/flow-canvas` | yes → lazy `ResearchFlowCanvasRoute` | REDIRECT then REMOVE page |
| `ResearchRoute.tsx` | **orphan** (not in router) | REMOVE |
| ChallengeCupOperationsWorkspace + StageRail | yes via Teams | REMOVE after adapters |
| ResearchOverviewSurface / ResearchStageNav | yes | REMOVE after switch |
| TeamKnowledgeCollectionCompletionFlowPanel | yes | REMOVE |
| TeamOrganizationCanvasSurface | yes | KEEP generic Teams; Challenge Cup secondary |
| researchStageAgentBindings | yes | KEEP as migration input |

Frontend inventory test:

- `web/src/routes/teams/research-workflow/researchLegacySurfaceInventory.test.ts`

## 4. Agent session / task / turn baseline

| Capability | Current state |
| --- | --- |
| `returnTo` safe path | Present (`navigationReturn.ts`) |
| Research project agent tasks | `taskId`, optional `sessionId` on task models |
| Chat `focusTask` / `focusTurn` | **Not** a standard deep-link contract yet (Task 7) |
| Node → exact session attempt lineage | **Not** persisted as NodeAgentSessionBinding |
| RunAgentBindingSnapshot | **Not** present; bindings read live config/canvas |

## 5. Behaviors to preserve vs replace

| Preserve | Replace with new domain |
| --- | --- |
| Organization graph for generic Teams | Flow-canvas as run graph |
| Agent Center identity/config | Binding uses stable agentId only |
| SC / experiment / iteration business panels | Mount as node adapters |
| Historical knowledge/protocol/artifacts data | NodeHandoff + ArtifactRef |
| Legacy URL reachability during migration | Compatibility resolver → canonical URL |

| Replace (do not preserve as SSOT) | Reason |
| --- | --- |
| GET org graph as “workflow run” | Wrong graph |
| execute saved canvas writer | Dual write / non-LangGraph |
| selectedNode / stage tab as runtime current | UI-only |
| Stage rail / overview dual nav | Duplicate stage navigation |
| Display name agent authorization | ADR 0007 |

## 6. Disposition table coverage check

Disposition file:

`docs/archive/plans/2026-08-07/challenge-cup-legacy-surface-disposition.md`

All inventory rows above are covered. Unknown `collectionStage` values must map to workflow global view (not blank).

## 7. Stop conditions (Task 0)

- [x] Dual SSOT proven by focused tests
- [x] No third execute writer found
- [x] Orphan ResearchRoute documented
- [x] Session anchor gap documented
- [ ] **Do not change production behavior in Task 0**

## 8. Next

Task 1: `core/research/workflow/` domain contracts + fixed node catalog + handoff/binding types + TS DTO mirror.
