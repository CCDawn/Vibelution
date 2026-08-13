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
  return role === "workbench" ? `${name} 台` : `${name} 控`;
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
