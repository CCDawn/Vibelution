import { fetchJson } from "./client";

export type WorkbenchUiPreferences = {
  schemaVersion: number;
  paneLayouts: Record<string, Record<string, number>>;
  shell: {
    /** Leftover-only; current clients never write this. Migrated once into paneLayouts.chat. */
    chatPanelWidths?: {
      leftPanelWidth?: number;
      rightPanelWidth?: number;
    };
    topBarMode?: "full" | "hidden";
    leftRailCollapsed?: boolean;
    rightPaneCollapsed?: boolean;
  };
  updatedAt?: string | null;
};

export type WorkbenchUiPreferencesUpdate = {
  paneLayouts?: Record<string, Record<string, number>>;
  paneLayout?: {
    layoutId: string;
    widths: Record<string, number>;
  };
  shell?: WorkbenchUiPreferences["shell"];
};

export const WORKBENCH_UI_PREFERENCES_ENDPOINT = "/api/workbench/ui-preferences";

export function getWorkbenchUiPreferences() {
  return fetchJson<WorkbenchUiPreferences>(WORKBENCH_UI_PREFERENCES_ENDPOINT);
}

export function saveWorkbenchUiPreferences(payload: WorkbenchUiPreferencesUpdate) {
  return fetchJson<{ ok: boolean; preferences: WorkbenchUiPreferences }>(WORKBENCH_UI_PREFERENCES_ENDPOINT, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
