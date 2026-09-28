import { useEffect, useState } from "react";
import {
  applySessionTurnRewind,
  isFetchJsonHttpError,
  previewSessionTurnRewind,
  sessionRewindUnsafeFilesFromError,
} from "../../api/chat";
import type {
  SessionRewindFileItem,
  SessionRewindPreviewResponse,
  SessionRewindUnsafeFile,
} from "../../api/types";
import { VButton, VChip, VDialog } from "../vui";
import styles from "./ConversationFileRewindDialog.styles";

export type ConversationFileRewindDialogProps = {
  open: boolean;
  sessionId: string;
  turnId: string;
  language: "zh" | "en";
  onOpenChange: (open: boolean) => void;
};

type RewindApplyResult = {
  alreadyApplied: boolean;
  appliedCount: number;
  skippedCount: number;
};

/**
 * Human-facing label per server classification. Internal terms never leak:
 * e.g. `external_modified` reads as "another program changed the file after
 * this turn wrote it".
 */
const CLASSIFICATION_PRESENTATION: Record<string, { zh: string; en: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  safe: { zh: "可恢复", en: "Restorable", tone: "success" },
  checkpoint_missing: { zh: "无写入前检查点", en: "No before-checkpoint", tone: "warning" },
  external_modified: { zh: "写入后被其他程序修改", en: "Changed by another program after the turn", tone: "danger" },
  not_in_checkpoint: { zh: "不在检查点内", en: "Not in the checkpoint", tone: "neutral" },
  ignored: { zh: "不在回退范围", en: "Out of rewind scope", tone: "neutral" },
};

const ACTION_PRESENTATION: Record<string, { zh: string; en: string }> = {
  restore: { zh: "将恢复写入前内容", en: "Will restore the pre-turn content" },
  delete: { zh: "将删除该文件", en: "Will delete the file" },
  none: { zh: "无需操作", en: "No action needed" },
};

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function errorMessage(error: unknown, zh: boolean): string {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  if (isFetchJsonHttpError(error) && error.status === 404) {
    return zh ? "该轮次没有可回退的文件检查点。" : "This turn has no rewindable file checkpoints.";
  }
  return detail || (zh ? "请求失败，请稍后重试。" : "The request failed; please retry.");
}

/**
 * Whole-turn file rewind dialog (designs/product/conversation.md):
 * previews the server-classified per-file plan, applies strict by default and
 * falls back to force after a 409 conflict. The server stays the only safety
 * authority; this dialog only presents it and relays the operator decision.
 */
