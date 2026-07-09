# Large File Structure Optimization Implementation Plan

> **Historical note for agentic workers:** This file records the accepted large-file optimization plan and split ledger. Do not execute it as a live active plan without first refreshing scope, claims, and validation against current `main`.

**Status:** historical

**Owner:** Vibelution structure-maintenance effort across `web-workbench-surface`, `chat-coding-surface`, and `quality-and-operations`

**Claim / Branch / Worktree:** implemented and merged into local `main`; original `codex/large-file-structure-optimization` branch/worktree has been cleaned up.

**Scope:** Reduce maintenance cost of the largest frontend routes, shared frontend API DTO file, and backend orchestration services by extracting stable, testable modules behind compatibility facades.

**Supersedes:** none

**Implementation link:** local main merge commits `7df387a6` and `38711b2c`; implementation commits include frontend API type domain split, Chat/Teams route helper extraction, test matrix updates, and Team workflow source-collection helper extraction.

**Validation:** `npm --prefix web run test`, `npm --prefix web run build`, `C:\Users\17533\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_select_tests.py -v`, focused Team workflow/source-collection tests, Teams layout tests, Challenge Cup generated-site build, and relevant `git diff --check` gates passed during the merge round.

**Close condition:** Historical record retained for traceability; implemented slices are merged into local `main`. Any remaining large-file extraction work needs a fresh plan, guard claim, and validation matrix before execution.

**Goal:** Turn the current large-file maintenance hotspots into smaller owned modules without changing product behavior or breaking existing import/API contracts.

**Architecture:** Use staged compatibility-first extraction. Frontend route shells keep route/query ownership while display panels, pure view models, and hooks move into route-local folders; `web/src/api/types.ts` becomes a compatibility barrel over domain modules; backend public service files stay as facades while pure normalization/projection/source-collection helpers move into package modules. Every split must first protect the old behavior with static or focused tests, then move one responsibility, then run the matching validation.

**Tech Stack:** Python service modules under `core/web/services`, FastAPI route contracts, React/TypeScript route code under `web/src/routes`, shared DTOs under `web/src/api`, Vitest, pytest, `tests/select_tests.py`, Tailwind/VUI/HeroUI constraints, and project-memory guard claims.

## Current State (2026-07-09)

- Implemented and merged: API DTO compatibility barrel/domain modules, ChatCodingRoute workspace/view-model extraction, Teams source-collection wrapper/view-model extraction, test matrix selector updates, and Team workflow source-collection helper modules.
- Deferred from this historical plan: broader `session_service.py` facade splitting, `ConversationView.tsx` splitting, and any additional route/component extraction not already represented by the local main commits above.
- The original split ledger below is preserved as planning history. Fields such as `Current Stage`, `Recommended Route Out`, old guard claim IDs, and old worktree paths are not live instructions.

## Global Constraints

- Root `C:\Users\17533\Desktop\Vibelution` must remain on `main`; implementation uses a task worktree.
- Do not overwrite current dirty files in root: `core/web/services/session_service.py`, `tests/test_session_detail_contract.py`, and `tests/test_web_app.py`.
- Current active guard claims block direct implementation overlap: `claim-3d1c0cae713d` covers `core/web/services/session_service.py`, `tests`, and `web/src/components/conversation`; `claim-f648853db0f4` covers self-evolution files. Implementation must wait, coordinate, or choose a non-overlapping slice before editing those scopes.
- No broad formatting, rename-only churn, import rewrites across the whole app, or opportunistic behavior changes.
- Keep public behavior stable. Backend route responses, frontend visible UI, conversation/session lifecycle, Team workflow semantics, and Challenge Cup generated flow behavior must remain unchanged unless a later task explicitly scopes a behavior fix.
- Keep compatibility facades until all call sites and tests are migrated. Do not delete old public exports in the same slice that creates a new module.
- `web/src/api/types.ts`, `core/web/services/session_service.py`, `tests/**`, and project-memory files are hot/shared surfaces; take narrow guard claims before implementation edits.
- Frontend split code must keep Tailwind/VUI/HeroUI ownership: child components get local style maps or VUI primitives and must not import parent route style internals.
- Backend extraction must prefer pure functions and data normalization before moving orchestration loops, persistence writers, or runtime side effects.
- Docs-only plan creation does not require Launcher refresh. Implementation touching UI/backend/API/build inputs will require a Launcher refresh decision before runtime verification.
- Version impact for this plan is `none`; implementation slices are likely `patch` when behavior stays identical and `minor` only if a public capability or contract changes.

---

## Audit Baseline

Largest maintenance hotspots from the read-only review:

