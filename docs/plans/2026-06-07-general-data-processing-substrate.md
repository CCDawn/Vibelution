# General Data Processing Substrate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a generic data processing substrate that can run intake -> extraction -> transformation -> validation -> review -> publish workflows, with Challenge Cup research ingestion as only one profile.

**Architecture:** Introduce a domain-neutral processing layer with pipeline profiles, records, artifacts, stages, validation results, review gates, and publish adapters. Existing Challenge Cup Team Workflow/CandidateStore APIs become one adapter/profile instead of the core abstraction; Team Knowledge, memory graph, RAG, and local model invocation remain pluggable sinks/tools behind explicit adapters.

**Tech Stack:** FastAPI/Python backend, React TypeScript frontend, Vitest tests, pytest route/service tests, generated Challenge Cup HTML site for project-specific visualization.

---

## Behavior Contract

### Confirmed Intent

The user does not want a Challenge Cup-only or neuroscience-only launchpad. The required capability is a reusable data processing part of Vibelution that can later support research ingestion, document processing, dataset cleaning, knowledge ingestion, experiment data preparation, or other structured workflows.

### Primary Users

- Operators who need to process arbitrary data batches.
- Team coordinators who need to observe stages, blockers, and review gates.
- Domain profiles such as Challenge Cup research that provide schema, prompts, tools, and publish rules.

### Observable Result

The product exposes a generic processing surface where the user can:

- Create or select a processing pipeline profile.
- Register input records from files, URLs, text notes, API payloads, or existing workspace artifacts.
- Assign data collection work to functional Agents instead of expecting the user to manually gather every source.
- Run extraction/transformation steps through tools, models, or manual actions.
- Validate outputs against profile contracts.
- Route invalid or incomplete records back to earlier stages.
- Submit reviewed outputs to a configured sink such as Team Knowledge, memory graph, dataset store, export files, or future services.
- Inspect every record's trace from input to published output.

### Hard Boundaries

- Generic core must not contain Challenge Cup, neuroscience, steward pack, or qwen-specific names.
- Domain-specific schemas live in profiles/adapters, not in the core data processing model.
- Model invocation is a tool adapter. No model output is trusted until validated.
- Publish adapters must be explicit. The core cannot silently write Team Knowledge, RAG, memory graph, files, or external systems.
- Review gates are first-class and cannot be bypassed by a profile unless the profile declares a safe auto-publish policy.
- The existing Challenge Cup flow can reuse the substrate, but the substrate must remain useful without Teams or research concepts.

---

## Data Collection Agent Model

Data collection is an Agent workflow, not just a form submission. The generic substrate should define functional Agent roles that can be bound to any profile:

- `Data Intake Coordinator Agent`: owns the collection batch, scope, acceptance criteria, dedupe policy, and escalation path.
- `Data Discovery Agent`: finds candidate sources from search tools, existing memory, workspace files, configured directories, URLs, or API catalogs.
- `Source Acquisition Agent`: fetches or registers the raw source reference without rewriting the content.
- `Content Extraction Agent`: turns files, pages, PDFs, or raw payloads into text, metadata, anchors, checksums, and excerpts.
- `Source Deduplication Agent`: detects duplicate URLs, files, checksums, titles, DOI-like IDs, or near-duplicate excerpts.
- `Source Quality Agent`: scores source relevance, credibility, freshness, completeness, permission, and risk.
- `Intake Review Agent`: approves, returns, or rejects collected records before downstream transformation.

These roles are profile-neutral. Challenge Cup can bind them to research-specific prompts and tools, but the core contract remains about data records and source quality.

### Generic Collection Handoff

Each collection Agent passes a structured handoff:

- `runId`
- `recordId`
- `sourceType`
- `sourceRef`
- `acquisitionMethod`
- `rawLocation`
- `checksum`
- `anchors`
- `excerpt`
- `metadata`
- `qualitySignals`
- `dedupeGroupId`
- `permissionStatus`
- `recommendedNextStage`
- `blockingIssues`

### Collection Boundaries

