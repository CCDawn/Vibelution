import { contextBridge, ipcRenderer, webUtils } from "electron";
import { createAssistantThemePreload } from "./assistant/assistantThemePreload.js";
import { IPC_CHANNELS } from "./ipc.js";
import { installRendererWindowClose } from "./windows/rendererWindowClose.js";

const isLauncherControlWindow = process.argv.includes("--vibelution-window-role=launcher-control");
const isDesktopPetWindow = process.argv.includes("--vibelution-window-role=desktop-pet");
const isLauncherAssistantWindow = process.argv.includes("--vibelution-window-role=launcher-assistant");

if (isLauncherAssistantWindow) {
  contextBridge.exposeInMainWorld("vibelutionLauncherTheme",createAssistantThemePreload(ipcRenderer));
  contextBridge.exposeInMainWorld("vibelutionLauncherAssistant", {
    invoke: (payload: unknown) => ipcRenderer.invoke(IPC_CHANNELS.assistantInvoke, payload),
  });
  // The unified resident assistant surface reuses the desktop pet drag and
  // expand IPC. Expose only that pet subset here; the full vibelutionLauncher
  // bridge stays limited to workbench and launcher control windows.
  contextBridge.exposeInMainWorld("vibelutionLauncher", {
    setDesktopPetExpanded: (expanded: boolean) =>
      ipcRenderer.invoke(IPC_CHANNELS.setDesktopPetExpanded, expanded),
    openConversationFromPet: (sessionId: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.openConversationFromPet, sessionId),
    beginDesktopPetWindowDrag: (point: unknown) =>
      ipcRenderer.send(IPC_CHANNELS.beginDesktopPetWindowDrag, point),
    moveDesktopPetWindowDrag: (point: unknown) =>
      ipcRenderer.send(IPC_CHANNELS.moveDesktopPetWindowDrag, point),
    endDesktopPetWindowDrag: () =>
      ipcRenderer.send(IPC_CHANNELS.endDesktopPetWindowDrag)
  });
}

if (!isLauncherAssistantWindow) {
contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke(IPC_CHANNELS.getVersion),
  getDesktopShellSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getDesktopShellSummary),
  ...(!isLauncherControlWindow && !isDesktopPetWindow ? {
    requestWindowClose: () => ipcRenderer.invoke(IPC_CHANNELS.requestWindowClose),
    readThemeAuthority: () => ipcRenderer.invoke(IPC_CHANNELS.readThemeAuthority),
    setThemeAuthority: (input: unknown) => ipcRenderer.invoke(IPC_CHANNELS.setThemeAuthority, input),
    reportThemeProjection: (input: unknown) => ipcRenderer.invoke(IPC_CHANNELS.themeProjectionResult, input),
    onAssistantThemeChanged: (listener: (theme: unknown) => void) => {
      const wrapped = (_event: unknown, theme: unknown) => listener(theme);
      ipcRenderer.on(IPC_CHANNELS.assistantThemeChanged, wrapped);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.assistantThemeChanged, wrapped);
    },
    controlDesktopPet: (open?: boolean, mode?: "pet" | "assistant") => ipcRenderer.invoke(IPC_CHANNELS.controlDesktopPet, open, mode),
    requestWorkbenchRestart: (trigger?: string) => ipcRenderer.invoke(IPC_CHANNELS.requestWorkbenchRestart, trigger),
    requestWorkbenchShellUpdate: () => ipcRenderer.invoke(IPC_CHANNELS.requestWorkbenchShellUpdate),
    getLauncherFreshness: () => ipcRenderer.invoke(IPC_CHANNELS.getLauncherFreshness),
    showLauncherWindow: () => ipcRenderer.invoke(IPC_CHANNELS.showLauncherWindow)
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
  notifyHumanAttention: (payload: unknown) =>
    ipcRenderer.invoke(IPC_CHANNELS.notifyHumanAttention, payload),
  getHumanAttentionCapabilities: () => ipcRenderer.invoke(IPC_CHANNELS.humanAttentionCapabilities),
  onHumanAttentionOpened: (listener: (payload: unknown) => void) => {
    const wrapped = (_event: unknown, payload: unknown) => listener(payload);
    ipcRenderer.on(IPC_CHANNELS.humanAttentionOpened, wrapped);
    return () => {
      ipcRenderer.removeListener(IPC_CHANNELS.humanAttentionOpened, wrapped);
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
        getDesktopAssistantContext: () =>
          ipcRenderer.invoke(IPC_CHANNELS.getDesktopAssistantContext),
        setDesktopPetExpanded: (expanded: boolean) =>
          ipcRenderer.invoke(IPC_CHANNELS.setDesktopPetExpanded, expanded),
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
}

if (!isLauncherControlWindow && !isDesktopPetWindow && !isLauncherAssistantWindow) {
  contextBridge.executeInMainWorld({ func: installRendererWindowClose });
}
