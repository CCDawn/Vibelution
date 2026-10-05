import type { ReactNode } from "react";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/financialMarket";
import type { SessionSummary } from "../../api/types";
import { VButton, VChip, VStateSurface, VSurface, VTabs } from "../../components/vui";
import { isBlankResearchPlaceholder, researchRecordStatus } from "./stockResearchModel";
import styles from "./FinanceTaskCenter.styles";
import { FinanceSessionMenu, type FinanceSessionAction } from "./FinanceSessionMenu";

import { FinanceResearchJobs } from "./FinanceResearchJobs";

export function FinanceTaskCenter({ assistant, stock, watchlist, onOpenRun, moreRecords, tab, onTabChange, records, selectedId, onOpen, onRefresh, loading, error, zh, onAction, actionPending }: {
  assistant: FinancialAssistant; stock: StockIdentity; watchlist: StockIdentity[];
  onOpenRun: (runId: string, symbol: string) => void; moreRecords?: ReactNode;
  tab: string; onTabChange: (tab: string) => void;
  records: SessionSummary[]; selectedId: string; onOpen: (record: SessionSummary) => void;
  onRefresh: () => void; loading: boolean; error: boolean; zh: boolean;
  onAction?: (record: SessionSummary, action: FinanceSessionAction) => void; actionPending?: boolean;
}) {
  const visible = records.filter((record) => !isBlankResearchPlaceholder(record));
  const active = visible.filter((record) => researchRecordStatus(record, false) === "Running");
  const waiting = visible.filter((record) => researchRecordStatus(record, false) === "Needs continuation");
  return <div className={styles.page} data-finance-task-center><div className={styles.toolbar}><h1 className={styles.heading}>{zh ? "研究任务" : "Research tasks"}</h1>{tab === "records" ? <VButton onPress={onRefresh} isPending={loading}>{zh ? "刷新" : "Refresh"}</VButton> : null}</div>
    <VTabs value={tab} onValueChange={onTabChange} aria-label={zh ? "研究任务类型" : "Research task type"} items={[{ id: "records", label: zh ? "研究记录" : "Research records" }, { id: "batches", label: zh ? "批量研究" : "Batch research" }, { id: "schedules", label: zh ? "定时计划" : "Schedules" }]} />
    {tab !== "records" ? <FinanceResearchJobs assistant={assistant} stock={stock} watchlist={watchlist} mode={tab === "batches" ? "batches" : "schedules"} zh={zh} onOpenRun={onOpenRun} /> : <><div className={styles.metrics}><VSurface className={styles.metric}><span>{zh ? "运行中" : "Running"}</span><strong>{active.length}</strong></VSurface><VSurface className={styles.metric}><span>{zh ? "待继续" : "Needs continuation"}</span><strong>{waiting.length}</strong></VSurface><VSurface className={styles.metric}><span>{zh ? "已加载记录" : "Loaded tasks"}</span><strong>{visible.length}</strong></VSurface></div>
    {error ? <VStateSurface tone="error" title={zh ? "任务加载失败" : "Tasks unavailable"} actions={<VButton onPress={onRefresh}>{zh ? "重试" : "Retry"}</VButton>} /> : loading && !visible.length ? <VStateSurface tone="loading" busy title={zh ? "加载研究任务" : "Loading tasks"} /> : !visible.length ? <VStateSurface tone="empty" title={zh ? "暂无研究任务" : "No research tasks"} /> : <div className={styles.list}>{visible.map((record) => { const state = researchRecordStatus(record, false); return <VSurface key={record.id} className={[styles.row, selectedId === record.id ? styles.selected : ""].join(" ")}><div className={styles.identity}><strong className={styles.title}>{record.title || (zh ? "研究会话" : "Research session")}</strong><span className={styles.small}>{record.updatedAt ? new Date(record.updatedAt).toLocaleString() : ""}</span></div><VChip tone={state === "Failed" || state === "Needs continuation" || state === "Stopped" ? "warning" : state === "Completed" ? "success" : "neutral"}>{researchRecordStatus(record, zh)}</VChip><VButton onPress={() => onOpen(record)}>{zh ? "查看" : "Open"}</VButton>{onAction ? <FinanceSessionMenu record={record} zh={zh} onAction={onAction} disabled={actionPending} /> : null}</VSurface>; })}</div>}
    {moreRecords}</>}
  </div>;
}
