# Desktop Conversation Notifications Design

Date: 2026-07-05
Status: Draft approved for written spec review

## Confirmed Intent

Vibelution should remind the operator at the desktop level whenever a conversation turn finishes, similar to the Codex taskbar/desktop behavior shown by the user. The reminder should make completed work visible when Vibelution is in the background without interrupting the operator when they are already looking at the active workbench.

Confirmed behavior:

- Scope: direct Chat/Coding conversations and Agent-backed session turns that flow through the existing session stream. Group or Team flows are covered only when their user-visible turn completion is already represented through the same session completion path.
- Foreground policy: when the workbench window is focused, do not show an OS notification; clear pending desktop attention for the active workbench.
- Background policy: when the workbench window is not focused, show a native desktop notification, increment an unread desktop attention count, apply a Windows taskbar overlay badge where available, and flash the workbench taskbar entry when appropriate.
- Click behavior: clicking a notification focuses the workbench window. It must not silently submit messages, switch workflows, restart Launcher, or mutate session data.
- Dedupe: a single completed turn must notify at most once even if the session SSE reconnects, sends a final snapshot after an assistant delta, or the frontend cache re-applies the same settled detail.
- Non-goals: no remote push notification service, no new runtime task queue, no notification preference page in the first slice, no backend-owned Windows notification code, no Teams workflow state rewrite, and no Launcher restart as part of implementation.

## Existing Facts

The project already has the right layers:

- `web/src/routes/ChatCodingRoute.tsx` owns the current session SSE client, active turn overlay state, and direct session busy/settled transitions.
- `desktop/electron/src/preload.ts` exposes a narrow `window.vibelutionLauncher` bridge from renderer to Electron main process.
- `desktop/electron/src/ipc.ts` defines the IPC channel allow-list.
- `desktop/electron/src/main.ts` already validates IPC sender origins with `assertTrustedIpcSender`.
- `desktop/electron/src/windows/electronWindowProvider.ts` owns launcher/workbench window state and focus/open operations.
- `desktop/electron/tests/windowProvider.test.ts` already guards bridge width, trusted IPC sender behavior, and workbench window focus semantics.

Electron's official notification guide says main-process notifications use Electron's `Notification` module and created notification objects do not appear until `show()` is called. It also recommends IPC when crossing renderer/main process APIs. Electron's `BrowserWindow` API is the existing authority for window focus and taskbar attention. Windows taskbar overlay and flash behavior should therefore live in Electron main/window provider code, not in the Python backend or pure React view.

References:

