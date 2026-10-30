export type LauncherAssistantPanel = "dialogue" | "overview" | "affairs" | "dispatches" | "computer" | "preferences" | "assistant-settings";
export const LAUNCHER_ASSISTANT_PANELS: readonly LauncherAssistantPanel[] = ["dialogue", "overview", "affairs", "dispatches", "computer", "preferences", "assistant-settings"];
const panelLabels: Record<LauncherAssistantPanel, readonly [string, string]> = {
  dialogue: ["对话", "Chat"], overview: ["平台概览", "Overview"], affairs: ["事务", "Affairs"], dispatches: ["派遣与回执", "Dispatches & receipts"],
  computer: ["电脑操作", "Computer"], preferences: ["对话偏好", "Dialogue preferences"], "assistant-settings": ["助理设置", "Assistant settings"],
};
export function resolveLauncherAssistantPanel(search: string): LauncherAssistantPanel {
  const panel = new URLSearchParams(search).get("panel");
  return LAUNCHER_ASSISTANT_PANELS.find(value => value === panel) ?? "dialogue";
}
export function launcherAssistantPanelLabel(panel: LauncherAssistantPanel, lang: "zh" | "en"): string { return panelLabels[panel][lang === "zh" ? 0 : 1]; }
export function launcherAssistantPanelPath(panel: LauncherAssistantPanel): string {
  return panel === "dialogue" ? "/launcher/assistant" : `/launcher/assistant?panel=${panel}`;
}
