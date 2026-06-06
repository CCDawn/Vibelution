# Challenge Cup Research Launchpad Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Teams-page launchpad that lets the Challenge Cup research team start and operate the knowledge collection -> screening -> Team Knowledge proposal flow without manually calling APIs.

**Architecture:** Keep Team workflow orchestration as the backend source of truth and add a thin UI/action layer in `TeamsRoute`. The launchpad reuses existing CandidateStore, local research model invoke, candidate graph, steward ingestion, Team Knowledge review, coordination status, and knowledge ingestion status APIs; it must not bypass approval gates or write official knowledge directly.

**Tech Stack:** FastAPI/Python backend, React TypeScript frontend, Vitest layout/logic tests, pytest backend route/service tests, generated Challenge Cup HTML site.

---

## Behavior Contract

### Confirmed Intent

The user needs a practical starter surface for the current research team. The first useful slice is not a full autonomous scientist; it is an operator-facing launchpad that starts the front half of the research ingestion flow and shows where qwen/local model, functional Agents, Team shared memory, and governance gates participate.

### Primary User

Research Coordination Agent/operator using the existing `research-team` in Vibelution Teams.

### Observable Result

On `/teams?team=research-team`, the user can:

- See the current research ingestion stage and next recommended action.
- Register a source candidate.
- Trigger source extraction for a local PDF candidate.
- Trigger local qwen generation for supported task types.
- Refresh the candidate graph.
- Submit a valid steward pack to Team Knowledge pending proposal.
- Review a pending steward pack proposal in the minimal first-party flow.
- See failures as repairable states instead of silent no-ops.

### Hard Boundaries

- The launchpad never writes formal `KnowledgeItem` directly.
- The local qwen model only generates CandidateStore drafts.
- `approvalRequired=true` remains mandatory for steward packs.
- `coordination/status` communication briefs remain read-only in this slice; no auto-send.
- Candidate graph remains preview-only until official knowledge review succeeds.
- Non-research teams must not be auto-initialized into challenge-cup workflow merely by opening Teams.

---

## Task 1: Add Launchpad Display Model

**Files:**
- Modify: `web/src/routes/TeamsRoute.tsx`
- Modify: `web/src/routes/TeamsRoute.module.css`
- Test: `web/src/routes/TeamsRoute.logic.test.ts`

**Step 1: Write the failing test**

Add a pure helper test that maps workflow/ingestion/coordination snapshots into launchpad steps:

```ts
it("marks source registration as the next action when the research candidate store is empty", () => {
  const model = buildResearchLaunchpadModel({
    workflow: { candidateStore: { candidateCount: 0 } },
    ingestion: { summary: { sourceCandidateCount: 0 }, actionItems: [] },
    coordination: { summary: { totalQueueItemCount: 0 } },
  });

  expect(model.steps[0].status).toBe("ready");
  expect(model.nextAction?.id).toBe("register_source");
});
```

**Step 2: Run test to verify it fails**

Run:

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts
```

Expected: fail because `buildResearchLaunchpadModel` does not exist.

**Step 3: Implement minimal display model**

Create an exported helper in `TeamsRoute.tsx` or nearby route logic section:

- Inputs: workflow, candidates, validation, coordination status, knowledge ingestion status.
- Output: steps for `source`, `extraction`, `local_model`, `graph`, `steward`, `review`.
- Each step has `id`, `label`, `status`, `count`, `nextActionId`, `disabledReason`.

**Step 4: Run test to verify it passes**

Run:

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts
```

Expected: new launchpad model test passes.

**Step 5: Commit**

```powershell
git add web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.logic.test.ts
git commit -m "feat: model challenge cup research launchpad"
```

---

## Task 2: Render the Launchpad Panel

**Files:**
- Modify: `web/src/routes/TeamsRoute.tsx`
- Modify: `web/src/routes/TeamsRoute.module.css`
- Test: `web/src/routes/TeamsRoute.layout.test.ts`

**Step 1: Write the failing layout test**

Assert the research team page renders a launchpad heading and expected step labels when workflow queries have data.

**Step 2: Run test to verify it fails**

```powershell
npm --prefix web run test -- TeamsRoute.layout.test.ts
```

Expected: fail because the panel is absent.

**Step 3: Render compact launchpad UI**

Add a dense operations panel in the existing Teams research workflow area:

- Step rail: source, extraction, qwen draft, graph, steward pack, review.
- Current next action bar.
- Action buttons disabled unless required candidate/status exists.
- No large marketing hero, no nested cards.

**Step 4: Run layout test**

```powershell
npm --prefix web run test -- TeamsRoute.layout.test.ts
```

Expected: pass.

**Step 5: Commit**

```powershell
git add web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.module.css web/src/routes/TeamsRoute.layout.test.ts
git commit -m "feat: show challenge cup research launchpad"
```

---

## Task 3: Add Source Registration Action

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/TeamsRoute.tsx`
- Modify: `web/src/routes/TeamsRoute.module.css`
- Test: `web/src/routes/TeamsRoute.logic.test.ts`
- Test: `web/src/routes/TeamsRoute.layout.test.ts`

**Step 1: Write failing tests**

Cover:

- Form payload normalization.
- Required title/sourceRef validation.
- Successful mutation invalidates workflow/candidate/ingestion queries.

**Step 2: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: fail because source registration UI/action is absent.

**Step 3: Implement form and mutation**

POST:

```text
/api/teams/{teamId}/workflow-orchestration/candidates/source
```

Fields:

- `title`
- `candidateType=source_manifest`
- `sourceType`
- `sourceRef`
- `summary`
- `createdByAgent=research_source_collector`
- `metadata.tags`

**Step 4: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: pass.

**Step 5: Commit**

```powershell
git add web/src/api/types.ts web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.module.css web/src/routes/TeamsRoute.logic.test.ts web/src/routes/TeamsRoute.layout.test.ts
git commit -m "feat: add research source registration"
```

---

## Task 4: Add Source Extraction and Local qwen Actions

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/TeamsRoute.tsx`
- Test: `web/src/routes/TeamsRoute.logic.test.ts`
- Test: `web/src/routes/TeamsRoute.layout.test.ts`

