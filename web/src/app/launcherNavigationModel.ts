export type LauncherAssistantPanel = "dialogue" | "tasks" | "browser" | "affairs" | "computer" | "preferences" | "assistant-settings";
export const LAUNCHER_ASSISTANT_PANELS: readonly LauncherAssistantPanel[] = ["dialogue", "tasks", "browser", "affairs", "computer", "preferences", "assistant-settings"];
const panelLabels: Record<LauncherAssistantPanel, readonly [string, string]> = {
  dialogue: ["对话", "Chat"], tasks: ["任务", "Tasks"], browser: ["浏览器", "Browser"], affairs: ["待办与提醒", "To-dos & reminders"],
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
