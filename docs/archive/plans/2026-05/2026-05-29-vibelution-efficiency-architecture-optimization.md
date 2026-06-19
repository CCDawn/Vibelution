# Vibelution Efficiency Architecture Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce repeated frontend/server-state work, improve startup bundle efficiency, and deepen the Team/Chat/Session modules without broad risky rewrites.

**Architecture:** Execute in small slices with one measurable efficiency target per slice. Prefer deeper Modules with narrow semantic Interfaces over moving code sideways: a chat workspace cache coordinator, a preview lazy-load Adapter, a Team Conversation projection contract, a message rendering pipeline, and a reusable concurrent-turn test harness.

**Tech Stack:** Python/FastAPI backend, React + TypeScript + TanStack Query frontend, Vite build, pytest, Vitest/Testing Library, runtime scene logs under `logs/runtime_scenes/`.

---

## Current Evidence Snapshot

- `web/src/routes/ChatCodingRoute.tsx`: 4277 lines, 14 `useQuery`, 17 `useMutation`, 78 `invalidateQueries`, 15 `setQueryData`.
- `/chat` runtime telemetry: `queryCount=18`, `activeQueryCount=17`.
- `session.list.loaded` in `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/conversation.jsonl`: 16 calls, min 299ms, max 719ms, avg 459.7ms.
- `session.list.loaded` in `logs/runtime_scenes/20260529T111213Z__af8c62fa8551/events/conversation.jsonl`: 85 calls, min 289ms, max 1292ms, avg 428.8ms.
- `web/dist/assets/index-C-WjzDQR.js`: 2,020,513 bytes.
- `web/dist/assets/index-C_eZjHMN.css`: 472,171 bytes.
- Vite warning: `FilePreview.tsx` is dynamically imported by `ChatCodingRoute.tsx` but statically imported by `LogsRoute.tsx` and `RuntimeScenesPane.tsx`, so the dynamic import is ineffective.
- `core/web/services/session_service.py`: 7999 lines.
- `core/web/services/chat_room_service.py`: 2143 lines, high Team/Room/Agent reference density.
- `core/web/services/team_service.py`: high Team/Room/Agent reference density.
- `web/src/components/conversation/ConversationView.tsx`: 1594 lines.
- `tests/test_web_app.py`: 10670 lines.

## Safety Rules For Execution

- Start from a dedicated branch/worktree if possible; do not develop directly on `main`.
- Before each task: run `git status --short --branch` and identify unrelated existing changes.
- Never use `git add .`; stage only files touched by that task.
- Keep each task commit small and behavior-oriented.
- For every behavior change, make an explicit logging decision and test decision.
- For frontend visual-impact changes, verify in browser or with screenshots after build/test.
- Treat runtime scene logs as primary evidence for performance and diagnosis.

---

### Task 1: Baseline Measurement And Guardrails

**Files:**
- Read: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/browser_page.jsonl`
- Read: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/conversation.jsonl`
- Read: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/raw/frontend.build.log`
- Optional create: `docs/ops/efficiency-baselines/2026-05-29-chat-workspace-baseline.md`

**Step 1: Record current Git state**

Run:

```powershell
git status --short --branch
```

Expected: Worktree may be dirty. Note unrelated changes before editing.

**Step 2: Recompute session-list latency baseline**

Run:

```powershell
$p='logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/conversation.jsonl'
$vals=@()
Get-Content $p | ForEach-Object {
  if ($_ -match 'session\.list\.loaded') {
    $o=$_ | ConvertFrom-Json
    $vals += [int]$o.fields.elapsedMs
  }
}
$stats=$vals | Measure-Object -Average -Minimum -Maximum
"count=$($vals.Count) min=$($stats.Minimum) max=$($stats.Maximum) avg=$([math]::Round($stats.Average,1))"
```

Expected: About `count=16 min=299 max=719 avg=459.7`.

**Step 3: Recompute frontend query baseline**

Run:

```powershell
Select-String -Path 'logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/browser_page.jsonl' -Pattern 'queryCount|activeQueryCount'
```

Expected: `/chat` samples show about `queryCount=18`, `activeQueryCount=17`.

**Step 4: Recompute bundle baseline**

Run:

```powershell
Get-ChildItem -Path 'web/dist/assets' |
  Where-Object { $_.Extension -in '.js','.css' } |
  Sort-Object Length -Descending |
  Select-Object -First 8 Name,Length