**Step 1: Write failing tests**

Cover:

- A source candidate with a local PDF shows extraction action.
- A completed source extraction shows qwen generation actions.
- qwen action uses supported task type and selected candidate id.

**Step 2: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: fail.

**Step 3: Implement mutations**

POST extraction:

```text
/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/source-extraction
```

POST qwen invoke:

```text
/api/teams/{teamId}/workflow-orchestration/local-research-model/invoke
```

Supported first-slice task types:

- `paper_note_draft`
- `neuro_mechanism_extract`
- `mechanism_mapping`
- `algorithm_hypothesis`
- `review_prefilter`
- `steward_pack_draft`

**Step 4: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: pass.

**Step 5: Commit**

```powershell
git add web/src/api/types.ts web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.logic.test.ts web/src/routes/TeamsRoute.layout.test.ts
git commit -m "feat: trigger research extraction and qwen drafts"
```

---

## Task 5: Add Graph, Steward Submit, and Review Actions

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/TeamsRoute.tsx`
- Test: `web/src/routes/TeamsRoute.logic.test.ts`
- Test: `web/src/routes/TeamsRoute.layout.test.ts`
- Test: `tests/test_team_workflow_routes.py` only if route payload mismatch is found

**Step 1: Write failing tests**

Cover:

- Candidate graph refresh button calls `candidate-graph`.
- Valid steward pack shows submit-to-knowledge action.
- Pending steward candidate shows approve/reject review actions.
- Buttons are disabled when required `knowledgeBaseId` or `proposalId` is missing.

**Step 2: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: fail.

**Step 3: Implement mutations**

POST graph:

```text
/api/teams/{teamId}/workflow-orchestration/candidate-graph
```

POST steward submit:

```text
/api/teams/{teamId}/workflow-orchestration/steward-packs/{candidateId}/knowledge-ingestion
```

POST review:

```text
/api/teams/{teamId}/workflow-orchestration/steward-packs/{candidateId}/knowledge-ingestion/review
```

**Step 4: Run tests**

```powershell
npm --prefix web run test -- TeamsRoute.logic.test.ts TeamsRoute.layout.test.ts
```

Expected: pass.

**Step 5: Commit**

```powershell
git add web/src/api/types.ts web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.logic.test.ts web/src/routes/TeamsRoute.layout.test.ts
git commit -m "feat: operate research graph and ingestion gates"
```

---

## Task 6: Backend Guard and Logging Audit

**Files:**
- Inspect: `core/web/services/team_workflow_orchestration_service.py`
- Inspect: `core/web/routes/team_workflows.py`
- Test: `tests/test_team_workflow_orchestration_service.py`
- Test: `tests/test_team_workflow_routes.py`

**Step 1: Confirm no new backend behavior is needed**

Run:

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py
```

Expected: pass.

**Step 2: Add tests only if UI needs a missing backend contract**

If a missing action is found, add a focused route/service test first.

**Step 3: Keep logging decision explicit**

Current expected decision: UI launchpad adds no new backend runtime event by itself. Backend mutations already log candidate registration, local model invocation, graph build, steward submission, review, and status viewed events. If a new backend route is introduced, add a count-only runtime scene event and test it.

**Step 4: Commit if backend changes were needed**

```powershell
git add core/web/services/team_workflow_orchestration_service.py core/web/routes/team_workflows.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py
git commit -m "fix: align research launchpad backend contract"
```

---

## Task 7: Update Challenge Cup HTML

**Files:**
- Modify: `挑战杯/build_research_flow_site.mjs`
- Generated: `挑战杯/research_team_flow_design.html`
- Generated: `挑战杯/research_flow_pages/*.html`

**Step 1: Update generator**

Add the launchpad as milestone `M6.2` and reflect the UI operation boundary:

- Launchpad starts actions.
- qwen writes only drafts.
- approval gate remains required.
- coordination communication remains read-only.

**Step 2: Regenerate**

```powershell
node "C:\Users\17533\Desktop\Vibelution\挑战杯\build_research_flow_site.mjs"
```

**Step 3: Check local HTML links**

Use a local link checker over `挑战杯/research_team_flow_design.html` and `挑战杯/research_flow_pages/*.html`.

**Step 4: Commit**

```powershell
git add 挑战杯/build_research_flow_site.mjs 挑战杯/research_team_flow_design.html 挑战杯/research_flow_pages
git commit -m "docs: document challenge cup research launchpad"
```

---

## Final Validation

Run:

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py
npm --prefix web run test -- TeamsRoute.layout.test.ts TeamsRoute.logic.test.ts
npm --prefix web run build
git diff --check
```

Also verify:

- Challenge Cup HTML links pass.
- Version bump decision is made. This launchpad is user-visible frontend behavior, so PATCH bump is expected when implemented.
- Launcher refresh is needed after implementation merge because running Teams UI must load new frontend build.

