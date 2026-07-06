import { useId } from "react";
import { ShieldAlert, ShieldCheck, X } from "lucide-react";

import { VButton } from "../../components/vui";
import styles from "./ChatToolApprovalDialog.styles";

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
  onApprove: () => void;
  onReject: () => void;
};

export function ChatToolApprovalDialog({
  lang,
  pending,
  rawTitle,
  riskLabel,
  scopeLabel,
  toolLabels,
  onApprove,
  onReject,
}: ChatToolApprovalDialogProps) {
  const dialogId = useId();
  const titleId = `${dialogId}-title`;
  const descriptionId = `${dialogId}-description`;
  const scopeId = `${dialogId}-scope`;
  const riskId = `${dialogId}-risk`;
  const toolListId = `${dialogId}-tools`;
  const descriptionIds = `${descriptionId} ${riskId} ${scopeId} ${toolListId}`;
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
            <strong id={titleId}>{lang === "zh" ? "工具权限审批" : "Tool permission approval"}</strong>
            <span id={riskId}>{riskLabel}</span>
          </div>
          <p id={descriptionId}>
            {lang === "zh"
              ? `当前助手请求启用${toolLabels.length > 1 ? "这些能力" : "此能力"}，批准后仅在${scopeLabel}生效。`
              : `The current agent requests tool access. Approval applies to ${scopeLabel}.`}
          </p>
          <span id={scopeId} className={styles.visuallyHidden}>{scopeLabel}</span>
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
            onClick={onReject}
            isDisabled={pending}
          >
            <X size={15} aria-hidden="true" />
            <span>{lang === "zh" ? "拒绝" : "Reject"}</span>
          </VButton>
          <VButton
            type="button"
            className={styles.allowButton}
            onClick={onApprove}
            isDisabled={pending}
          >
            <ShieldCheck size={15} aria-hidden="true" />
            <span>{pending ? (lang === "zh" ? "处理中" : "Resolving") : (lang === "zh" ? "允许" : "Allow")}</span>
          </VButton>
        </div>
      </section>
    </div>
  );
}
