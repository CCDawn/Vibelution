import { AgentPersonaProfile } from "../api/types";
import { VButton, VFieldRow, VNativeInput, VNativeTextarea } from "../components/vui";
import styles from "./AgentsRoute.styles";

export type AgentPersonaDraft = Omit<AgentPersonaProfile, "expertise"> & {
  expertise: string;
};

export type AgentPersonaProfilePanelCopy = {
  personaTitle: string;
  gender: string;
  age: string;
  pronouns: string;
  expertise: string;
  expertisePlaceholder: string;
  personality: string;
  communicationStyle: string;
  background: string;
  collaborationPreference: string;
  identityNotes: string;
  resetConfig: string;
  savePersona: string;
  savingPersona: string;
};

type AgentPersonaProfilePanelProps = {
  copy: AgentPersonaProfilePanelCopy;
  lang: "zh" | "en";
  summary: string;
  draft: AgentPersonaDraft;
  dirty: boolean;
  canSave: boolean;
  pending: boolean;
  onDraftChange: (patch: Partial<AgentPersonaDraft>) => void;
  onReset: () => void;
  onSave: () => void;
};

export function AgentPersonaProfilePanel({
  copy,
  lang,
  summary,
  draft,
  dirty,
  canSave,
  pending,
  onDraftChange,
  onReset,
  onSave,
}: AgentPersonaProfilePanelProps) {
  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.personaTitle}</p>
          <h3>{summary}</h3>
        </div>
        <span className={dirty ? styles.dirtyPill : styles.cleanPill}>
          {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
        </span>
      </div>
      <div className={styles.editorGrid}>
        <VFieldRow label={copy.gender}>
          <VNativeInput value={draft.gender} onChange={(event) => onDraftChange({ gender: event.target.value })} />
        </VFieldRow>
        <VFieldRow label={copy.age}>
          <VNativeInput value={draft.age} onChange={(event) => onDraftChange({ age: event.target.value })} />
        </VFieldRow>
        <VFieldRow label={copy.pronouns}>
          <VNativeInput value={draft.pronouns} onChange={(event) => onDraftChange({ pronouns: event.target.value })} />
        </VFieldRow>
        <VFieldRow label={copy.expertise}>
          <VNativeInput
            value={draft.expertise}
            placeholder={copy.expertisePlaceholder}
            onChange={(event) => onDraftChange({ expertise: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.personality} className="col-span-full">
          <VNativeTextarea value={draft.personality} onChange={(event) => onDraftChange({ personality: event.target.value })} />
        </VFieldRow>
        <VFieldRow label={copy.communicationStyle} className="col-span-full">
          <VNativeTextarea
            value={draft.communicationStyle}
            onChange={(event) => onDraftChange({ communicationStyle: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.background} className="col-span-full">
          <VNativeTextarea value={draft.background} onChange={(event) => onDraftChange({ background: event.target.value })} />
        </VFieldRow>
        <VFieldRow label={copy.collaborationPreference} className="col-span-full">
          <VNativeTextarea
            value={draft.collaborationPreference}
            onChange={(event) => onDraftChange({ collaborationPreference: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.identityNotes} className="col-span-full">
          <VNativeTextarea value={draft.identityNotes} onChange={(event) => onDraftChange({ identityNotes: event.target.value })} />
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
          {pending ? copy.savingPersona : copy.savePersona}
        </VButton>
      </div>
    </section>
  );
}
