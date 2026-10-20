import { useEffect, useState } from "react";
import { History, Plus, X } from "lucide-react";
import type { SessionSummary } from "../../api/types";
import { VIconButton, VTabs } from "../../components/vui";
import { FinanceSessionMenu, type FinanceSessionAction } from "./FinanceSessionMenu";
import styles from "./FinanceDesktopSessions.styles";

/** Open tabs are UI state. Closing one never deletes or archives a Session. */
export function FinanceDesktopSessions({ activeId, sessions, activeSession, removedIds = [], zh, creating, pending, onOpen, onNew, onManage, onAction }: {
  activeId: string; sessions: SessionSummary[]; activeSession?: SessionSummary; zh: boolean; creating: boolean; pending: boolean;
  removedIds?: string[];
  onOpen: (row: SessionSummary) => void; onNew: () => void; onManage: () => void;
  onAction: (row: SessionSummary, action: FinanceSessionAction) => void;
}) {
  const [openedIds, setOpenedIds] = useState([activeId]);
  const [knownSessions, setKnownSessions] = useState<SessionSummary[]>([]);
  useEffect(() => { setOpenedIds(ids => ids.includes(activeId) ? ids : [...ids, activeId]); }, [activeId]);
  useEffect(() => {
    setKnownSessions(previous => {
      const next = new Map(previous.map(row => [row.id, row]));
      for (const row of sessions) if (openedIds.includes(row.id)) next.set(row.id, row);
      if (activeSession) next.set(activeId, activeSession);
      for (const id of removedIds) next.delete(id);
      const value = [...next.values()].filter(row => openedIds.includes(row.id) || row.id === activeId);
      return JSON.stringify(previous) === JSON.stringify(value) ? previous : value;
    });
  }, [sessions, activeSession, activeId, openedIds, removedIds]);
  const rows = new Map([...knownSessions, ...sessions].map(row => [row.id, row]));
  if (activeSession) rows.set(activeId, activeSession);
  for (const id of removedIds) rows.delete(id);
  const visibleIds = openedIds.includes(activeId) ? openedIds : [...openedIds, activeId];
  const opened = visibleIds.flatMap(id => { const row = rows.get(id); return row && row.archiveState?.status !== "archived" ? [row] : []; });
  const current = rows.get(activeId);
  function closeCurrent() {
    if (opened.length < 2) return;
    const index = opened.findIndex(row => row.id === activeId);
    const next = opened[index > 0 ? index - 1 : 1];
    if (!next) return;
    onOpen(next);
    setOpenedIds(ids => ids.filter(id => id !== activeId));
  }
  return <div className={styles.root} data-finance-desktop-sessions>
    <div className={styles.scroll}><VTabs className={styles.tabs} listClassName={styles.list} triggerClassName={styles.trigger} value={activeId} onValueChange={id => { const row = rows.get(id); if (row) onOpen(row); }} aria-label={zh ? "已打开的研究会话" : "Open research sessions"} items={opened.map(row => ({ id: row.id, title: row.title, label: <span className={styles.label}>{["running", "stopping"].includes(row.status) ? <i className={styles.busy} aria-label={zh ? "研究中" : "Running"} /> : null}<span>{row.title || (zh ? "研究会话" : "Research session")}</span></span> }))} /></div>
    <div className={styles.actions}><VIconButton variant="ghost" className={styles.icon} label={zh ? "追加研究" : "Continue research"} icon={<Plus size={15} />} isDisabled={creating} onPress={onNew} /><VIconButton variant="ghost" className={styles.icon} label={zh ? "全部会话" : "All sessions"} icon={<History size={15} />} onPress={onManage} /><VIconButton variant="ghost" className={styles.icon} label={zh ? "关闭当前标签" : "Close current tab"} title={zh ? "只关闭标签，会话保留；至少保留一个标签" : "Close the tab only; keep at least one tab"} icon={<X size={14} />} isDisabled={opened.length < 2} onPress={closeCurrent} />{current ? <FinanceSessionMenu record={current} zh={zh} disabled={pending} onAction={onAction} /> : null}</div>
  </div>;
}
