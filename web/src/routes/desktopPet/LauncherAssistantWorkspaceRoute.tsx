import { useSearchParams } from "react-router-dom";
import { resolveLauncherAssistantPanel, type LauncherAssistantPanel } from "../../app/launcherNavigationModel";
import { useShellI18n } from "../../i18n/useShellI18n";
import { LauncherAssistantBrowserWorkspace } from "./LauncherAssistantBrowserWorkspace";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

/** Old bookmarks offer an explicit conversation request, never an automatic write. */
export function launcherAgentEntry(panel: LauncherAssistantPanel, lang: "zh" | "en") {
  const entries = {
    affairs: ["在对话里管理待办与提醒", "查看我的待办与提醒", "请查看我的待办与提醒，先不要修改。",
      "Manage to-dos and reminders in chat", "Show my to-dos and reminders", "Show my to-dos and reminders without changing them."],
    preferences: ["直接告诉助理你喜欢的回答方式", "查看当前对话偏好", "请读取我的当前对话偏好，先不要修改。",
      "Tell the assistant how you like to work", "Show conversation preferences", "Read my current conversation preferences without changing them."],
    "assistant-settings": ["在对话中调整助理", "查看助理设置", "请读取你的当前设置和可用外观选项，先不要修改。",
      "Adjust your assistant in chat", "Show assistant settings", "Read your current assistant settings and available appearance options without changing them."],
  } as const;
  if (!(panel in entries)) return undefined;
  const values = entries[panel as keyof typeof entries];
  const start = lang === "zh" ? 0 : 3;
  return { key: panel, title: values[start], label: values[start + 1], message: values[start + 2] };
}

export function LauncherAssistantWorkspaceRoute() {
  const [params] = useSearchParams();
  const panel = resolveLauncherAssistantPanel(params.toString());
  const { lang } = useShellI18n();
  if (panel === "browser") return <LauncherAssistantBrowserWorkspace />;
  return <LauncherAssistantRoute embedded navigationOwned computerRequested={panel === "computer"} entryIntent={launcherAgentEntry(panel, lang)} />;
}

export default LauncherAssistantWorkspaceRoute;
