import { contextBridge, ipcRenderer, webUtils } from "electron";
import { IPC_CHANNELS } from "./ipc.js";

const isLauncherControlWindow = process.argv.includes("--vibelution-window-role=launcher-control");
const isDesktopPetWindow = process.argv.includes("--vibelution-window-role=desktop-pet");

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke(IPC_CHANNELS.getVersion),
  getDesktopShellSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getDesktopShellSummary),
  ...(!isLauncherControlWindow && !isDesktopPetWindow ? {
    controlDesktopPet: (open?: boolean) => ipcRenderer.invoke(IPC_CHANNELS.controlDesktopPet, open),
    requestWorkbenchRestart: (trigger?: string) => ipcRenderer.invoke(IPC_CHANNELS.requestWorkbenchRestart, trigger)
  } : {}),
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
  /** 从拖拽/文件输入得到的 Web File 解析真实本地路径（Electron 32+ 需经 preload webUtils） */
  getPathForFile: (file: unknown): string | null => {
    try {
      const path = webUtils.getPathForFile(file as File).trim();
      return path.length > 0 ? path : null;
    } catch {
      // 非 File 入参或解析失败时返回 null，让 Web 端继续走二进制上传兜底。
      return null;
    }
  },
  /** 用系统默认浏览器/处理程序打开 http/https/mailto 链接；scheme 白名单在 main 侧复核。 */
  openExternalUrl: (url: string) => ipcRenderer.invoke(IPC_CHANNELS.openExternalUrl, url),
  /** 用系统默认程序打开绝对路径指向的文件/目录；main 侧复核绝对路径。 */
  openPath: (path: string) => ipcRenderer.invoke(IPC_CHANNELS.openPath, path),
  /** 在系统文件管理器中显示该绝对路径对应的条目。 */
  showItemInFolder: (path: string) => ipcRenderer.invoke(IPC_CHANNELS.showItemInFolder, path),
  onLauncherStateChanged: (listener: (payload: unknown) => void) => {
    const wrapped = (_event: unknown, payload: unknown) => listener(payload);
    ipcRenderer.on(IPC_CHANNELS.launcherStateChanged, wrapped);
    return () => {
      ipcRenderer.removeListener(IPC_CHANNELS.launcherStateChanged, wrapped);
    };
  },
  ...(isLauncherControlWindow
    ? {
        launcherInvoke: (payload: unknown) => ipcRenderer.invoke(IPC_CHANNELS.launcherInvoke, payload),
        refreshLauncherState: () => ipcRenderer.invoke(IPC_CHANNELS.refreshLauncherState)
      }
    : {}),
  ...(isDesktopPetWindow
    ? {
        openConversationFromPet: (sessionId: string) =>
          ipcRenderer.invoke(IPC_CHANNELS.openConversationFromPet, sessionId),
        beginDesktopPetWindowDrag: (point: unknown) =>
          ipcRenderer.send(IPC_CHANNELS.beginDesktopPetWindowDrag, point),
        moveDesktopPetWindowDrag: (point: unknown) =>
          ipcRenderer.send(IPC_CHANNELS.moveDesktopPetWindowDrag, point),
        endDesktopPetWindowDrag: () =>
          ipcRenderer.send(IPC_CHANNELS.endDesktopPetWindowDrag)
      }
    : {})
});
