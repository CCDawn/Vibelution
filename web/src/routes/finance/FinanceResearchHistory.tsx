import styles from "./FinanceResearchHistory.styles";
import { useState } from "react";
import type { SessionSummary } from "../../api/types";
import { VButton, VInput, VSelect, VStateSurface } from "../../components/vui";
import { cleanResearchPreview, researchRecordStatus } from "./stockResearchModel";

export function FinanceResearchHistory({ records, selectedId, onOpen, zh, compact = false }: { records: SessionSummary[]; selectedId: string; onOpen: (record: SessionSummary) => void; zh: boolean; compact?: boolean }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const filtered = records.filter((row) => `${row.title} ${row.taskSummary}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()) && (status === "all" || researchRecordStatus(row, false) === status));
  return <div className={styles.list} data-finance-report-history>
    {!compact ? <div className={styles.filters}><VInput value={search} onChange={(event) => setSearch(event.target.value)} placeholder={zh ? "股票、报告期或关键词" : "Stock, period or keyword"} aria-label={zh ? "搜索研究记录" : "Search research history"} /><VSelect className={styles.statusSelect} selectedKey={status} onSelectionChange={(key) => setStatus(String(key))} aria-label={zh ? "研究状态" : "Research status"} options={[{ id: "all", label: zh ? "全部状态" : "All statuses" }, { id: "Running", label: zh ? "研究中" : "Running" }, { id: "Completed", label: zh ? "已完成" : "Completed" }, { id: "Stopped", label: zh ? "已停止" : "Stopped" }, { id: "Failed", label: zh ? "失败" : "Failed" }, { id: "Needs continuation", label: zh ? "待继续" : "Needs continuation" }]} /></div> : null}
    {!filtered.length ? <VStateSurface density="compact" tone="empty" title={zh ? "暂无匹配记录" : "No matching research"} /> : filtered.map((row) => <VButton key={row.id} variant="ghost" contentLayout="plain" className={[styles.record, row.id === selectedId ? styles.selectedRecord : ""].join(" ")} aria-pressed={row.id === selectedId} onPress={() => onOpen(row)}>
      <span className={styles.recordContent}><span className={styles.recordText}><strong className={styles.title}>{row.title || (zh ? "研究会话" : "Research session")}</strong><span className={styles.preview}>{compact ? researchRecordStatus(row, zh) : cleanResearchPreview(row.taskSummary) || researchRecordStatus(row, zh)}</span></span>{!compact ? <span className={styles.metadata}><span>{researchRecordStatus(row, zh)}</span><br />{row.updatedAt ? new Date(row.updatedAt).toLocaleDateString("zh-CN") : ""}</span> : null}</span>
    </VButton>)}
  </div>;
}