```

Expected: Main JS about `2,020,513` bytes, CSS about `472,171` bytes.

**Step 5: Commit only if a baseline document was created**

Run:

```powershell
git add docs/ops/efficiency-baselines/2026-05-29-chat-workspace-baseline.md
git commit -m "docs: record chat workspace efficiency baseline"
```

Skip commit if no file was created.

---

### Task 2: Introduce Chat Workspace Query Orchestrator Module

**Files:**
- Create: `web/src/routes/chatWorkspaceCache.ts`
- Create: `web/src/routes/chatWorkspaceCache.test.ts`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify only if needed: `web/src/api/queryKeys.ts`

**Intent:**

Create a deeper Module that hides query-key fanout behind semantic Interface methods. The route should call actions such as `afterMessageSubmitted`, `afterRoomLinked`, `afterGroupRoundStarted`, and `refreshConversationIndex` instead of directly repeating `invalidateQueries`.

**Step 1: Write failing cache contract tests**

Create tests that use a mocked `QueryClient`-like object and assert exact invalidation keys.

Example test shape:

```ts
import { describe, expect, it, vi } from 'vitest'
import { createChatWorkspaceCache } from './chatWorkspaceCache'

describe('createChatWorkspaceCache', () => {
  it('refreshes the conversation index once through a semantic action', async () => {
    const invalidateQueries = vi.fn()
    const setQueryData = vi.fn()
    const cache = createChatWorkspaceCache({ invalidateQueries, setQueryData })

    await cache.refreshConversationIndex()

    expect(invalidateQueries).toHaveBeenCalled()
    expect(invalidateQueries.mock.calls.length).toBeLessThanOrEqual(3)
  })
})
```

**Step 2: Run the focused failing test**

Run:

```powershell
cd web
npm test -- chatWorkspaceCache.test.ts --runInBand
```

Expected: FAIL because `chatWorkspaceCache.ts` does not exist or exported functions are missing.

**Step 3: Implement minimal Module**

Create `createChatWorkspaceCache` with a narrow Interface:

```ts
type QueryInvalidator = {
  invalidateQueries: (options: unknown) => Promise<unknown> | unknown
  setQueryData?: (queryKey: unknown, updater: unknown) => unknown
}

export function createChatWorkspaceCache(queryClient: QueryInvalidator) {
  return {
    refreshConversationIndex() {
      return queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    afterMessageSubmitted(sessionId: string) {
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sessions'] }),
        queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
      ])
    },
    afterRoomLinked(roomId: string) {
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ['chatRooms'] }),
        queryClient.invalidateQueries({ queryKey: ['chatRoom', roomId] }),
      ])
    },
  }
}
```

Adjust exact query keys to match `web/src/api/queryKeys.ts`.

**Step 4: Replace the first low-risk invalidation cluster**

In `ChatCodingRoute.tsx`, replace one repeated cluster around message submit or room refresh with the new semantic method.

Do not attempt to replace all 78 invalidations in one commit.

**Step 5: Run focused tests**

Run:

```powershell
cd web
npm test -- chatWorkspaceCache.test.ts ChatCodingRoute --runInBand
```

Expected: PASS or only unrelated pre-existing failures.

**Step 6: Run TypeScript/build check**

Run:

```powershell
cd web
npm run build
```

Expected: Build succeeds. Vite dynamic import warning may still exist until Task 3.

**Step 7: Logging decision**

No new backend runtime logs are required for this slice because behavior is frontend cache coordination only. If frontend telemetry already records query counts, use it as validation evidence.

**Step 8: Commit**

Run:

```powershell
git add web/src/routes/chatWorkspaceCache.ts web/src/routes/chatWorkspaceCache.test.ts web/src/routes/ChatCodingRoute.tsx
git commit -m "refactor: centralize chat workspace cache refresh"
```

---

### Task 3: Reduce Chat Query Fanout In Two More Slices

**Files:**
- Modify: `web/src/routes/chatWorkspaceCache.ts`
- Modify: `web/src/routes/chatWorkspaceCache.test.ts`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Optional modify: `web/src/routes/TeamsRoute.tsx`
- Optional modify: `web/src/routes/AgentsRoute.tsx`

**Step 1: Add failing tests for room/team mutation recipes**

Cover:

- `afterGroupRoundStarted(roomId)`
- `afterAgentBindingChanged(agentId)`
- `afterTeamRoomMembershipChanged(teamId, roomId)`

Expected test assertion: duplicate invalidations are coalesced by semantic recipe.

**Step 2: Implement recipes one at a time**

Keep each recipe small. Prefer typed helper arrays of query keys over inline repeated calls.

**Step 3: Replace another 10-20 direct invalidations**

Target only clusters that already call the same keys together.

**Step 4: Run focused tests**

Run:

```powershell
cd web
npm test -- chatWorkspaceCache.test.ts ChatCodingRoute TeamsRoute AgentsRoute --runInBand
```

Expected: PASS or unrelated pre-existing failures documented.

**Step 5: Run build**

Run:

```powershell
cd web
npm run build
```

Expected: Build succeeds.

**Step 6: Runtime validation**

Start the workbench using the project-native script and inspect fresh logs:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts\start_workbench.ps1"
```

