import { RefreshCw } from "lucide-react";

import { VIconButton } from "../../components/vui";
import { TeamShellModeSwitch } from "./TeamShellModeSwitch";
import type { TeamShellMode } from "./teamShellModel";

export type TeamShellToolbarProps = {
  lang: "zh" | "en";
  teamName: string;
  purpose: string;
  mode: TeamShellMode;
  onModeChange: (mode: TeamShellMode) => void;
  onRefresh: () => void;
  identityClassName?: string;
  actionsClassName?: string;
  refreshButtonClassName?: string;
};

/**
 * Shared Teams shell toolbar: identity + board/canvas mode + refresh.
 */
export function TeamShellToolbar({
  lang,
  teamName,
  purpose,
  mode,
  onModeChange,
  onRefresh,
  identityClassName = "",
  actionsClassName = "",
  refreshButtonClassName = "",
}: TeamShellToolbarProps) {
  const fallbackName = lang === "zh" ? "暂无团队" : "No team";
  const fallbackPurpose =
    mode === "canvas"
      ? (lang === "zh" ? "组织画布" : "Organization canvas")
      : (lang === "zh" ? "看板工作台" : "Board workbench");

  return (
    <>
      <div className={identityClassName}>
        <strong>{teamName || fallbackName}</strong>
        <span>{purpose || fallbackPurpose}</span>
      </div>
      <div className={actionsClassName}>
        <TeamShellModeSwitch lang={lang} mode={mode} onChange={onModeChange} />
        <VIconButton
          className={refreshButtonClassName}
          label={lang === "zh" ? "刷新团队" : "Refresh teams"}
          icon={<RefreshCw size={15} />}
          onPress={onRefresh}
        />
      </div>
    </>
  );
}