| Surface | Current risk signal | Why it is first-class |
| --- | --- | --- |
| `core/web/services/team_workflow_orchestration_service.py` | about 23,275 lines, 628 top-level defs, high recent commit churn | Dense Challenge Cup/source-collection orchestration mixes projections, prompts, writeback, logs, and stores. |
| `core/web/services/session_service.py` | about 21,780 lines, 638 top-level defs, high recent commit churn | Chat/session lifecycle, projections, live output, runtime notices, and direct-agent repair share one hot file. |
| `web/src/routes/TeamsRoute.tsx` | about 13,500 lines; main component region about 8,786 lines | Route-level UI, canvas, source collection, status panels, and workflow controls are hard to review in one context window. |
| `web/src/routes/ChatCodingRoute.tsx` | about 7,817 lines; main component region about 5,976 lines | Route state, session windowing, composer wiring, status, file preview, and terminal panels are still concentrated. |
| `web/src/api/types.ts` | about 7,850 lines; 478 top-level types | Cross-domain DTOs make small contract changes look global and raise merge conflict risk. |
| `web/src/components/conversation/ConversationView.tsx` | about 3,607 lines; main component about 3,164 lines | Important but currently blocked by active conversation claim; treat as a later or coordinated slice. |

Existing positive patterns to reuse:

- `web/src/routes/chat/` already contains route-local panels and layout tests such as `ChatFilePreviewPanel`, `ChatRuntimeNoticeStack`, `CliAgentRunTerminalPanel`, and `ChatConversationComposerBridge`.
- `AgentsRoute.layout.test.ts` already guards extracted Agent panels so child panels do not import `AgentsRoute.styles`.
- `tests/test_matrix.yaml` maps touched files to focused validation commands and should be updated when new module paths are introduced.
- Local Codex-RS project reference supports the same principle: extract pure data/projection/sidecar/UI pieces before moving compatibility-sensitive orchestration.

## File Structure

### Frontend Route Split

- Modify `web/src/routes/TeamsRoute.tsx`: keep route-level queries, mutations, selected IDs, and composition only.
- Create `web/src/routes/teams/TeamsSourceCollectionPanel.tsx`: render source-collection stage lists, empty/loading states, record/candidate summaries, and action groups.
- Create `web/src/routes/teams/TeamsWorkflowStatusPanel.tsx`: render workflow run/stage status blocks currently embedded in `TeamsRoute.tsx`.
- Create `web/src/routes/teams/TeamsCanvasPanel.tsx`: isolate organization canvas composition while reusing existing `TeamsRoute.canvasData.ts` and `TeamWorkflowGraphView.tsx`.
- Create `web/src/routes/teams/teamsRouteViewModel.ts`: pure selectors and display-state helpers for Teams panels.
- Create `web/src/routes/teams/teamsRouteViewModel.test.ts`: pure tests for panel input shaping and edge cases.
- Modify `web/src/routes/TeamsRoute.layout.test.ts`: add structure guards for route shell size trend, child panel imports, and parent-style isolation.
- Modify `web/src/routes/ChatCodingRoute.tsx`: keep route-level data ownership and composition only.
- Create `web/src/routes/chat/chatCodingRouteViewModel.ts`: pure selectors for active session, window state, runtime notices, empty/loading states, and composer availability.
- Create `web/src/routes/chat/chatCodingRouteViewModel.test.ts`: pure tests for the selectors.
- Create `web/src/routes/chat/ChatSessionWorkspacePanel.tsx`: route-local composition for session body, file preview, terminal panel, and runtime notice stack.
- Modify `web/src/routes/ChatCodingRoute.layout.test.ts`: guard imports and route shell responsibilities after extraction.

### Frontend API Types Split

- Keep `web/src/api/types.ts` as the compatibility import target for all current consumers.
- Create `web/src/api/types/shared.ts`: shared primitives, statuses, paging, errors, file tree, generic metadata, and reusable utility DTOs.
- Create `web/src/api/types/chat.ts`: session, conversation, chat-room, transcript, runtime notice, and chat window DTOs.
- Create `web/src/api/types/teams.ts`: Team, Team workflow, Team knowledge, source-collection, graph, and Challenge Cup DTOs.
- Create `web/src/api/types/agents.ts`: Agent instance, profile, mode binding, tool governance, and directory DTOs.
- Create `web/src/api/types/runtime.ts`: runtime scene, Launcher, Git status, kernel, and work-run DTOs.
- Create `web/src/api/types/memory.ts`: memory, knowledge, RAG, Markdown/user-content, and governance DTOs.
- Create `web/src/api/types/evolution.ts`: supervised/self-evolution DTOs.
- Create `web/src/api/types/config.ts`: config, provider, model library, health diagnostics, and workbench contract DTOs.
- Modify `web/src/api/types.ts`: re-export the domain modules without changing the public `../api/types` import path.

### Backend Facade Split