If this script does not exist, use the existing local launcher documented by the repo. Then open `/chat`, perform one normal message submit, and compare fresh telemetry:

- `queryCount`
- `activeQueryCount`
- `session.list.loaded` count
- `session.list.loaded` avg/max

**Step 7: Commit**

Run:

```powershell
git add web/src/routes/chatWorkspaceCache.ts web/src/routes/chatWorkspaceCache.test.ts web/src/routes/ChatCodingRoute.tsx web/src/routes/TeamsRoute.tsx web/src/routes/AgentsRoute.tsx
git commit -m "refactor: reduce chat workspace query fanout"
```

Stage only files actually modified.

---

### Task 4: Fix Ineffective FilePreview Dynamic Import

**Files:**
- Modify: `web/src/components/preview/FilePreview.tsx`
- Optional create: `web/src/components/preview/LazyFilePreview.tsx`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/LogsRoute.tsx`
- Modify: `web/src/routes/RuntimeScenesPane.tsx`
- Modify if needed: `web/vite.config.ts`

**Step 1: Add or identify a render smoke test**

Prefer existing tests around preview rendering. If none are adequate, add a small test that verifies the lazy Adapter renders fallback and then preview content.

**Step 2: Introduce a single lazy Adapter**

Create `LazyFilePreview.tsx`:

```tsx
import { lazy, Suspense } from 'react'

const FilePreview = lazy(() => import('./FilePreview'))

export function LazyFilePreview(props: React.ComponentProps<typeof FilePreview>) {
  return (
    <Suspense fallback={<div className="previewLoading">Loading preview...</div>}>
      <FilePreview {...props} />
    </Suspense>
  )
}
```

Adjust type syntax if `React.ComponentProps<typeof FilePreview>` is not accepted for a lazy component.

**Step 3: Replace static route imports**

Routes that do not need immediate preview rendering should import `LazyFilePreview` instead of `FilePreview`.

**Step 4: Run build**

Run:

```powershell
cd web
npm run build
```

Expected:

- Build succeeds.
- The `INEFFECTIVE_DYNAMIC_IMPORT` warning disappears.
- `web/dist/assets` contains more than one meaningful JS chunk, or main JS size decreases.

**Step 5: Browser verification**

Open:

- `/chat`
- `/logs` or runtime scenes page that uses preview

Verify:

- Preview still renders.
- No visible layout jump beyond loading fallback.
- No console error.

**Step 6: Commit**

Run:

```powershell
git add web/src/components/preview/LazyFilePreview.tsx web/src/components/preview/FilePreview.tsx web/src/routes/ChatCodingRoute.tsx web/src/routes/LogsRoute.tsx web/src/routes/RuntimeScenesPane.tsx web/vite.config.ts
git commit -m "refactor: make file preview lazy loading effective"
```

Stage only files actually modified.

---

### Task 5: Add Team Conversation Projection Contract

**Files:**
- Create: `core/web/services/team_conversation_contract.py`
- Create: `tests/test_team_conversation_contract.py`
- Modify: `core/web/services/team_service.py`
- Modify: `core/web/services/chat_room_service.py`
- Optional modify: `core/web/routes/teams.py`
- Optional modify: `web/src/api/types.ts`
- Optional modify: `web/src/routes/TeamsRoute.tsx`

**Intent:**

Create a backend Module that describes Team-to-conversation state in one read-only projection before moving any write behavior. This gives a real Seam without risky migration.

**Step 1: Write failing projection tests**

Cover:

- Team has no linked room.
- Team has one linked room.
- Team has linked room with missing Agent.
- Team has membership conflict or stale room link.

Example Python test shape:

```python
def test_projection_marks_team_without_room_as_unlinked(tmp_path):
    projection = build_team_conversation_projection(
        team={"id": "team-a", "name": "Team A", "memberAgentIds": []},
        linked_room=None,
        agents_by_id={},
    )

    assert projection.team_id == "team-a"
    assert projection.linked_room_id is None
    assert projection.status == "unlinked"
