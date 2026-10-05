import { Archive, ArchiveRestore, MoreHorizontal, Trash2 } from "lucide-react";
import type { SessionSummary } from "../../api/types";
import { VDropdownMenu, VIconButton } from "../../components/vui";
import { researchRecordStatus } from "./stockResearchModel";

export type FinanceSessionAction = "archive" | "restore" | "delete";
export type FinanceSessionMenuProps = {
  record: SessionSummary;
  zh: boolean;
  disabled?: boolean;
  onAction: (record: SessionSummary, action: FinanceSessionAction) => void;
};

export function FinanceSessionMenu({ record, zh, disabled, onAction }: FinanceSessionMenuProps) {
  const archived = record.archiveState?.status === "archived";
  const running = ["Running", "Stopping"].includes(researchRecordStatus(record, false));
  const busy = disabled || running;
  return <VDropdownMenu align="end" aria-label={zh ? "研究会话操作" : "Research session actions"}
    trigger={<VIconButton variant="ghost" label={zh ? `管理研究：${record.title || "研究会话"}` : `Manage research: ${record.title || "Research session"}`} icon={<MoreHorizontal size={16} />} />}
    items={[
      { id: "archive", icon: archived ? <ArchiveRestore size={14} /> : <Archive size={14} />, label: archived ? (zh ? "恢复研究" : "Restore") : (zh ? "归档研究" : "Archive"), disabled: busy, title: running ? (zh ? "请先停止研究" : "Stop research first") : undefined, onSelect: () => onAction(record, archived ? "restore" : "archive") },
      { id: "delete", icon: <Trash2 size={14} />, label: zh ? "删除研究" : "Delete", disabled: busy, danger: true, title: running ? (zh ? "请先停止研究" : "Stop research first") : undefined, onSelect: () => onAction(record, "delete") },
    ]} />;
}
