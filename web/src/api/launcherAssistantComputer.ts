import { launcherAssistantBridge } from "./launcherAssistant";
import type { ComputerTransport } from "./personalAssistantComputer";
import type { ComputerControlAction, ComputerState, ComputerWindow } from "./types/personalAssistantComputer";

const statuses = ["idle", "ready", "working", "waiting_confirmation", "paused", "manual", "ended", "error"];
const controls: ComputerControlAction[] = ["pause", "resume", "takeover", "return", "end"];
const actions = ["click", "set_value", "type_text", "scroll"];
const invalid = () => new Error("Launcher 电脑操作状态不可用，请重试。");
const exact = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
const bounded = (value: unknown, max: number): value is string => typeof value === "string" && value.length <= max;
const token = (value: unknown): value is string => bounded(value, 100) && value.length > 0;
function windowValue(value: unknown): value is ComputerWindow {
  return exact(value, ["selectionId", "title", "appName"]) && token(value.selectionId)
    && bounded(value.title, 240) && bounded(value.appName, 80);
}
function stateValue(value: unknown): ComputerState {
  if (!exact(value, ["available", "status", "message", "grantId", "window", "pending"])
    || typeof value.available !== "boolean" || typeof value.status !== "string" || !statuses.includes(value.status)
    || !bounded(value.message, 2000) || !(value.grantId === null || token(value.grantId))
    || !(value.window === null || windowValue(value.window))
    || (value.grantId === null) !== (value.window === null)) throw invalid();
  if (value.pending !== null && (!exact(value.pending, ["id", "action", "targetLabel", "text"])
    || !token(value.pending.id) || typeof value.pending.action !== "string" || !actions.includes(value.pending.action)
    || !bounded(value.pending.targetLabel, 400) || !(value.pending.text === null || bounded(value.pending.text, 2000))
    || value.grantId === null || value.status !== "waiting_confirmation")) throw invalid();
  return value as ComputerState;
}

/** Fixed operator verbs only. Electron main owns authentication and routing. */
export const launcherAssistantComputer: ComputerTransport = {
  scope: "launcher",
  async state(options) {
    options?.signal?.throwIfAborted();
    const result = await launcherAssistantBridge().invoke({ operation: "computerState" });
    options?.signal?.throwIfAborted();
    return stateValue(result);
  },
  async windows(options) {
    options?.signal?.throwIfAborted();
    const result = await launcherAssistantBridge().invoke({ operation: "computerWindows" });
    options?.signal?.throwIfAborted();
    if (!exact(result, ["windows"]) || !Array.isArray(result.windows)
      || result.windows.length > 256 || !result.windows.every(windowValue)) throw invalid();
    return { windows: result.windows as ComputerWindow[] };
  },
  async grant(payload) {
    if (!token(payload.selectionId) || payload.allowVision !== true) throw invalid();
    return stateValue(await launcherAssistantBridge().invoke({ operation: "computerGrant", selectionId: payload.selectionId, allowVision: true }));
  },
  async control(payload) {
    if (!token(payload.grantId) || !controls.includes(payload.action)) throw invalid();
    return stateValue(await launcherAssistantBridge().invoke({ operation: "computerControl", grantId: payload.grantId, action: payload.action }));
  },
  async confirm(payload) {
    if (!token(payload.grantId) || !token(payload.pendingId) || typeof payload.approved !== "boolean") throw invalid();
    return stateValue(await launcherAssistantBridge().invoke({ operation: "computerConfirm", grantId: payload.grantId, pendingId: payload.pendingId, approved: payload.approved }));
  },
};