```

**Step 2: Run failing test**

Run:

```powershell
pytest tests/test_team_conversation_contract.py -q
```

Expected: FAIL because module/function is missing.

**Step 3: Implement read-only projection Module**

Keep the Interface small:

- `build_team_conversation_projection(...)`
- dataclass or TypedDict projection output
- status enum/string with explicit values such as `unlinked`, `linked`, `agent_missing`, `membership_conflict`

**Step 4: Integrate one caller**

Use projection in one low-risk read path, preferably a list/detail route that already computes similar state.

Do not replace creation/update/delete logic in this task.

**Step 5: Logging decision**

If projection detects stale state, emit bounded runtime scene log fields:

- `teamId`
- `roomId`
- `status`
- `missingAgentCount`

Do not log full team payloads or prompts.

**Step 6: Run backend focused tests**

Run:

```powershell
pytest tests/test_team_conversation_contract.py tests/test_team_service.py tests/test_chat_room_service.py -q
```

Expected: PASS or documented unrelated failures.

**Step 7: Commit**

Run:

```powershell
git add core/web/services/team_conversation_contract.py tests/test_team_conversation_contract.py core/web/services/team_service.py core/web/services/chat_room_service.py
git commit -m "refactor: add team conversation projection contract"
```

---

### Task 6: Move Frontend Team/Room Display To Projection

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/TeamsRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/TeamsRoute.layout.test.ts`
- Optional modify: `tests/test_team_routes.py`

**Step 1: Add API route test if backend response changes**

Run or add:

```powershell
pytest tests/test_team_routes.py -q
```

Expected: API shape includes projection fields or remains backward-compatible.

**Step 2: Update TypeScript DTO**

Add a narrow type, for example:

```ts
export type TeamConversationProjection = {
  teamId: string
  linkedRoomId: string | null
  status: 'unlinked' | 'linked' | 'agent_missing' | 'membership_conflict'
  missingAgentCount: number
}
```

**Step 3: Replace duplicated display logic**

Use projection fields for Team linked-room badges, conflict notices, and action enabling.

**Step 4: Run frontend tests**

Run:

```powershell
cd web
npm test -- TeamsRoute ChatCodingRoute --runInBand
npm run build
```

Expected: PASS/build success.

**Step 5: Commit**

Run:

```powershell
git add web/src/api/types.ts web/src/routes/TeamsRoute.tsx web/src/routes/ChatCodingRoute.tsx web/src/routes/TeamsRoute.layout.test.ts tests/test_team_routes.py
git commit -m "refactor: consume team conversation projection"
```

Stage only files actually modified.

---

### Task 7: Deepen Conversation Rendering Pipeline

**Files:**
- Modify: `web/src/components/conversation/messageSections.ts`
- Modify: `web/src/components/conversation/messageSections.test.ts`
- Modify: `web/src/components/conversation/ConversationView.tsx`
- Modify: `web/src/components/conversation/ConversationView.test.tsx`

**Intent:**

Move one rendering concern at a time behind a typed section Interface. Start with artifact/image links because they frequently affect visual output.

**Step 1: Write failing message section test**

Add test for assistant content containing artifact image markdown and download URL.

Expected output: a typed section such as `artifactImage` with stable fields.

