# Agent Tool Authorization Entry Points

This inventory is the Milestone 0 baseline for the unified authorization design. It records where tools become visible to a model and where calls reach executable implementations. It does not change runtime behavior.

## Policy baselines

| Agent class | Current policy source | Migration requirement |
|---|---|---|
| Default session Agent | private session default policy | Preserve the complete current coding tool assignment |
| Explicit zero-tool Agent | private policy with `allowedTools=[]` | Preserve zero tools as an explicit valid policy |
| Research fixed role | `agent_role_tool_profile_service` | Materialize the role profile as ordinary ToolPolicy v2 |
| Team operation role | `agent_role_tool_profile_service` | Materialize bounded context/writeback policy |
| Self-evolution executor | executable session policy | Materialize explicit policy without broadening |
| Supervised/observer role | system no-tool role | Materialize explicit zero-tool policy |
| Legacy wide private policy | Agent Directory private policy | Preserve and label for operator review |
| Missing/corrupt policy | unresolved state | Deny all and require repair |

The machine-readable baseline is `tests/fixtures/tool_authorization/agent_policy_baselines.json`.

## Model visibility entry points

| Entry | Run kinds | Current authority | Target authority |
|---|---|---|---|
| `SelfEvolvingAgent._init_llm` | session, room, team, research, evolution | current-Agent filter | `AuthorizationDecision.visibleTools` |
| `SelfEvolvingAgent._get_llm_for_current_mode` | all Agent modes | mode and Agent filters | `AuthorizationDecision.visibleTools` |
| `run_existing_agent_single_turn` | direct session, chat room | Agent-bound surface | host `TurnToolGrant` plus decision |
| Responses wire projection | all LLM turns, replay, parallel | bound semantic tools | protocol projection of the same decision |
| Chat Completions wire projection | all LLM turns, replay, parallel | bound semantic tools | protocol projection of the same decision |
| Subagent runtime binding | delegated work | parent runtime plus child filter | parent grant intersect child policy |

Protocol adapters project schemas only. They must never add, remove, or reinterpret authorization.

## Execution entry points

| Entry | Current authority | Target authority |
|---|---|---|
| `ToolLifecycleBridge` | Agent guard plus lifecycle checks | authorization pre-dispatch check with Agent/turn/call identity |
| `ToolExecutor.execute` | distributed special guards | mandatory final `authorize_tool_call` before implementation dispatch |

Both layers remain useful: the lifecycle layer binds semantic call identity, while the executor is the non-bypassable security boundary.

## Required run-kind coverage

- `direct_session`
- `chat_room`
- `team_workflow`
- `research`
- `supervised`
- `self_evolution`
- `replay`
- `parallel`
- `subagent`

The machine-readable inventory is `tests/fixtures/tool_authorization/runtime_entrypoints.json`.

## Known bypass risks to eliminate

1. Permission lookup exceptions can return an unfiltered tool list.
2. Missing runtime-goal facts can permit selected operations.
3. Replay or direct dispatch can reach the executor without proving model visibility.
4. Subagent permission inheritance is not a formal parent/child intersection.
5. Protocol requests do not bind schemas and execution to one authorization fingerprint.

## Milestone 0 exit contract

Milestone 1 may start when:

- all policy baseline fixtures pass structural and current-contract tests;
- every required run kind appears in both visibility and dispatch inventories;
- default session tools and explicit zero-tool policies are protected from silent migration drift;
- known bypass risks have named target owners.
