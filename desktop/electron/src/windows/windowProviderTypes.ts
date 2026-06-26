export type ElectronWindowRole = "launcher" | "workbench";

export type ManagedWindowState = {
  role: ElectronWindowRole;
  provider: "electron";
  open: boolean;
  focused: boolean;
  windowId: number;
  rendererProcessId: number;
  url: string;
};

export function closedWindowState(role: ElectronWindowRole): ManagedWindowState {
  return { role, provider: "electron", open: false, focused: false, windowId: 0, rendererProcessId: 0, url: "" };
}
