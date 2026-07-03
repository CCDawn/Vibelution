import { ArrowLeft } from "lucide-react";

import { VNativeButton } from "../components/vui";
import styles from "./AgentsRoute.styles";

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
    <section className={styles.returnBanner} aria-label={copy.returnBannerTitle} title={copy.returnBannerHint}>
      <div className={styles.returnBannerCopy}>
        <strong>{copy.returnBannerTitle}</strong>
      </div>
      <VNativeButton
        type="button"
        className={styles.returnBannerButton}
        onClick={onReturn}
        title={returnToLabel}
      >
        <ArrowLeft size={16} />
        <span>{returnToLabel}</span>
      </VNativeButton>
    </section>
  );
}
