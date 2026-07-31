import { useId } from "react";
import { ShieldAlert } from "lucide-react";

import { VButton } from "../../components/vui";
import styles from "./ChatToolApprovalDialog.styles";
import {
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
  actionPreview?: string;
  sessionGrantScope?: Record<string, unknown>;
  toolName?: string;
  onApprove: () => void;
  onApproveForSession?: () => void;
  onReject: () => void;
};

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
  const displayName = toolApprovalDisplayName(toolName || toolLabels[0]?.id, lang);
  const visibleLabels = toolLabels.slice(0, 4);
  const extraCount = Math.max(0, toolLabels.length - visibleLabels.length);

  return (
    <div className={styles.overlay} role="presentation">
      <section
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
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
          </div>
          <p id={descriptionId}>
            {lang === "zh"
              ? `助手请求执行「${displayName}」。请选择本次允许、会话内始终允许或拒绝。`
              : `The agent wants to run “${displayName}”. Allow once, always for this session, or decline.`}
          </p>
          <span id={scopeId} className={styles.visuallyHidden}>{scopeLabel}</span>
          <pre id={previewId} className={styles.commandPreview}>{actionPreview || rawTitle}</pre>
          <p id={grantId} className={styles.grantDescription}>
            {toolApprovalSessionGrantDescription(sessionGrantScope, lang)}
          </p>
          <div id={toolListId} className={styles.toolList} title={rawTitle} role="list">
            {visibleLabels.length
              ? visibleLabels.map((item) => (
                <span key={item.id} className={styles.toolItem} role="listitem">{item.label}</span>
              ))
              : <span className={styles.toolItem} role="listitem">{lang === "zh" ? "工具策略变更" : "Tool policy change"}</span>}
            {extraCount ? (
              <span className={styles.toolItem} role="listitem">{lang === "zh" ? `另 ${extraCount} 项` : `+${extraCount}`}</span>
            ) : null}
          </div>
        </div>
        <div className={styles.actions}>
          <VButton
            type="button"
            className={styles.allowButton}
            onClick={onApprove}
            isDisabled={pending}
          >
            <span>{pending ? buttons.resolving : buttons.yes}</span>
          </VButton>
          {onApproveForSession ? (
            <VButton
              type="button"
              className={styles.allowButton}
              onClick={onApproveForSession}
              isDisabled={pending}
            >
              <span>{buttons.always}</span>
            </VButton>
          ) : null}
          <VButton
            type="button"
            onClick={onReject}
            isDisabled={pending}
          >
            <span>{buttons.no}</span>
          </VButton>
        </div>
      </section>
    </div>
  );
}
