import { useEffect, useMemo, useState } from "react";

import { exportSessionHtml, isFetchJsonHttpError } from "../../api/chat";
import type { ConversationMessage } from "../../api/types";
import { VButton, VCheckbox, VDialog } from "../vui";
import {
  buildConversationShareExportTurns,
  type ConversationShareExportTurn,
} from "./conversationShareExportModel";
import styles from "./ConversationShareExportDialog.styles";

export type ConversationShareExportDialogProps = {
  open: boolean;
  sessionId: string;
  messages: ConversationMessage[];
  language: "zh" | "en";
  onOpenChange: (open: boolean) => void;
};

type ExportOutcome = {
  filename: string;
  skippedCount: number;
};

/** Blob download via `<a download>`; Electron surfaces its native save dialog. */
function saveHtmlDocument(filename: string, html: string): void {
  if (typeof URL.createObjectURL !== "function") {
    return;
  }
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportErrorMessage(error: unknown, zh: boolean): string {
  if (isFetchJsonHttpError(error) && error.status === 404) {
    return zh ? "会话不存在或已被删除。" : "The session no longer exists.";
  }
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return detail || (zh ? "导出失败，请稍后重试。" : "The export failed; please retry.");
}

/**
 * Turn-selection dialog for the local HTML export (designs/product/
 * conversation.md): per-turn checkboxes with previews default to all turns,
 * the export action stays visible with a live count, and zero selection
 * disables it. The API response is saved client-side as one Blob download.
 */
export function ConversationShareExportDialog({
  open,
  sessionId,
  messages,
  language,
  onOpenChange,
}: ConversationShareExportDialogProps) {
  const zh = language === "zh";
  const turns = useMemo(() => buildConversationShareExportTurns(messages), [messages]);
  const allTurnIds = useMemo(() => turns.map((turn) => turn.turnId), [turns]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set(allTurnIds));
  const [includeImages, setIncludeImages] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ExportOutcome | null>(null);

  useEffect(() => {
    if (open) {
      setSelectedIds(new Set(allTurnIds));
      setIncludeImages(true);
      setExporting(false);
      setError(null);
      setOutcome(null);
    }
  }, [open, allTurnIds]);

  if (!open) {
    return null;
  }

  const toggleTurn = (turn: ConversationShareExportTurn, selected: boolean) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (selected) {
        next.add(turn.turnId);
      } else {
        next.delete(turn.turnId);
      }
      return next;
    });
  };
  const allSelected = allTurnIds.length > 0 && selectedIds.size === allTurnIds.length;
  const selectionCount = selectedIds.size;
  const exportDisabled = selectionCount === 0 || exporting;

  const runExport = async () => {
    setExporting(true);
    setError(null);
    setOutcome(null);
    try {
      const requested = allTurnIds.filter((turnId) => selectedIds.has(turnId));
      const result = await exportSessionHtml(sessionId, {
        turnIds: requested,
        includeAttachments: includeImages,
      });
      saveHtmlDocument(result.filename, result.html);
      setOutcome({ filename: result.filename, skippedCount: result.skippedTurnIds.length });
    } catch (caught) {
      setError(exportErrorMessage(caught, zh));
    } finally {
      setExporting(false);
    }
  };

  return (
    <VDialog
      data-vui="conversation-share-export-dialog"
      open
      onOpenChange={(next) => {
        if (!next && !exporting) onOpenChange(false);
      }}
      title={zh ? "导出会话为 HTML" : "Export conversation as HTML"}
      description={zh
        ? "选择要导出的轮次，生成一个本地自包含 HTML 文件（图片内嵌）并在浏览器中另存。"
        : "Pick the turns to export into one local self-contained HTML file (images embedded) and save it."}
      size="md"
      className={styles.dialog}
    >
      <div className={styles.body}>
        <div className={styles.controls} data-vui="conversation-share-export-controls">
          <VCheckbox
            isSelected={allSelected}
            onChange={(selected) => setSelectedIds(selected ? new Set(allTurnIds) : new Set<string>())}
          >
            {zh ? "全选" : "Select all"}
          </VCheckbox>
          <VCheckbox isSelected={includeImages} onChange={setIncludeImages}>
            {zh ? "内嵌图片附件" : "Embed image attachments"}
          </VCheckbox>
        </div>
        {turns.length === 0 ? (
          <p className={styles.empty}>{zh ? "没有可导出的轮次。" : "No turns to export."}</p>
        ) : (
          <ul className={styles.list} data-vui="conversation-share-export-turns">
            {turns.map((turn) => (
              <li key={turn.turnId} className={styles.row}>
                <VCheckbox
                  aria-label={zh ? `第 ${turn.turnNumber} 轮` : `Turn ${turn.turnNumber}`}
                  isSelected={selectedIds.has(turn.turnId)}
                  onChange={(selected) => toggleTurn(turn, selected)}
                />
                <div className={styles.rowBody}>
                  <span className={styles.rowHead}>
                    <span className={styles.turnLabel}>
                      {zh ? `第 ${turn.turnNumber} 轮` : `Turn ${turn.turnNumber}`}
                    </span>
                    {turn.timestamp ? <span className={styles.timestamp}>{turn.timestamp}</span> : null}
                    {turn.hasAttachments ? (
                      <span className={styles.timestamp}>{zh ? "含附件" : "attachments"}</span>
                    ) : null}
                  </span>
                  {turn.userPreviewText ? <p className={styles.preview}>{turn.userPreviewText}</p> : null}
                  {turn.assistantPreviewText ? (
                    <p className={styles.previewAssistant}>{turn.assistantPreviewText}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
        {error ? <p role="alert" className={styles.error}>{error}</p> : null}
        {outcome ? (
          <p role="status" className={styles.result} data-vui="conversation-share-export-result">
            {zh
              ? `已生成 ${outcome.filename}，正在另存。${outcome.skippedCount > 0 ? `已忽略 ${outcome.skippedCount} 个无效轮次。` : ""}`
              : `Generated ${outcome.filename}; saving now.${outcome.skippedCount > 0 ? ` ${outcome.skippedCount} unknown turn(s) skipped.` : ""}`}
          </p>
        ) : null}
      </div>
      <div className={styles.footer}>
        <VButton variant="ghost" isDisabled={exporting} onPress={() => onOpenChange(false)}>
          {zh ? "取消" : "Cancel"}
        </VButton>
        <VButton
          variant="primary"
          isPending={exporting}
          isDisabled={selectionCount === 0}
          onPress={() => void runExport()}
        >
          {zh
            ? `导出所选轮次（${selectionCount}）`
            : `Export selected turns (${selectionCount})`}
        </VButton>
      </div>
    </VDialog>
  );
}