- Keep `core/web/services/session_service.py` as the public facade for existing routes/tests.
- Create `core/web/services/session/__init__.py`: package marker and internal import boundary.
- Create `core/web/services/session/detail_window.py`: session detail window coercion and transcript-scope helpers.
- Create `core/web/services/session/runtime_notices.py`: runtime notice normalization, append/visible helpers, and status formatting.
- Create `core/web/services/session/projection.py`: pure summary/detail/projection helpers that do not mutate stores or spawn turns.
- Create `core/web/services/session/cache_projection.py`: cache-usage/context-usage projection helpers and token estimate helpers.
- Keep `submit_session_message`, delete/archive/repair lifecycle, and work-run release code in the facade until a later behavior-protected slice.
- Keep `core/web/services/team_workflow_orchestration_service.py` as the public facade for routes/tests.
- Create `core/web/services/team_workflow/__init__.py`: package marker and internal import boundary.
- Create `core/web/services/team_workflow/source_collection_context.py`: context ranking, compact summaries, context modes, and continuation hints.
- Create `core/web/services/team_workflow/source_collection_stage_tasks.py`: stage task IDs, writeback contracts, status projection, and turn-result normalization.
- Create `core/web/services/team_workflow/source_collection_projection.py`: stage cards, current stage summaries, readiness, and user-facing status labels.
- Create `core/web/services/team_workflow/workflow_events.py`: bounded event payload shaping and sample-count helpers.
- Keep prompt construction, session submission, persistence writes, and lifecycle reconciliation in the facade until extracted helpers are proven.

### Test Matrix And Architecture Guards

- Modify `tests/test_matrix.yaml`: add new frontend route subdirectories and backend service packages to existing `web-session-chat`, `teams-knowledge`, and `frontend-workbench` rules.
- Add or extend static layout tests, not runtime screenshots, for the first extraction slice.
- Add backend import/behavior smoke tests only where moved helpers are used by existing service tests.
- Do not add line-count tests as hard pass/fail gates. Track line count in review notes to avoid brittle churn.

---

## Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Chat/session lifecycle | `core/web/services/session_service.py` facade and existing stores | session service public functions | FastAPI session routes, Chat UI, conversation components, tests | existing service invalidation paths | helper modules do not write state in early phases |
| Team workflow/source collection state | existing Team workflow stores and `team_workflow_orchestration_service.py` facade | Team workflow service public functions | Team workflow routes, Teams UI, Challenge Cup flow site | existing workflow persistence and generated site rebuild | helper modules are pure projections until later phases |
| Frontend DTO public import path | `web/src/api/types.ts` compatibility barrel | API type split task | all existing `../api/types` imports | TypeScript build and Vitest import checks | direct consumer import migration is optional later work |
| Teams route UI state | `TeamsRoute.tsx` route shell | route queries/mutations | route-local `teams/*` panels | React state and query invalidation already present | extracted panels receive props and do not own persistence |
| Chat route UI state | `ChatCodingRoute.tsx` route shell | route queries/mutations | route-local `chat/*` panels | React state and existing session cache helpers | extracted panels receive props and do not own backend state |
| Validation selection | `tests/test_matrix.yaml` | quality-and-operations slice | Agents, CI/manual validation | update when paths move | old paths remain until no longer matched |

---

## Execution Phases

### Phase 0: Worktree, Claim, And Baseline

**Goal:** Create a safe implementation lane and freeze the baseline evidence.

**Files:**
- Modify later: none in this phase unless the guard claim requires memory metadata.

**Steps:**
- [ ] Confirm root status with `git status --short --branch`; expected branch is `main`.
- [ ] Wait for or coordinate active overlapping claims before touching `session_service.py`, `tests`, or `web/src/components/conversation`.
- [ ] Create `C:\Users\17533\Desktop\Vibelution-worktrees\large-file-structure-optimization` from local `main` on branch `codex/large-file-structure-optimization`.
- [ ] Claim the first narrow slice only, not the whole refactor. Recommended first claim scopes: `web/src/routes/TeamsRoute.tsx`, `web/src/routes/TeamsRoute.layout.test.ts`, and `web/src/routes/teams/**`.
- [ ] Run the current selector for planned files:

```powershell
.\.venv\Scripts\python.exe .\tests\select_tests.py --changed-file "web/src/routes/TeamsRoute.tsx" --changed-file "web/src/routes/TeamsRoute.layout.test.ts"
```

Expected: `git diff --check`, `npm --prefix web run test -- TeamsRoute.layout.test.ts`, and `npm --prefix web run build` are part of the slice validation.

### Phase 1: Frontend Route Extraction First

**Goal:** Reduce frontend review size without changing API contracts or backend behavior.

**Recommended order:**
1. Extract `TeamsRoute` display panels into `web/src/routes/teams/`.
2. Extract `TeamsRoute` pure selectors into `teamsRouteViewModel.ts`.
3. Extract `ChatCodingRoute` pure selectors into `chatCodingRouteViewModel.ts`.
4. Extract one `ChatCodingRoute` composition panel that reuses existing `chat/` child components.

**Guard tests to add before each extraction:**

```ts
import panelSource from "./teams/TeamsSourceCollectionPanel.tsx?raw";

it("keeps extracted Teams panels independent from parent route styles", () => {
  expect(panelSource).not.toContain("TeamsRoute.styles");
});
```

