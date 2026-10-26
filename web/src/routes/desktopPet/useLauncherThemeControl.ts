import { useEffect } from "react";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme, subscribeStoredWorkbenchTheme,
  writeStoredWorkbenchTheme, type WorkbenchTheme } from "../../app/themePreference";

export interface LauncherThemeBridge {
  onCommand(listener: (payload: unknown) => void): () => void;
  respond(payload: unknown): Promise<unknown>;
}
type Command = { deliveryId: string; operation: "read" | "set"; theme?: WorkbenchTheme };

function commandFrom(payload: unknown): Command | null {
  try {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    const prototype = Object.getPrototypeOf(payload);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const values: Record<string, unknown> = Object.create(null);
    for (const key of Reflect.ownKeys(payload)) {
      if (typeof key !== "string") return null;
      const descriptor = Object.getOwnPropertyDescriptor(payload, key);
      if (!descriptor || !("value" in descriptor)) return null;
      values[key] = descriptor.value;
    }
    if (typeof values.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(values.deliveryId)) return null;
    const keys = values.operation === "read" ? ["deliveryId", "operation"] : ["deliveryId", "operation", "theme"];
    if (Object.keys(values).length !== keys.length || !keys.every(key => Object.hasOwn(values, key))) return null;
    if (values.operation === "read") return { deliveryId: values.deliveryId, operation: "read" };
    if (values.operation !== "set" || (values.theme !== "dark" && values.theme !== "light")) return null;
    return { deliveryId: values.deliveryId, operation: "set", theme: values.theme };
  } catch { return null; }
}

function browserBridge(): LauncherThemeBridge | undefined {
  return typeof window === "undefined" ? undefined
    : (window as Window & { vibelutionLauncherTheme?: LauncherThemeBridge }).vibelutionLauncherTheme;
}

/** Launcher-origin storage remains the sole preference authority. */
export function useLauncherThemeControl(bridge: LauncherThemeBridge | undefined = browserBridge()): void {
  useEffect(() => {
    const apply = (theme: WorkbenchTheme) => applyWorkbenchDocumentTheme(document, theme);
    const unsubscribeTheme = subscribeStoredWorkbenchTheme(apply);
    apply(readStoredWorkbenchTheme());
    if (!bridge) return unsubscribeTheme;
    const unsubscribeCommand = bridge.onCommand(payload => {
      const command = commandFrom(payload);
      if (!command) return;
      const respond = (code: "read" | "applied" | "unavailable" | "persistence_failed", theme?: WorkbenchTheme) => {
        const result = { deliveryId: command.deliveryId, operation: command.operation, code, ...(theme ? { theme } : {}) };
        void Promise.resolve().then(() => bridge.respond(result)).catch(() => undefined);
      };
      try {
        if (command.operation === "set" && !writeStoredWorkbenchTheme(command.theme!)) {
          respond("persistence_failed"); return;
        }
        const theme = readStoredWorkbenchTheme();
        apply(theme);
        if (document.documentElement.dataset.theme !== theme || (command.operation === "set" && theme !== command.theme)) {
          respond("unavailable"); return;
        }
        respond(command.operation === "read" ? "read" : "applied", theme);
      } catch { respond("unavailable"); }
    });
    return () => { unsubscribeCommand(); unsubscribeTheme(); };
  }, [bridge]);
}
