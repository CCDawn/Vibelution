import type { IpcMainInvokeEvent } from "electron";

/** Runs in the main world before page scripts can retain Electron's destructive close. */
export function installRendererWindowClose(): void {
  const page = window as unknown as Window & {
    vibelutionLauncher: { requestWindowClose(): Promise<unknown> };
  };
  const requestClose = page.vibelutionLauncher.requestWindowClose;
  Object.defineProperty(page, "close", {
    configurable: false,
    writable: false,
    value: () => {
      void requestClose().catch(() => {
        console.warn("Managed window close failed; the window remains open.");
      });
    }
  });
}

export function requestRendererWindowClose(
  event: IpcMainInvokeEvent,
  resolveWindow: () => { id: number; isDestroyed(): boolean } | null,
  requestClose: (windowId: number, senderUrl: string) => void
): { requested: true } {
  if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame) {
    throw new Error("Only the managed main frame can request window close.");
  }
  const window = resolveWindow();
  if (!window || window.isDestroyed()) {
    throw new Error("Managed window is unavailable.");
  }
  requestClose(window.id, event.senderFrame.url);
  return { requested: true };
}
