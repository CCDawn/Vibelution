import { VButton, VCheckbox, VFieldRow, VNativeSelect } from "../components/vui";
import styles from "./AgentModeMembershipPanel.styles";

export type AgentModeMembershipDraft = {
  chatDefault: boolean;
  chatAvailable: boolean;
  researchPool: boolean;
  supervisedSlot: string;
  selfEvolutionSlot: string;
};

export type AgentModeMembershipPanelCopy = {
  membershipTitle: string;
  chatDefault: string;
  chatAvailable: string;
  researchPool: string;
  supervisedSlot: string;
  selfEvolutionSlot: string;
  noSlot: string;
  resetConfig: string;
  saveMembership: string;
  savingMembership: string;
};

type AgentModeMembershipPanelProps = {
  copy: AgentModeMembershipPanelCopy;
  lang: "zh" | "en";
  modesLabel: string;
  draft: AgentModeMembershipDraft;
  supervisedSlots: string[];
  selfEvolutionSlots: string[];
  dirty: boolean;
  canSave: boolean;
  pending: boolean;
  onDraftChange: (patch: Partial<AgentModeMembershipDraft>) => void;
  onReset: () => void;
  onSave: () => void;
};

export function AgentModeMembershipPanel({
  copy,
  lang,
  modesLabel,
  draft,
  supervisedSlots,
  selfEvolutionSlots,
  dirty,
  canSave,
  pending,
  onDraftChange,
  onReset,
  onSave,
}: AgentModeMembershipPanelProps) {
  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.membershipTitle}</p>
          <h3>{modesLabel || "-"}</h3>
        </div>
        <span className={dirty ? styles.dirtyPill : styles.cleanPill}>
          {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
        </span>
      </div>
      <div className={styles.toggleGrid}>
        <VCheckbox
          isSelected={draft.chatDefault}
          onChange={(value) => onDraftChange({ chatDefault: value, chatAvailable: value ? true : draft.chatAvailable })}
        >
          {copy.chatDefault}
        </VCheckbox>
        <VCheckbox
          isSelected={draft.chatAvailable}
          onChange={(value) => onDraftChange({ chatAvailable: value, chatDefault: value ? draft.chatDefault : false })}
        >
          {copy.chatAvailable}
        </VCheckbox>
        <VCheckbox
          isSelected={draft.researchPool}
          onChange={(value) => onDraftChange({ researchPool: value })}
        >
          {copy.researchPool}
        </VCheckbox>
      </div>
      <div className={styles.editorGrid}>
        <VFieldRow label={copy.supervisedSlot}>
          <VNativeSelect value={draft.supervisedSlot} onChange={(event) => onDraftChange({ supervisedSlot: event.target.value })}>
            <option value="">{copy.noSlot}</option>
            {supervisedSlots.map((slot) => (
              <option key={slot} value={slot}>{slot}</option>
            ))}
          </VNativeSelect>
        </VFieldRow>
        <VFieldRow label={copy.selfEvolutionSlot}>
          <VNativeSelect value={draft.selfEvolutionSlot} onChange={(event) => onDraftChange({ selfEvolutionSlot: event.target.value })}>
            <option value="">{copy.noSlot}</option>
            {selfEvolutionSlots.map((slot) => (
              <option key={slot} value={slot}>{slot}</option>
            ))}
          </VNativeSelect>
        </VFieldRow>
      </div>
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          isDisabled={!dirty || pending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          isDisabled={!canSave || pending}
          onPress={onSave}
        >
          {pending ? copy.savingMembership : copy.saveMembership}
        </VButton>
      </div>
    </section>
  );
}
