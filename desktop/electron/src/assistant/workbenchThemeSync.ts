import type { IpcMainInvokeEvent } from "electron";
import type { ElectronWindowProvider } from "../windows/electronWindowProvider.js";
import type { ThemeSnapshot } from "./themeAuthority.js";

/** Bind theme access to a currently registered workbench main frame. */
export function workbenchThemeScope(event: IpcMainInvokeEvent,
  provider: Pick<ElectronWindowProvider, "trustedWorkbenchInstanceForSender"> | null): "main" | "local" | null {
  if (!provider || !event.senderFrame || event.senderFrame !== event.sender.mainFrame) return null;
  try {
    const instance = provider.trustedWorkbenchInstanceForSender(event.sender, event.senderFrame.url);
    return instance === "main" ? "main" : instance ? "local" : null;
  } catch { return null; }
}

export function publishAssistantTheme(snapshot: ThemeSnapshot,
  provider: Pick<ElectronWindowProvider, "trustedWorkbenchInstanceForSender" | "workbenchDialogParent" | "sendToWorkbench"> | null,
  channel: string, explicit = false): boolean {
  if (!provider) return false;
  try {
    const window = provider.workbenchDialogParent();
    if (!window || provider.trustedWorkbenchInstanceForSender(window.webContents, window.webContents.getURL()) !== "main") return false;
    return provider.sendToWorkbench(channel, { snapshot, explicit });
  } catch { return false; }
}

type ProjectionState = "applied" | "conflict" | "unavailable" | "unknown";
/** Bounded acknowledgements; sending an event alone is never confirmation. */
export class ThemeProjectionTracker {
  private entries = new Map<string, { promise: Promise<ProjectionState>; finish: (value: ProjectionState) => void }>();
  private key(value: Pick<ThemeSnapshot, "epoch" | "revision">, actor: "workbench" | "assistant"): string { return `${value.epoch}:${value.revision}:${actor}`; }
  begin(snapshot: ThemeSnapshot, actor: "workbench" | "assistant", send: () => boolean): void {
    if (this.entries.size >= 64) this.entries.delete(this.entries.keys().next().value!);
    const key = this.key(snapshot, actor);
    let resolve!: (value: ProjectionState) => void;
    const promise = new Promise<ProjectionState>(done => { resolve = done; });
    let finished = false;
    const timeout = setTimeout(() => finish("unknown"), 2000);
    const finish = (value: ProjectionState) => { if (finished) return; finished = true; clearTimeout(timeout); resolve(value); };
    this.entries.set(key, { promise, finish });
    setTimeout(() => { if (this.entries.get(key)?.promise === promise) this.entries.delete(key); }, 10_000).unref?.();
    try { if (!send()) finish("unavailable"); } catch { finish("unavailable"); }
  }
  acknowledge(snapshot: Pick<ThemeSnapshot, "epoch" | "revision">, actor: "workbench" | "assistant", state: ProjectionState): void {
    this.entries.get(this.key(snapshot, actor))?.finish(state);
  }
  wait(snapshot: ThemeSnapshot, actor: "workbench" | "assistant"): Promise<ProjectionState> {
    return this.entries.get(this.key(snapshot, actor))?.promise ?? Promise.resolve("unknown");
  }
}