- Discovery can propose sources, but cannot mark them trusted.
- Acquisition can fetch/register sources, but cannot transform them into facts.
- Extraction can produce excerpts and anchors, but cannot publish knowledge.
- Deduplication can merge candidates only through trace-preserving aliases.
- Source quality can score and recommend, but review/publish still needs a gate.
- Profile-specific Agents may add domain fields, but must preserve the generic handoff.

---

## Core Model

Use neutral names:

- `DataPipelineProfile`: reusable processing definition.
- `DataProcessingRun`: one execution instance for a batch or workflow.
- `DataRecord`: one input or intermediate unit.
- `DataArtifact`: extracted/transformed output attached to a record.
- `ProcessingStage`: intake, extract, transform, validate, review, publish, archive, or profile-defined extension.
- `ValidationReport`: structured errors, warnings, and readiness.
- `ReviewDecision`: approve, return, reject, hold.
- `PublishTarget`: Team Knowledge, memory graph, dataset export, file export, API sink, or profile-specific adapter.
- `ProcessingTrace`: source -> artifact -> validation -> review -> publish lineage.
- `CollectionAssignment`: Agent-owned collection task for a run or record group.
- `SourceQualitySignal`: relevance, credibility, freshness, permission, completeness, and risk signals.

Challenge Cup mapping is only a profile:

- `source_manifest` maps to a `DataRecord`.
- `paper_note`, `neuro_mechanism`, `mechanism_mapping`, `algorithm_hypothesis`, `review_record`, and `candidate_graph` map to `DataArtifact` types.
- Team Knowledge pending proposal maps to a `PublishTarget` adapter.
- Existing `knowledge-ingestion/status` maps to a profile-specific status projection.

---

## Task 1: Define Generic DTOs and Profile Contract

**Files:**
- Modify: `web/src/api/types.ts`
- Create: `core/web/services/data_processing_service.py`
- Create: `core/web/routes/data_processing.py`
- Test: `tests/test_data_processing_service.py`
- Test: `tests/test_data_processing_routes.py`

**Step 1: Write failing backend tests**

Cover profile listing and empty run creation:

```python
def test_data_processing_profile_lists_generic_contract(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    response = data_processing_service.list_pipeline_profiles()

    assert response["summary"]["profileCount"] >= 1
    assert all("profileId" in item for item in response["profiles"])
    assert all("stages" in item for item in response["profiles"])
```

**Step 2: Run test to verify it fails**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py -v
```

Expected: fail because the service does not exist.

**Step 3: Implement minimal service contract**

Create `data_processing_service.py` with:

- `list_pipeline_profiles()`
- `get_pipeline_profile(profile_id)`
- `create_processing_run(profile_id, payload)`
- neutral profile schema fields

Seed only one generic built-in profile:

- `generic_document_processing`
- stages: intake, extract, transform, validate, review, publish
- no Challenge Cup-specific fields

**Step 4: Add API routes**

Create:

```text
GET /api/data-processing/profiles
GET /api/data-processing/profiles/{profile_id}
POST /api/data-processing/runs
GET /api/data-processing/runs/{run_id}
```

**Step 5: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py tests/test_data_processing_routes.py
```

Expected: pass.

**Step 6: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/routes/data_processing.py core/web/app.py tests/test_data_processing_service.py tests/test_data_processing_routes.py web/src/api/types.ts
git commit -m "feat: add generic data processing contract"
```

---

## Task 2: Add Generic Run Storage and Record Intake

**Files:**
- Modify: `core/web/services/data_processing_service.py`
- Test: `tests/test_data_processing_service.py`
- Test: `tests/test_data_processing_routes.py`

**Step 1: Write failing tests**

Cover:

- Create run writes `workspace/data_processing/runs/<runId>/run.json`.
- Add record writes one `DataRecord`.
- Source fields remain neutral: `sourceType`, `sourceRef`, `title`, `summary`, `metadata`.

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py::test_processing_run_records_intake -v
```

Expected: fail.

**Step 3: Implement run store**

