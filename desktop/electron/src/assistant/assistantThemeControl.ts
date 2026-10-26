import { assertAssistantSender } from "./assistantBridge.js";

type Theme = "dark" | "light";
export type AssistantThemeInput = { deliveryId: string; operation: "read" | "set"; theme?: Theme };
export type AssistantThemeResult = {
  schemaVersion: 1; operation: "read" | "set";
  code: "read" | "applied" | "unavailable" | "persistence_failed"; theme?: Theme;
};
export type AssistantThemeContents = {
  mainFrame: unknown; send(channel: string, payload: unknown): void; isDestroyed(): boolean; getURL?(): string;
};
type Sender = Parameters<typeof assertAssistantSender>[0];
type Pending = {
  contents: AssistantThemeContents; frame: unknown; input: AssistantThemeInput;
  finish(result: AssistantThemeResult): void;
};

/** Inspect data descriptors before reading any values supplied across the boundary. */
function record(value: unknown): Record<string, unknown> | null {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const output: Record<string, unknown> = Object.create(null);
    for (const key of Reflect.ownKeys(value)) {
      if (typeof key !== "string") return null;
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !("value" in descriptor)) return null;
      output[key] = descriptor.value;
    }
    return output;
  } catch { return null; }
}
const themeIsValid = (value: unknown): value is Theme => value === "dark" || value === "light";
const validDelivery = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{32}$/.test(value);
const keysAre = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));

/** Main owns delivery identity; a renderer may only report its observed theme. */
export class AssistantThemeControl {
  private pending = new Map<string, Pending>();
  // The broker never reuses a random delivery ID. Retain only bounded recent
  // tombstones beyond its 20-second theme lifetime to reject late replies.
  private delivered = new Map<string, number>();

  request(contents: AssistantThemeContents, input: AssistantThemeInput, signal?: AbortSignal): Promise<AssistantThemeResult> {
    const now = performance.now();
    for (const [id,expires] of this.delivered) if (expires <= now) this.delivered.delete(id);
    const data = record(input);
    const operation = data?.operation === "set" ? "set" : "read";
    const unavailable: AssistantThemeResult = { schemaVersion: 1, operation, code: "unavailable" };
    if (!data || !validDelivery(data.deliveryId) || (data.operation !== "read" && data.operation !== "set")
        || !keysAre(data, operation === "read" ? ["deliveryId", "operation"] : ["deliveryId", "operation", "theme"])
        || (operation === "set" && !themeIsValid(data.theme))
        || this.pending.size >= 4 || this.delivered.size >= 512 || this.delivered.has(data.deliveryId) || signal?.aborted) return Promise.resolve(unavailable);
    try {
      const frame = contents.mainFrame as Sender["senderFrame"];
      assertAssistantSender({ sender: contents, senderFrame: frame }, contents);
      if (contents.getURL && contents.getURL() !== frame?.url) return Promise.resolve(unavailable);
    } catch { return Promise.resolve(unavailable); }
    const command: AssistantThemeInput = { deliveryId: data.deliveryId, operation,
      ...(operation === "set" ? { theme: data.theme as Theme } : {}) };
    this.delivered.set(command.deliveryId, now + 60_000);
    return new Promise(resolve => {
      const finish = (result: AssistantThemeResult) => {
        if (this.pending.get(command.deliveryId) !== pending) return;
        this.pending.delete(command.deliveryId);
        clearTimeout(timeout);
        signal?.removeEventListener("abort", abort);
        resolve(result);
      };
      const abort = () => finish(unavailable);
      const timeout = setTimeout(abort, 3_000);
      const pending: Pending = { contents, frame: contents.mainFrame, input: command, finish };
      this.pending.set(command.deliveryId, pending);
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) { abort(); return; }
      try { contents.send("vibelution:assistant-theme-command", command); }
      catch { finish(unavailable); }
    });
  }

  /** Called on main-frame navigation or WebContents destruction. */
  invalidate(contents: AssistantThemeContents): void {
    for (const pending of this.pending.values()) {
      if (pending.contents === contents) pending.finish({ schemaVersion: 1, operation: pending.input.operation, code: "unavailable" });
    }
  }

  acceptResult(event: Sender, payload: unknown): boolean {
    const data = record(payload);
    if (!data || !validDelivery(data.deliveryId)) return false;
    const pending = this.pending.get(data.deliveryId);
    if (!pending || pending.frame !== pending.contents.mainFrame) return false;
    try { assertAssistantSender(event, pending.contents); } catch { return false; }
    const { operation } = pending.input;
    if (data.operation !== operation) return false;
    const success = operation === "read" ? data.code === "read" : data.code === "applied";
    const failure = data.code === "unavailable" || (operation === "set" && data.code === "persistence_failed");
    if ((!success && !failure) || !keysAre(data, success
      ? ["deliveryId", "operation", "code", "theme"] : ["deliveryId", "operation", "code"])
      || (success && !themeIsValid(data.theme))) return false;
    const matches = success && (operation === "read" || data.theme === pending.input.theme);
    pending.finish({ schemaVersion: 1, operation,
      code: matches ? operation === "read" ? "read" : "applied" : data.code === "persistence_failed" ? "persistence_failed" : "unavailable",
      ...(matches ? { theme: data.theme as Theme } : {}) });
    return true;
  }
}
