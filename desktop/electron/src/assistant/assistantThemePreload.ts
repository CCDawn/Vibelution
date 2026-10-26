type IpcRenderer = {
  on(channel: string, listener: (event: unknown, payload: unknown) => void): unknown;
  removeListener(channel: string, listener: (event: unknown, payload: unknown) => void): unknown;
  invoke(channel: string, payload: unknown): Promise<unknown>;
};

/** No Electron event, sender, or arbitrary channel is exposed to the renderer. */
export function createAssistantThemePreload(ipcRenderer: IpcRenderer) {
  return {
    onCommand(listener: (payload: unknown) => void): () => void {
      const wrapped = (_event: unknown, payload: unknown) => listener(payload);
      ipcRenderer.on("vibelution:assistant-theme-command", wrapped);
      return () => { ipcRenderer.removeListener("vibelution:assistant-theme-command", wrapped); };
    },
    respond: (payload: unknown): Promise<unknown> => ipcRenderer.invoke("vibelution:assistant-theme-result", payload),
  };
}
