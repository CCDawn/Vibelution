import { ExternalLink, SquarePen } from "lucide-react";

import {
  type AgentLlmBindings,
  type AgentLlmSlotDefinition,
  type AgentModelChoice,
  type AgentPermissionPreset,
} from "../api/types";
import { VButton, VFieldRow, VNativeInput, VSettingsFormPage, VStringSelect } from "../components/vui";
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
  section?: "all" | "models" | "basic";
  groupDirty?: { models: boolean; basic: boolean };
  groupCanSave?: { models: boolean; basic: boolean };
  onSaveGroup?: (group: "models" | "basic") => void;
  onResetGroup?: (group: "models" | "basic") => void;
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
  return tone === "blocking" ? styles.healthGuide_blocking : styles.healthGuide_info;
}

function fallbackReasoningEffortLabel(copy: AgentCoreConfigPanelCopy, value: string) {
  return ({ low: copy.reasoningEffortLow, medium: copy.reasoningEffortMedium, high: copy.reasoningEffortHigh } as Record<string, string>)[value] || value;
}

export function AgentCoreConfigPanel({
  section = "all", groupDirty, groupCanSave, onSaveGroup, onResetGroup,
  copy, lang, agentName, draft, dirty, configDraftDirty, canSave, pending, notice,
  title, health, llmSlots, pendingModelRef, promptTemplateOptions,
  toolPolicyOptions, toolPolicyTooltip, memoryPolicyOptions, memoryPolicyTooltip,
  contextCompressionTitle, onDraftChange, onLlmSlotModelChange, onPromoteModel,
  onReasoningEffortChange, onContextCompressionChange, onOpenModelConfig,
  onOpenPromptConfig, onOpenContextConfig, onReset, onSave,
}: AgentCoreConfigPanelProps) {
  const primaryLlmSlot = llmSlots.find(({ slot }) => slot.slot === "dialogue") ?? llmSlots[0];
  const advancedLlmSlots = llmSlots.filter((item) => item !== primaryLlmSlot);
  const showModels = section !== "basic";
  const showBasic = section !== "models";
  const group = section === "models" ? "models" : "basic";
  const groupIsDirty = section === "all" ? dirty : groupDirty?.[group] ?? dirty;
  const groupMaySave = section === "all" ? canSave : groupCanSave?.[group] ?? canSave;
  const text = (zh: string, en: string) => lang === "zh" ? zh : en;
  void toolPolicyTooltip; void memoryPolicyTooltip;
  const reasoning = (view: AgentCoreConfigLlmSlotView) => view.supportsReasoningEffort && view.reasoningEffortOptions.length > 0 ? (
    <VFieldRow label={copy.reasoningEffort} className={styles.fieldRow}>
      <VStringSelect className={styles.selectControl} isDisabled={pending}
        ariaLabel={`${view.slot.label} ${copy.reasoningEffort}`} value={view.reasoningEffort}
        onValueChange={(value) => onReasoningEffortChange(view.slot.slot, value)}
        options={[{ value: "", label: copy.reasoningEffortDefault }, ...view.reasoningEffortOptions.map(option => ({ value: option.value, label: option.label || fallbackReasoningEffortLabel(copy, option.value) }))]}/>
    </VFieldRow>
  ) : null;
  const model = (view: AgentCoreConfigLlmSlotView, label: string) => {
    const { slot, selectedModelId, candidates } = view;
    return <VFieldRow label={label} className={styles.fieldRow}>
      <div className={styles.modelControl}>
        <AgentModelPicker candidates={candidates} slot={slot} selectedModelRef={selectedModelId}
          disabled={pending} pendingModelRef={pendingModelRef} configDraftDirty={configDraftDirty}
          agentDraftDirty={dirty} lang={lang}
          onSelectPinned={(modelRef) => onLlmSlotModelChange(slot, modelRef)}
          onPromote={(candidate) => onPromoteModel(slot, candidate)}/>
        {!slot.required && selectedModelId ? <VButton className={styles.quietButton} isDisabled={pending} onPress={() => onLlmSlotModelChange(slot, "")}>{text("恢复默认", "Reset to default")}</VButton> : null}
      </div>
    </VFieldRow>;
  };
  const select = (label: string, value: string, options: AgentCoreConfigSelectOption[], onChange: (value: string) => void) => (
    <VFieldRow label={label} className={styles.fieldRow}>
      <VStringSelect className={styles.selectControl} isDisabled={pending} ariaLabel={label}
        value={value} options={options} onValueChange={onChange}/>
    </VFieldRow>
  );
  return <VSettingsFormPage title={text("Agent 配置", "Agent configuration")} ariaLabel={title}
    className={styles.configEditor} headerClassName="hidden" bodyClassName={styles.editorBody}
    footerClassName={styles.footer} footer={(
      <div className={styles.editorActions}>
        <span role="status" className={styles.saveStatus}>{groupIsDirty ? text("未保存", "Unsaved") : text("已保存", "Saved")}</span>
        <div className={styles.actionButtons}>
          <VButton className={styles.quietButton} variant="secondary" isDisabled={!groupIsDirty || pending} onPress={() => section !== "all" && onResetGroup ? onResetGroup(group) : onReset()}>{text("还原", "Reset")}</VButton>
          <VButton className={styles.saveButton} variant="primary" aria-label={text(group === "models" ? "保存模型配置" : "保存基本配置", group === "models" ? "Save model settings" : "Save basic settings")} isDisabled={!groupMaySave || pending} onPress={() => section !== "all" && onSaveGroup ? onSaveGroup(group) : onSave()}>{pending ? text("保存中…", "Saving…") : text("保存", "Save")}</VButton>
        </div>
      </div>
    )}>
    <div className={styles.editorGrid}>
      {health.tone === "blocking" ? <p role="alert" className={`${styles.healthGuidePanel} ${healthGuideToneClass(health.tone)}`}>{health.headline}</p> : null}
      {notice ? <p role={notice.tone === "error" ? "alert" : "status"} className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p> : null}
      {showModels && primaryLlmSlot ? <section className={styles.configGroup} aria-label={copy.llmSlotsHint}>
        <div className={styles.groupHeader}><h3 className={styles.groupTitle}>{text("主模型", "Primary model")}</h3><VButton className={styles.quietButton} variant="ghost" icon={<ExternalLink size={13}/>} onPress={onOpenModelConfig}>{text("模型库", "Model library")}</VButton></div>
        <div className={styles.groupFields}>{model(primaryLlmSlot, text("模型", "Model"))}{reasoning(primaryLlmSlot)}</div>
      </section> : null}
      {showModels && advancedLlmSlots.length > 0 ? <details className={styles.advancedConfig}>
        <summary>{text("专用模型", "Specialized models")}</summary>
        <div className={styles.llmSlotGrid}>{advancedLlmSlots.map(view => <div key={view.slot.slot} className={styles.llmSlotField}>{model(view, view.slot.label)}{reasoning(view)}</div>)}</div>
      </details> : null}
      {showBasic ? <>
        <section className={styles.configGroup}><h3 className={styles.groupTitle}>{text("基本信息", "Basic information")}</h3><div className={styles.groupFields}>
          <VFieldRow label={text("显示名称", "Display name")} className={styles.fieldRow}><VNativeInput className={styles.control} aria-label={text("显示名称", "Display name")} disabled={pending} value={draft.displayName} onChange={event => onDraftChange({ displayName: event.target.value })}/></VFieldRow>
          <VFieldRow label={text("提示词模板", "Prompt template")} className={styles.fieldRow}><div className={styles.promptConfigRow}><VStringSelect className={styles.selectControl} isDisabled={pending} ariaLabel={copy.prompt} value={draft.promptTemplateId} options={[{value:"",label:"-"},...promptTemplateOptions]} onValueChange={promptTemplateId => onDraftChange({promptTemplateId})}/><VButton className={styles.quietButton} variant="ghost" aria-label={text("配置提示词", "Configure prompt")} icon={<SquarePen size={14}/>} onPress={onOpenPromptConfig}/></div></VFieldRow>
          {select(copy.status, draft.status, [{value:"active",label:text("活跃", "Active")}], status => onDraftChange({status}))}
        </div></section>
        <section className={styles.configGroup}><h3 className={styles.groupTitle}>{text("权限与策略", "Permissions and policies")}</h3><div className={styles.groupFields}>
          <VFieldRow label={text("工具调用批准", "Tool approval")} className={styles.fieldRow}><div className={styles.permissionControl}><AgentPermissionPresetControl value={draft.permissionPreset} lang={lang} surface="settings" disabled={pending} pending={pending} agentName={agentName} onChange={permissionPreset => onDraftChange({permissionPreset})}/></div></VFieldRow>
          {select(copy.tools, draft.toolPolicyId, toolPolicyOptions, toolPolicyId => onDraftChange({toolPolicyId}))}
          {select(copy.memory, draft.memoryPolicyId, memoryPolicyOptions, memoryPolicyId => onDraftChange({memoryPolicyId}))}
        </div></section>
        <details className={styles.advancedConfig}><summary>{text("上下文压缩", "Context compression")}</summary><div className={styles.advancedConfigBody}><AgentContextCompressionPanel copy={copy} lang={lang} policy={draft.contextCompressionPolicy} title={contextCompressionTitle} onPolicyChange={onContextCompressionChange} onOpenContextConfig={onOpenContextConfig}/></div></details>
      </> : null}
    </div>
  </VSettingsFormPage>;
}
