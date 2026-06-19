# Unified Agent Configuration Architecture

Date: 2026-05-27
Owner: agent runtime / settings
Status: implementation-ready design

## Goal

Unify Vibelution's scattered Agent settings into one maintainable architecture where every long-lived Agent is represented by a persistent `AgentInstance`.

This design covers:

- chat session agents
- research agents
- self-evolution agents
- supervised-evolution agents
- future specialist lanes
- temporary sub-agent / background-task boundaries

The final state must not be "old config plus a nicer settings page". Compatibility code is allowed only as a migration scaffold. After migration, the old per-mode Agent binding fields should be removable without changing runtime behavior.

## Confirmed Product Decisions

The following decisions are locked from the BRT alignment:

- `AgentInstance` becomes the single source of truth for long-lived Agents.
- Models are not Agents. `LLMProfile` only describes model/provider/key behavior.
- System prompts are their own layer. `AgentInstance` references a `PromptTemplate` instead of embedding full prompt text.
- Long-lived Agents are globally reusable. A `primaryMode` only controls default grouping in settings.
- Modes reference Agents through `ModeBinding`.
- Fixed-role modes use role slots. Example: `supervised_evolution.slots.reviewer -> agentId`.
- Open-ended modes use an Agent pool. Example: research mode owns a pool of available research Agents.
- Long-lived Agents default to strong isolation:
  - independent `workspacePath`
  - independent `directSessionId` / sessions
  - independent `memoryPolicyId`
  - independent `toolPolicyId`
  - independent runtime state
- Long-lived Agents may share:
  - `LLMProfile`
  - `PromptTemplate`
- Temporary sub-agents are background runs, not long-lived settings entries.
- Sub-agent context is isolated by default. `contextMode="fork"` must be explicit.

## Current Starting Point

Current code already has the first half of the target shape:

- `core/web/services/agent_directory_service.py`
  - persistent `AgentInstance` registry
  - `agentId`, `agentCode`, `profileId`, `directSessionId`, `workspacePath`, `toolPolicyId`, `memoryPolicyId`
  - runtime context, tool policy, memory policy, inbox messages
- `web/src/api/types.ts`
  - frontend `AgentInstance`
  - `ResearchAgentConfig`
  - `ConversationSummary`
- `core/web/services/session_service.py`
  - historical chat sessions may carry `agent_profile_id`, but new saves use `agentId`
  - direct sessions are repaired into AgentInstances
- `core/research/agent_templates.py`
  - research still exposes `ResearchAgentConfig` aliases for older UI/API readers, but new model binding storage uses `profileId` plus `agentId`
- `core/web/services/supervised_agent_service.py`
  - supervised fixed roles already sync into persistent AgentInstances
- `scripts/evolution_harness.py` and `agent.py`
  - supervised baseline/candidate subprocesses can receive Agent binding and map the bound profile into the runtime primary profile
- `web/src/routes/ConfigRoute.tsx`
  - settings already displays supervised and research Agent bindings in the model config area

The main problem is not lack of an Agent registry. The problem is that each mode still has private binding vocabulary:

- chat: `agent_profile_id`
- research: `agentKey`, `llmConfigId`, `promptFilename`, `templateId`
- supervised evolution: fixed role metadata and binding payloads
- self-evolution: still needs explicit long-lived role Agents
- prompt settings: prompt sections and feature prompt files are not yet modeled as reusable `PromptTemplate`

## Architecture Layers

### 1. `LLMProfile`

Purpose: model capability.

It answers:

- which provider
- which model id
- which key/env
- timeouts
- streaming/tool-call mode
- context window
- test/warmup/discovery behavior

It must not answer:

- what job the Agent performs
- which mode owns the Agent
- what prompt/persona the Agent uses
- where the Agent stores memory

Existing source:

- `config.models.LLMConfig.profiles`
- config editor model profile UI

### 2. `PromptTemplate`

Purpose: reusable prompt/persona/contract layer.

It answers:

- system prompt or role prompt text
- output contract
- prompt category
- version / source file
- default language or style if needed

Suggested fields:

```json
{
  "promptTemplateId": "prompt-research-broad",
  "name": "科研广搜提示词",
  "category": "research",
  "sourceType": "workspace_file",
  "sourcePath": "workspace/prompts/research/broad.md",
  "contentHash": "sha256:...",
  "status": "active",
  "metadata": {
    "defaultForRoleKey": "research_broad"
  },
  "createdAt": "...",
  "updatedAt": "..."
}
```

Storage options:

- Phase 1 can keep existing prompt files as the physical source.
- Add a prompt-template index that maps IDs to files.
- Do not move all prompt text into JSON at once.

Recommended initial storage:

```text
workspace/agent_config/prompt_templates.json
workspace/prompts/research/*.md
workspace/prompts/*.md
```

This gives a clean logical layer while preserving existing file editing workflows.

### 3. `AgentInstance`

Purpose: long-lived Agent identity and isolated brain boundary.

It answers:

- who this Agent is
- which model profile it uses
- which prompt template it uses
- which workspace/session/memory/tool policy belongs to it
- which mode it is primarily grouped under
- which stable role key it commonly represents

Target fields:

```json
{
  "agentId": "agent-abc123",
  "agentCode": "A001",
  "displayName": "科研广搜 Agent",
  "kind": "persistent",
  "primaryMode": "research",
  "roleKey": "research_broad",
  "templateId": "research_broad_explorer",
  "profileId": "research_broad",
  "promptTemplateId": "prompt-research-broad",
  "directSessionId": "session-...",
  "workspacePath": "workspace/agents/agent-abc123",
  "toolPolicyId": "tool-agent-abc123",
  "memoryPolicyId": "memory-agent-abc123",
  "status": "active",
  "metadata": {
    "createdBy": "research_agent_migration"
  },
  "createdAt": "...",
  "updatedAt": "..."
}
```

Compatibility with current fields:

- Keep `profileId`.
- Keep `templateId` for now, but treat it as default seed, not runtime source of truth.
- Add `primaryMode`.
- Add `roleKey`.
- Add `promptTemplateId`.

The important line is: runtime code should eventually read `AgentInstance`, not the per-mode config object.

### 4. `ModeBinding`

Purpose: mode orchestration and role assignment.

It answers:

- which long-lived Agents are used by a mode
- which slot each Agent fills
- which Agent pool a dynamic mode may use
- which default Agent should be selected

It must not duplicate:

- model config
- prompt text
- workspace
- memory/tool policy

Suggested storage:

```text
workspace/agent_config/mode_bindings.json
```

Target shape:

```json
{
  "schemaVersion": 1,
  "modes": {
    "chat": {
      "defaultAgentId": "agent-chat-default",
      "availableAgentIds": ["agent-chat-default", "agent-research-review"]
    },
    "research": {
      "pool": ["agent-research-broad", "agent-research-deep", "agent-research-review"],
      "flowBindings": {
        "broad_search": "agent-research-broad",
        "deep_search": "agent-research-deep"
      }
    },
    "self_evolution": {
      "slots": {
        "executor": "agent-self-executor",
        "reviewer": "agent-self-reviewer",
        "summarizer": "agent-self-summarizer"
      }
    },
    "supervised_evolution": {
      "slots": {
        "baseline": "agent-supervised-baseline",
        "candidate": "agent-supervised-candidate",
        "reviewer": "agent-supervised-reviewer",
        "auditor": "agent-supervised-auditor",
        "judge": "agent-supervised-judge"
      }
    }
  }
}
```

### 5. `AgentRun` and `SubAgentRun`

Purpose: runtime execution, not settings.

Long-lived Agents can run turns, sessions, workbench jobs, research steps, supervised cases, or background tasks.

Suggested distinction:

- `AgentInstance`: persistent identity.
- `AgentRun`: one runtime invocation for a persistent Agent.
- `SubAgentRun`: temporary background run spawned by another Agent.

Sub-agent rules:

- not shown in long-lived Agent settings
- has `runId`
- has `parentAgentId`
- has `parentSessionId` or `parentRunId`
- default `contextMode="isolated"`
- optional `contextMode="fork"`
- default no message/session/system tools unless explicitly granted
- writes result back to parent run/session
- should be visible under background tasks/history

Suggested shape:

