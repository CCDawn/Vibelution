# Agent directory modules (`core/web/services/agent_directory`)

Ownership map for Agent registry / directory service.
Prefer slice modules over growing `agent_directory_service.py` when possible.

`agent_directory_service.py` remains the **public import facade**.

## 30-second routing (edit here first)

| You are changing… | Open first |
|-------------------|------------|
| Persona / task profile normalize | `profiles.py` |
| Tool / memory / delegation / supervision policy | `policies.py` |
| Archive / purge / reset | `lifecycle.py` |
| List/get / API hydration | `projections.py` |
| Create/update agent / avatar | `mutations.py` |
| Registry repair / load/save / shrink guard | `repair_store.py` |
| Inbox / workspace write / ensure-session / profile defaults | `ops_residual.py` |
| Personal lossless episode append / supersede | `episodic_memory.py` |
| Agent-facing private episode write/supersede tools | `tools/episodic_memory_tools.py` |
| Personal episode prompt dump | `projections.py` + `context_engine.py` |
| Lifecycle serializers on facade | `../agent_directory_service.py` (wrappers only) |
| Public import surface | `../agent_directory_service.py` (prefer re-export) |

Structure awareness (soft): `docs/standards/development-standard.md` §8.3.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Persona / task profile pure normalizers | `profiles.py` | registry save/load |
| Tool/memory/delegation/supervision policy | `policies.py` | session submit |
| Archive / purge / reset lifecycle | `lifecycle.py` | team membership graph |
| List/get API hydration projections | `projections.py` | team canvas |
| Create/update + avatar mutations | `mutations.py` | lifecycle purge path |
| Registry repair / load-save / normalize | `repair_store.py` | workflow orchestration |
| Inbox / workspace / ensure-session residual | `ops_residual.py` | team membership graph |
| Personal lossless episode jsonl | `episodic_memory.py` | `team_knowledge`, `outcomeGraph`, `memory_graph_service` |
| Generation-handoff brain (`memory.json`) | self-evolution tool policy | default session `allowedTools` / `core` bundle |

## Sole-owner rules

1. Pure profile normalizers stay free of registry locks and disk IO.
2. Policy evaluate/normalize stay free of create/update registry mutations.
3. Lifecycle archive/purge/reset keep serializer wrappers on the facade (`__wrapped__` identity).
4. Re-export public symbols from `agent_directory_service` for route stability.
5. `get_core_context_tool` / `get_current_goal_tool` / `commit_compressed_memory_tool` belong to self-evolution generation handoff, not the default session pack.
6. Current personal episodes are dumped into `build_agent_context` so every session of the same Agent can see them.

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| `profiles.py` | done | persona/task profile normalizers (Stage 4) |
| `policies.py` | done | Phase 11 — policy normalize/evaluate/resolve |
| `lifecycle.py` | done | Phase 11 — archive/purge/reset |
| `projections.py` | done | Phase 12 — list/get + hydration + API builders |
| `mutations.py` | done | Phase 12 — create/update + avatar |
| `repair_store.py` | done | Phase 17 — registry repair/load-save |
| `ops_residual.py` | done | Phase 17 — inbox/workspace/ensure-session residual |
| `episodic_memory.py` | done | P0 — lossless `episodic_events.jsonl`; no summaries/public lift |
| facade residual | serializers only | lifecycle wrappers |

## Related

- Routes: `core/web/routes/agents.py`
- Historical plans: `docs/archive/plans/2026-06-07/`
