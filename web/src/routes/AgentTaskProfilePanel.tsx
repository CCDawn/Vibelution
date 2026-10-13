import { AgentTaskProfile } from "../api/types";
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
import styles from "./AgentTaskProfilePanel.styles";

export type AgentTaskDraft = Omit<AgentTaskProfile, "taskTypes"> & {
  taskTypes: string;
};

export type AgentTaskProfilePanelCopy = {
  taskTitle: string;
  taskHint: string;
  mission: string;
  taskTypes: string;
  taskTypesPlaceholder: string;
  responsibilities: string;
  preferredTasks: string;
  avoidTasks: string;
  successCriteria: string;
  deliverables: string;
  constraints: string;
  handoffNotes: string;
  resetConfig: string;
  saveTask: string;
  savingTask: string;
};

type AgentTaskProfilePanelProps = {
  copy: AgentTaskProfilePanelCopy;
  lang: "zh" | "en";
  summary: string;
  draft: AgentTaskDraft;
  dirty: boolean;
  canSave: boolean;
  pending: boolean;
  onDraftChange: (patch: Partial<AgentTaskDraft>) => void;
  onReset: () => void;
  onSave: () => void;
};

export function AgentTaskProfilePanel({
  copy,
  lang,
  draft,
  dirty,
  canSave,
  pending,
  onDraftChange,
  onReset,
  onSave,
}: AgentTaskProfilePanelProps) {
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
          aria-label={lang === "zh" ? `重置${copy.taskTitle}` : `Reset ${copy.taskTitle.toLowerCase()}`}
          isDisabled={!dirty || pending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          className={agentConfigPrimaryButtonClass}
          variant="primary"
          aria-label={pending ? copy.savingTask : copy.saveTask}
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
      ariaLabel={copy.taskTitle}
      title=""
      headerClassName="hidden"
      bodyClassName={agentConfigEditorClass}
      footerClassName={agentConfigFooterClass}
      footer={footer}
    >
      <div className={agentConfigContentClass}>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "职责与范围" : "Scope and responsibilities"}</h3>
          <VFieldRow label={copy.mission} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.mission}
              onChange={(event) => onDraftChange({ mission: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.taskTypes} className={agentConfigRowClass}>
            <VNativeInput
              className={agentConfigControlClass}
              value={draft.taskTypes}
              placeholder={copy.taskTypesPlaceholder}
              onChange={(event) => onDraftChange({ taskTypes: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.responsibilities} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.responsibilities}
              onChange={(event) => onDraftChange({ responsibilities: event.target.value })}
            />
          </VFieldRow>
        </section>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "交付要求" : "Deliverable requirements"}</h3>
          <VFieldRow label={copy.deliverables} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.deliverables}
              onChange={(event) => onDraftChange({ deliverables: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.successCriteria} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.successCriteria}
              onChange={(event) => onDraftChange({ successCriteria: event.target.value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.constraints} className={agentConfigRowClass}>
            <VNativeTextarea
              className={`${agentConfigControlClass} ${styles.textarea}`}
              value={draft.constraints}
              onChange={(event) => onDraftChange({ constraints: event.target.value })}
            />
          </VFieldRow>
        </section>
        <section>
          <details className={styles.advancedDetails}>
            <summary>{lang === "zh" ? "偏好与交接" : "Preferences and handoff"}</summary>
            <div className={styles.advancedBody}>
              <VFieldRow label={copy.preferredTasks} className={agentConfigRowClass}>
                <VNativeTextarea
                  className={`${agentConfigControlClass} ${styles.textarea}`}
                  value={draft.preferredTasks}
                  onChange={(event) => onDraftChange({ preferredTasks: event.target.value })}
                />
              </VFieldRow>
              <VFieldRow label={copy.avoidTasks} className={agentConfigRowClass}>
                <VNativeTextarea
                  className={`${agentConfigControlClass} ${styles.textarea}`}
                  value={draft.avoidTasks}
                  onChange={(event) => onDraftChange({ avoidTasks: event.target.value })}
                />
              </VFieldRow>
              <VFieldRow label={copy.handoffNotes} className={agentConfigRowClass}>
                <VNativeTextarea
                  className={`${agentConfigControlClass} ${styles.textarea}`}
                  value={draft.handoffNotes}
                  onChange={(event) => onDraftChange({ handoffNotes: event.target.value })}
                />
              </VFieldRow>
            </div>
          </details>
        </section>
      </div>
    </VSettingsFormPage>
  );
}