- [Electron Notifications guide](https://electronjs.org/docs/latest/tutorial/notifications)
- [Electron Notification API](https://electronjs.org/docs/latest/api/notification)
- [Electron BrowserWindow API](https://electronjs.org/docs/latest/api/browser-window)

## Approach Decision

Use a narrow Web-to-Electron notification bridge:

```text
session stream completion
  -> ChatCodingRoute dedupes completed turn
  -> preload IPC method
  -> Electron main validates sender
  -> Desktop notification service decides focus/background behavior
  -> ElectronWindowProvider updates workbench focus/attention state
```

This keeps completion detection near the UI stream that already observes the user-visible turn, while keeping native OS behavior in the desktop shell.

Rejected alternatives:

- Backend directly shows desktop notifications: rejected because the backend does not own the Electron window focus state, should not depend on Windows desktop APIs, and would make local service behavior depend on a desktop shell detail.
- Browser-only toast: rejected because it does not satisfy the requested desktop/taskbar reminder behavior.
- New external notification library: rejected for the first slice because Electron already has built-in Notification, taskbar overlay, and flash APIs, and an added dependency would increase packaging and permission surface.

## Architecture

### Frontend Completion Detector

Create a small helper module near the chat route, for example:

```text
web/src/routes/chatDesktopNotifications.ts
```

Responsibilities:

- classify whether a session stream event represents a completed user-visible turn;
- derive a stable notification key from `sessionId`, `turnId`, and terminal status;
- suppress duplicate notifications for the same key during the page lifetime;
- call the desktop bridge only when `window.vibelutionLauncher.notifyConversationCompleted` exists;
- avoid throwing when the app runs in a plain browser instead of Electron.

`ChatCodingRoute.tsx` should call this helper from the existing final paths:

- `assistant_delta` with `done=true`;
- `session_detail` whose `currentPhase` / `status` is no longer busy after a previously busy turn;
- cache invalidation paths should not themselves emit notifications.

The detector should prefer a real turn ID from stream payload or active turn layer. If no turn ID is available, it may use the latest assistant message ID plus session status as a fallback. The fallback is still deduped and is acceptable only because the notification is user-facing attention, not canonical session state.

### Preload Bridge

Extend `window.vibelutionLauncher` with one method:

```ts
notifyConversationCompleted(payload: DesktopConversationCompletionNotification): Promise<DesktopConversationNotificationResult>
```

Payload fields:

- `schemaVersion: 1`
- `notificationKey: string`
- `sessionId: string`
- `turnId?: string`
- `title: string`
- `body: string`
- `completedAt?: string`
- `terminalStatus?: string`

The bridge must remain narrow and renderer-safe. It should not expose raw `ipcRenderer`, window objects, or filesystem paths.

### Electron Main Service

Create a focused desktop notification module, for example:

```text
desktop/electron/src/notifications/conversationNotifications.ts
```

Responsibilities:

- validate and normalize renderer payloads;
- keep a bounded in-memory set of recently seen notification keys;
- inspect workbench focus through `ElectronWindowProvider`;
- when focused: clear unread attention state and return `suppressed_focused`;
- when unfocused: show native notification if supported, increment unread count, update taskbar overlay/attention, and return `notified`;
- on notification click: focus the workbench window.

Unread attention is a desktop shell state, not session truth. It can reset when:

- the workbench gains focus;
- the renderer sends a foreground completion for the active workbench;
- the Electron shell restarts.

No durable unread store is needed in the first slice.

### Window Provider Additions

`ElectronWindowProvider` should expose focused helper methods rather than leaking raw window instances:

- `isWorkbenchFocused(): boolean`
- `focusWorkbench(): Promise<ManagedWindowState>` already exists and should be reused on notification click.
- `setWorkbenchAttention(options)` or equivalent method to apply/clear overlay and flash state.

Tests can use the existing fake window class by adding optional methods for overlay and flash calls.

### Badge Strategy

The screenshot shows a small count badge on the app taskbar icon. On Windows, the closest Electron-owned behavior is a taskbar overlay icon. The first implementation should:

- show no overlay when unread count is `0`;
- show a simple generated overlay image for `1` to `9`;
- show `9+` for counts above `9`;
- keep overlay generation in Electron main process using built-in `nativeImage` or an existing project asset path;
- degrade gracefully on platforms or windows where overlay is unavailable.

This is not a product data counter. It is only desktop attention state.

## Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| A session turn is currently busy or settled | Existing session service / session stream detail | Existing backend session flow | ChatCodingRoute, conversation view | SSE `assistant_delta` / `session_detail`, query invalidation | No new source |
| Whether a completion was already notified in the current renderer page | Frontend helper in-memory notification-key set | ChatCodingRoute helper | ChatCodingRoute helper only | Page reload clears it; key changes per turn | No old source |
| Desktop unread attention count | Electron main in-memory notification service | Electron notification service | Taskbar overlay, notification result | Workbench focus or Electron restart clears it | No old source |
| Whether to show native desktop notification | Electron main process focus decision | Electron notification service | OS notification API | Evaluated per completion event | No old source |

## Logging Decision

Add bounded browser telemetry when the frontend emits or suppresses a desktop completion notification:

- `browser.desktop_notification.conversation_completed_emitted`
- `browser.desktop_notification.conversation_completed_skipped`

Add bounded Electron runtime-scene events only around native action outcomes:

- `electron.conversation_notification.notified`
- `electron.conversation_notification.suppressed`
- `electron.conversation_notification.failed`

Do not log message content, full assistant text, prompts, attachments, or large payloads. Include only `sessionId`, `turnId`, `notificationKey`, `terminalStatus`, `focused`, `unreadCount`, and result status.

## Error Handling

- If the bridge is missing, the frontend silently skips desktop notification and records a browser telemetry skip.
- If Electron rejects the sender origin, the existing IPC sender validation should throw and block the request.
- If notification payload is invalid, Electron returns a rejected/failed result and records a bounded event.
- If OS notifications are unavailable or fail, Electron should still update taskbar attention if possible and return `notification_failed_attention_applied` or equivalent.
- If overlay or flash APIs are unavailable, native notification should still proceed.
- Notification click focus failures should be logged but must not mark the session turn failed.

## Privacy And Safety

The notification body should be short and generic by default:

```text
对话已完成
<session title or Agent name> 已完成一轮回复。
```

It should not include assistant answer content, tool output, local file paths, prompts, secrets, or user-provided attachments. Session title / Agent display name is acceptable because it is already visible in the app shell.

## Developer Mode Parity

Developer mode and formal mode should use the same renderer-to-Electron contract. Plain browser development without Electron should degrade to a no-op. No separate developer-mode storage or API route is required.

Decision: `parity preserved` for Electron runs; graceful no-op for browser-only development.

## Implementation Boundary

Expected files to change in implementation:

- `desktop/electron/src/ipc.ts`
- `desktop/electron/src/preload.ts`
- `desktop/electron/src/main.ts`
- `desktop/electron/src/windows/electronWindowProvider.ts`
- `desktop/electron/src/notifications/conversationNotifications.ts`
- `desktop/electron/tests/windowProvider.test.ts`
- new or existing Electron notification tests
- `web/src/routes/chatDesktopNotifications.ts`
- `web/src/routes/ChatCodingRoute.tsx`
- a focused frontend test for notification dedupe / completion detection

Avoid changing:

- backend session completion semantics;
- `core/web/services/session_service.py` unless implementation proves the stream lacks a stable turn identifier;
- `web/src/api/types.ts` unless a typed bridge declaration already lives there and must be extended;
- project memory files during the implementation task unless the memory guard is clear;
- Launcher restart logic.

## Testing Strategy

Use TDD for implementation:

1. Electron RED tests for `conversationNotifications`:
   - focused workbench suppresses OS notification and clears attention;
   - unfocused workbench shows notification, increments unread count, applies overlay, and flashes;
   - duplicate `notificationKey` is ignored;
   - notification click focuses workbench.
2. Electron RED tests for IPC bridge width:
   - `IPC_CHANNELS` contains only the expected added notification channel;
   - untrusted sender origins are rejected by existing validation.
3. Frontend RED tests for helper behavior:
   - `assistant_delta.done=true` emits once;
   - final `session_detail` after a running phase emits once;
   - Electron bridge missing is a no-op;
   - focused/foreground suppression is left to Electron, not duplicated in browser state.
4. Validation commands:
   - `npm --prefix desktop/electron run test`
   - narrow frontend Vitest for the helper / Chat route integration
   - `npm --prefix web run build`
   - `git diff --check`

Manual or smoke verification after merge should launch the Electron shell, run a short conversation, move focus away, and confirm a desktop notification plus taskbar attention appears. Launcher refresh is recommended before user testing and required before release/runtime verification.

## Acceptance Criteria

- A completed conversation turn in background Vibelution creates one desktop notification and one unread taskbar attention increment.
- The same completed turn does not notify twice after SSE reconnects or final detail re-application.
- Foreground completion does not show a system notification and clears desktop attention.
- Clicking the notification focuses the workbench window.
- Running in a normal browser without Electron does not error.
- No answer content, prompts, tool output, or local paths are leaked into the notification body or telemetry.
- Tests prove Electron focus/background behavior, bridge validation, and frontend dedupe.

## Review Notes

The design intentionally keeps canonical conversation state in the existing backend/session stream and treats desktop unread count as ephemeral shell attention. This prevents a second source of truth for session unread status while still matching the Codex-like desktop cue the user requested.

