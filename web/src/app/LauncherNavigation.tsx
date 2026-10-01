import { Activity, Box, GitBranch, Settings2, Wrench } from "lucide-react";
import { useLocation } from "react-router-dom";
import type { LauncherBranchInstance } from "../api/launcher";
import { VRouteLinkButton } from "../components/vui";
import { instanceRuntimeState } from "../routes/LauncherBranchInstancesPanel.model";

/** Stable destinations; lifecycle operations remain owned by their existing routes. */
export function LauncherNavigation({ lang, items }: { lang: "zh" | "en"; items: LauncherBranchInstance[] }) {
  const location = useLocation();
  const view = new URLSearchParams(location.search).get("view");
  const selected = location.pathname.endsWith("/tools") ? (view === "maintenance" ? "maintenance" : "diagnostics") : view === "settings" ? "settings" : "branches";
  const links = [
    { id: "branches", label: lang === "zh" ? "分支" : "Branches", to: "/launcher", Icon: Box },
    { id: "diagnostics", label: lang === "zh" ? "诊断" : "Diagnostics", to: "/launcher/tools?view=diagnostics", Icon: Activity },
    { id: "maintenance", label: lang === "zh" ? "维护" : "Maintenance", to: "/launcher/tools?view=maintenance", Icon: Wrench },
    { id: "settings", label: lang === "zh" ? "设置" : "Settings", to: "/launcher?view=settings", Icon: Settings2 },
  ];
  const running = items.filter((item) => instanceRuntimeState(item) === "running").length;
  return <nav aria-label={lang === "zh" ? "Launcher 功能导航" : "Launcher navigation"} className="flex h-full flex-col gap-1 border-r border-vui-border-subtle bg-vui-surface-workspace p-3 max-[700px]:flex-row max-[700px]:overflow-auto max-[700px]:border-b max-[700px]:border-r-0 max-[700px]:p-2">
    <div className="mb-5 px-3 pt-2 max-[700px]:hidden"><p className="m-0 text-vui-xs text-vui-fg-tertiary">{lang === "zh" ? "本地项目" : "Local project"}</p><p className="mb-0 mt-2 flex items-center gap-2 text-vui-sm font-semibold"><GitBranch size={16} aria-hidden="true" />Vibelution</p></div>
    {links.map(({ id, label, to, Icon }) => <div key={id} className={id === "settings" ? "mt-auto max-[700px]:mt-0" : ""}>
      {id === "settings" ? <p className="mb-3 px-3 text-vui-xs text-vui-fg-tertiary max-[700px]:hidden">{lang === "zh" ? `本地运行 · ${running} 个工作区` : `${running} running workspaces`}</p> : null}
      <VRouteLinkButton to={to} chrome="shell-nav" aria-current={selected === id ? "page" : undefined} className={`flex min-h-10 w-full items-center gap-3 rounded-md px-3 text-vui-sm font-medium max-[700px]:min-h-11 ${selected === id ? "bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool)]" : "text-vui-fg-secondary hover:bg-vui-surface-row-hover"}`} icon={<Icon size={17} aria-hidden="true" />}>{label}</VRouteLinkButton>
    </div>)}
  </nav>;
}
