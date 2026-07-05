# Task 5 Report: Chat Stream Integration

## Scope

- Task: Chat Stream Integration
- Worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\desktop-conversation-notifications`
- Branch: `codex/desktop-conversation-notifications`

## Files Changed

- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/ChatCodingRoute.layout.test.ts`
- `web/src/routes/chatDesktopNotifications.test.ts`
- `web/src/routes/ChatCodingRoute.layout.test.ts`

## TDD Evidence

### Step 1: Helper-level route-pattern contract

Added helper-level test:

- `supports the route pattern of assistant delta final followed by final detail without duplicate notification`

Command:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts
```

Output:

```text
> vibelution-web-workbench@1.0.16 test
> vitest run chatDesktopNotifications.test.ts

RUN  v3.2.4 C:/Users/17533/Desktop/Vibelution-worktrees/desktop-conversation-notifications/web
✓ src/routes/chatDesktopNotifications.test.ts (9 tests) 8ms

Test Files  1 passed (1)
Tests  9 passed (9)
Duration  702ms
```

Result:

- PASS as expected by the brief. The helper already supported the route-compatible dedupe pattern, so this stays as a regression contract test.

### Step 2: Source-contract RED before route integration

Added source-contract test:

- `wires completed session stream events into the desktop notification helper`

Command:

```powershell
npm --prefix web run test -- ChatCodingRoute.layout.test.ts
```

Output:

```text
FAIL  src/routes/ChatCodingRoute.layout.test.ts > ChatCodingRoute layout contract > wires completed session stream events into the desktop notification helper
AssertionError: expected route source to contain 'createDesktopConversationNotifier'

Test Files  1 failed | 1 passed (2)
Tests  1 failed | 86 passed (87)
Duration  1.27s
```

Result:

- RED confirmed for production integration gap. `ChatCodingRoute.tsx` did not yet import or call the desktop notifier helper.

### Step 3: Production integration

Integrated the notifier into the existing direct-session SSE path only:

- imported `browserDesktopNotificationBridge` and `createDesktopConversationNotifier`
- created `desktopConversationNotifierRef` with `postBrowserTelemetry`
- called `handleSessionDetail(detail, { sessionTitle: detail.title || detail.id })` after `syncSessionDetail(detail)`
- called `handleAssistantDelta(payload, { sessionTitle: sessionDetailQuery.data?.title || directSessionActiveSummary?.title || streamSessionId })` after payload validation and `setSessionStreamConnected(true)` and before `queueAssistantDelta(...)`

Privacy checks preserved:

- no assistant content
- no tool output
- no local paths
- no prompts/secrets/attachments
- only existing title/id metadata passed

### Step 4: GREEN verification

Command:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts ChatCodingRoute.layout.test.ts
```

Output:

```text
> vibelution-web-workbench@1.0.16 test
> vitest run chatDesktopNotifications.test.ts ChatCodingRoute.layout.test.ts

RUN  v3.2.4 C:/Users/17533/Desktop/Vibelution-worktrees/desktop-conversation-notifications/web
✓ src/routes/chatDesktopNotifications.test.ts (9 tests) 8ms
✓ ChatCodingRoute.layout.test.ts (3 tests) 3ms
✓ src/routes/ChatCodingRoute.layout.test.ts (84 tests) 54ms

Test Files  3 passed (3)
Tests  96 passed (96)
Duration  1.18s
```

Result:

- GREEN confirmed.

## Task 5 Review Follow-up

Reviewer finding:

- The original `wires completed session stream events into the desktop notification helper` check only asserted raw string presence.
- That was too weak because it did not lock the helper calls to the actual `handleAssistantDelta(...)` / `applyPendingDetail(...)` code paths or their relative order.

Contract tightening:

- Added local source-slice helpers that fail fast when the expected function or section markers are missing.
- The route test now verifies `desktopConversationNotifierRef.current.handleAssistantDelta(payload, ...)` inside `function handleAssistantDelta(...)`, after the `shouldAcceptSessionStreamEvent(...)` filter and before `queueAssistantDelta(payload, event.data.length)`.
- The route test now verifies `desktopConversationNotifierRef.current.handleSessionDetail(detail, ...)` inside the accepted detail apply path, after `syncSessionDetail(detail)`.

RED / GREEN evidence for the tightened contract:

- RED probe: a temporary reversed fragment order made the new contract fail in `ChatCodingRoute.layout.test.ts` with the expected missing-fragment assertion.
- GREEN: the helper was restored to the correct order and the production route already satisfied the reviewed integration contract, so no production code change was required in this follow-up.

Final validation command for the tightened contract:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts ChatCodingRoute.layout.test.ts
```

Expected result:

- both targeted test files pass, with the route source-contract test now checking function-local sequence rather than raw file-wide substring presence.

## Self-Review

- The route does not keep any duplicate notification state; dedupe remains helper-owned.
- Browser-only fallback remains helper/bridge-owned through `browserDesktopNotificationBridge()`.
- The detail-path call is placed after accepted detail sync, avoiding pre-sync notification and avoiding double-calling per single `session_detail` event.
- The assistant-delta call is placed before the route queues the final delta layer, matching the requested source path and preserving existing SSE behavior.
- No backend/shared DTO changes were made.

## Concerns

- None at implementation time. Focused frontend contracts passed.
