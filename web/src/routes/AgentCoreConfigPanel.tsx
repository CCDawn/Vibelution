import { ExternalLink, SquarePen } from "lucide-react";

import {
  type AgentLlmBindings,
  type AgentLlmSlotDefinition,
  type AgentModelChoice,
  type AgentPermissionPreset,
} from "../api/types";
import { VButton, VContextualHint, VFieldRow, VNativeInput, VNativeSelect } from "../components/vui";
import { AgentPermissionPresetControl } from "../components/vui/product/agent-management";
import {
  AgentContextCompressionPanel,
  type AgentContextCompressionPanelCopy,
  type AgentContextCompressionPolicyDraft,
} from "./AgentContextCompressionPanel";
import { AgentModelPicker } from "./AgentModelPicker";
import styles from "./AgentCoreConfigPanel.styles";

export type AgentConfigDraft = {
  displayName: string;
  llmBindings: AgentLlmBindings;
  reasoningEffortBySlot: Record<string, string>;
  promptTemplateId: string;
  toolPolicyId: string;
  memoryPolicyId: string;
  permissionPreset: AgentPermissionPreset;
  contextCompressionPolicy: AgentContextCompressionPolicyDraft;
  status: string;
};

export type AgentCoreConfigSelectOption = {
  value: string;
  label: string;
  title?: string;
};

export type AgentCoreConfigLlmSlotView = {
  slot: AgentLlmSlotDefinition;
  selectedModelId: string;
  candidates: AgentModelChoice[];
  supportsReasoningEffort: boolean;
  reasoningEffort: string;
  /** Protocol contract options for the bound model; empty when unsupported. */
  reasoningEffortOptions: Array<{ value: string; label: string; description?: string }>;
};

export type AgentCoreConfigHealthView = {
  tone: "blocking" | "warning" | "info" | "ok";
  label: string;
  headline: string;
  nextStepLabel: string;
  nextStep: string;
};

export type AgentCoreConfigPanelCopy = AgentContextCompressionPanelCopy & {
  configTitle: string;
  healthNextStep: string;
  inheritDialogueModel: string;
  llmSlots: string;
  llmSlotsHint: string;
  memory: string;
  memoryPolicyPickerHint: string;
  optionalSlot: string;
  prompt: string;
  reasoningEffort: string;
  reasoningEffortDefault: string;
  reasoningEffortHigh: string;
  reasoningEffortLow: string;
  reasoningEffortMedium: string;
  /** Optional fallback label builder when option.label is empty. */
  reasoningEffortOptionLabel?: (value: string) => string;
  requiredSlot: string;
  resetConfig: string;
  saveConfig: string;
  savingConfig: string;
  status: string;
  toolPolicyPickerHint: string;
  tools: string;
};

type AgentCoreConfigPanelProps = {
  copy: AgentCoreConfigPanelCopy;
  lang: "zh" | "en";
  agentName: string;
  draft: AgentConfigDraft;
  dirty: boolean;
  configDraftDirty: boolean;
  canSave: boolean;
  pending: boolean;
  notice: { tone: "success" | "error"; text: string } | null;
  title: string;
  health: AgentCoreConfigHealthView;
  llmSlots: AgentCoreConfigLlmSlotView[];
  pendingModelRef: string;
  promptTemplateOptions: AgentCoreConfigSelectOption[];
  toolPolicyOptions: AgentCoreConfigSelectOption[];
  toolPolicyTooltip: string;
  memoryPolicyOptions: AgentCoreConfigSelectOption[];
  memoryPolicyTooltip: string;
  contextCompressionTitle: string;
  onDraftChange: (patch: Partial<AgentConfigDraft>) => void;
  onLlmSlotModelChange: (slot: AgentLlmSlotDefinition, modelId: string) => void;
  onPromoteModel: (slot: AgentLlmSlotDefinition, candidate: AgentModelChoice) => void;
  onReasoningEffortChange: (slot: string, reasoningEffort: string) => void;
  onContextCompressionChange: (patch: Partial<AgentContextCompressionPolicyDraft>) => void;
  onOpenModelConfig: () => void;
  onOpenPromptConfig: () => void;
  onOpenContextConfig: () => void;
  onReset: () => void;
  onSave: () => void;
};

