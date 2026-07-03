import { Bot, Plus } from "lucide-react";

import { type AgentLlmBindings, type ToolBundle } from "../api/types";
import { VButton, VFieldRow, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import styles from "./AgentsRoute.styles";

export type AgentCreateDraft = {
  displayName: string;
  llmBindings: AgentLlmBindings;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
  personaSummary: string;
  taskMission: string;
  selectedToolBundleIds: string[];
  allowedTools: string;
};

export type AgentCreatePanelModelChoice = {
  key: string;
  modelId: string;
  label: string;
  modelLabel: string;
};

export type AgentCreateSelectOption = {
  value: string;
  label: string;
};

export type AgentCreatePanelCopy = {
  createAgent: string;
  createAgentTitle: string;
  createAgentHint: string;
  createAgentName: string;
  createAgentNamePlaceholder: string;
  createAgentRole: string;
  createAgentRolePlaceholder: string;
  createAgentPersonaSummary: string;
  createAgentPersonaPlaceholder: string;
  createAgentTaskMission: string;
  createAgentTaskMissionPlaceholder: string;
  createAgentAllowedToolsPlaceholder: string;
  createAgentToolBundles: string;
  createAgentToolBundlesHint: string;
  createAgentToolBundlePreview: string;
  createAgentToolBundleEmpty: string;
  cancelCreate: string;
  creatingAgent: string;
  modeMembership: string;
  model: string;
  prompt: string;
};

type AgentCreatePanelProps = {
  copy: AgentCreatePanelCopy;
  draft: AgentCreateDraft;
  selectedModelId: string;
  isWorkSession: boolean;
  canCreate: boolean;
  pending: boolean;
  notice: { tone: "success" | "error"; text: string } | null;
  modelChoices: AgentCreatePanelModelChoice[];
  primaryModeOptions: AgentCreateSelectOption[];
  promptTemplateOptions: AgentCreateSelectOption[];
  toolBundles: ToolBundle[];
  toolBundleSummary: {
    label: string;
    meta: string;
  };
  toolBundleMeta: (bundle: ToolBundle) => string;
  onDraftChange: (patch: Partial<AgentCreateDraft>) => void;
  onModelChange: (modelId: string) => void;
  onPrimaryModeChange: (primaryMode: string) => void;
  onToolBundleToggle: (bundleId: string, selected: boolean) => void;
  onCancel: () => void;
  onCreate: () => void;
};

export function AgentCreatePanel({
  copy,
  draft,
  selectedModelId,
  isWorkSession,
  canCreate,
  pending,
  notice,
  modelChoices,
  primaryModeOptions,
  promptTemplateOptions,
  toolBundles,
  toolBundleSummary,
  toolBundleMeta,
  onDraftChange,
  onModelChange,
  onPrimaryModeChange,
  onToolBundleToggle,
  onCancel,
  onCreate,
}: AgentCreatePanelProps) {
  return (
    <section className={styles.createAgentPanel} title={copy.createAgentHint}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.createAgentTitle}</p>
          <h3>{copy.createAgent}</h3>
        </div>
        <Bot size={16} />
      </div>
      <div className={styles.createAgentGrid}>
        <VFieldRow label={copy.createAgentName}>
          <VNativeInput
            value={draft.displayName}
            placeholder={copy.createAgentNamePlaceholder}
            onChange={(event) => onDraftChange({ displayName: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.model}>
          <VNativeSelect
            value={selectedModelId}
            onChange={(event) => onModelChange(event.target.value)}
          >
            {modelChoices.map((model) => (
              <option key={model.key} value={model.modelId} title={model.modelLabel || model.modelId}>
                {model.label}
              </option>
            ))}
          </VNativeSelect>
        </VFieldRow>
        <VFieldRow label={copy.modeMembership}>
          <VNativeSelect
            value={draft.primaryMode}
            onChange={(event) => onPrimaryModeChange(event.target.value)}
          >
            {primaryModeOptions.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </VNativeSelect>
        </VFieldRow>
        {!isWorkSession ? (
          <VFieldRow label={copy.createAgentRole}>
            <VNativeInput
              value={draft.roleKey}
              placeholder={copy.createAgentRolePlaceholder}
              onChange={(event) => onDraftChange({ roleKey: event.target.value })}
            />
          </VFieldRow>
        ) : null}
        <VFieldRow label={copy.prompt}>
          <VNativeSelect value={draft.promptTemplateId} onChange={(event) => onDraftChange({ promptTemplateId: event.target.value })}>
            <option value="">-</option>
            {promptTemplateOptions.map((template) => (
              <option key={template.value || template.label} value={template.value}>
                {template.label}
              </option>
            ))}
          </VNativeSelect>
        </VFieldRow>
        {!isWorkSession ? (
          <>
            <VFieldRow label={copy.createAgentPersonaSummary} className="col-span-full">
              <VNativeTextarea
                value={draft.personaSummary}
                placeholder={copy.createAgentPersonaPlaceholder}
                onChange={(event) => onDraftChange({ personaSummary: event.target.value })}
              />
            </VFieldRow>
            <VFieldRow label={copy.createAgentTaskMission} className="col-span-full">
              <VNativeTextarea
                value={draft.taskMission}
                placeholder={copy.createAgentTaskMissionPlaceholder}
                onChange={(event) => onDraftChange({ taskMission: event.target.value })}
              />
            </VFieldRow>
          </>
        ) : null}
        <section className={styles.fieldWide} title={copy.createAgentToolBundlesHint}>
          <span>{copy.createAgentToolBundles}</span>
          {toolBundles.length ? (
            <div className={styles.createToolBundleGrid}>
              {toolBundles.map((bundle) => {
                const selected = draft.selectedToolBundleIds.includes(bundle.bundleId);
                return (
                  <label
                    key={bundle.bundleId}
                    className={selected ? styles.createToolBundleSelected : styles.createToolBundleOption}
                    title={[bundle.label, toolBundleMeta(bundle), bundle.description].filter(Boolean).join("\n")}
                  >
                    <VNativeInput
                      type="checkbox"
                      checked={selected}
                      onChange={(event) => onToolBundleToggle(bundle.bundleId, event.target.checked)}
                    />
                    <span>
                      <strong>{bundle.label}</strong>
                    </span>
                  </label>
                );
              })}
            </div>
          ) : (
            <VNativeInput
              value={draft.allowedTools}
              placeholder={copy.createAgentAllowedToolsPlaceholder}
              onChange={(event) => onDraftChange({ allowedTools: event.target.value })}
            />
          )}
        </section>
        <section
          className={`${styles.fieldWide} ${styles.createToolBundlePreview}`}
          title={toolBundleSummary.meta || copy.createAgentToolBundleEmpty}
        >
          <span>{copy.createAgentToolBundlePreview}</span>
          <strong>{toolBundleSummary.label}</strong>
        </section>
      </div>
      {notice ? (
        <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
      ) : null}
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          isDisabled={pending}
          onPress={onCancel}
        >
          {copy.cancelCreate}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          icon={<Plus size={15} />}
          isDisabled={!canCreate || pending}
          onPress={onCreate}
        >
          {pending ? copy.creatingAgent : copy.createAgent}
        </VButton>
      </div>
    </section>
  );
}
