import { contextBridge, ipcRenderer } from "electron";
import { IPC_CHANNELS } from "./ipc.js";

const isLauncherControlWindow = process.argv.includes("--vibelution-window-role=launcher-control");

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke(IPC_CHANNELS.getVersion),
  getDesktopShellSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getDesktopShellSummary),
  focusWorkbenchWindow: () => ipcRenderer.invoke(IPC_CHANNELS.focusWorkbenchWindow),
  requestDesktopShellExit: () => ipcRenderer.invoke(IPC_CHANNELS.requestDesktopShellExit),
  notifyConversationCompleted: (payload: unknown) =>
    ipcRenderer.invoke(IPC_CHANNELS.notifyConversationCompleted, payload),
  onConversationNotificationOpened: (listener: (payload: unknown) => void) => {
    const wrapped = (_event: unknown, payload: unknown) => listener(payload);
    ipcRenderer.on(IPC_CHANNELS.conversationNotificationOpened, wrapped);
    return () => {
      ipcRenderer.removeListener(IPC_CHANNELS.conversationNotificationOpened, wrapped);
    };
  },
  getLauncherState: () => ipcRenderer.invoke(IPC_CHANNELS.getLauncherState),
  onLauncherStateChanged: (listener: (payload: unknown) => void) => {
    const wrapped = (_event: unknown, payload: unknown) => listener(payload);
    ipcRenderer.on(IPC_CHANNELS.launcherStateChanged, wrapped);
    return () => {
      ipcRenderer.removeListener(IPC_CHANNELS.launcherStateChanged, wrapped);
    };
  },
  ...(isLauncherControlWindow
    ? {
        launcherInvoke: (payload: unknown) => ipcRenderer.invoke(IPC_CHANNELS.launcherInvoke, payload)
      }
    : {})
});