```json
{
  "runId": "subrun-...",
  "runKind": "sub_agent_run",
  "parentAgentId": "agent-...",
  "parentSessionId": "session-...",
  "agentId": "agent-temp-or-specialist",
  "contextMode": "isolated",
  "status": "running",
  "depth": 1,
  "maxDepth": 2,
  "createdAt": "...",
  "endedAt": "",
  "resultRef": ""
}
```

This follows the useful OpenClaw distinction without copying its storage layout directly.

## Context Boundary

Vibelution should introduce a `ContextEngine` boundary before adding more multi-Agent complexity.

Responsibilities:

- ingest new message/event
- assemble model context
- include Agent runtime context block
- include inbox messages
- include group context events
- compact history
- persist after turn
- prepare sub-agent spawn context
- handle sub-agent completion callback

Candidate module:

```text
core/orchestration/context_engine.py
```

Initial public functions:

```python
build_agent_context(agent_id: str, *, session_id: str = "", run_id: str = "") -> AgentContextPacket
prepare_subagent_spawn(parent_agent_id: str, parent_session_id: str, *, context_mode: str) -> SubAgentContextPacket
record_agent_turn_result(agent_id: str, session_id: str, result: dict) -> None
record_subagent_result(parent_run_id: str, sub_run_id: str, result: dict) -> None
```

Do not put multi-Agent context boundaries only into prompt text. Prompt text can describe the rule, but code must own the routing and isolation.

## Settings Information Architecture

Settings should use user-facing concepts, not internal migration terms.

Recommended sections:

### Model Config

Contents:

- providers
- profiles
- model discovery
- key source and key health
- lightweight test
- warmup test

Do not show:

- Agent role
- mode binding
- prompt file names except model-related test prompt if necessary

### Prompt Templates

Contents:

- prompt template list
- category
- source file
- edited content
- usage count
- linked Agents
- reset to default

Grouping:

- 通用
- 会话
- 科研
- 自进化
- 监督进化
- 工具/诊断

### Agent Config Center

Contents:

- all long-lived Agents
- grouped by `primaryMode`
- search/filter by mode, role, model, prompt, status
- each row shows:
  - `agentCode`
  - display name
  - primary mode
  - role key
  - referenced by modes
  - model profile
  - prompt template
  - tool policy
  - memory policy
  - workspace
  - direct session
  - status

Actions:

- create Agent
- edit Agent
- archive Agent
- duplicate Agent from template
- open direct session
- inspect workspace/events

Do not show temporary sub-agents here.

### Mode Bindings

Contents:

- chat mode:
  - default Agent
  - available Agents
- research mode:
  - Agent pool
  - flow node bindings
- self-evolution:
  - role slots
- supervised evolution:
  - role slots

Fixed role slot UI:

```text
Role             Bound Agent          Model        Prompt       Status
baseline         A012 监督基线 Agent   qwen-plus    监督基线模板 active
candidate        A013 监督候选 Agent   qwen-plus    监督候选模板 active
reviewer         A014 监督评审 Agent   gpt-...      评审模板     active
```

Dynamic pool UI:

```text
科研 Agent 池
[+] 添加 Agent
A021 广搜 Agent
A022 深搜 Agent
A023 证据审查 Agent
```

Flow nodes should reference `agentId`, not `llmConfigId`.

## Data Migration Strategy

Migration must be incremental but terminal. Compatibility code gets an exit plan from the start.

### Phase 0: Schema Additions Only

Add fields to `AgentInstance`:

- `primaryMode`
- `roleKey`
- `promptTemplateId`

Add stores:

- `workspace/agent_config/prompt_templates.json`
- `workspace/agent_config/mode_bindings.json`

No runtime behavior changes yet.

Tests:

- create/update/repair AgentInstance preserves old fields
- new fields default correctly
- unknown fields do not crash old records

Logging:

- `agent_directory.schema_repaired`
- log counts only, not prompt text or secrets

### Phase 1: PromptTemplate Index

Create a logical prompt template registry over existing prompt files.

Examples:

- research `broad.md` -> `prompt-research-broad`
- supervised baseline prompt -> `prompt-supervised-baseline`
- chat default prompt -> `prompt-chat-default`
- self-evolution executor prompt -> `prompt-self-executor`

