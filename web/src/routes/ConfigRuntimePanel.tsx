import { SlidersHorizontal } from "lucide-react";

import { VButton, VSection } from "../components/vui";
import type { ConfigCopy } from "./ConfigRoute";
import styles from "./ConfigRuntimePanel.styles";

type ConfigRuntimePanelProps = {
  copy: ConfigCopy;
  eyebrow: string;
  currentIntakeMode: string;
  structuredActionsDisabled: boolean;
  intakeLabel: (mode: string) => string;
  onIntakeModeChange: (mode: "manual_review" | "auto") => void;
};

export function ConfigRuntimePanel({
  copy,
  eyebrow,
  currentIntakeMode,
  structuredActionsDisabled,
  intakeLabel,
  onIntakeModeChange,
}: ConfigRuntimePanelProps) {
  return (
    <VSection
      id="config-shell"
      className={styles.sectionSurface}
      headerClassName={styles.sectionHeader}
      eyebrow={eyebrow}
      title={copy.runtimeTitle}
      actions={<SlidersHorizontal size={16} className={styles.sectionIcon} />}
    >
      <div className={styles.behaviorRow}>
        <div className={styles.behaviorCopy}>
          <strong>{copy.intakeMode}</strong>
          <span>{copy.runtimeBody}</span>
        </div>
        <div className={styles.segmented} role="group" aria-label={copy.intakeMode}>
            {(["manual_review", "auto"] as const).map((mode) => (
              <VButton
                key={mode}
                type="button"
                aria-pressed={currentIntakeMode === mode}
                className={
                  currentIntakeMode === mode
                    ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                    : styles.segmentButton
                }
                isDisabled={structuredActionsDisabled}
                onClick={() => onIntakeModeChange(mode)}
              >
                {intakeLabel(mode)}
              </VButton>
            ))}
        </div>
      </div>
    </VSection>
  );
}