Storage:

```text
workspace/data_processing/profiles/
workspace/data_processing/runs/<runId>/run.json
workspace/data_processing/runs/<runId>/records.jsonl
workspace/data_processing/runs/<runId>/artifacts.jsonl
workspace/data_processing/runs/<runId>/events.jsonl
```

Add:

```text
POST /api/data-processing/runs/{run_id}/records
GET /api/data-processing/runs/{run_id}/records
```

**Step 4: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py tests/test_data_processing_routes.py
```

Expected: pass.

**Step 5: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/routes/data_processing.py tests/test_data_processing_service.py tests/test_data_processing_routes.py
git commit -m "feat: store generic data processing runs"
```

---

## Task 3: Add Data Collection Agent Assignments

**Files:**
- Modify: `core/web/services/data_processing_service.py`
- Modify: `core/web/routes/data_processing.py`
- Test: `tests/test_data_processing_service.py`
- Test: `tests/test_data_processing_routes.py`

**Step 1: Write failing tests**

Cover:

- A run can create a `CollectionAssignment` for a functional Agent role.
- Assignment roles are generic and profile-neutral.
- Discovery output creates candidate records with `collectionTrace`.
- Quality scoring updates `qualitySignals` but does not publish.
- Returned assignments keep the record in `intake_needs_revision`.

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py -k "collection_assignment" -v
```

Expected: fail.

**Step 3: Implement assignment APIs**

Add:

```text
POST /api/data-processing/runs/{run_id}/collection-assignments
GET /api/data-processing/runs/{run_id}/collection-assignments
POST /api/data-processing/runs/{run_id}/collection-assignments/{assignment_id}/outputs
```

Storage:

```text
workspace/data_processing/runs/<runId>/collection_assignments.jsonl
workspace/data_processing/runs/<runId>/collection_outputs.jsonl
```

Assignment fields:

- `assignmentId`
- `runId`
- `agentRole`
- `agentId`
- `scope`
- `inputRefs`
- `expectedRecordTypes`
- `status`
- `acceptance`
- `createdAt`
- `updatedAt`

**Step 4: Add runtime event decision**

Record count-only events:

- `data_processing.collection_assignment.created`
- `data_processing.collection_output.recorded`

Do not log full source text or raw excerpts.

**Step 5: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py tests/test_data_processing_routes.py
```

Expected: pass.

**Step 6: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/routes/data_processing.py tests/test_data_processing_service.py tests/test_data_processing_routes.py
git commit -m "feat: add data collection agent assignments"
```

---

## Task 4: Add Stage State Machine and Validation Reports

**Files:**
- Modify: `core/web/services/data_processing_service.py`
- Test: `tests/test_data_processing_service.py`

**Step 1: Write failing tests**

Cover:

- A record can move from `intake` to `extract`.
- A failed validation moves to `needs_revision`.
- A returned review decision can target an earlier stage.
- A rejected record is archived but remains traceable.

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py -k "stage or validation or review"
```

Expected: fail.

**Step 3: Implement state helpers**

Add neutral functions:

- `advance_record_stage(run_id, record_id, payload)`
- `record_validation_report(run_id, record_id, payload)`
- `submit_review_decision(run_id, record_id, payload)`
- `get_processing_status(run_id)`

Do not call Team Knowledge or Challenge Cup APIs here.

**Step 4: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py tests/test_data_processing_routes.py
```

Expected: pass.

**Step 5: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/routes/data_processing.py tests/test_data_processing_service.py tests/test_data_processing_routes.py
git commit -m "feat: add data processing stage gates"
```

---

## Task 5: Add Tool Adapter Contract

**Files:**
- Modify: `core/web/services/data_processing_service.py`
- Create: `core/web/services/data_processing_tool_adapter_service.py`
- Test: `tests/test_data_processing_service.py`
- Test: `tests/test_data_processing_tool_adapter_service.py`

**Step 1: Write failing tests**

Cover a registered tool action:

