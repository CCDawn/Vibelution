import { Archive, EyeOff, LayoutDashboard, Pencil, Settings2 } from "lucide-react";
import type { Team } from "../../api/types";
import { VDropdownMenu, type VDropdownMenuItem } from "../../components/vui";
import styles from "./TeamContextMenu.styles";
import { isReadOnlyTeam } from "./TeamSettingsDialog";

export type TeamContextMenuState = { x: number; y: number; team: Team };
type Props = {
  lang: "zh" | "en";
  state: TeamContextMenuState;
  onRename: (team: Team) => void;
  onManage: (team: Team) => void;
  onOpenWorkspace: (team: Team) => void;
  onHide: (team: Team) => void;
  onArchive: (team: Team) => void;
  onDismiss: () => void;
};

export function teamContextMenuItems(props: Props): VDropdownMenuItem[] {
  const { lang, state: { team }, onRename, onManage, onOpenWorkspace, onHide, onArchive } = props;
  const zh = lang === "zh";
  const locked = isReadOnlyTeam(team);
  const lockReason = zh ? "该团队由系统工作流维护，不能在这里修改或归档" : "This team is maintained by a system workflow.";
  return [
    { id: "rename", label: zh ? "重命名" : "Rename", icon: <Pencil size={14} />, disabled: locked,
      title: locked ? lockReason : undefined, onSelect: () => onRename(team) },
    { id: "manage", label: zh ? "管理团队" : "Manage team", icon: <Settings2 size={14} />,
      title: locked ? (zh ? "查看团队设置（只读）" : "View team settings (read-only)") : undefined,
      onSelect: () => onManage(team) },
    { id: "workspace", label: zh ? "打开团队工作台" : "Open team workspace", icon: <LayoutDashboard size={14} />,
      onSelect: () => onOpenWorkspace(team) },
    { id: "hide", label: zh ? "隐藏团队" : "Hide team", icon: <EyeOff size={14} />,
      title: zh ? "仅从当前浏览器的左栏隐藏，保留全部记录；可在已隐藏团队中恢复" : "Hide from this browser's rail; keep all records and restore later.",
      onSelect: () => onHide(team) },
    { id: "archive", label: zh ? "归档团队" : "Archive team", icon: <Archive size={14} />, danger: true, disabled: locked,
      title: locked ? lockReason : (zh ? "归档后只读，当前成员 Agent 一并归档，关联群聊房间将被删除；需要再次确认" : "Locks the team, archives current member Agents, and deletes linked chat rooms; confirmation required."),
      onSelect: () => onArchive(team) },
  ];
}

export function TeamContextMenu(props: Props) {
  return <VDropdownMenu open position={{ x: props.state.x, y: props.state.y }}
    aria-label={props.lang === "zh" ? "团队操作" : "Team actions"}
    onOpenChange={(open) => { if (!open) props.onDismiss(); }}
    contentClassName={styles.sessionContextMenu} itemClassName={styles.sessionContextMenuItem}
    dangerItemClassName={styles.sessionContextMenuDanger}
    contentProps={{ "data-team-context-menu": props.state.team.teamId }}
    items={teamContextMenuItems(props)} />;
}
