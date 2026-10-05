import styles from "./FinanceResearchHistory.styles";
import { useState } from "react";
import type { SessionSummary } from "../../api/types";
import { VButton, VInput, VSelect, VStateSurface } from "../../components/vui";
import { cleanResearchPreview, researchRecordStatus } from "./stockResearchModel";
import { FinanceSessionMenu, type FinanceSessionAction } from "./FinanceSessionMenu";

export function FinanceResearchHistory({ records, selectedId, onOpen, zh, compact = false, searchValue, onSearchChange, busy = false, error, onRetry, onAction, actionPending = false, archived = false }: {
  records: SessionSummary[]; selectedId: string; onOpen: (record: SessionSummary) => void; zh: boolean; compact?: boolean;
  searchValue?: string; onSearchChange?: (value: string) => void; busy?: boolean; error?: boolean; onRetry?: () => void;
  onAction?: (record: SessionSummary, action: FinanceSessionAction) => void; actionPending?: boolean; archived?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  // Server search includes transcript bodies. A second title-only filter would
  // discard those valid matches. Outcome filtering explicitly covers this page.
  const filtered = records.filter((row) => (searchValue !== undefined || `${row.title ?? ""} ${row.taskSummary ?? ""}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())) && (status === "all" || researchRecordStatus(row, false) === status));
  return <div className={styles.list} data-finance-report-history>
    {!compact ? <div className={styles.filters}><VInput value={searchValue ?? search} onChange={(event) => onSearchChange ? onSearchChange(event.target.value) : setSearch(event.target.value)} maxLength={200} placeholder={archived ? (zh ? "搜索已加载的归档研究" : "Search loaded archived research") : (zh ? "搜索全部研究：股票、报告期、正文" : "Search all research: stock, period, body")} aria-label={zh ? "搜索研究记录" : "Search research history"} /><VSelect className={styles.statusSelect} selectedKey={status} onSelectionChange={(key) => setStatus(String(key))} aria-label={zh ? "研究状态（已加载记录）" : "Status of loaded records"} options={[{ id: "all", label: zh ? "当前列表：全部状态" : "Loaded: all statuses" }, { id: "Running", label: zh ? "研究中" : "Running" }, { id: "Completed", label: zh ? "已完成" : "Completed" }, { id: "Stopped", label: zh ? "已停止" : "Stopped" }, { id: "Failed", label: zh ? "失败" : "Failed" }, { id: "Needs continuation", label: zh ? "待继续" : "Needs continuation" }]} /></div> : null}
    {error ? <VStateSurface density="compact" tone="error" title={zh ? "记录加载失败" : "History unavailable"} actions={<VButton onPress={onRetry}>{zh ? "重试" : "Retry"}</VButton>} /> : busy ? <VStateSurface density="compact" tone="loading" busy title={zh ? "正在查找研究记录" : "Searching research"} /> : !filtered.length ? <VStateSurface density="compact" tone="empty" title={zh ? "暂无匹配记录" : "No matching research"} /> : filtered.map((row) => <div key={row.id} className={styles.actionRow}><VButton variant="ghost" contentLayout="plain" className={[styles.record, row.id === selectedId ? styles.selectedRecord : ""].join(" ")} aria-pressed={row.id === selectedId} onPress={() => onOpen(row)}>
      <span className={styles.recordContent}><span className={styles.recordText}><strong className={styles.title}>{row.title || (zh ? "研究会话" : "Research session")}</strong><span className={styles.preview}>{compact ? researchRecordStatus(row, zh) : cleanResearchPreview(row.taskSummary ?? "") || researchRecordStatus(row, zh)}</span></span>{!compact ? <span className={styles.metadata}><span>{researchRecordStatus(row, zh)}</span><br />{row.updatedAt ? new Date(row.updatedAt).toLocaleDateString("zh-CN") : ""}</span> : null}</span>
    </VButton>{onAction ? <FinanceSessionMenu record={row} zh={zh} onAction={onAction} disabled={actionPending} /> : null}</div>)}
  </div>;
}
