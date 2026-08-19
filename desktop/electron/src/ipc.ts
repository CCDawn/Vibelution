export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getDesktopShellSummary: "launcher:get-desktop-shell-summary",
  focusWorkbenchWindow: "launcher:focus-workbench-window",
  requestDesktopShellExit: "launcher:request-desktop-shell-exit",
  notifyConversationCompleted: "launcher:notify-conversation-completed",
  conversationNotificationOpened: "launcher:conversation-notification-opened",
  getLauncherState: "launcher:get-state",
  refreshLauncherState: "launcher:refresh-state",
  launcherStateChanged: "launcher:state-changed",
  launcherInvoke: "launcher:invoke"
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
