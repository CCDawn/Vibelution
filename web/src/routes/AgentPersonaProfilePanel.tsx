import { AgentPersonaProfile } from "../api/types";
import { VButton, VFieldRow, VNativeInput, VNativeTextarea, VSettingsFormPage } from "../components/vui";
import {
  agentConfigFormPageClass,
  agentConfigActionsClass,
  agentConfigContentClass,
  agentConfigControlClass,
  agentConfigEditorClass,
  agentConfigFooterClass,
  agentConfigPrimaryButtonClass,
  agentConfigQuietButtonClass,
  agentConfigRowClass,
} from "./agentConfigForm.styles";
import styles from "./AgentPersonaProfilePanel.styles";

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
  draft,
  dirty,
  canSave,
  pending,
  onDraftChange,
  onReset,
  onSave,
}: AgentPersonaProfilePanelProps) {
  const footer = (
    <div className={agentConfigActionsClass}>
      <span className={dirty ? styles.pendingStatus : styles.savedStatus} aria-live="polite">
        {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已保存" : "Saved")}
      </span>
      <div>
        <VButton
          type="button"
          className={agentConfigQuietButtonClass}
          variant="secondary"
          aria-label={lang === "zh" ? `重置${copy.personaTitle}` : `Reset ${copy.personaTitle.toLowerCase()}`}
          isDisabled={!dirty || pending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          className={agentConfigPrimaryButtonClass}
          variant="primary"
          aria-label={pending ? copy.savingPersona : copy.savePersona}
          isDisabled={!canSave || pending}
          onPress={onSave}
        >
          {pending ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存" : "Save")}
        </VButton>
      </div>
    </div>
  );

  return (
    <VSettingsFormPage
      className={agentConfigFormPageClass}
      ariaLabel={copy.personaTitle}
      title=""
      headerClassName="hidden"
      bodyClassName={agentConfigEditorClass}
      footerClassName={agentConfigFooterClass}
      footer={footer}
    >
      <div className={agentConfigContentClass}>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "专业与沟通" : "Expertise and communication"}</h3>
          <VFieldRow label={copy.expertise} className={agentConfigRowClass}>
            <VNativeInput
              className={agentConfigControlClass}
              value={draft.expertise}
              placeholder={copy.expertisePlaceholder}
              onChange={(event) => onDraftChange({ expertise: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.personality} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.personality}
              onChange={(event) => onDraftChange({ personality: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.communicationStyle} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.communicationStyle}
              onChange={(event) => onDraftChange({ communicationStyle: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.collaborationPreference} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.collaborationPreference}
              onChange={(event) => onDraftChange({ collaborationPreference: event.target.value })}
            />
          </VFieldRow>
        </section>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "背景" : "Background"}</h3>
          <VFieldRow label={copy.background} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.background}
              onChange={(event) => onDraftChange({ background: event.target.value })}
            />
          </VFieldRow>
        </section>
        <section>
          <details className={styles.advancedDetails}>
            <summary>{lang === "zh" ? "其他身份信息" : "Additional identity"}</summary>
            <div className={styles.advancedBody}>
              <VFieldRow label={copy.gender} className={agentConfigRowClass}>
                <VNativeInput
                  className={agentConfigControlClass}
                  value={draft.gender}
                  onChange={(event) => onDraftChange({ gender: event.target.value })}
                />
              </VFieldRow>
              <VFieldRow label={copy.age} className={agentConfigRowClass}>
                <VNativeInput
                  className={agentConfigControlClass}
                  value={draft.age}
                  onChange={(event) => onDraftChange({ age: event.target.value })}
                />
              </VFieldRow>
              <VFieldRow label={copy.pronouns} className={agentConfigRowClass}>
                <VNativeInput
                  className={agentConfigControlClass}
                  value={draft.pronouns}
                  onChange={(event) => onDraftChange({ pronouns: event.target.value })}
                />
              </VFieldRow>
              <VFieldRow label={copy.identityNotes} className={agentConfigRowClass}>
                <VNativeTextarea
                  className={`${agentConfigControlClass} ${styles.textarea}`}
                  value={draft.identityNotes}
                  onChange={(event) => onDraftChange({ identityNotes: event.target.value })}
                />
              </VFieldRow>
            </div>
          </details>
        </section>
      </div>
    </VSettingsFormPage>
  );
}