```ts
import { describe, expect, it } from "vitest";
import { buildTeamsSourceCollectionPanelState } from "./teams/teamsRouteViewModel";

it("keeps source-collection empty state separate from record rendering", () => {
  const state = buildTeamsSourceCollectionPanelState({
    records: [],
    candidates: [],
    isLoading: false,
    activeStageId: "source_collection",
  });

  expect(state.kind).toBe("empty");
  expect(state.visibleRecordCount).toBe(0);
});
```

**Validation:**
- `npm --prefix web run test -- TeamsRoute.layout.test.ts teamsRouteViewModel.test.ts`
- `npm --prefix web run test -- ChatCodingRoute.layout.test.ts chatCodingRouteViewModel.test.ts`
- `npm --prefix web run build`
- `git diff --check`

**Stop conditions:**
- A panel needs to mutate route state directly instead of receiving explicit callbacks.
- A child imports `TeamsRoute.styles` or `ChatCodingRoute.styles`.
- Extraction forces backend/DTO changes. Move that work to a later phase.

### Phase 2: API Types Domain Split

**Goal:** Reduce merge conflict risk in `web/src/api/types.ts` while preserving every existing import path.

**Steps:**
- [ ] Create `web/src/api/types/` modules by domain.
- [ ] Move declarations by domain in small batches.
- [ ] Keep `web/src/api/types.ts` as a barrel:

```ts
export * from "./types/shared";
export * from "./types/chat";
export * from "./types/teams";
export * from "./types/agents";
export * from "./types/runtime";
export * from "./types/memory";
export * from "./types/evolution";
export * from "./types/config";
```

- [ ] Do not rewrite consumers from `../api/types` during the first split.
- [ ] If a module depends on another domain, import from the smaller module, not from the barrel, to avoid circular re-export confusion.
- [ ] Update `tests/test_matrix.yaml` so `web/src/api/types/**` maps to `frontend-workbench`.

**Validation:**
- `npm --prefix web run test`
- `npm --prefix web run build`
- `git diff --check`

**Stop conditions:**
- TypeScript emits a circular or duplicate export problem.
- Any runtime import appears from a type-only domain module.
- The split requires touching large unrelated UI files. Preserve the barrel and defer consumer import cleanup.

### Phase 3: Backend Compatibility Facades

**Goal:** Move pure backend helpers out of the largest files while keeping public service imports stable.

**Session service first candidates:**
- Detail window coercion helpers.
- Runtime notice normalization helpers.
- Cache/context usage projection helpers.
- Summary/detail projection helpers that can be passed all inputs explicitly.

**Team workflow first candidates:**
- Source-collection context ranking and compact summary helpers.
- Stage task status/turn-result normalization.
- Stage card projection and readable labels.
- Workflow event payload shaping.

**Extraction rule:**
- A moved helper should be pure or close to pure.
- If the helper reads/writes stores, submits sessions, records runtime scenes, repairs lifecycle, or mutates Team/session state, leave it in the facade until a dedicated behavior-protected plan exists.
- Keep names private if they are only facade internals; do not turn accidental helpers into public API.

**Validation:**
- For session slices:

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests/test_web_session_routes.py tests/test_chat_room_service.py tests/test_chat_room_routes.py -q
npm --prefix web run test -- ChatCodingRoute.layout.test.ts
npm --prefix web run build
```

- For Teams/source-collection slices:

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests/test_team_service.py tests/test_team_knowledge_service.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py -q
npm --prefix web run test -- TeamsRoute.layout.test.ts
npm --prefix web run build
node 挑战杯/build_research_flow_site.mjs
```

**Stop conditions:**
- Moving a helper changes serialization, timestamps, ordering, IDs, or fallback labels.
- Import cycles appear between facade and package modules.
- Existing dirty user changes touch the same helper region.

### Phase 4: Test Matrix And Closure

**Goal:** Make the new structure maintainable for future Agents.

**Steps:**
- [ ] Update `tests/test_matrix.yaml` for new module paths.
- [ ] Add static architecture assertions to the route layout tests.
- [ ] Run `tests/select_tests.py` against representative changed files:

```powershell
.\.venv\Scripts\python.exe .\tests\select_tests.py --changed-file "core/web/services/session/detail_window.py" --changed-file "core/web/services/team_workflow/source_collection_context.py" --changed-file "web/src/routes/teams/TeamsSourceCollectionPanel.tsx" --changed-file "web/src/api/types/chat.ts"
```

- [ ] Verify the selected commands include the expected session, Teams, and frontend lanes.
- [ ] Self-review the diff for accidental behavior changes, broad formatting, and stale compatibility exports.
- [ ] Commit each phase separately with behavior-oriented messages such as `refactor(web): extract teams source collection panel` or `refactor(api): split frontend dto barrel`.

---

## Validation Strategy