**Step 2: Run failing test**

Run:

```powershell
cd web
npm test -- messageSections.test.ts --runInBand
```

Expected: FAIL until parser supports the new typed section.

**Step 3: Implement parser change**

Keep the parser deterministic. Do not add broad markdown rewrites.

**Step 4: Update ConversationView Adapter**

Render `artifactImage` section from typed fields, not by re-parsing markdown inside the view.

**Step 5: Run focused tests**

Run:

```powershell
cd web
npm test -- messageSections.test.ts ConversationView.test.tsx --runInBand
npm run build
```

Expected: PASS/build success.

**Step 6: Visual verification**

Use a conversation with image artifact output and confirm:

- image renders
- download link works
- text does not overlap
- tables/tool sections still render

**Step 7: Commit**

Run:

```powershell
git add web/src/components/conversation/messageSections.ts web/src/components/conversation/messageSections.test.ts web/src/components/conversation/ConversationView.tsx web/src/components/conversation/ConversationView.test.tsx
git commit -m "refactor: type artifact image conversation sections"
```

---

### Task 8: De-noise Missing-Agent Session Index Warnings

**Files:**
- Modify: `core/web/services/session_service.py`
- Modify: `tests/test_web_app.py` or create focused `tests/test_session_index_warnings.py`
- Optional modify: runtime scene helper if severity classification is centralized

**Intent:**

Keep real errors visible, but stop treating already-hidden missing-Agent sessions as active warning clusters when they are stale/control-state.

**Step 1: Write failing test**

Test that known missing-agent sessions hidden from indexes produce a repaired/control event or lower severity when no user-visible failure remains.

**Step 2: Run failing test**

Run:

```powershell
pytest tests/test_session_index_warnings.py -q
```

Expected: FAIL until classification changes.

**Step 3: Implement minimal classification change**

Keep a warning for newly discovered or user-visible missing-Agent cases. Downgrade only repeated already-hidden stale sessions.

**Step 4: Run focused backend tests**

Run:

```powershell
pytest tests/test_session_index_warnings.py tests/test_web_app.py -q
```

Expected: PASS or documented unrelated failures.

**Step 5: Runtime validation**

Start workbench, open `/chat`, inspect newest runtime scene summary:

- `session.agent_missing.hidden_from_index` should not dominate active issue clusters when all such sessions are hidden successfully.

**Step 6: Commit**

Run:

```powershell
git add core/web/services/session_service.py tests/test_session_index_warnings.py tests/test_web_app.py
git commit -m "fix: de-noise hidden missing-agent session warnings"
```

Stage only files actually modified.

---

### Task 9: Introduce Concurrent Chat Turn Test Harness

**Files:**
- Create: `tests/helpers/chat_turn_harness.py`
- Create: `tests/test_chat_turn_harness.py`
- Modify: `tests/test_session_turn_scheduler.py`
- Optional modify: `tests/test_chat_room_service.py`
- Avoid broad modification: `tests/test_web_app.py`

**Intent:**

Make future scheduler/room-turn tests shorter and less timing-fragile without trying to split the entire 10670-line `tests/test_web_app.py` at once.

**Step 1: Write harness tests**

Cover:

- deterministic event wait
- timeout produces readable failure
- fake agent turn records status transitions

**Step 2: Run failing harness test**

Run:

```powershell
pytest tests/test_chat_turn_harness.py -q
```

Expected: FAIL because helper does not exist.

**Step 3: Implement helper**

Keep the helper small:

- `wait_for_condition(label, timeout_s, predicate)`
- `FakeTurnRunner`
- `recorded_events`

Do not encode production behavior into the helper.

**Step 4: Migrate one existing scheduler test**

Use the harness in one test from `tests/test_session_turn_scheduler.py`.

**Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_chat_turn_harness.py tests/test_session_turn_scheduler.py -q
```

Expected: PASS.

**Step 6: Commit**

Run:

```powershell
git add tests/helpers/chat_turn_harness.py tests/test_chat_turn_harness.py tests/test_session_turn_scheduler.py
git commit -m "test: add concurrent chat turn harness"
```

---

### Task 10: End-To-End Efficiency Validation

**Files:**
- Read: newest `logs/runtime_scenes/<latest>/summary.json`
- Read: newest `logs/runtime_scenes/<latest>/events/browser_page.jsonl`
- Read: newest `logs/runtime_scenes/<latest>/events/conversation.jsonl`
- Read: newest `logs/runtime_scenes/<latest>/raw/frontend.build.log`
- Optional create: `docs/ops/efficiency-baselines/2026-05-29-post-optimization.md`

**Step 1: Run full relevant backend tests**

Run:

```powershell
pytest tests/test_session_turn_scheduler.py tests/test_chat_room_service.py tests/test_team_service.py tests/test_team_routes.py -q
```

Expected: PASS.

**Step 2: Run frontend tests/build**

Run:

```powershell
cd web
npm test -- --runInBand
npm run build
```

Expected: PASS/build success. If the full test suite is too slow or has known unrelated failures, document exact focused tests run instead.

**Step 3: Start fresh workbench**

Use the project-native launcher. Then perform:

- open `/chat`
- send one normal message
- open Team page
- open a file preview

**Step 4: Compare metrics**

Expected improvement targets:

- `ChatCodingRoute.tsx` direct `invalidateQueries` count reduced by at least 25 percent in the first pass.
- Fresh `/chat` active query count lower than baseline or no longer repeatedly causing unnecessary session list reloads.
- `session.list.loaded` count after simple chat interaction lower than previous 16/85-call baselines.
- Vite ineffective dynamic import warning removed.
- Main JS chunk smaller or split into multiple meaningful chunks.
- Missing-agent hidden sessions no longer dominate active issue clusters when already handled.

**Step 5: Update project memory**

Run the project memory sync script from the local project-memory skill root, using the stable lane `web-workbench-surface`:

```powershell
python <skill-root>\scripts\sync_project_memory.py "C:\Users\17533\Desktop\Vibelution" --lane "web-workbench-surface" --focus "Chat workspace efficiency and frontend bundle optimization" --update "Centralized chat workspace cache refresh, fixed ineffective FilePreview lazy loading, and recorded post-optimization runtime evidence."
python <skill-root>\scripts\render_overview.py "C:\Users\17533\Desktop\Vibelution"
```

Resolve `<skill-root>` to the installed project-memory skill path used by this repo.

**Step 6: Final commit if memory changed**

Run:

```powershell
git add .docs/project-memory/INDEX.md .docs/project-memory/memory.json .docs/project-memory/lanes/web-workbench-surface.json .docs/project-memory/overview.html .docs/project-memory/lanes.html .docs/project-memory/modules.html .docs/project-memory/decisions.html .docs/project-memory/issues.html .docs/project-memory/todos.html .docs/project-memory/tech-notes.html .docs/project-memory/recent-updates.html PROJECT_MEMORY.html
git commit -m "docs: record efficiency optimization results"
```

Only stage files that actually changed.

---

## Recommended Execution Order

1. Task 1: Baseline measurement.
2. Task 2: First Chat Workspace Query Orchestrator slice.
3. Task 3: Reduce more query fanout.
4. Task 4: Fix ineffective dynamic import and bundle split.
5. Task 10 partial: compare frontend/runtime metrics.
6. Task 5: Backend Team Conversation projection.
7. Task 6: Frontend consumes projection.
8. Task 7: Conversation rendering pipeline slice.
9. Task 8: Missing-Agent warning de-noise.
10. Task 9: Concurrent chat turn test harness.
11. Task 10 full: final validation and memory update.

## Stop Conditions

- Stop and report if `npm run build` fails with a new TypeScript/JSX error unrelated to the current task.
- Stop and report if a fresh runtime scene shows new backend errors or warning clusters introduced by the task.
- Stop and report if current worktree contains conflicting edits in the same files that make a safe minimal patch impossible.
- Stop and report if query/bundle metrics regress after a slice.

## Version Bump Decision

- No version bump for Task 1, Task 9, or docs-only baseline work.
- Consider PATCH bump after Tasks 2-4 if the user-facing workbench load behavior measurably improves.
- Consider PATCH bump after Task 8 if runtime diagnosis guarantees improve.
- Do not use MINOR unless the Team Conversation projection becomes a public API contract consumed by frontend routes.
