import { CheckCircle2, Eye, Trash2, TriangleAlert } from "lucide-react";

import type { MemoryCleanupExecuteResponse, MemoryCleanupPreviewResponse } from "../api/types";
import { VButton, VNativeInput } from "../components/vui";
import styles from "./MemoryCleanupPanel.styles";

export type MemoryCleanupTargetOptionView = {
  key: string;
  label: string;
  detail: string;
  risk: "critical" | "high" | "medium" | "low";
};

export type MemoryCleanupPanelCopy = {
  loading: string;
  missing: string;
  cleanupSelectedTargets: string;
  cleanupRows: string;
  cleanupHardDelete: string;
  cleanupFiles: string;
  cleanupVectorRecords: string;
  cleanupNoBackup: string;
  cleanupTargets: string;
  cleanupSelectTargets: string;
  cleanupNoTargets: string;
  cleanupPreview: string;
  cleanupCentralSourceBoundary: string;
  cleanupBytes: string;
  cleanupExecute: string;
  cleanupConfirmPhrase: string;
  cleanupConfirmPlaceholder: string;
  cleanupExecuteDone: string;
};

type MemoryCleanupFeedback = {
  tone: "idle" | "success" | "error";
  text: string;
};

type MemoryCleanupPanelProps = {
  copy: MemoryCleanupPanelCopy;
  targetOptions: MemoryCleanupTargetOptionView[];
  selectedTargetKeys: string[];
  selectedTargetCount: number;
  totalTargetCount: number;
  targetsLoading: boolean;
  report: MemoryCleanupPreviewResponse | MemoryCleanupExecuteResponse | null;
  execution: MemoryCleanupExecuteResponse | null;
  confirmationText: string;
  feedback: MemoryCleanupFeedback;
  previewPending: boolean;
  executePending: boolean;
  canExecute: boolean;
  formatByteCount: (value: number) => string;
  onToggleTarget: (targetKey: string) => void;
  onPreview: () => void;
  onExecute: () => void;
  onConfirmationTextChange: (value: string) => void;
};

