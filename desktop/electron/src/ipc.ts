export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getDesktopShellSummary: "launcher:get-desktop-shell-summary",
  focusWorkbenchWindow: "launcher:focus-workbench-window",
  requestDesktopShellExit: "launcher:request-desktop-shell-exit"
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
