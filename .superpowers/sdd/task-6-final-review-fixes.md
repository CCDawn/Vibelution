# Task 6 Final Review Fixes

## Findings

1. Critical privacy leak in frontend payload
   - `web/src/routes/chatDesktopNotifications.ts` previously derived IPC `body` from `context.sessionTitle`.
   - Risk: user-controlled session title could carry secret-like strings or local paths across the preload/IPC boundary.

2. Important stale unreadCount on workbench focus
   - `desktop/electron/src/windows/electronWindowProvider.ts` previously cleared overlay attention on workbench focus without clearing `ConversationNotificationService` internal unread state.
   - Risk: next background completion could continue from stale unread count.

## RED

### Added/strengthened tests

- `web/src/routes/chatDesktopNotifications.test.ts`
  - Added malicious `sessionTitle` regression with `sk-live-secret` and `C:\Users\17533\Desktop\prompt.txt`.
  - Asserted payload copy is generic safe text and telemetry does not contain attacker-controlled strings.

- `desktop/electron/tests/windowProvider.test.ts`
  - Added focus-event regression asserting a workbench focus callback is invoked.

- `desktop/electron/tests/conversationNotifications.test.ts`
  - Added regression asserting unread count returns to `1` after a focus-driven clear and the next background completion.

### RED command output summary

- `npm --prefix web run test -- chatDesktopNotifications.test.ts`
  - FAILED as expected.
  - Failure showed emitted payload body still contained `sk-live-secret from C:\Users\17533\Desktop\prompt.txt 已完成一轮回复。`

- `npm --prefix desktop/electron run test -- conversationNotifications.test.ts windowProvider.test.ts`
  - FAILED as expected.
  - Failure showed `onWorkbenchFocusAttentionClear` callback was never invoked on workbench focus.

## GREEN

### Production changes

- Frontend payload is now fixed to generic safe copy:
  - `title: "对话已完成"`
  - `body: "Vibelution 已完成一轮回复。"`

- Electron window provider now accepts an optional `onWorkbenchFocusAttentionClear` callback.
- Main-process wiring now calls `conversationNotificationService?.clearAttention()` on workbench focus.
- Existing provider overlay clearing remains in place; no recursive loop was introduced.

### GREEN command output summary

- `npm --prefix web run test -- chatDesktopNotifications.test.ts`
  - PASS, `10/10` tests.

- `npm --prefix desktop/electron run test -- conversationNotifications.test.ts windowProvider.test.ts`
  - PASS, `24/24` files and `96/96` tests in the desktop suite run.

- `npm --prefix web run build`
  - PASS.

- `npm --prefix desktop/electron run build`
  - PASS.

- `git diff --check`
  - PASS.

- `git status --short --branch`
  - Verified branch `codex/desktop-conversation-notifications` with only scoped task files modified before commit.

## Changed Files

- `web/src/routes/chatDesktopNotifications.ts`
- `web/src/routes/chatDesktopNotifications.test.ts`
- `desktop/electron/src/windows/electronWindowProvider.ts`
- `desktop/electron/src/main.ts`
- `desktop/electron/tests/windowProvider.test.ts`
- `desktop/electron/tests/conversationNotifications.test.ts`
- `.superpowers/sdd/task-6-final-review-fixes.md`

## Concerns

- Project memory guard commands were attempted for `status` and `check`, but in this session both returned exit code `1` with no stdout/stderr payload. Work proceeded in the assigned task worktree with narrowly scoped edits only.
- `chatDesktopNotifications.ts` still accepts `NotificationContext.sessionTitle` for API compatibility, but the notification payload no longer uses it.