export function ConversationFileRewindDialog({
  open,
  sessionId,
  turnId,
  language,
  onOpenChange,
}: ConversationFileRewindDialogProps) {
  const zh = language === "zh";
  const [preview, setPreview] = useState<SessionRewindPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [unsafeFiles, setUnsafeFiles] = useState<SessionRewindUnsafeFile[] | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [result, setResult] = useState<RewindApplyResult | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPreview(null);
    setLoadError(null);
    setUnsafeFiles(null);
    setApplyError(null);
    setResult(null);
    setLoading(true);
    previewSessionTurnRewind(sessionId, turnId)
      .then((next) => {
        if (!cancelled) setPreview(next);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(errorMessage(error, zh));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, sessionId, turnId, zh, reloadToken]);

  const apply = async (force: boolean) => {
    setApplying(true);
    setApplyError(null);
    try {
      const response = await applySessionTurnRewind(sessionId, { turnId, force });
      setUnsafeFiles(null);
      setResult({
        alreadyApplied: Boolean(response.alreadyApplied),
        appliedCount: response.applied?.length ?? 0,
        skippedCount: response.skipped?.length ?? 0,
      });
    } catch (error) {
      if (isFetchJsonHttpError(error) && error.status === 409) {
        setUnsafeFiles(sessionRewindUnsafeFilesFromError(error));
      } else {
        setApplyError(errorMessage(error, zh));
      }
    } finally {
      setApplying(false);
    }
  };

  if (!open) return null;
  const classificationLabel = (item: { classification?: string }) => {
    const presentation = CLASSIFICATION_PRESENTATION[item.classification ?? ""]
      ?? CLASSIFICATION_PRESENTATION.not_in_checkpoint;
    return zh ? presentation.zh : presentation.en;
  };
  const actionLabel = (item: SessionRewindFileItem) => {
    const presentation = ACTION_PRESENTATION[item.action ?? "none"] ?? ACTION_PRESENTATION.none;
    return zh ? presentation.zh : presentation.en;
  };
  return (
    <VDialog
      data-vui="conversation-file-rewind-dialog"
      open
      onOpenChange={(next) => {
        if (!next && !applying) onOpenChange(false);
      }}
      title={zh ? "回退本轮文件" : "Rewind this turn's files"}
      description={zh
        ? "把本轮写入的文件恢复到本轮开始前的状态。回退只改动下方列出的文件。"
        : "Restore the files written in this turn to their state before it. Only the listed files are touched."}
      size="md"
      className={styles.dialog}
    >
      <div className={styles.body}>
        {loading ? <p role="status" className={styles.status}>{zh ? "正在加载回退预览…" : "Loading the rewind preview…"}</p> : null}
        {loadError ? (
          <>
            <p role="alert" className={styles.error}>{loadError}</p>
            <div className={styles.footer}>
              <VButton variant="secondary" onPress={() => setReloadToken((token) => token + 1)}>{zh ? "重试" : "Retry"}</VButton>
            </div>
          </>
        ) : null}
        {preview ? (
          <>
            {preview.capabilityNote ? <p className={styles.note}>{preview.capabilityNote}</p> : null}
            <ul className={styles.list}>
              {preview.files.map((item) => (
                <li key={item.path} className={styles.row}>
                  <span className={styles.path} title={item.path}>{item.path}</span>
                  <VChip tone={CLASSIFICATION_PRESENTATION[item.classification ?? "not_in_checkpoint"]?.tone ?? "neutral"}>
                    {classificationLabel(item)}
                  </VChip>
                  <span className={styles.rowMeta}>
                    <span className={styles.action}>{actionLabel(item)}</span>
                    <span className={styles.action}>
                      {item.currentExists ? formatFileSize(item.currentSize) : (zh ? "当前不存在" : "Missing on disk")}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            {unsafeFiles?.length ? (
              <div className={styles.conflict} data-vui="conversation-rewind-conflict">
                <p className={styles.conflictTitle}>
                  {zh
                    ? "部分文件在本轮写入后被再次修改，整批回退已被拒绝。"
                    : "Some files changed after this turn wrote them, so the batch rewind was rejected."}
                </p>
                <ul className={styles.list}>
                  {unsafeFiles.map((item) => (
                    <li key={item.path} className={styles.rowMeta}>
                      <span className={styles.path} title={item.path}>{item.path}</span>
                      <VChip tone={CLASSIFICATION_PRESENTATION[item.classification ?? "not_in_checkpoint"]?.tone ?? "danger"}>
                        {classificationLabel(item)}
                      </VChip>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {applyError ? <p role="alert" className={styles.error}>{applyError}</p> : null}
            {result ? (
              <p role="status" className={styles.result} data-vui="conversation-rewind-result">
                {result.alreadyApplied
                  ? (zh ? "本轮文件此前已恢复过，未重复执行。" : "This turn was already rewound; nothing was applied again.")
                  : (zh
                    ? `已恢复 ${result.appliedCount} 个文件；跳过 ${result.skippedCount} 个。`
                    : `Restored ${result.appliedCount} file(s); skipped ${result.skippedCount}.`)}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
      <div className={styles.footer}>
        <VButton variant="ghost" isDisabled={applying} onPress={() => onOpenChange(false)}>
          {result || loadError ? (zh ? "关闭" : "Close") : (zh ? "取消" : "Cancel")}
        </VButton>
        {preview && !result ? (
          <>
            {unsafeFiles?.length ? (
              <VButton variant="secondary" isPending={applying} onPress={() => void apply(true)}>
                {zh ? "仍恢复安全文件" : "Restore safe files only"}
              </VButton>
            ) : null}
            <VButton variant="primary" isPending={applying} onPress={() => void apply(false)}>
              {zh ? "回退本轮文件" : "Rewind files"}
            </VButton>
          </>
        ) : null}
      </div>
    </VDialog>
  );
}