Do not move text yet.

Tests:

- missing prompt index can be repaired from defaults
- prompt template points only to safe project-local files
- linked Agent resolves prompt content through `promptTemplateId`

Logging:

- `prompt_template.repaired`
- `prompt_template.missing_source`

### Phase 2: ModeBinding Store

Create and repair `mode_bindings.json`.

Initial binding sources:

- chat:
  - existing direct session AgentInstances
  - current active/default Agent
- research:
  - existing `ResearchAgentConfig.agentId` or repaired AgentInstance
  - existing `key` becomes Agent `roleKey`
- supervised:
  - existing `supervised_agent_service` roles
- self-evolution:
  - create fixed role slot defaults if missing

Tests:

- fixed role binding repairs missing roles
- dynamic pool repairs research Agents
- binding never points to archived/missing Agent without producing a repair warning

Logging:

- `mode_binding.repaired`
- `mode_binding.missing_agent`
- `mode_binding.slot_created`

### Phase 3: Settings Writes Only New Structure

Settings UI edits should write:

- Agent edits -> `AgentInstance`
- prompt edits -> `PromptTemplate` source
- model edits -> `LLMProfile`
- mode role/pool edits -> `ModeBinding`

Old per-mode structures may still be read for repair, but UI must stop writing them.

Specific changes:

- Research Agent edit form saves AgentInstance + ModeBinding.
- Research flow node editor saves `agentId`, not `llmConfigId`.
- Chat Agent selector saves `agentId`, not only `agent_profile_id`.
- Supervised role table edits `ModeBinding.slots`.
- Self-evolution role table edits `ModeBinding.slots`.

Tests:

- saving research Agent does not write new `llmConfigId` into legacy config as source of truth
- saving flow node persists `agentId`
- saving role slot changes only binding, not model profile
- settings dirty/save guard still works

### Phase 4: Runtime Reads `AgentInstance`

Runtime code consumes `AgentInstance` first.

Chat:

- submit turn resolves `agentId`
- Agent runtime config maps `AgentInstance.profileId` to runtime primary profile
- prompt is loaded through `AgentInstance.promptTemplateId`

Research:

- `LLMResearchAgentRunner` resolves node `agentId`
- model comes from AgentInstance profile
- prompt comes from AgentInstance prompt template
- `agentKey` remains only as migration/display alias

Supervised:

- baseline/candidate/reviewer/auditor/judge resolve through `ModeBinding.slots`
- harness receives Agent binding from the slot AgentInstance

Self-evolution:

- executor/reviewer/summarizer resolve through `ModeBinding.slots`
- risky write and review flows keep existing lease/transaction boundaries

Tests:

- chat session uses bound Agent model and prompt
- research run uses AgentInstance model/prompt, not legacy `llmConfigId`
- supervised run uses slot AgentInstance
- self-evolution role lookup fails clearly if required slot missing

Logging:

- `agent_runtime.resolved`
- `agent_runtime.resolve_failed`
- include `agentId`, `agentCode`, `profileId`, `promptTemplateId`, `mode`, `roleKey`
- never log API keys or full prompt text

### Phase 5: Compatibility Exit

Remove or downgrade legacy fields after evidence shows no new writes.

Exit requirements:

- no UI write path writes legacy Agent binding fields
- runtime reads `AgentInstance` and `ModeBinding`
- migration tests cover old data repair
- logs show successful repair events
- static search shows legacy fields only in migration code, tests, or archived docs
- deleting compatibility reader does not break focused tests

Candidates for cleanup:

- research runtime dependency on `ResearchAgentConfig.llmConfigId`
- research runtime dependency on `ResearchAgentConfig.promptFilename`
- chat runtime dependency on `agent_profile_id` as source of truth
- supervised ad hoc binding payload construction outside `ModeBinding`
- duplicated model-role labels in settings

## Concrete Implementation Slices

### Slice 1: Extend AgentInstance Shape

Files:

- `core/web/services/agent_directory_service.py`
- `web/src/api/types.ts`
- `tests/test_supervised_agent_instances.py`
- `tests/test_multi_agent_conversations.py`

