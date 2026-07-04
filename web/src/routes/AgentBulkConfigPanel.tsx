import { CheckSquare } from "lucide-react";

import { VButton, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./AgentBulkConfigPanel.styles";

export type AgentBulkConfigField = "dialogueModelId" | "promptTemplateId" | "primaryMode" | "roleKey";
export type AgentBulkConfigDraft = Record<AgentBulkConfigField, string>;
export type AgentBulkConfigApply = Record<AgentBulkConfigField, boolean>;

export type AgentBulkConfigPanelCopy = {
  bulkEditTitle: string;
  bulkEditSelected: string;
  bulkApplyField: string;
  bulkDialogueModel: string;
  prompt: string;
  bulkPrimaryMode: string;
  bulkRoleKey: string;
  bulkEditMixed: string;
  bulkConfigReset: string;
  bulkWorking: string;
  bulkApplyConfig: string;
};

type AgentBulkConfigPanelOption = {
  value: string;
  label: string;
};

type AgentBulkConfigPanelAgent = {
  agentId: string;
  label: string;
};

type AgentBulkConfigPanelNotice = {
  tone: "error" | "success";
  text: string;
};

type AgentBulkConfigPanelProps = {
  copy: AgentBulkConfigPanelCopy;
  selectedAgents: AgentBulkConfigPanelAgent[];
  draft: AgentBulkConfigDraft;
  apply: AgentBulkConfigApply;
  mixed: AgentBulkConfigApply;
  pending: boolean;
  canSave: boolean;
  notice: AgentBulkConfigPanelNotice | null;
  modelOptions: AgentBulkConfigPanelOption[];
  promptTemplateOptions: AgentBulkConfigPanelOption[];
  primaryModeOptions: AgentBulkConfigPanelOption[];
  onToggleApply: (field: AgentBulkConfigField, checked: boolean) => void;
  onDraftChange: (patch: Partial<AgentBulkConfigDraft>) => void;
  onReset: () => void;
  onSave: () => void;
};

export function AgentBulkConfigPanel({
  copy,
  selectedAgents,
  draft,
  apply,
  mixed,
  pending,
  canSave,
  notice,
  modelOptions,
  promptTemplateOptions,
  primaryModeOptions,
  onToggleApply,
  onDraftChange,
  onReset,
  onSave,
}: AgentBulkConfigPanelProps) {
  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.bulkEditTitle}</p>
          <h3>{copy.bulkEditSelected}: {selectedAgents.length}</h3>
        </div>
        <CheckSquare size={17} />
      </div>
      <div className={styles.bulkSelectionList}>
        {selectedAgents.slice(0, 8).map((agent) => (
          <span key={`bulk-selected:${agent.agentId}`}>{agent.label}</span>
        ))}
        {selectedAgents.length > 8 ? <span>+{selectedAgents.length - 8}</span> : null}
      </div>
      <div className={styles.editorGrid}>
        <label className={styles.field}>
          <span className={styles.bulkFieldHeader}>
            <VNativeInput
              type="checkbox"
              checked={apply.dialogueModelId}
              onChange={(event) => onToggleApply("dialogueModelId", event.target.checked)}
            />
            {copy.bulkApplyField}
          </span>
          <span>{copy.bulkDialogueModel}</span>
          <VNativeSelect
            value={draft.dialogueModelId}
            disabled={!apply.dialogueModelId || pending}
            onChange={(event) => onDraftChange({ dialogueModelId: event.target.value })}
          >
            <option value="">{mixed.dialogueModelId ? copy.bulkEditMixed : "-"}</option>
            {modelOptions.map((model) => (
              <option key={`bulk-dialogue:${model.value}`} value={model.value}>
                {model.label}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <label className={styles.field}>
          <span className={styles.bulkFieldHeader}>
            <VNativeInput
              type="checkbox"
              checked={apply.promptTemplateId}
              onChange={(event) => onToggleApply("promptTemplateId", event.target.checked)}
            />
            {copy.bulkApplyField}
          </span>
          <span>{copy.prompt}</span>
          <VNativeSelect
            value={draft.promptTemplateId}
            disabled={!apply.promptTemplateId || pending}
            onChange={(event) => onDraftChange({ promptTemplateId: event.target.value })}
          >
            <option value="">{mixed.promptTemplateId ? copy.bulkEditMixed : "-"}</option>
            {promptTemplateOptions.map((template) => (
              <option key={`bulk-prompt:${template.value}`} value={template.value}>
                {template.label}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <label className={styles.field}>
          <span className={styles.bulkFieldHeader}>
            <VNativeInput
              type="checkbox"
              checked={apply.primaryMode}
              onChange={(event) => onToggleApply("primaryMode", event.target.checked)}
            />
            {copy.bulkApplyField}
          </span>
          <span>{copy.bulkPrimaryMode}</span>
          <VNativeSelect
            value={draft.primaryMode}
            disabled={!apply.primaryMode || pending}
            onChange={(event) => onDraftChange({ primaryMode: event.target.value })}
          >
            <option value="">{mixed.primaryMode ? copy.bulkEditMixed : "-"}</option>
            {primaryModeOptions.map((mode) => (
              <option key={`bulk-mode:${mode.value}`} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <label className={styles.field}>
          <span className={styles.bulkFieldHeader}>
            <VNativeInput
              type="checkbox"
              checked={apply.roleKey}
              onChange={(event) => onToggleApply("roleKey", event.target.checked)}
            />
            {copy.bulkApplyField}
          </span>
          <span>{copy.bulkRoleKey}</span>
          <VNativeInput
            value={draft.roleKey}
            placeholder={mixed.roleKey ? copy.bulkEditMixed : "-"}
            disabled={!apply.roleKey || pending}
            onChange={(event) => onDraftChange({ roleKey: event.target.value })}
          />
        </label>
      </div>
      {notice ? <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p> : null}
      <div className={styles.editorActions}>
        <VButton type="button" variant="secondary" isDisabled={pending} onPress={onReset}>
          {copy.bulkConfigReset}
        </VButton>
        <VButton type="button" variant="primary" isDisabled={!canSave} onPress={onSave}>
          {pending ? copy.bulkWorking : copy.bulkApplyConfig}
        </VButton>
      </div>
    </section>
  );
}
