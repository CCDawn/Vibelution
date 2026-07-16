import { Bot, Check, ChevronLeft, ChevronRight, Plus, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { type AgentLlmBindings, type ToolBundle } from "../api/types";
import { VButton, VContextualHint, VFieldRow, VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea, VTooltip } from "../components/vui";
import styles from "./AgentCreatePanel.styles";

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
  providerId: string;
  providerLabel: string;
  providerKind: string;
};

export type AgentCreateSelectOption = {
  value: string;
  label: string;
};

export type AgentCreatePreset = {
  id: "recommended" | "coding" | "research";
  label: string;
  description: string;
  draft: AgentCreateDraft;
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
  presets: AgentCreatePreset[];
  lang: "zh" | "en";
  onDraftChange: (patch: Partial<AgentCreateDraft>) => void;
  onApplyPreset: (draft: AgentCreateDraft) => void;
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
  presets,
  lang,
  onDraftChange,
  onApplyPreset,
  onModelChange,
  onPrimaryModeChange,
  onToolBundleToggle,
  onCancel,
  onCreate,
}: AgentCreatePanelProps) {
  const [activeStep, setActiveStep] = useState(0);
  const providerChoices = useMemo(() => Array.from(new Map(modelChoices.map((model) => {
    const providerLabel = model.providerLabel || model.providerKind || model.providerId;
    const label = [
      providerLabel,
      model.providerKind && model.providerKind !== providerLabel ? model.providerKind : "",
      model.providerId !== providerLabel ? model.providerId : "",
    ].filter(Boolean).join(" · ");
    return [model.providerId, { id: model.providerId, label }];
  })).values()), [modelChoices]);
  const selectedModel = modelChoices.find((model) => model.modelId === selectedModelId);
  const selectedProviderId = selectedModel?.providerId || providerChoices[0]?.id || "";
  const providerModels = modelChoices.filter((model) => model.providerId === selectedProviderId);
  const selectedPrompt = promptTemplateOptions.find((template) => template.value === draft.promptTemplateId)?.label || draft.promptTemplateId || "-";
  const selectedProvider = providerChoices.find((provider) => provider.id === selectedProviderId)?.label || "-";
  const basicReady = Boolean(
    draft.displayName.trim()
    && draft.primaryMode.trim()
    && (isWorkSession || (draft.roleKey.trim() && draft.personaSummary.trim() && draft.taskMission.trim())),
  );
  const modelReady = Boolean(selectedProviderId && selectedModelId);
  const stepReady = [basicReady, modelReady, canCreate];
  const stepLabels = lang === "zh"
    ? ["基本信息", "服务商与模型", "提示词与工具"]
    : ["Basics", "Provider & model", "Prompt & tools"];
  const nextLabel = lang === "zh" ? "下一步" : "Next";
  const previousLabel = lang === "zh" ? "上一步" : "Back";
  const quickFillTitle = lang === "zh" ? "快速填写" : "Quick fill";
  const quickFillHint = lang === "zh"
    ? "配置来自当前模型库、提示词模板和工具包，可一键填写后再逐项调整。"
    : "Defaults come from the current model library, prompt templates, and tool packages. Apply once, then fine-tune.";
  const summaryTitle = lang === "zh" ? "创建前确认" : "Review before creation";
  const summaryItems = lang === "zh"
    ? [["名称", draft.displayName || "-"], ["服务商", selectedProvider], ["模型", selectedModel?.modelLabel || selectedModelId || "-"], ["提示词", selectedPrompt], ["工具", toolBundleSummary.label]]
    : [["Name", draft.displayName || "-"], ["Provider", selectedProvider], ["Model", selectedModel?.modelLabel || selectedModelId || "-"], ["Prompt", selectedPrompt], ["Tools", toolBundleSummary.label]];

  const applyPreset = (preset: AgentCreatePreset) => {
    onApplyPreset(preset.draft);
    setActiveStep(1);
  };

  return (
    <section className={styles.createAgentPanel}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.createAgentTitle}</p>
          <div className="flex min-w-0 items-center gap-1.5">
            <h3>{copy.createAgent}</h3>
            <VContextualHint
              label={lang === "zh" ? "新建 Agent 说明" : "New Agent details"}
              content={copy.createAgentHint}
              width="wide"
            />
          </div>
        </div>
        <Bot size={16} />
      </div>

      <section className={styles.quickFill} aria-label={quickFillTitle}>
        <div className={styles.quickFillHeader}>
          <span>
            <Sparkles size={14} /> {quickFillTitle}
            <VContextualHint
              label={lang === "zh" ? "快速填写说明" : "Quick fill details"}
              content={quickFillHint}
              width="wide"
            />
          </span>
        </div>
        <div className={styles.presetGrid}>
          {presets.map((preset) => (
            <VTooltip key={preset.id} content={preset.description} width="wide">
              <VNativeButton type="button" className={styles.presetButton} disabled={pending} onClick={() => applyPreset(preset)}>
                <strong>{preset.label}</strong>
              </VNativeButton>
            </VTooltip>
          ))}
        </div>
      </section>

      <ol className={styles.wizardSteps} aria-label={lang === "zh" ? "新建 Agent 步骤" : "New Agent steps"}>
        {stepLabels.map((label, index) => {
          const complete = index < activeStep && stepReady[index];
          const reachable = index === 0 || stepReady.slice(0, index).every(Boolean);
          return (
            <li key={label}>
              <VNativeButton
                type="button"
                className={index === activeStep ? styles.wizardStepActive : complete ? styles.wizardStepComplete : styles.wizardStep}
                aria-current={index === activeStep ? "step" : undefined}
                disabled={pending || !reachable}
                onClick={() => setActiveStep(index)}
              >
                <span>{complete ? <Check size={13} /> : index + 1}</span>
                {label}
              </VNativeButton>
            </li>
          );
        })}
      </ol>

      <div className={styles.stepBody}>
        {activeStep === 0 ? (
          <div className={styles.createAgentGrid}>
            <VFieldRow label={copy.createAgentName} className="col-span-full">
              <VNativeInput
                autoFocus
                value={draft.displayName}
                placeholder={copy.createAgentNamePlaceholder}
                onChange={(event) => onDraftChange({ displayName: event.target.value })}
              />
            </VFieldRow>
            <VFieldRow label={copy.modeMembership} className="col-span-full">
              <VNativeSelect value={draft.primaryMode} onChange={(event) => onPrimaryModeChange(event.target.value)}>
                {primaryModeOptions.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
              </VNativeSelect>
            </VFieldRow>
            {!isWorkSession ? (
              <>
                <VFieldRow label={copy.createAgentRole} className="col-span-full">
                  <VNativeInput value={draft.roleKey} placeholder={copy.createAgentRolePlaceholder} onChange={(event) => onDraftChange({ roleKey: event.target.value })} />
                </VFieldRow>
                <VFieldRow label={copy.createAgentPersonaSummary} className="col-span-full">
                  <VNativeTextarea value={draft.personaSummary} placeholder={copy.createAgentPersonaPlaceholder} onChange={(event) => onDraftChange({ personaSummary: event.target.value })} />
                </VFieldRow>
                <VFieldRow label={copy.createAgentTaskMission} className="col-span-full">
                  <VNativeTextarea value={draft.taskMission} placeholder={copy.createAgentTaskMissionPlaceholder} onChange={(event) => onDraftChange({ taskMission: event.target.value })} />
                </VFieldRow>
              </>
            ) : null}
          </div>
        ) : null}

        {activeStep === 1 ? (
          <div className={styles.createAgentGrid}>
            <VFieldRow label={lang === "zh" ? "服务商" : "Provider"} className="col-span-full">
              <VNativeSelect
                value={selectedProviderId}
                disabled={!providerChoices.length}
                onChange={(event) => {
                  const nextModel = modelChoices.find((model) => model.providerId === event.target.value);
                  onModelChange(nextModel?.modelId || "");
                }}
              >
                {!providerChoices.length ? <option value="">{lang === "zh" ? "没有可用服务商" : "No available provider"}</option> : null}
                {providerChoices.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
              </VNativeSelect>
            </VFieldRow>
            <VFieldRow label={copy.model} className="col-span-full">
              <VNativeSelect value={selectedModelId} disabled={!providerModels.length} onChange={(event) => onModelChange(event.target.value)}>
                {!providerModels.length ? <option value="">{lang === "zh" ? "该服务商没有可用模型" : "No model available for this provider"}</option> : null}
                {providerModels.map((model) => (
                  <option key={model.key} value={model.modelId} title={model.modelLabel || model.modelId}>{model.label}</option>
                ))}
              </VNativeSelect>
            </VFieldRow>
            {!modelChoices.length ? <p className={styles.errorText}>{lang === "zh" ? "请先在模型库中配置至少一个可运行模型。" : "Configure at least one runtime model in the model library first."}</p> : null}
          </div>
        ) : null}

        {activeStep === 2 ? (
          <div className={styles.createAgentGrid}>
            <VFieldRow label={copy.prompt} className="col-span-full">
              <VNativeSelect value={draft.promptTemplateId} onChange={(event) => onDraftChange({ promptTemplateId: event.target.value })}>
                <option value="">-</option>
                {promptTemplateOptions.map((template) => <option key={template.value || template.label} value={template.value}>{template.label}</option>)}
              </VNativeSelect>
            </VFieldRow>
            <section className={styles.fieldWide}>
              <span className="inline-flex items-center gap-1.5">
                {copy.createAgentToolBundles}
                <VContextualHint
                  label={lang === "zh" ? "工具能力包说明" : "Tool bundle details"}
                  content={copy.createAgentToolBundlesHint}
                  width="wide"
                />
              </span>
              {toolBundles.length ? (
                <div className={styles.createToolBundleGrid}>
                  {toolBundles.map((bundle) => {
                    const selected = draft.selectedToolBundleIds.includes(bundle.bundleId);
                    return (
                      <label key={bundle.bundleId} className={selected ? styles.createToolBundleSelected : styles.createToolBundleOption} title={[bundle.label, toolBundleMeta(bundle), bundle.description].filter(Boolean).join("\n")}>
                        <VNativeInput type="checkbox" checked={selected} onChange={(event) => onToolBundleToggle(bundle.bundleId, event.target.checked)} />
                        <span><strong>{bundle.label}</strong></span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <VNativeInput value={draft.allowedTools} placeholder={copy.createAgentAllowedToolsPlaceholder} onChange={(event) => onDraftChange({ allowedTools: event.target.value })} />
              )}
            </section>
            <VTooltip content={toolBundleSummary.meta || copy.createAgentToolBundleEmpty} width="wide">
              <section
                className={`${styles.fieldWide} ${styles.createToolBundlePreview}`}
                role="group"
                tabIndex={0}
                aria-label={`${copy.createAgentToolBundlePreview}：${toolBundleSummary.label}`}
              >
                <span>{copy.createAgentToolBundlePreview}</span>
                <strong>{toolBundleSummary.label}</strong>
              </section>
            </VTooltip>
            <section className={`${styles.fieldWide} ${styles.createSummary}`} aria-label={summaryTitle}>
              <strong>{summaryTitle}</strong>
              <dl>{summaryItems.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            </section>
          </div>
        ) : null}
      </div>

      {notice ? <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p> : null}
      <div className={styles.editorActions}>
        <VButton type="button" variant="secondary" isDisabled={pending} onPress={onCancel}>{copy.cancelCreate}</VButton>
        {activeStep > 0 ? (
          <VButton type="button" variant="secondary" icon={<ChevronLeft size={15} />} isDisabled={pending} onPress={() => setActiveStep((step) => Math.max(0, step - 1))}>{previousLabel}</VButton>
        ) : null}
        {activeStep < 2 ? (
          <VButton type="button" variant="primary" icon={<ChevronRight size={15} />} isDisabled={!stepReady[activeStep] || pending} onPress={() => setActiveStep((step) => Math.min(2, step + 1))}>{nextLabel}</VButton>
        ) : (
          <VButton type="button" variant="primary" icon={<Plus size={15} />} isDisabled={!canCreate || pending} onPress={onCreate}>{pending ? copy.creatingAgent : copy.createAgent}</VButton>
        )}
      </div>
    </section>
  );
}
