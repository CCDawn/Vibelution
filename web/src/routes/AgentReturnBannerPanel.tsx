import { ArrowLeft } from "lucide-react";

import { VContextualHint, VNativeButton } from "../components/vui";
import styles from "./AgentReturnBannerPanel.styles";

export type AgentReturnBannerPanelCopy = {
  returnBannerTitle: string;
  returnBannerHint: string;
};

type AgentReturnBannerPanelProps = {
  copy: AgentReturnBannerPanelCopy;
  returnToLabel: string;
  onReturn: () => void;
};

export function AgentReturnBannerPanel({ copy, returnToLabel, onReturn }: AgentReturnBannerPanelProps) {
  return (
    <section className={styles.returnBanner} aria-label={copy.returnBannerTitle}>
      <div className={styles.returnBannerCopy}>
        <strong className={styles.contextualHintRow}>
          {copy.returnBannerTitle}
          <VContextualHint content={copy.returnBannerHint} label={`${copy.returnBannerTitle}说明`} />
        </strong>
      </div>
      <VNativeButton
        type="button"
        className={styles.returnBannerButton}
        onClick={onReturn}
      >
        <ArrowLeft size={16} />
        <span>{returnToLabel}</span>
      </VNativeButton>
    </section>
  );
}
