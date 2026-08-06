import { SlidersHorizontal } from "lucide-react";

import { VSection, VTabs } from "../components/vui";
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
        <VTabs
          density="compact"
          className={styles.intakeTabs}
          listClassName={styles.intakeTabsList}
          triggerClassName={styles.intakeTabsTrigger}
          aria-label={copy.intakeMode}
          value={currentIntakeMode === "auto" ? "auto" : "manual_review"}
          onValueChange={(value) => {
            if (structuredActionsDisabled) {
              return;
            }
            if (value === "manual_review" || value === "auto") {
              onIntakeModeChange(value);
            }
          }}
          items={[
            {
              id: "manual_review",
              label: intakeLabel("manual_review"),
              disabled: structuredActionsDisabled,
            },
            {
              id: "auto",
              label: intakeLabel("auto"),
              disabled: structuredActionsDisabled,
            },
          ]}
        />
      </div>
    </VSection>
  );
}