Work:

- add `primaryMode`, `roleKey`, `promptTemplateId`
- repair old Agent records
- expose fields through API
- update TypeScript type

Validation:

- Agent create/update/repair tests
- API shape tests
- py_compile

### Slice 2: Prompt Template Registry

Files:

- new `core/web/services/prompt_template_service.py`
- new `tests/test_prompt_template_service.py`
- `web/src/api/types.ts`

Work:

- create prompt template store
- seed from existing research prompt files and core prompt defaults
- safe project-local path validation
- read/update/reset prompt template

Validation:

- missing store repair
- unsafe path rejection
- source file missing warning
- content hash updates after edit

### Slice 3: Mode Binding Store

Files:

- new `core/web/services/agent_mode_binding_service.py`
- tests
- possibly `core/web/routes/agents.py`

Work:

- create `mode_bindings.json`
- repair chat/research/self/supervised bindings
- expose API for settings

Validation:

- default bindings created
- fixed slots created
- research pool populated from existing research agents
- archived Agent is reported and not silently used

### Slice 4: Research Migration

Files:

- `core/research/agent_templates.py`
- `core/research/agent_runner.py`
- `core/web/services/research_service.py`
- `web/src/routes/ResearchFlowCanvasRoute.tsx`
- `web/src/routes/ConfigRoute.tsx`
- tests around research config and flow canvas

Work:

- create/reuse AgentInstance for every research Agent
- flow nodes store `agentId`
- runner resolves model/prompt through AgentInstance
- legacy `agentKey/llmConfigId/promptFilename` used only for repair

Validation:

- old research config repairs to AgentInstance
- new settings save writes AgentInstance and ModeBinding
- runner ignores stale `llmConfigId` when `agentId` exists
- flow canvas remains backward compatible for old files

### Slice 5: Chat Migration

Files:

- `core/web/services/session_service.py`
- `core/web/services/conversation_service.py`
- `web/src/routes/ChatCodingRoute.tsx`
- tests around sessions/conversations

Work:

- persist `agentId` as primary chat session binding
- keep `agent_profile_id` as repair-only compatibility field
- chat turn resolves AgentInstance before model/prompt

Validation:

- old session with only `agent_profile_id` repairs to direct AgentInstance
- new session stores `agentId`
- changing selected Agent updates AgentInstance binding, not only profile id

### Slice 6: Self-Evolution Role Slots

Files:

- `core/web/services/self_evolution_control_service.py`
- new or shared `agent_mode_binding_service.py`
- settings UI
- tests

Work:

- define fixed slots: `executor`, `reviewer`, `summarizer`
- create default Agents if missing
- runtime resolves roles through ModeBinding

Validation:

- missing slot repair
- archived slot Agent blocks with clear error
- self-evolution run snapshot logs resolved role Agent IDs

### Slice 7: Supervised Role Slots

Files:

- `core/web/services/supervised_agent_service.py`
- `core/web/services/supervised_control_service.py`
- `core/evaluation/supervised_evolution.py`
- settings UI
- tests

Work:

- move role source from metadata scan to `ModeBinding.slots`
- keep metadata only for display/repair
- harness binding comes from slot AgentInstance

Validation:

- existing supervised roles migrate into ModeBinding
- role replacement affects next run
- baseline/candidate subprocess receives replaced Agent binding

### Slice 8: Settings IA Cleanup

Files:

- `web/src/routes/ConfigRoute.tsx`
- `web/src/routes/configRouteLogic.ts`
- `web/src/routes/configRouteLogic.test.ts`
- CSS

Work:

- split settings into:
  - Model Config
  - Prompt Templates
  - Agent Config Center
  - Mode Bindings
- stop showing hidden migration terms
- show compatibility warnings only when repair is needed

Validation:

- layout tests
- logic tests for grouping and counts
- dirty save guard
- no text overlap across main viewports if frontend is changed materially

## API Sketch

### Agent APIs

```http
GET /api/agents
POST /api/agents
PATCH /api/agents/{agentId}
DELETE /api/agents/{agentId}
```

Extend payload with:

```json
{
  "primaryMode": "research",
  "roleKey": "research_broad",
  "promptTemplateId": "prompt-research-broad"
}
```