Baseline selector for the full hotspot set currently returns:

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests/test_web_session_routes.py tests/test_chat_room_service.py tests/test_chat_room_routes.py -q
npm --prefix web run test -- ChatCodingRoute.layout.test.ts
npm --prefix web run build
.\.venv\Scripts\python.exe -m pytest tests/test_team_service.py tests/test_team_knowledge_service.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py -q
npm --prefix web run test -- TeamsRoute.layout.test.ts
node 挑战杯/build_research_flow_site.mjs
npm --prefix web run test
```

Use the full selector set only when a phase touches all listed surfaces. For each narrow slice, run the smallest matching subset plus `git diff --check`; widen when shared DTOs, shared app fixtures, Challenge Cup projections, or frontend build inputs change.

## Non-Goals

- Do not redesign the Chat/Coding visual language.
- Do not change Team workflow behavior, source-collection prompts, Challenge Cup generated content, or writeback semantics.
- Do not migrate every import to new API type modules in the first DTO split.
- Do not convert private backend helpers into a new public service API.
- Do not split `ConversationView.tsx` while `claim-3d1c0cae713d` or another conversation projection claim is active.
- Do not update `VERSION`, `CHANGELOG.md`, `web/package.json`, `web/package-lock.json`, project memory, or Launcher runtime state for the plan-only round.

## Plan Review Loop

| View | Challenge | Evidence | Conclusion |
| --- | --- | --- | --- |
| User intent | The user asked for lower maintenance cost, not behavior changes. | Plan is compatibility-first and lists behavior changes as non-goals. | PASS |
| Pre-plan evidence | The largest files have different risk profiles; one generic split would be too risky. | Audit identified frontend route, DTO, session, and Team workflow hotspots separately. | PASS |
| Implementer | A future Agent needs concrete first slices and validation commands. | File structure, phase order, stop conditions, and selector commands are named. | PASS |
| Test validation | Refactor-only work can pass old tests while missing import-boundary regressions. | Plan adds static architecture guards and updates `tests/test_matrix.yaml`. | PASS |
| Risk boundary | Active claims and root dirty files can collide with backend/test work. | Plan records active claims and makes frontend Teams extraction the safest first claim. | PASS |
| Maintainability | Moving orchestration too early can produce import cycles and hidden behavior drift. | Plan restricts backend Phase 3 to pure/projection helpers behind facades. | PASS |

## Plan Corrections Applied

- Backend extraction was moved after frontend/API phases to avoid colliding with the active `session_service.py` and broad `tests` claim.
- Hard line-count gates were rejected because they create brittle churn; route structure guards and review metrics are used instead.
- `ConversationView.tsx` was kept out of the initial execution route because a conversation projection claim is active.

## Task Split Decision

- **Decision:** SPLIT
- **Reason:** The accepted plan crosses frontend routes, shared DTOs, backend service facades, and test selection rules. These surfaces have different owners, validation commands, active-claim risks, and rollback boundaries.
- **Critical Path:** Task 0 -> Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8
- **Optional Path:** Later consumer import cleanup from `../api/types` to domain modules; later `ConversationView.tsx` split after active conversation claims clear.
- **Parallelism:** Task 6 and Task 7 can be independent backend branches after Task 5 updates selector coverage. Task 3 must wait for the conversation/session claim to clear or be coordinated. Task 4 should not run in parallel with unrelated DTO work because `web/src/api/types.ts` is a hot file.
- **Current Task:** Task 0, then Task 1. The first real implementation slice is Task 1 because it avoids the active `session_service.py` / conversation claim and gives immediate review-size relief.

### Task 0: Implementation Worktree And Guard Claim

- **Output:** A clean task worktree and a narrow first-slice guard claim for Teams frontend extraction.
- **Files/Boundary:** No business-code edits. Use root only for preflight; implementation belongs in `C:\Users\17533\Desktop\Vibelution-worktrees\large-file-structure-optimization`.
- **Reuse:** Existing worktree protocol and project-memory guard script.
- **Dependencies:** Accepted plan and this task graph.
- **Criticality:** critical
- **Development Mode:** SIMPLE
- **BDD/TDD Anchor:** Not needed; this is setup and guard validation only.
- **Verification:** `git status --short --branch`; guard `status` and `check`; `tests/select_tests.py` for `web/src/routes/TeamsRoute.tsx` and `web/src/routes/TeamsRoute.layout.test.ts`.
- **Review Gate:** Confirm root remains on `main`, worktree branch is `codex/large-file-structure-optimization`, and first claim excludes active session/conversation scopes.
- **Risk:** Accidentally starting implementation in root local `main` or claiming too broad a scope.

### Task 1: Extract First Teams Display Panel

- **Goal:** Move one coherent Teams display region, preferably source-collection display, from `TeamsRoute.tsx` into `web/src/routes/teams/TeamsSourceCollectionPanel.tsx` without changing visible behavior.
- **Inputs:** Existing `TeamsRoute.tsx`, `TeamsRoute.layout.test.ts`, `TeamsRoute.styles.ts`, `TeamWorkflowStatusPanels.tsx`, and current route props/state.
- **Outputs:** New route-local panel, parent route composed through explicit props, and static guard that child panels do not import `TeamsRoute.styles`.
- **Files:** Modify `web/src/routes/TeamsRoute.tsx`; create `web/src/routes/teams/TeamsSourceCollectionPanel.tsx`; modify `web/src/routes/TeamsRoute.layout.test.ts`.
- **Boundary:** Do not change backend routes, Team workflow service behavior, DTO types, Challenge Cup generated files, global VUI components, or source-collection prompts.
- **Reuse:** Reuse the `AgentsRoute.layout.test.ts` child-panel import guard pattern and existing VUI/HeroUI route conventions.
- **Dependencies:** Task 0.
- **Criticality:** critical
- **Development Mode:** BDD_TDD
- **BDD/TDD Anchor:** Given `TeamsRoute` has an extracted source-collection panel, When layout tests read child source raw text, Then the child must not import `TeamsRoute.styles` and the parent must still render the source-collection composition. First failing test: add a `TeamsSourceCollectionPanel.tsx?raw` assertion before extracting the panel.
- **Verification:** `npm --prefix web run test -- TeamsRoute.layout.test.ts`; `npm --prefix web run build`; `git diff --check`.
- **Review Gate:** Check the diff is mostly move/composition, callbacks are explicit, and no route state moved into the child.
- **Risk:** Pulling query/mutation ownership into a child panel or silently changing loading/empty-state layout.

### Task 2: Extract Teams View Model Helpers

- **Output:** `web/src/routes/teams/teamsRouteViewModel.ts` and focused pure tests for panel state shaping.
- **Files/Boundary:** Create `web/src/routes/teams/teamsRouteViewModel.ts` and `web/src/routes/teams/teamsRouteViewModel.test.ts`; touch `TeamsRoute.tsx` only to consume pure helpers. Do not touch API DTOs or backend data shape.
- **Reuse:** Existing route-local helper/test style such as `chatSessionState.ts`, `conversationIndexModel.ts`, and their tests.
- **Dependencies:** Task 1.
- **Criticality:** critical
- **Development Mode:** SIMPLE
- **BDD/TDD Anchor:** Not needed; pure selector tests and route layout tests are sufficient because no state contract changes.
- **Verification:** `npm --prefix web run test -- teamsRouteViewModel.test.ts TeamsRoute.layout.test.ts`; `npm --prefix web run build`; `git diff --check`.
- **Review Gate:** Helpers are pure, typed, and receive all inputs explicitly.
- **Risk:** Recreating backend projection logic in frontend instead of only shaping display state.

### Task 3: Extract Chat Route View Model And Workspace Panel

- **Goal:** Reduce `ChatCodingRoute.tsx` by moving pure chat route selectors and one composition panel under `web/src/routes/chat/`.
- **Inputs:** Existing `web/src/routes/chat/*` components, `ChatCodingRoute.tsx`, `ChatCodingRoute.layout.test.ts`, and active claim status.
- **Outputs:** `chatCodingRouteViewModel.ts`, `chatCodingRouteViewModel.test.ts`, and `ChatSessionWorkspacePanel.tsx`.
- **Files:** Modify `web/src/routes/ChatCodingRoute.tsx` and `web/src/routes/ChatCodingRoute.layout.test.ts`; create `web/src/routes/chat/chatCodingRouteViewModel.ts`, `web/src/routes/chat/chatCodingRouteViewModel.test.ts`, and `web/src/routes/chat/ChatSessionWorkspacePanel.tsx`.
- **Boundary:** Do not touch `web/src/components/conversation/**` while `claim-3d1c0cae713d` or equivalent conversation claim is active. Do not change session service or DTO contracts in this task.
- **Reuse:** Existing `ChatFilePreviewPanel`, `ChatRuntimeNoticeStack`, `CliAgentRunTerminalPanel`, and `ChatConversationComposerBridge`.
- **Dependencies:** Task 0 and active conversation/session claim clearance or explicit coordination.
- **Criticality:** critical
- **Development Mode:** BDD_TDD
- **BDD/TDD Anchor:** Given route state remains in `ChatCodingRoute`, When the workspace panel receives props, Then it renders existing chat child components without importing parent route styles or owning backend/session cache. First failing test: add layout/static guard for the new panel import boundary.
- **Verification:** `npm --prefix web run test -- ChatCodingRoute.layout.test.ts chatCodingRouteViewModel.test.ts`; `npm --prefix web run build`; `git diff --check`.
- **Review Gate:** Verify no conversation component internals were changed and no active claim scope was touched.
- **Risk:** Colliding with active conversation projection work or moving session-cache authority into a presentational panel.

### Task 4: Split Frontend API Types Into Domain Modules

- **Goal:** Turn `web/src/api/types.ts` into a compatibility barrel over domain modules while preserving every existing `../api/types` import.
- **Inputs:** Current `web/src/api/types.ts`, import graph, and Task 1-3 frontend extraction results.
- **Outputs:** `web/src/api/types/*.ts` domain modules and a barrel-only `web/src/api/types.ts`.
- **Files:** Create `web/src/api/types/shared.ts`, `chat.ts`, `teams.ts`, `agents.ts`, `runtime.ts`, `memory.ts`, `evolution.ts`, and `config.ts`; modify `web/src/api/types.ts`.
- **Boundary:** Do not rewrite app consumers in this task except where required to resolve domain-module internal imports. Do not change DTO names, field optionality, or runtime imports.
- **Reuse:** Preserve current public barrel contract and TypeScript type-only import style.
- **Dependencies:** Task 0; should not run in parallel with unrelated DTO work.
- **Criticality:** critical
- **Development Mode:** BDD_TDD
- **BDD/TDD Anchor:** Given existing consumers import from `../api/types`, When DTO declarations move to domain modules, Then all current imports still typecheck and no duplicate/circular exports appear. First failing test/check: run `npm --prefix web run build` after moving one small domain group before completing the barrel.
- **Verification:** `npm --prefix web run test`; `npm --prefix web run build`; `git diff --check`.
- **Review Gate:** Confirm `types.ts` only re-exports and no consumer import churn hides behavior changes.
- **Risk:** Circular type dependencies, duplicate export names, or accidentally introducing runtime imports into type modules.

### Task 5: Update Test Matrix For New Paths

- **Output:** `tests/test_matrix.yaml` recognizes new frontend route folders, API type modules, and backend service packages.
- **Files/Boundary:** Modify only `tests/test_matrix.yaml` and, if selector behavior requires it, `tests/test_select_tests.py`. Do not change production code.
- **Reuse:** Existing `web-session-chat`, `teams-knowledge`, and `frontend-workbench` rules.
- **Dependencies:** Task 1 and Task 4; can run before backend tasks if backend paths are included proactively.
- **Criticality:** critical
- **Development Mode:** SIMPLE
- **BDD/TDD Anchor:** Not needed; selector command output proves coverage.
- **Verification:** `.\.venv\Scripts\python.exe .\tests\select_tests.py --changed-file "web/src/routes/teams/TeamsSourceCollectionPanel.tsx" --changed-file "web/src/api/types/chat.ts" --changed-file "core/web/services/session/detail_window.py" --changed-file "core/web/services/team_workflow/source_collection_context.py"`; `git diff --check`.
- **Review Gate:** Confirm selected commands include Teams, chat/session, and frontend lanes where expected.
- **Risk:** New files become invisible to focused validation.

### Task 6: Extract Pure Session Service Facade Helpers

- **Goal:** Move the safest pure session helpers behind `session_service.py` while keeping all public imports and route behavior stable.
- **Inputs:** Active session claim status, existing session route tests, and Task 5 selector coverage.
- **Outputs:** `core/web/services/session/detail_window.py`, `runtime_notices.py`, and optionally `cache_projection.py` consumed by the facade.
- **Files:** Modify `core/web/services/session_service.py`; create `core/web/services/session/__init__.py`, `detail_window.py`, `runtime_notices.py`, and optional `cache_projection.py`.
- **Boundary:** Do not move `submit_session_message`, delete/archive/reset lifecycle, direct-agent repair, work-run release, persistence writes, or LLM invocation paths.
- **Reuse:** Existing private helper names and current route/service test fixtures.
- **Dependencies:** Task 5 and active session claim clearance or explicit coordination.
- **Criticality:** critical
- **Development Mode:** BDD_TDD
- **BDD/TDD Anchor:** Given session public routes still import the facade, When detail-window/runtime-notice helpers move, Then session route behavior and chat layout remain unchanged. First failing test/check: add or identify focused tests around moved helpers, then run them before and after extraction.
- **Verification:** `.\.venv\Scripts\python.exe -m pytest tests/test_web_session_routes.py tests/test_chat_room_service.py tests/test_chat_room_routes.py -q`; `npm --prefix web run test -- ChatCodingRoute.layout.test.ts`; `npm --prefix web run build`; `git diff --check`.
- **Review Gate:** Confirm moved helpers are pure or close to pure and facade remains the only public service import target.
- **Risk:** Import cycles or behavior drift in ordering, defaults, fallback labels, or runtime notice visibility.

### Task 7: Extract Pure Team Workflow Source-Collection Helpers

- **Goal:** Move pure source-collection projection/context helpers behind `team_workflow_orchestration_service.py` while preserving Team workflow and Challenge Cup behavior.
- **Inputs:** Existing source-collection tests, Challenge Cup generated-site command, and Task 5 selector coverage.
- **Outputs:** `core/web/services/team_workflow/source_collection_context.py`, `source_collection_stage_tasks.py`, `source_collection_projection.py`, and optional `workflow_events.py`.
- **Files:** Modify `core/web/services/team_workflow_orchestration_service.py`; create `core/web/services/team_workflow/__init__.py` and the helper modules above.
- **Boundary:** Do not move prompt construction, session submission, persistence writes, runtime-scene recording calls, writeback side effects, or lifecycle reconciliation in this task.
- **Reuse:** Current private helper behavior and existing `tests/test_team_workflow_orchestration_service.py` coverage.
- **Dependencies:** Task 5.
- **Criticality:** critical
- **Development Mode:** BDD_TDD
- **BDD/TDD Anchor:** Given Team workflow route projections and generated Challenge Cup pages use the facade, When pure source-collection helpers move, Then stage cards, readiness labels, task status, and generated site output stay stable. First failing test/check: add an import/selector guard or focused projection test before the move if existing tests do not touch the helper.
- **Verification:** `.\.venv\Scripts\python.exe -m pytest tests/test_team_service.py tests/test_team_knowledge_service.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py -q`; `npm --prefix web run test -- TeamsRoute.layout.test.ts`; `npm --prefix web run build`; `node 挑战杯/build_research_flow_site.mjs`; `git diff --check`.
- **Review Gate:** Confirm only pure helpers moved and no Challenge Cup projection changed unexpectedly.
- **Risk:** Hidden ordering or summarization changes that alter workflow cards, generated HTML, or source-collection continuation decisions.

### Task 8: Closure Review, Commit, And Memory Proposal

- **Output:** Self-reviewed phase commits or a clear blocked handoff; memory/version/Launcher decisions are recorded.
- **Files/Boundary:** No new product changes. Project memory sync only if holding the appropriate claim; otherwise provide exact proposal.
- **Reuse:** `ccdawn-completion-summary`, `ccdawn-pr-review`, and project memory sync scripts if implementation completed.
- **Dependencies:** Tasks 1-7 as implemented.
- **Criticality:** critical
- **Development Mode:** SIMPLE
- **BDD/TDD Anchor:** Not needed; this is review and closure.
- **Verification:** Relevant phase commands, `git status --short --branch`, scoped diff self-review, and final selector check.
- **Review Gate:** Confirm no broad formatting, no stale compatibility exports, no unclaimed hot-file edits, and no unfinished active claim.
- **Risk:** Calling the refactor complete with stale project memory, missing Launcher decision, or unmerged task branch.

## Split Ledger Update

- **Current Stage:** TASK_SPLITTING
- **Task Graph:** SPLIT with critical path Task 0 through Task 8; optional consumer-import cleanup and `ConversationView.tsx` split are deferred.
- **Current Task:** Task 0, then Task 1.
- **Verification Evidence:** The task graph inherits the plan's validation matrix and assigns commands to each critical task.
- **Decisions:** Start with Teams frontend extraction; defer backend/session/conversation work until active claims clear; use BDD_TDD only for large/hot or public-contract slices.
- **Unresolved Risks:** Active claim overlap can delay Task 3 and Task 6; DTO split may reveal circular type dependencies; backend helper extraction may uncover hidden side effects.
- **Recommended Next Stage:** Execute Task 0 as SIMPLE setup, then route Task 1 to `ccdawn-bdd-tdd-development`.
- **Route Out:** FAST_PATH light setup for Task 0, then `ccdawn-bdd-tdd-development` for Task 1.
- **Stop Condition:** Guard conflict, worktree creation failure, first-slice boundary expanding into backend/DTO behavior, or failing validation that cannot be fixed inside Task 1.

## Split Self-Review

| View | Challenge | Evidence | Conclusion |
| --- | --- | --- | --- |
| Plan coverage | Every plan phase must map to a task. | Frontend, DTO, backend facades, test matrix, and closure each have critical tasks. | PASS |
| Dependency clarity | Active claims can make a nominal first task unsafe. | Task 1 avoids active session/conversation scopes; Tasks 3 and 6 explicitly wait or coordinate. | PASS |
| Granularity | The split should not create tiny meaningless tasks. | Tasks produce independently reviewable outputs: panel extraction, view models, DTO barrel, selector matrix, backend facades. | PASS |
| Validation | Critical tasks need concrete commands. | Each task has command-level verification and review gates. | PASS |
| BDD/TDD routing | Only genuinely risky slices should use BDD_TDD. | Large route extraction, public DTO split, and backend hot facades are BDD_TDD; pure selector and setup tasks are SIMPLE. | PASS |

## Recommended Route Out

Default next stage: execute Task 0 as SIMPLE setup, then execute Task 1 through `ccdawn-bdd-tdd-development`.

Reason: task splitting is complete. The first executable slice should be `TeamsRoute` route-local extraction because it avoids the active session/conversation claim, follows the successful Agent panel pattern, and gives immediate maintenance relief without DTO/backend risk.

Execution options after approval:

1. **Subagent-Driven (recommended):** one fresh subagent for Task 1 after Task 0 setup, with review before moving to Task 2.
2. **Inline Execution:** execute Task 0 and Task 1 in this session using `ccdawn-bdd-tdd-development`, then checkpoint before Task 2.