function healthGuideToneClass(tone: AgentCoreConfigHealthView["tone"]) {
  const toneKey = `healthGuide_${tone}` as keyof typeof styles;
  return styles[toneKey] || styles.healthGuide_info;
}

function fallbackReasoningEffortLabel(copy: AgentCoreConfigPanelCopy, value: string) {
  switch (value) {
    case "low":
      return copy.reasoningEffortLow;
    case "medium":
      return copy.reasoningEffortMedium;
    case "high":
      return copy.reasoningEffortHigh;
    default:
      return value;
  }
}

function AgentLlmSlotField({
  slot,
  selectedModelId,
  candidates,
  supportsReasoningEffort,
  reasoningEffort,
  reasoningEffortOptions,
  copy,
  lang,
  pending,
  pendingModelRef,
  configDraftDirty,
  dirty,
  compact = false,
  hideLabel = false,
  onLlmSlotModelChange,
  onPromoteModel,
  onReasoningEffortChange,
}: {
  slot: AgentCoreConfigLlmSlotView["slot"];
  selectedModelId: string;
  candidates: AgentModelChoice[];
  supportsReasoningEffort: boolean;
  reasoningEffort: string;
  reasoningEffortOptions: AgentCoreConfigLlmSlotView["reasoningEffortOptions"];
  copy: AgentCoreConfigPanelCopy;
  lang: "zh" | "en";
  pending: boolean;
  pendingModelRef: string;
  configDraftDirty: boolean;
  dirty: boolean;
  compact?: boolean;
  hideLabel?: boolean;
  onLlmSlotModelChange: AgentCoreConfigPanelProps["onLlmSlotModelChange"];
  onPromoteModel: AgentCoreConfigPanelProps["onPromoteModel"];
  onReasoningEffortChange: AgentCoreConfigPanelProps["onReasoningEffortChange"];
}) {
  const slotHint = `${slot.required ? copy.requiredSlot : copy.optionalSlot} · ${slot.description}`;
  return (
    <section
      className={compact ? styles.llmSlotFieldCompact : styles.llmSlotField}
      aria-label={slotHint}
    >
      {hideLabel ? null : (
        <div className={styles.contextualHintRow}>
          <strong>{slot.label}</strong>
          <VContextualHint
            content={slotHint}
            label={`${slot.label} ${lang === "zh" ? "说明" : "details"}`}
            width="wide"
          />
        </div>
      )}
      <AgentModelPicker
        candidates={candidates}
        slot={slot}
        selectedModelRef={selectedModelId}
        disabled={pending}
        pendingModelRef={pendingModelRef}
        configDraftDirty={configDraftDirty}
        agentDraftDirty={dirty}
        onSelectPinned={(modelRef) => onLlmSlotModelChange(slot, modelRef)}
        onPromote={(candidate) => onPromoteModel(slot, candidate)}
      />
      {!slot.required ? (
        <VButton type="button" variant="ghost" isDisabled={pending || !selectedModelId} onPress={() => onLlmSlotModelChange(slot, "")}>
          {copy.inheritDialogueModel}
        </VButton>
      ) : null}
      {supportsReasoningEffort && reasoningEffortOptions.length > 0 ? (
        <VNativeSelect value={reasoningEffort} aria-label={`${slot.label} ${copy.reasoningEffort}`} onChange={(event) => onReasoningEffortChange(slot.slot, event.target.value)}>
          <option value="">{copy.reasoningEffort}: {copy.reasoningEffortDefault}</option>
          {reasoningEffortOptions.map((option) => {
            const label = option.label || fallbackReasoningEffortLabel(copy, option.value);
            return (
              <option key={option.value} value={option.value}>
                {copy.reasoningEffort}: {label}
              </option>
            );
          })}
        </VNativeSelect>
      ) : null}
    </section>
  );
}

