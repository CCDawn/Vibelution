export type InstanceWindowRole = "workbench" | "launcher";

export type InstanceWindowTitleSource = {
  currentShortName?: string;
  currentWorkbenchTitle?: string;
  currentLauncherTitle?: string;
  items?: Array<{
    current?: boolean;
    shortName?: string;
    workbenchTitle?: string;
    launcherTitle?: string;
  }>;
};

export function instanceWindowTitle(role: InstanceWindowRole, shortName = "main"): string {
  const name = String(shortName || "main").trim() || "main";
  if (role === "launcher") return "Vibelution 启动管理";
  const label = name.replace(/^(branch\+|retired\+)/, "");
  return name === "main" ? "Vibelution 工作台 · main" : `Vibelution 测试工作台 · ${label}`;
}

export function currentInstanceWindowTitle(
  role: InstanceWindowRole,
  payload: InstanceWindowTitleSource | null | undefined,
): string {
  if (role === "workbench" && payload?.currentWorkbenchTitle) {
    return payload.currentWorkbenchTitle;
  }
  if (role === "launcher" && payload?.currentLauncherTitle) {
    return payload.currentLauncherTitle;
  }
  const current = payload?.items?.find((item) => item.current);
  if (current?.shortName) {
    return instanceWindowTitle(role, current.shortName);
  }
  return instanceWindowTitle(role, payload?.currentShortName);
}