### Prompt Template APIs

```http
GET /api/prompt-templates
GET /api/prompt-templates/{id}
PATCH /api/prompt-templates/{id}
POST /api/prompt-templates/{id}/reset
```

### Mode Binding APIs

```http
GET /api/agent-mode-bindings
PATCH /api/agent-mode-bindings/{mode}
PATCH /api/agent-mode-bindings/{mode}/slots/{slot}
PATCH /api/agent-mode-bindings/{mode}/pool
```

Validation:

- slot Agent must exist and be active
- pool Agent IDs must exist and be active
- mode must be known
- slot must be known for fixed-role modes
- archived Agent replacement should be explicit, not silent

## Logging Contract

New behavior should log at actual state transitions:

- `agent_directory.schema_repaired`
- `prompt_template.repaired`
- `prompt_template.updated`
- `mode_binding.repaired`
- `mode_binding.updated`
- `agent_runtime.resolved`
- `agent_runtime.resolve_failed`
- `agent_migration.legacy_binding_repaired`
- `agent_migration.compat_read_used`

Fields:

- `agentId`
- `agentCode`
- `mode`
- `roleKey`
- `slot`
- `profileId`
- `promptTemplateId`
- `source`
- `repairCount`
- `status`

Never log:

- API keys
- full prompt text
- full transcript
- unbounded tool output
- raw environment variables

## Test Strategy

Minimum useful test layers:

### Unit tests

- Agent repair defaults
- Prompt template normalization
- ModeBinding validation
- legacy-to-new migration helpers
- slot vs pool behavior

### Integration tests

- `/api/agents` returns new fields
- prompt template update modifies source safely
- mode binding update changes next runtime resolution
- old research config migrates
- old chat session migrates
- supervised role replacement affects next run binding

### Frontend tests

- ConfigRoute grouping
- Agent table row content
- mode binding role-slot editor
- research pool editor
- dirty save prompt
- no migration terms shown as primary UX

### Runtime tests

- chat turn uses AgentInstance profile/prompt
- research node uses AgentInstance profile/prompt
- supervised harness receives slot Agent binding
- self-evolution run logs role Agent resolution
- sub-agent run remains background task, not persistent Agent

## Compatibility Policy

Allowed temporarily:

- reading `agent_profile_id` to repair chat sessions
- reading research `llmConfigId`, `promptFilename`, `templateId` to seed AgentInstance and PromptTemplate
- reading supervised role metadata to seed ModeBinding
- preserving old fields in serialized data while runtime no longer depends on them

Not allowed long term:

- new settings writes to legacy binding fields as source of truth
- runtime preferring legacy fields when `agentId` exists
- silent fallback that hides broken ModeBinding
- duplicated UI sections for the same Agent role
- sub-agent/background task entries in long-lived Agent config center

Compatibility code must be named as migration/repair code, not generic business logic.

## Compatibility Exit Audit

Current implementation status as of the 2026-05-27 compatibility pass:

- `ModeBinding.flowBindings` now participates in binding repair signatures, so flow-node binding normalization and repair are persisted instead of being treated as invisible metadata.
- Research Agent deletion checks the primary `agentId` binding as well as legacy `agentKey`; a stale legacy key can no longer hide an active canvas reference.
- Research Agent deletion removes the Agent from research `ModeBinding` pool, available Agents, and flow bindings before archiving the `AgentInstance`.
- Self-evolution fixed-role slots now match supervised evolution behavior: a raw slot pointing at an archived or missing Agent fails before default role repair can mask the bad binding.
- Chat session list/detail/turn resolution now treats `AgentInstance.agentId` as the primary binding; stale `agent_profile_id`/`agentProfileId` values are repaired from the AgentInstance profile instead of overriding it.
- The new failure paths write bounded diagnostic events:
  - `research.agent_binding.delete_failed`
  - `research.mode_binding.delete_sync_failed`
  - `agent_runtime.resolve_failed` for self-evolution slot resolution
  - `session.agent_profile_repaired` for chat legacy profile repair

Still remaining before compatibility readers can be removed:

- Chat no longer writes `agent_profile_id`/`agentProfileId` into saved conversation state; those fields are read only to repair historical sessions, while API `agentProfileId` is derived from the bound `AgentInstance.profileId`.
- Research Agent config writes now strip `llmConfigId` from the persisted index and store the unified `profileId` repair hint instead; API responses may still expose `llmConfigId` as a derived alias for older frontend call sites.
- Research flow canvas save/default paths now clear node-level `llmConfigId`; stale node values are accepted as old input but are not persisted back. `agentKey` remains as the action/role alias until the canvas schema can rename it explicitly.
- Research runtime now resolves LLM calls through `AgentInstance.profileId`/`profileId`; old `llmConfigId` is only a fallback for pre-migration records without an Agent binding.
- Research still carries `promptFilename` and `templateId` in the API/storage index until the prompt-template migration fully removes file/template aliases from per-mode config.
- Settings UI still needs complete Agent create/edit/archive/duplicate/open-session actions before old mode-specific editors can be retired.
- Sub-agent lifecycle remains recording-only; spawn permissions, callback, and depth enforcement are not yet the full final system.

## Failure Behavior

If a mode references a missing Agent:

- settings shows a repairable warning
- runtime fails clearly before LLM call
- log `agent_runtime.resolve_failed`
- do not silently switch to `primary`

If a prompt template source is missing:

- settings shows missing prompt source
- runtime fails clearly unless a default prompt has been explicitly repaired
- log `prompt_template.missing_source`

If an Agent is archived but still bound:

- settings shows stale binding
- runtime blocks fixed-role execution
- dynamic pools skip archived Agents only after logging and showing repair status

If migration detects conflicting legacy data:

- prefer explicit `agentId`
- otherwise repair from role key
- otherwise create new AgentInstance
- write a migration event with source and outcome

## OpenClaw Reference Adaptation

Useful ideas to adopt:

- long-lived specialist Agents should have isolated workspace/session/memory/tool state
- sub-agents are background tasks, not permanent settings objects
- default sub-agent context isolation
- explicit context fork
- bounded nested sub-agent depth
- lane contracts before complex central scheduling
- context assembly as a dedicated module

Ideas not copied directly:

- one `agentDir` per full product account is too heavy for current Vibelution layout
- Vibelution can share `LLMProfile` and `PromptTemplate` safely
- Vibelution should keep current project-local workspace conventions
- do not introduce a complex coordinator before role boundaries are clean

## Lane Contracts Before Scheduling

Before adding a central coordinator, define lane contracts.

Each specialist lane should declare:

```text
owns:
  what this Agent is responsible for
does_not_own:
  what it must not do
handoff:
  when it should pass work to another Agent
tools:
  default allowed/blocked tools
memory:
  what it may persist
```

Initial lane contracts:

- chat default Agent
- research broad/deep/review/themes/card Agents
- self-evolution executor/reviewer/summarizer
- supervised baseline/candidate/reviewer/auditor/judge

This should happen before complex traffic control or priority scheduling.

## Definition Of Done For Full Migration

The architecture is complete only when:

- all long-lived Agents are `AgentInstance`
- all mode orchestration reads `ModeBinding`
- all model use goes through `LLMProfile`
- all role prompt use goes through `PromptTemplate`
- chat sessions store `agentId` as primary binding
- research flow nodes store `agentId` as primary binding
- supervised/self fixed roles are slot bindings
- settings no longer exposes legacy binding terms
- compatibility readers can be removed
- tests pass after compatibility removal
- runtime logs can explain every Agent resolution path

## Recommended First Implementation Step

Start with Slice 1 and Slice 3 together:

1. Extend `AgentInstance` with `primaryMode`, `roleKey`, `promptTemplateId`.
2. Add `ModeBinding` store with repair-only behavior.
3. Seed ModeBinding from current chat/research/supervised data.
4. Expose the new fields in API and tests.

Do not move research runtime first. Research has the most duplicated private vocabulary, so it should be migrated after the new store exists and is covered by tests.

## Non-Goals For The First Implementation Step

- no full prompt content migration
- no deletion of legacy research config
- no central scheduler
- no new sub-agent spawning system
- no broad settings redesign in the same commit
- no forced migration that breaks existing workspace data