- declares inputs and output artifact type
- can be invoked with dry-run payload
- writes artifact only after validator accepts the output
- records failure without creating artifact

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_tool_adapter_service.py -v
```

Expected: fail.

**Step 3: Implement adapter interface**

Neutral adapter fields:

- `adapterId`
- `displayName`
- `inputRecordTypes`
- `outputArtifactType`
- `requiresModel`
- `requiresNetwork`
- `mutationBoundary`
- `invokeMode`: `manual`, `model`, `tool`, `external`

First implementation can be a no-op/manual adapter plus a generic local model adapter shell. Do not hard-code qwen; qwen is a configured model provider behind the local model adapter.

**Step 4: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_tool_adapter_service.py tests/test_data_processing_service.py
```

Expected: pass.

**Step 5: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/services/data_processing_tool_adapter_service.py tests/test_data_processing_service.py tests/test_data_processing_tool_adapter_service.py
git commit -m "feat: add data processing tool adapters"
```

---

## Task 6: Add Publish Adapter Boundary

**Files:**
- Modify: `core/web/services/data_processing_service.py`
- Create: `core/web/services/data_processing_publish_adapter_service.py`
- Test: `tests/test_data_processing_publish_adapter_service.py`

**Step 1: Write failing tests**

Cover:

- Publish target lists safe capabilities.
- Publish requires approved review unless profile declares otherwise.
- Team Knowledge adapter creates pending proposal, not formal item.
- File export adapter writes export artifact only in configured path.

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_publish_adapter_service.py -v
```

Expected: fail.

**Step 3: Implement adapter boundary**

Adapters:

- `file_export`
- `team_knowledge_pending_proposal`
- placeholder `memory_graph_proposal`
- placeholder `dataset_export`

Publishing must write:

- publish request
- adapter response
- trace entry
- runtime scene event with IDs/counts only

**Step 4: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_publish_adapter_service.py tests/test_data_processing_service.py
```

Expected: pass.

**Step 5: Commit**

```powershell
git add core/web/services/data_processing_service.py core/web/services/data_processing_publish_adapter_service.py tests/test_data_processing_publish_adapter_service.py
git commit -m "feat: add data processing publish adapters"
```

---

## Task 7: Add Generic UI Surface

**Files:**
- Create: `web/src/routes/DataProcessingRoute.tsx`
- Create: `web/src/routes/DataProcessingRoute.module.css`
- Create: `web/src/routes/DataProcessingRoute.logic.test.ts`
- Create: `web/src/routes/DataProcessingRoute.layout.test.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/queryKeys.ts`
- Modify: `web/src/main.tsx`
- Modify: `web/src/i18n/dictionary.ts`

**Step 1: Write failing frontend tests**

Cover:

- Profiles are listed.
- A run can be selected.
- Stage rail renders generic labels.
- Empty state does not mention Challenge Cup or research.
- Publish target labels come from API/profile.

**Step 2: Run tests**

```powershell
npm --prefix web run test -- DataProcessingRoute.layout.test.ts DataProcessingRoute.logic.test.ts
```

Expected: fail.

**Step 3: Implement route**

Route can be:

```text
/data-processing
```

Initial UI:

- profile selector
- run list
- collection assignment board
- record intake form
- stage/status rail
- records table
- artifact trace panel
- action area based on available adapters

Use dense workbench UI, not a landing page.

**Step 4: Run tests and build**

```powershell
npm --prefix web run test -- DataProcessingRoute.layout.test.ts DataProcessingRoute.logic.test.ts
npm --prefix web run build
```

Expected: pass.

**Step 5: Commit**

```powershell
git add web/src/routes/DataProcessingRoute.tsx web/src/routes/DataProcessingRoute.module.css web/src/routes/DataProcessingRoute.logic.test.ts web/src/routes/DataProcessingRoute.layout.test.ts web/src/api/types.ts web/src/api/client.ts web/src/api/queryKeys.ts web/src/main.tsx web/src/i18n/dictionary.ts
git commit -m "feat: add generic data processing workbench"
```

---

## Task 8: Add Challenge Cup Profile Adapter

**Files:**
- Create: `core/web/services/data_processing_profiles/challenge_cup_research.py`
- Modify: `core/web/services/data_processing_service.py`
- Test: `tests/test_data_processing_challenge_cup_profile.py`
- Modify: `挑战杯/build_research_flow_site.mjs`

**Step 1: Write failing tests**

Cover:

- Challenge Cup profile appears as a profile, not as core logic.
- Its stages map to existing research ingestion concepts.
- Its publish adapter uses Team Knowledge pending proposal boundary.
- Its data collection roles bind to research-specific functional Agents without changing the generic core.
- It can reference existing Team Workflow/CandidateStore IDs without copying their schema into the core.

**Step 2: Run tests**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_challenge_cup_profile.py -v
```

