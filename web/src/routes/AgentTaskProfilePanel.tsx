import { AgentTaskProfile } from "../api/types";
import { VButton, VContextualHint, VNativeInput, VNativeTextarea } from "../components/vui";
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
  summary,
  draft,
  dirty,
  canSave,
  pending,
  onDraftChange,
  onReset,
  onSave,
}: AgentTaskProfilePanelProps) {
  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.taskTitle}</p>
          <h3 className={styles.contextualHintRow}>
            {summary}
            <VContextualHint content={copy.taskHint} label={`${copy.taskTitle}说明`} />
          </h3>
        </div>
        <span className={dirty ? styles.dirtyPill : styles.cleanPill}>
          {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
        </span>
      </div>
      <div className={styles.editorGrid}>
        <label className={styles.fieldWide}>
          <span>{copy.mission}</span>
          <VNativeTextarea value={draft.mission} onChange={(event) => onDraftChange({ mission: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.taskTypes}</span>
          <VNativeInput
            value={draft.taskTypes}
            placeholder={copy.taskTypesPlaceholder}
            onChange={(event) => onDraftChange({ taskTypes: event.target.value })}
          />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.responsibilities}</span>
          <VNativeTextarea value={draft.responsibilities} onChange={(event) => onDraftChange({ responsibilities: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.preferredTasks}</span>
          <VNativeTextarea value={draft.preferredTasks} onChange={(event) => onDraftChange({ preferredTasks: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.avoidTasks}</span>
          <VNativeTextarea value={draft.avoidTasks} onChange={(event) => onDraftChange({ avoidTasks: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.successCriteria}</span>
          <VNativeTextarea value={draft.successCriteria} onChange={(event) => onDraftChange({ successCriteria: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.deliverables}</span>
          <VNativeTextarea value={draft.deliverables} onChange={(event) => onDraftChange({ deliverables: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.constraints}</span>
          <VNativeTextarea value={draft.constraints} onChange={(event) => onDraftChange({ constraints: event.target.value })} />
        </label>
        <label className={styles.fieldWide}>
          <span>{copy.handoffNotes}</span>
          <VNativeTextarea value={draft.handoffNotes} onChange={(event) => onDraftChange({ handoffNotes: event.target.value })} />
        </label>
      </div>
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          isDisabled={!dirty || pending}
          tooltip={lang === "zh" ? "放弃本次未保存的任务档案修改。" : "Discard unsaved task profile changes."}
          disabledReason={!dirty ? (lang === "zh" ? "当前没有未保存修改。" : "There are no unsaved changes.") : (lang === "zh" ? "正在保存，请稍候。" : "Saving is in progress.")}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          isDisabled={!canSave || pending}
          tooltip={lang === "zh" ? "保存当前任务档案。" : "Save the current task profile."}
          disabledReason={!canSave ? (lang === "zh" ? "请先完成任务档案的必填内容。" : "Complete the required task profile fields first.") : (lang === "zh" ? "正在保存，请稍候。" : "Saving is in progress.")}
          onPress={onSave}
        >
          {pending ? copy.savingTask : copy.saveTask}
        </VButton>
      </div>
    </section>
  );
}