export function AgentCoreConfigPanel({
  copy,
  lang,
  agentName,
  draft,
  dirty,
  configDraftDirty,
  canSave,
  pending,
  notice,
  title,
  health,
  llmSlots,
  pendingModelRef,
  promptTemplateOptions,
  toolPolicyOptions,
  toolPolicyTooltip,
  memoryPolicyOptions,
  memoryPolicyTooltip,
  contextCompressionTitle,
  onDraftChange,
  onLlmSlotModelChange,
  onPromoteModel,
  onReasoningEffortChange,
  onContextCompressionChange,
  onOpenModelConfig,
  onOpenPromptConfig,
  onOpenContextConfig,
  onReset,
  onSave,
}: AgentCoreConfigPanelProps) {
  const primaryLlmSlot = llmSlots.find(({ slot }) => slot.slot === "dialogue") ?? llmSlots[0];
  const advancedLlmSlots = llmSlots.filter((item) => item !== primaryLlmSlot);
  const advancedLabel = lang === "zh" ? "高级模型与上下文" : "Advanced models and context";
  const primaryModelLabel = lang === "zh" ? "主要对话模型" : "Primary conversation model";
  return (
    <section className={styles.configEditor} aria-label={title}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.configTitle}</p>
          <h3 className={styles.contextualHintRow}>
            <span className={styles.panelTitle}>{lang === "zh" ? "基本配置" : "Basics"}</span>
            <VContextualHint
              content={title}
              label={`${agentName} ${lang === "zh" ? "配置说明" : "configuration details"}`}
              width="wide"
            />
          </h3>
        </div>
        <span className={dirty ? styles.dirtyPill : styles.cleanPill}>
          {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
        </span>
      </div>
      {health.tone === "blocking" ? (
        <section className={`${styles.healthGuidePanel} ${healthGuideToneClass(health.tone)}`}>
          <div>
            <span>{health.label}</span>
            <strong>{health.headline}</strong>
          </div>
          <p><strong>{health.nextStepLabel}</strong>{health.nextStep}</p>
        </section>
      ) : null}
      <div className={styles.editorGrid}>
        <VFieldRow label="Agent">
          <VNativeInput
            value={draft.displayName}
            onChange={(event) => onDraftChange({ displayName: event.target.value })}
          />
        </VFieldRow>
        <VFieldRow label={copy.status}>
          <VNativeSelect value={draft.status} onChange={(event) => onDraftChange({ status: event.target.value })}>
            <option value="active">{lang === "zh" ? "活跃" : "Active"}</option>
          </VNativeSelect>
        </VFieldRow>
        <VFieldRow
          label={lang === "zh" ? "工具调用批准" : "Tool approval"}
          tooltip={lang === "zh"
            ? "这是此 Agent 的唯一权限配置。消息框中的选择会写回同一字段，并从下一回合生效。"
            : "This is the Agent's sole permission setting. Composer changes write the same field and apply next turn."}
        >
          <AgentPermissionPresetControl
            value={draft.permissionPreset}
            lang={lang}
            surface="settings"
            disabled={pending}
            pending={pending}
            agentName={agentName}
            onChange={(permissionPreset) => onDraftChange({ permissionPreset })}
          />
        </VFieldRow>
        {primaryLlmSlot ? (
          <section className={styles.fieldWide} aria-label={copy.llmSlotsHint}>
            <div className={styles.contextualHintRow}>
              <span>{primaryModelLabel}</span>
              <VContextualHint
                content={copy.llmSlotsHint}
                label={`${primaryModelLabel} ${lang === "zh" ? "说明" : "details"}`}
                width="wide"
              />
            </div>
            <div className={styles.primaryLlmSlot}>
              <AgentLlmSlotField
                {...primaryLlmSlot}
                copy={copy}
                lang={lang}
                pending={pending}
                pendingModelRef={pendingModelRef}
                configDraftDirty={configDraftDirty}
                dirty={dirty}
                compact
                hideLabel
                onLlmSlotModelChange={onLlmSlotModelChange}
                onPromoteModel={onPromoteModel}
                onReasoningEffortChange={onReasoningEffortChange}
              />
            </div>
          </section>
        ) : null}
        <section className={`${styles.fieldWide} ${styles.promptConfigField}`}>
          <span>{copy.prompt}</span>
          <div className={styles.promptConfigRow}>
            <VNativeSelect value={draft.promptTemplateId} onChange={(event) => onDraftChange({ promptTemplateId: event.target.value })}>
              <option value="">-</option>
              {promptTemplateOptions.map((template) => (
                <option key={template.value || template.label} value={template.value}>
                  {template.label}
                </option>
              ))}
            </VNativeSelect>
            <VButton
              type="button"
              variant="secondary"
              icon={<SquarePen size={15} />}
              onPress={onOpenPromptConfig}
            >
              {lang === "zh" ? "配置提示词" : "Configure prompt"}
            </VButton>
          </div>
        </section>
        <div className={styles.bindingRow}>
          <VFieldRow
            label={copy.tools}
            tooltip={toolPolicyTooltip}
          >
            <VNativeSelect value={draft.toolPolicyId} onChange={(event) => onDraftChange({ toolPolicyId: event.target.value })}>
              {toolPolicyOptions.map((policy) => (
                <option key={policy.value} value={policy.value} title={policy.title}>
                  {policy.label}
                </option>
              ))}
            </VNativeSelect>
          </VFieldRow>
          <VFieldRow label={copy.memory} tooltip={memoryPolicyTooltip}>
            <VNativeSelect value={draft.memoryPolicyId} onChange={(event) => onDraftChange({ memoryPolicyId: event.target.value })}>
              {memoryPolicyOptions.map((policy) => (
                <option key={policy.value} value={policy.value} title={policy.title}>
                  {policy.label}
                </option>
              ))}
            </VNativeSelect>
          </VFieldRow>
        </div>
        <div className={`${styles.fieldWide} ${styles.configDeepLinkRow}`}>
          <VButton
            type="button"
            variant="secondary"
            icon={<ExternalLink size={15} />}
            onPress={onOpenModelConfig}
          >
            {lang === "zh" ? "去模型库配置" : "Open model library"}
          </VButton>
          <VButton
            type="button"
            variant="ghost"
            icon={<ExternalLink size={15} />}
            onPress={onOpenContextConfig}
          >
            {lang === "zh" ? "去上下文配置" : "Open context config"}
          </VButton>
        </div>
        <details className={styles.advancedConfig}>
          <summary>
            <span>{advancedLabel}</span>
            <small>{advancedLlmSlots.length}</small>
          </summary>
          <div className={styles.advancedConfigBody}>
            {advancedLlmSlots.length ? (
              <div className={styles.llmSlotGrid}>
                {advancedLlmSlots.map((slotView) => (
                  <AgentLlmSlotField
                    key={slotView.slot.slot}
                    {...slotView}
                    copy={copy}
                    lang={lang}
                    pending={pending}
                    pendingModelRef={pendingModelRef}
                    configDraftDirty={configDraftDirty}
                    dirty={dirty}
                    onLlmSlotModelChange={onLlmSlotModelChange}
                    onPromoteModel={onPromoteModel}
                    onReasoningEffortChange={onReasoningEffortChange}
                  />
                ))}
              </div>
            ) : null}
            <AgentContextCompressionPanel
              copy={copy}
              lang={lang}
              policy={draft.contextCompressionPolicy}
              title={contextCompressionTitle}
              onPolicyChange={onContextCompressionChange}
              onOpenContextConfig={onOpenContextConfig}
            />
          </div>
        </details>
      </div>
      {notice ? (
        <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
      ) : null}
      <div className={styles.editorActions}>
        <VButton type="button" variant="secondary" isDisabled={!dirty || pending} onPress={onReset}>
          {copy.resetConfig}
        </VButton>
        <VButton type="button" variant="primary" isDisabled={!canSave || pending} onPress={onSave}>
          {pending ? copy.savingConfig : copy.saveConfig}
        </VButton>
      </div>
    </section>
  );
}