Expected: fail.

**Step 3: Implement profile adapter**

Profile ID:

```text
challenge_cup_research_ingestion
```

Profile owns only:

- display labels
- artifact contracts
- stage mapping
- collection role bindings
- allowed tool adapters
- allowed publish targets
- bridge metadata to existing Team Workflow when needed

Core service remains generic.

**Step 4: Update Challenge Cup HTML**

Document that Challenge Cup uses the generic data processing substrate. Do not describe the substrate as a research-only launchpad.

**Step 5: Run tests and HTML checks**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_challenge_cup_profile.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py
node "C:\Users\17533\Desktop\Vibelution\挑战杯\build_research_flow_site.mjs"
```

Expected: pass and HTML links pass.

**Step 6: Commit**

```powershell
git add core/web/services/data_processing_profiles/challenge_cup_research.py core/web/services/data_processing_service.py tests/test_data_processing_challenge_cup_profile.py 挑战杯/build_research_flow_site.mjs 挑战杯/research_team_flow_design.html 挑战杯/research_flow_pages
git commit -m "feat: add challenge cup data processing profile"
```

---

## Task 9: Migration/Compatibility Decision

**Files:**
- Inspect: `core/web/services/team_workflow_orchestration_service.py`
- Inspect: `core/web/routes/team_workflows.py`
- Inspect: `web/src/routes/TeamsRoute.tsx`
- Create or modify docs only if compatibility notes are needed.

**Step 1: Decide whether to wrap or migrate**

Recommended first implementation:

- Keep existing Challenge Cup Team Workflow APIs stable.
- Add generic data processing as a new surface.
- Add profile adapter references to existing CandidateStore rather than migrating storage immediately.

Reason: the current research flow already works and has tests. A hard migration would add risk without improving generality immediately.

**Step 2: Add compatibility note**

Document:

- Existing `/api/teams/{teamId}/workflow-orchestration/*` remains supported.
- Generic `/api/data-processing/*` becomes the new substrate for future data workflows.
- Challenge Cup can gradually move from bespoke CandidateStore to generic DataRecord/DataArtifact storage.

**Step 3: Commit if docs changed**

```powershell
git add docs/plans/2026-06-07-general-data-processing-substrate.md
git commit -m "docs: record data processing compatibility plan"
```

---

## Final Validation

Run after implementation:

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_data_processing_service.py tests/test_data_processing_routes.py tests/test_data_processing_tool_adapter_service.py tests/test_data_processing_publish_adapter_service.py
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py
npm --prefix web run test -- DataProcessingRoute.layout.test.ts DataProcessingRoute.logic.test.ts
npm --prefix web run build
git diff --check
```

Also verify:

- Challenge Cup HTML links pass.
- Version bump decision is made. The generic data processing route/API is a new product capability, so MINOR should be considered when implemented.
- Launcher refresh is needed after implementation merge because a new route/API must be loaded by the running Workbench.

---

## Implementation Notes

- Do not name generic files after Challenge Cup.
- Do not add neuroscience terms to `web/src/api/types.ts` generic DTOs.
- Use `profileId` and adapter labels for domain-specific text.
- Keep publish operations guarded and auditable.
- Prefer a small generic substrate plus one profile adapter over another large specialized Teams panel.
