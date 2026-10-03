export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getDesktopShellSummary: "launcher:get-desktop-shell-summary",
  focusWorkbenchWindow: "launcher:focus-workbench-window",
  openConversationFromPet: "pet:open-conversation",
  controlDesktopPet: "pet:settings-control",
  beginDesktopPetWindowDrag: "pet:window-drag-begin",
  moveDesktopPetWindowDrag: "pet:window-drag-move",
  endDesktopPetWindowDrag: "pet:window-drag-end",
  requestDesktopShellExit: "launcher:request-desktop-shell-exit",
  requestWorkbenchRestart: "launcher:request-workbench-restart",
  notifyConversationCompleted: "launcher:notify-conversation-completed",
  conversationNotificationOpened: "launcher:conversation-notification-opened",
  getLauncherState: "launcher:get-state",
  refreshLauncherState: "launcher:refresh-state",
  launcherStateChanged: "launcher:state-changed",
  launcherInvoke: "launcher:invoke",
  openExternalUrl: "vui:open-external",
  openPath: "vui:open-path",
  showItemInFolder: "vui:show-item-in-folder"
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
