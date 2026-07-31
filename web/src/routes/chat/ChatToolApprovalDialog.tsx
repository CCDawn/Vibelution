import { useEffect, useId } from "react";
import { ShieldAlert } from "lucide-react";

import { VButton } from "../../components/vui";
import styles from "./ChatToolApprovalDialog.styles";
import {
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
  rawTitle: string;
  riskLabel: string;
  scopeLabel: string;
  toolLabels: ChatToolApprovalLabel[];
  /** Codex-style action body (command/path preview). */
  actionPreview?: string;
  sessionGrantScope?: Record<string, unknown>;
  toolName?: string;
  /** banner: sticky host; inline: under tool activity in transcript. */
  variant?: "banner" | "inline";
  onApprove: () => void;
  onApproveForSession?: () => void;
  onReject: () => void;
};

/**
 * Codex-aligned approval surface:
 * - Title: Allow this action? / 允许执行？
 * - Body: concrete command or tool preview
 * - Actions: Yes · Always (session) · No
 * - Hotkeys: y / a / n (when not pending)
 */
export function ChatToolApprovalDialog({
  lang,
  pending,
  rawTitle,
  riskLabel,
  scopeLabel,
  toolLabels,
  actionPreview,
  sessionGrantScope,
  toolName,
  variant = "banner",
  onApprove,
  onApproveForSession,
  onReject,
}: ChatToolApprovalDialogProps) {
  const dialogId = useId();
  const titleId = `${dialogId}-title`;
  const descriptionId = `${dialogId}-description`;
  const scopeId = `${dialogId}-scope`;
  const riskId = `${dialogId}-risk`;
  const toolListId = `${dialogId}-tools`;
  const previewId = `${dialogId}-preview`;
  const grantId = `${dialogId}-grant`;
  const descriptionIds = `${descriptionId} ${riskId} ${scopeId} ${toolListId} ${previewId} ${grantId}`;
  const buttons = toolApprovalCodexButtonLabels(lang);
  const primaryToolName = toolName || toolLabels[0]?.id || "";
  const displayName = toolApprovalDisplayName(primaryToolName, lang);
  const preview = String(actionPreview || toolApprovalActionPreview(undefined, primaryToolName) || rawTitle || "").trim();
  const visibleLabels = toolLabels.slice(0, 4);
  const extraCount = Math.max(0, toolLabels.length - visibleLabels.length);

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
        onApprove();
        return;
      }
      if (key === "a" && onApproveForSession) {
        event.preventDefault();
        onApproveForSession();
        return;
      }
      if (key === "n" || key === "escape") {
        event.preventDefault();
        onReject();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onApprove, onApproveForSession, onReject, pending]);

  return (
    <div
      className={variant === "inline" ? styles.overlayInline : styles.overlay}
      role="presentation"
      data-chat-tool-approval-variant={variant}
    >
      <section
        className={variant === "inline" ? styles.dialogInline : styles.dialog}
        role="dialog"
        aria-modal={variant === "banner" ? "true" : undefined}
        aria-labelledby={titleId}
        aria-describedby={descriptionIds}
        aria-busy={pending}
      >
        <div className={styles.icon} aria-hidden="true">
          <ShieldAlert size={18} />
        </div>
        <div className={styles.body}>
          <div className={styles.header}>
            <strong id={titleId}>{toolApprovalCodexTitle(lang)}</strong>
            <span id={riskId}>{riskLabel}</span>
            <span className={styles.scopeBadge} id={scopeId}>{scopeLabel}</span>
          </div>
          <p id={descriptionId} className={styles.lead}>
            {lang === "zh"
              ? `助手请求执行「${displayName}」。选择「是」仅本次；「始终」按下方范围授权；「否」拒绝并继续会话。`
              : `The agent wants to run “${displayName}”. Yes = once; Always uses the exact scope below; No = decline and continue.`}
          </p>
          <pre id={previewId} className={styles.commandPreview} title={preview}>
            {preview || (lang === "zh" ? "（无命令预览）" : "(no command preview)")}
          </pre>
          <p id={grantId} className={styles.grantDescription}>
            {toolApprovalSessionGrantDescription(sessionGrantScope, lang)}
          </p>
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
          <p className={styles.hotkeys} aria-hidden="true">
            {lang === "zh" ? "快捷键：Y 是 · A 始终 · N 否" : "Hotkeys: Y Yes · A Always · N No"}
          </p>
        </div>
        <div className={styles.actions}>
          <VButton
            type="button"
            className={styles.yesButton}
            onClick={onApprove}
            isDisabled={pending}
            title={lang === "zh" ? "仅批准本次（Y）" : "Allow this once (Y)"}
          >
            <span>{pending ? buttons.resolving : buttons.yes}</span>
          </VButton>
          {onApproveForSession ? (
            <VButton
              type="button"
              className={styles.alwaysButton}
              onClick={onApproveForSession}
              isDisabled={pending}
              title={lang === "zh" ? "本会话始终允许同类调用（A）" : "Always allow for this session (A)"}
            >
              <span>{buttons.always}</span>
            </VButton>
          ) : null}
          <VButton
            type="button"
            className={styles.noButton}
            onClick={onReject}
            isDisabled={pending}
            title={lang === "zh" ? "拒绝本次（N）" : "Decline (N)"}
          >
            <span>{buttons.no}</span>
          </VButton>
        </div>
      </section>
    </div>
  );
}