export function MemoryCleanupPanel({
  copy,
  targetOptions,
  selectedTargetKeys,
  selectedTargetCount,
  totalTargetCount,
  targetsLoading,
  report,
  execution,
  confirmationText,
  feedback,
  previewPending,
  executePending,
  canExecute,
  formatByteCount,
  onToggleTarget,
  onPreview,
  onExecute,
  onConfirmationTextChange,
}: MemoryCleanupPanelProps) {
  const totals = report?.totals;

  return (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.cleanupSelectedTargets}</span>
          <strong>{selectedTargetCount}</strong>
          <small>{totalTargetCount}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.cleanupRows}</span>
          <strong>{totals?.rowCount ?? 0}</strong>
          <small>{copy.cleanupHardDelete}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.cleanupFiles}</span>
          <strong>{totals?.fileCount ?? 0}</strong>
          <small>{formatByteCount(totals?.byteCount ?? 0)}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.cleanupVectorRecords}</span>
          <strong>{totals?.vectorRecordCount ?? 0}</strong>
          <small>RAG</small>
        </section>
      </div>

      <section className={styles.cleanupWarning} title={copy.cleanupNoBackup}>
        <TriangleAlert size={16} />
        <strong>{copy.cleanupHardDelete}</strong>
      </section>

      <div className={styles.cleanupWorkspace}>
        <section className={styles.cleanupTargetPanel}>
          <div className={styles.panelHeader}>
            <div>
              <h2 title={copy.cleanupSelectTargets}>{copy.cleanupTargets}</h2>
            </div>
            <span className={styles.countPill}>{selectedTargetCount}</span>
          </div>
          {targetsLoading ? <div className={styles.emptyState}>{copy.loading}</div> : null}
          {!targetsLoading && !targetOptions.length ? <div className={styles.emptyState}>{copy.cleanupNoTargets}</div> : null}
          <div className={styles.cleanupTargetList}>
            {targetOptions.map((option) => {
              const selected = selectedTargetKeys.includes(option.key);
              return (
                <label key={option.key} className={styles.cleanupTargetRow} data-selected={selected} data-risk={option.risk}>
                  <VNativeInput
                    type="checkbox"
                    checked={selected}
                    onChange={() => onToggleTarget(option.key)}
                    aria-label={option.label}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.detail}</small>
                  </span>
                </label>
              );
            })}
          </div>
        </section>

        <section className={styles.cleanupPreviewPanel}>
          <div className={styles.panelHeader}>
            <div>
              <h2 title={copy.cleanupCentralSourceBoundary}>{copy.cleanupPreview}</h2>
            </div>
            <VButton
              type="button"
              className={styles.inlineActionButton}
              onClick={onPreview}
              isDisabled={!selectedTargetCount || previewPending}
            >
              <Eye size={15} />
              {copy.cleanupPreview}
            </VButton>
          </div>
          {report ? (
            <>
              <div className={styles.cleanupStats}>
                <span>{copy.cleanupRows}: {report.totals.rowCount}</span>
                <span>{copy.cleanupFiles}: {report.totals.fileCount}</span>
                <span>{copy.cleanupBytes}: {formatByteCount(report.totals.byteCount)}</span>
                <span>{copy.cleanupVectorRecords}: {report.totals.vectorRecordCount}</span>
              </div>
              <div className={styles.cleanupPreviewList}>
                {report.targets.map((target) => (
                  <article key={target.targetKey} className={styles.cleanupPreviewItem}>
                    <header>
                      <strong>{target.label}</strong>
                      <span>{target.status}</span>
                    </header>
                    <div className={styles.cleanupPreviewCounts}>
                      <span>{copy.cleanupRows}: {target.counts.rowCount}</span>
                      <span>{copy.cleanupFiles}: {target.counts.fileCount}</span>
                      <span>{copy.cleanupVectorRecords}: {target.counts.vectorRecordCount}</span>
                    </div>
                    {target.warnings.map((warning) => (
                      <p key={warning} className={styles.cleanupInlineWarning}>{warning}</p>
                    ))}
                    <div className={styles.cleanupPathList}>
                      {target.paths.map((path) => (
                        <span key={`${target.targetKey}:${path.path}:${path.action}`}>
                          <small>{path.action}{path.status ? ` · ${path.status}` : ""}</small>
                          <strong>{path.path}</strong>
                          <em>{path.rowCount ? `${path.rowCount} ${copy.cleanupRows}` : path.fileCount ? `${path.fileCount} ${copy.cleanupFiles}` : path.exists ? path.kind : copy.missing}</em>
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className={styles.emptyState}>{copy.cleanupSelectTargets}</div>
          )}
        </section>

        <section className={styles.cleanupExecutePanel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>{copy.cleanupExecute}</h2>
              <p>{copy.cleanupConfirmPhrase}: {report?.confirmationPhrase ?? "硬删除记忆"}</p>
            </div>
            <Trash2 size={18} />
          </div>
          <label className={styles.cleanupConfirmField}>
            <span>{copy.cleanupConfirmPhrase}</span>
            <VNativeInput
              value={confirmationText}
              placeholder={copy.cleanupConfirmPlaceholder}
              onChange={(event) => onConfirmationTextChange(event.target.value)}
            />
          </label>
          <VButton
            type="button"
            className={styles.cleanupExecuteButton}
            onClick={onExecute}
            isDisabled={!canExecute || executePending}
          >
            <Trash2 size={15} />
            {copy.cleanupExecute}
          </VButton>
          {feedback.tone !== "idle" ? (
            <p className={styles.cleanupFeedback} data-tone={feedback.tone}>{feedback.text}</p>
          ) : null}
          {execution ? (
            <div className={styles.cleanupExecutionSummary}>
              <CheckCircle2 size={18} />
              <span>{copy.cleanupExecuteDone}</span>
              <strong>{execution.totals.targetCount}</strong>
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}
