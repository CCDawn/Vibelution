import { Check, ChevronLeft, ChevronRight, Plus, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { type AgentAvatarOptionsPayload, type ToolBundle } from "../api/types";
import { VButton, VContextualHint, VFieldRow, VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea, VTooltip } from "../components/vui";
import {
  buildAgentProviderChoices,
  firstAvailableModelId,
  probeStatusLabel,
  type AgentCreateDraft,
  type AgentCreatePanelModelChoice,
  type AgentCreatePreset,
  type AgentCreateSelectOption,
} from "./agent-create/agentCreateContract";
import { CreateOptionSelect } from "./agent-create/CreateOptionSelect";
import styles from "./AgentCreatePanel.styles";

export type {
  AgentCreateDraft,
  AgentCreatePanelModelChoice,
  AgentCreatePreset,
  AgentCreateSelectOption,
} from "./agent-create/agentCreateContract";

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
  createAgentAvatar?: string;
  createAgentAvatarHint?: string;
  createAgentAvatarDefault?: string;
  createAgentAvatarLibrary?: string;
  createAgentAvatarLoading?: string;
  createAgentAvatarEmpty?: string;
};

type AgentCreatePanelProps = {
  copy: AgentCreatePanelCopy;
  draft: AgentCreateDraft;
  selectedModelId: string;
  isWorkSession: boolean;
  canCreate: boolean;
  pending: boolean;
  loadingOptions?: boolean;
  optionsError?: string;
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
  probeBusy?: boolean;
  probeSummary?: string;
  onProbeSelected?: () => void;
  onProbeCredentialReady?: () => void;
  avatarOptions?: AgentAvatarOptionsPayload | null;
  avatarOptionsPending?: boolean;
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
  loadingOptions = false,
  optionsError = "",
  notice,
  modelChoices,
  primaryModeOptions,
  promptTemplateOptions,
  toolBundles,
  toolBundleSummary,
  toolBundleMeta,
  presets,
  lang,
  probeBusy = false,
  probeSummary = "",
  onProbeSelected,
  onProbeCredentialReady,
  avatarOptions = null,
  avatarOptionsPending = false,
  onDraftChange,
  onApplyPreset,
  onModelChange,
  onPrimaryModeChange,
  onToolBundleToggle,
  onCancel,
  onCreate,
}: AgentCreatePanelProps) {
  const [activeStep, setActiveStep] = useState(0);
  const providerChoices = useMemo(() => buildAgentProviderChoices(modelChoices, lang), [lang, modelChoices]);
  const credentialReadyCount = useMemo(
    () => modelChoices.reduce((total, model) => total + (model.available ? 1 : 0), 0),
    [modelChoices],
  );
  const probeOkCount = useMemo(
    () => modelChoices.reduce((total, model) => total + (model.probeUsable ? 1 : 0), 0),
    [modelChoices],
  );
  const selectedModel = modelChoices.find((model) => model.modelId === selectedModelId);
  const preferredProviderId = providerChoices.find((provider) => provider.available)?.id
    || providerChoices[0]?.id
    || "";
  const selectedProviderId = selectedModel?.providerId || preferredProviderId;
  const providerModels = modelChoices.filter((model) => model.providerId === selectedProviderId);
  const selectedPrompt = promptTemplateOptions.find((template) => template.value === draft.promptTemplateId)?.label || draft.promptTemplateId || "-";
  const selectedProvider = selectedModel?.providerLabel || selectedModel?.providerId || "-";
  const selectedToolBundleCount = draft.selectedToolBundleIds.length;
  const basicReady = Boolean(
    draft.displayName.trim()
    && draft.primaryMode.trim()
    && (isWorkSession || (draft.roleKey.trim() && draft.personaSummary.trim() && draft.taskMission.trim())),
  );
  const modelReady = Boolean(selectedProviderId && selectedModelId && selectedModel?.probeUsable);
  const stepReady = [basicReady, modelReady, canCreate];
  const stepLabels = lang === "zh"
    ? ["基本信息", "服务商与模型", "提示词与工具"]
    : ["Basics", "Provider & model", "Prompt & tools"];
  const nextLabel = lang === "zh" ? "下一步" : "Next";
  const previousLabel = lang === "zh" ? "上一步" : "Back";
  const quickFillTitle = lang === "zh" ? "快速填写" : "Quick fill";
  const quickFillHint = lang === "zh"
    ? "配置来自当前模型库。已配密钥的模型需要点「探测」确认真实连通后，才能进入下一步。"
    : "Defaults come from the model library. Credential-ready models must pass a live probe before you can continue.";
  const summaryTitle = lang === "zh" ? "创建前确认" : "Review before creation";
  const summaryItems = lang === "zh"
    ? [["名称", draft.displayName || "-"], ["服务商", selectedProvider], ["模型", selectedModel?.modelLabel || selectedModelId || "-"], ["探测", selectedModel ? probeStatusLabel(selectedModel.probeStatus, lang) : "-"], ["提示词", selectedPrompt], ["工具", toolBundleSummary.label]]
    : [["Name", draft.displayName || "-"], ["Provider", selectedProvider], ["Model", selectedModel?.modelLabel || selectedModelId || "-"], ["Probe", selectedModel ? probeStatusLabel(selectedModel.probeStatus, lang) : "-"], ["Prompt", selectedPrompt], ["Tools", toolBundleSummary.label]];
  const toolBundlesLabel = lang === "zh"
    ? `${copy.createAgentToolBundles} · 已选 ${selectedToolBundleCount}`
    : `${copy.createAgentToolBundles} · ${selectedToolBundleCount} selected`;
  const availabilitySummary = lang === "zh"
    ? `已配密钥 ${credentialReadyCount}/${modelChoices.length} · 探测通过 ${probeOkCount}`
    : `Keyed ${credentialReadyCount}/${modelChoices.length} · probe ok ${probeOkCount}`;
  const providerSelectOptions = providerChoices.map((provider) => ({
    value: provider.id,
    label: provider.label,
    disabled: !provider.available,
    description: provider.available
      ? (lang === "zh" ? `${provider.availableCount} 个可尝试` : `${provider.availableCount} candidate(s)`)
      : (lang === "zh" ? "无密钥，不可探测" : "No credential"),
  }));
  const modelSelectOptions = providerModels.map((model) => ({
    value: model.modelId,
    // Keep credential-ready options selectable so they can be probed even before pass.
    disabled: !model.available || model.probeStatus === "probing",
    label: model.label,
    description: model.probeMessage || model.unavailableReason || probeStatusLabel(model.probeStatus, lang),
  }));

  const applyPreset = (preset: AgentCreatePreset) => {
    onApplyPreset(preset.draft);
    setActiveStep(1);
  };

  return (
    <section className={styles.createAgentPanel}>
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
            <div className={styles.avatarSection}>
              <div className={styles.avatarHeader}>
                <span>{copy.createAgentAvatar || (lang === "zh" ? "头像" : "Avatar")}</span>
                <small>
                  {draft.avatarImagePath
                    ? (lang === "zh" ? "图库指定" : "Library pick")
                    : (copy.createAgentAvatarDefault || (lang === "zh" ? "职责默认" : "Role default"))}
                </small>
              </div>
              <div className={styles.avatarPreviewRow}>
                <span className={styles.avatarPreview} aria-hidden="true">
                  {(() => {
                    const selected = (avatarOptions?.options ?? []).find((item) => item.path === draft.avatarImagePath);
                    const fallbackSession = (avatarOptions?.options ?? []).find((item) => item.filename.startsWith("01-session") || item.filename.includes("session-agent"));
                    const previewUrl = selected?.url || (!draft.avatarImagePath ? fallbackSession?.url : "") || "";
                    return previewUrl
                      ? <img src={previewUrl} alt="" />
                      : (draft.displayName.trim().slice(0, 2) || "AI");
                  })()}
                </span>
                <p className={styles.avatarHint}>
                  {copy.createAgentAvatarHint
                    || (lang === "zh"
                      ? "默认随职责选择头像；也可从图库指定。创建后仍可在 Agent 详情中修改。"
                      : "A role default is used unless you pick from the library. You can still change it later.")}
                </p>
                <VButton
                  type="button"
                  variant="secondary"
                  isDisabled={pending || !draft.avatarImagePath}
                  onPress={() => onDraftChange({ avatarImagePath: "" })}
                >
                  {copy.createAgentAvatarDefault || (lang === "zh" ? "使用职责默认" : "Use role default")}
                </VButton>
              </div>
              <div className={styles.avatarHeader}>
                <span>{copy.createAgentAvatarLibrary || (lang === "zh" ? "图库" : "Library")}</span>
                <small>{avatarOptions?.count ?? 0}</small>
              </div>
              {avatarOptionsPending ? (
                <p className={styles.availabilitySummary}>{copy.createAgentAvatarLoading || (lang === "zh" ? "正在加载头像库…" : "Loading avatar library…")}</p>
              ) : avatarOptions?.options?.length ? (
                <div className={styles.avatarOptionGrid} role="listbox" aria-label={copy.createAgentAvatarLibrary || (lang === "zh" ? "头像图库" : "Avatar library")}>
                  {avatarOptions.options.map((option) => {
                    const selected = option.path === draft.avatarImagePath;
                    return (
                      <VTooltip key={option.path} content={option.filename} width="compact">
                        <VNativeButton
                          type="button"
                          role="option"
                          aria-selected={selected}
                          className={selected ? `${styles.avatarOption} ${styles.avatarOptionSelected}` : styles.avatarOption}
                          disabled={pending}
                          onClick={() => onDraftChange({ avatarImagePath: option.path })}
                          aria-label={option.filename}
                        >
                          <img src={option.url} alt="" />
                        </VNativeButton>
                      </VTooltip>
                    );
                  })}
                </div>
              ) : (
                <p className={styles.availabilitySummary}>{copy.createAgentAvatarEmpty || (lang === "zh" ? "暂无可用头像文件，将使用职责默认。" : "No avatar files available; the role default will be used.")}</p>
              )}
            </div>
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
            {loadingOptions ? <div className={styles.loadingRows} aria-label={lang === "zh" ? "正在加载模型选项" : "Loading model options"} /> : null}
            {!loadingOptions && modelChoices.length ? (
              <p className={styles.availabilitySummary} aria-live="polite">{availabilitySummary}</p>
            ) : null}
            <VFieldRow label={lang === "zh" ? "服务商" : "Provider"} className="col-span-full">
              <CreateOptionSelect
                label={lang === "zh" ? "服务商" : "Provider"}
                value={selectedProviderId}
                disabled={!providerChoices.length || probeBusy}
                placeholder={lang === "zh" ? "选择服务商" : "Choose provider"}
                options={providerSelectOptions}
                onChange={(providerId) => {
                  const nextModelId = firstAvailableModelId(modelChoices, providerId)
                    || modelChoices.find((model) => model.providerId === providerId)?.modelId
                    || "";
                  onModelChange(nextModelId);
                }}
              />
            </VFieldRow>
            <VFieldRow label={copy.model} className="col-span-full">
              <CreateOptionSelect
                label={copy.model}
                value={selectedModelId}
                disabled={!providerModels.length || probeBusy}
                placeholder={lang === "zh" ? "选择模型" : "Choose model"}
                options={modelSelectOptions}
                onChange={onModelChange}
              />
            </VFieldRow>
            <div className={styles.probeActions}>
              <VButton
                type="button"
                variant="secondary"
                isDisabled={pending || probeBusy || !selectedModel?.available}
                onPress={() => onProbeSelected?.()}
              >
                {probeBusy && selectedModel?.probeStatus === "probing"
                  ? (lang === "zh" ? "正在探测…" : "Probing…")
                  : (lang === "zh" ? "探测当前模型" : "Probe selected")}
              </VButton>
              <VButton
                type="button"
                variant="secondary"
                isDisabled={pending || probeBusy || credentialReadyCount === 0}
                onPress={() => onProbeCredentialReady?.()}
              >
                {lang === "zh" ? `探测全部已配密钥（${credentialReadyCount}）` : `Probe all keyed (${credentialReadyCount})`}
              </VButton>
            </div>
            {probeSummary ? <p className={styles.availabilitySummary} aria-live="polite">{probeSummary}</p> : null}
            {selectedModel && !selectedModel.available ? (
              <p className={styles.errorText}>
                {lang === "zh"
                  ? `当前模型不可用${selectedModel.unavailableReason ? `：${selectedModel.unavailableReason}` : "。"}请选择已配密钥的模型，或先到配置页补齐 API Key。`
                  : `Selected model is unavailable${selectedModel.unavailableReason ? `: ${selectedModel.unavailableReason}` : "."} Choose a keyed model or configure the API key first.`}
              </p>
            ) : null}
            {selectedModel?.available && selectedModel.probeStatus === "idle" ? (
              <p className={styles.availabilitySummary}>
                {lang === "zh"
                  ? "已配密钥，但尚未探测连通性。请点击「探测当前模型」后再进入下一步。"
                  : "Credentials look ready, but connectivity is unprobed. Run a probe before continuing."}
              </p>
            ) : null}
            {selectedModel?.probeStatus === "fail" ? (
              <p className={styles.errorText}>
                {lang === "zh"
                  ? `探测失败${selectedModel.probeMessage ? `：${selectedModel.probeMessage}` : "。"}请换模型或检查密钥/网络。`
                  : `Probe failed${selectedModel.probeMessage ? `: ${selectedModel.probeMessage}` : "."} Switch model or check credentials/network.`}
              </p>
            ) : null}
            {selectedModel?.probeUsable ? (
              <p className={styles.successText}>
                {lang === "zh" ? "探测通过，可以使用该模型创建会话。" : "Probe passed. This model can be used to create the session."}
              </p>
            ) : null}
            {!loadingOptions && !modelChoices.length ? (
              <p className={styles.errorText}>
                {lang === "zh" ? "请先在模型库中配置至少一个可运行模型。" : "Configure at least one runtime model in the model library first."}
              </p>
            ) : null}
            {!loadingOptions && modelChoices.length > 0 && credentialReadyCount === 0 ? (
              <p className={styles.errorText}>
                {lang === "zh"
                  ? "已列出服务商，但当前没有已配密钥的模型。请先到配置页完成密钥。"
                  : "Providers are listed, but no credential-ready models exist. Configure API keys first."}
              </p>
            ) : null}
          </div>
        ) : null}

        {activeStep === 2 ? (
          <div className={styles.finalStepLayout}>
            <div className={styles.finalStepMain}>
              {loadingOptions ? <div className={styles.loadingRows} aria-label={lang === "zh" ? "正在加载提示词和工具" : "Loading prompts and tools"} /> : null}
              <VFieldRow label={copy.prompt}>
                <VNativeSelect value={draft.promptTemplateId} onChange={(event) => onDraftChange({ promptTemplateId: event.target.value })}>
                  <option value="">-</option>
                  {promptTemplateOptions.map((template) => <option key={template.value || template.label} value={template.value}>{template.label}</option>)}
                </VNativeSelect>
              </VFieldRow>
              <section className={styles.fieldWide}>
                <span className={styles.contextualHintRow}>
                  {toolBundlesLabel}
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
                      const bundleHint = [toolBundleMeta(bundle), bundle.description].filter(Boolean).join("\n") || bundle.label;
                      return (
                        <div key={bundle.bundleId} className={selected ? styles.createToolBundleSelected : styles.createToolBundleOption}>
                          <label>
                            <VNativeInput type="checkbox" checked={selected} onChange={(event) => onToolBundleToggle(bundle.bundleId, event.target.checked)} />
                            <strong>{bundle.label}</strong>
                          </label>
                          <VContextualHint
                            label={`${bundle.label} ${lang === "zh" ? "说明" : "details"}`}
                            content={bundleHint}
                            width="wide"
                          />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <VNativeInput value={draft.allowedTools} placeholder={copy.createAgentAllowedToolsPlaceholder} onChange={(event) => onDraftChange({ allowedTools: event.target.value })} />
                )}
              </section>
            </div>
            <section className={styles.createSummary} aria-label={summaryTitle}>
              <strong>{summaryTitle}</strong>
              <dl>{summaryItems.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            </section>
          </div>
        ) : null}
      </div>

      {optionsError ? <p className={styles.errorText}>{optionsError}</p> : null}
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
