import { useEffect, useId } from "react";
import { ShieldAlert } from "lucide-react";

import { VButton } from "../../components/vui";
import type { SessionToolApprovalRequest } from "../../api/types";
import styles from "./ChatToolApprovalDialog.styles";
import {
  assistantActionWindowSummary,
  toolApprovalActionPreview,
  toolApprovalCodexButtonLabels,
  toolApprovalCodexTitle,
  toolApprovalDisplayName,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

export type ChatToolApprovalLabel = {
  id: string;
  label: string;
};

type ChatToolApprovalDialogProps = {
  lang: "zh" | "en";
  pending: boolean;
  /** Prevent approval when the caller cannot verify the displayed request. */
  approveDisabled?: boolean;
  /** Prevent rejection when the caller cannot bind the decision safely. */
  rejectDisabled?: boolean;
  rawTitle: string;
  riskLabel: string;
  scopeLabel: string;
  toolLabels: ChatToolApprovalLabel[];
  /** Codex-style action body (command/path preview). */
  actionPreview?: string;
  /** Show the complete preview in a keyboard-scrollable area. */
  fullActionPreview?: boolean;
  sessionGrantScope?: Record<string, unknown>;
  toolName?: string;
  /** b3: assistant manage action-window projection (remaining delegation time). */
  assistantActionWindow?: SessionToolApprovalRequest["assistantActionWindow"];
  /** banner: composer-adjacent bar; inline: under tool activity in transcript. */
  variant?: "banner" | "inline";
  onApprove: () => void;
  onApproveForSession?: () => void;
  /** b1: coarser opt-in tier — this tool for the rest of the session. */
  onApproveForSessionTool?: () => void;
  /** b3: approve once and open the low-risk manage action window. */
  onApproveWithActionWindow?: () => void;
  onReject: () => void;
};

/**
 * Compact Codex-aligned approval surface (composer-adjacent by default):
 * - Title: Allow this action? / 允许执行？
 * - Body: one-line command preview
 * - Actions: Yes · Always · No
 * - Hotkeys: y / a / n (when not pending)
 *
 * Semantics: this banner/inline surface is intentionally non-modal — it has no
 * focus trap or background blocking, so aria-modal is never declared.
 * variant === "banner" renders composer-adjacent; "inline" renders in transcript.
 */
export function ChatToolApprovalDialog({
  lang,
  pending,
  approveDisabled = false,
  rejectDisabled = false,
  rawTitle,
  riskLabel,
  scopeLabel,
  toolLabels,
  actionPreview,
  fullActionPreview = false,
  sessionGrantScope,
  toolName,
  assistantActionWindow,
  variant = "banner",
  onApprove,
  onApproveForSession,
  onApproveForSessionTool,
  onApproveWithActionWindow,
  onReject,
}: ChatToolApprovalDialogProps) {
  const dialogId = useId();
  const titleId = `${dialogId}-title`;
  const scopeId = `${dialogId}-scope`;
  const riskId = `${dialogId}-risk`;
  const toolListId = `${dialogId}-tools`;
  const previewId = `${dialogId}-preview`;
  const grantId = `${dialogId}-grant`;
  const windowId = `${dialogId}-window`;
  const descriptionIds = `${riskId} ${scopeId} ${toolListId} ${previewId} ${grantId} ${windowId}`;
  const buttons = toolApprovalCodexButtonLabels(lang);
  const primaryToolName = toolName || toolLabels[0]?.id || "";
  const displayName = toolLabels.find((item) => item.id === primaryToolName)?.label || toolApprovalDisplayName(primaryToolName, lang);
  const preview = String(actionPreview || toolApprovalActionPreview(undefined, primaryToolName) || rawTitle || "").trim();
  const grantText = toolApprovalSessionGrantDescription(sessionGrantScope, lang).trim();
  const showGrant = Boolean(grantText) && onApproveForSession;
  const riskText = String(riskLabel || "").trim();
  const scopeText = String(scopeLabel || "").trim();
  const visibleLabels = toolLabels.slice(0, 4);
  const extraCount = Math.max(0, toolLabels.length - visibleLabels.length);
  const actionWindowText = assistantActionWindowSummary(assistantActionWindow, lang).trim();

  useEffect(() => {
    if (pending) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const target = event.target as HTMLElement | null;
      const tag = String(target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "y") {
        event.preventDefault();
        if (!approveDisabled) onApprove();
        return;
      }
      if (key === "a" && onApproveForSession) {
        event.preventDefault();
        if (!approveDisabled) onApproveForSession();
        return;
      }
      if (key === "n" || key === "escape") {
        if (!rejectDisabled) {
          event.preventDefault();
          onReject();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [approveDisabled, rejectDisabled, onApprove, onApproveForSession, onReject, pending]);

  return (
    <div
      className={variant === "inline" ? styles.overlayInline : styles.overlay}
      role="presentation"
      data-chat-tool-approval-variant={variant}
    >
      <section
        className={variant === "inline" ? styles.dialogInline : styles.dialog}
        role="dialog"
        aria-labelledby={titleId}
        aria-describedby={descriptionIds}
        aria-busy={pending}
      >
        <div className={styles.icon} aria-hidden="true">
          <ShieldAlert size={16} />
        </div>
        <div className={styles.body}>
          <div className={styles.header}>
            <strong id={titleId} className={styles.headerTitle}>{toolApprovalCodexTitle(lang)}</strong>
            {riskText ? <span id={riskId} className={styles.scopeBadge}>{riskText}</span> : <span id={riskId} className="sr-only" />}
            {scopeText ? <span className={styles.scopeBadge} id={scopeId}>{scopeText}</span> : <span id={scopeId} className="sr-only" />}
            {displayName ? <span className={styles.scopeBadge}>{displayName}</span> : null}
          </div>
          <pre id={previewId} className={fullActionPreview ? styles.commandPreviewFull : styles.commandPreview}
            title={preview} tabIndex={fullActionPreview ? 0 : undefined}>
            {preview || (lang === "zh" ? "（无命令预览）" : "(no command preview)")}
          </pre>
          {showGrant ? (
            <p id={grantId} className={styles.grantDescription}>{grantText}</p>
          ) : (
            <span id={grantId} className="sr-only" />
          )}
          {actionWindowText ? (
            <p id={windowId} className={styles.grantDescription} data-chat-approval-action-window>
              {actionWindowText}
            </p>
          ) : (
            <span id={windowId} className="sr-only" />
          )}
          {/* Keep labels for a11y without visual chip clutter. */}
          <div id={toolListId} className={styles.toolList} title={rawTitle} role="list">
            {visibleLabels.length
              ? visibleLabels.map((item) => (
                <span key={item.id} className={styles.toolItem} role="listitem">{item.label}</span>
              ))
              : (
                <span className={styles.toolItem} role="listitem">
                  {displayName}
                </span>
              )}
            {extraCount ? (
              <span className={styles.toolItem} role="listitem">{lang === "zh" ? `另 ${extraCount} 项` : `+${extraCount}`}</span>
            ) : null}
          </div>
          {!rejectDisabled ? <p className={styles.hotkeys}>
            {lang === "zh"
              ? onApproveForSession ? "Y 是 · A 始终 · N 否" : "Y 是 · N 否"
              : onApproveForSession ? "Y Yes · A Always · N No" : "Y Yes · N No"}
          </p> : null}
        </div>
        <div className={styles.actions}>
          <VButton
            type="button"
            className={styles.yesButton}
            onClick={onApprove}
            isDisabled={pending || approveDisabled}
            title={lang === "zh" ? "仅批准本次（Y）" : "Allow this once (Y)"}
          >
            <span>{pending ? buttons.resolving : buttons.yes}</span>
          </VButton>
          {onApproveForSession ? (
            <VButton
              type="button"
              className={styles.alwaysButton}
              onClick={onApproveForSession}
              isDisabled={pending || approveDisabled}
              title={lang === "zh" ? "本会话始终允许同类调用（A）" : "Always allow for this session (A)"}
            >
              <span>{buttons.always}</span>
            </VButton>
          ) : null}
          {onApproveForSessionTool ? (
            <VButton
              type="button"
              className={styles.alwaysButton}
              onClick={onApproveForSessionTool}
              isDisabled={pending || approveDisabled}
              data-chat-approval-accept-tool-session="true"
              title={lang === "zh" ? "本会话内此工具不再询问" : "Stop asking for this tool this session"}
            >
              <span>{buttons.toolSession}</span>
            </VButton>
          ) : null}
          {onApproveWithActionWindow ? (
            <VButton
              type="button"
              className={styles.alwaysButton}
              onClick={onApproveWithActionWindow}
              isDisabled={pending || approveDisabled}
              data-chat-approval-accept-action-window="true"
              title={lang === "zh" ? "批准本次并授权未来 4 小时内同类低风险操作直办" : "Approve once and allow this low-risk action directly for 4 hours"}
            >
              <span>{buttons.actionWindow}</span>
            </VButton>
          ) : null}
          <VButton
            type="button"
            className={styles.noButton}
            onClick={onReject}
            isDisabled={pending || rejectDisabled}
            title={lang === "zh" ? "拒绝本次（N）" : "Decline (N)"}
          >
            <span>{buttons.no}</span>
          </VButton>
        </div>
      </section>
    </div>
  );
}
