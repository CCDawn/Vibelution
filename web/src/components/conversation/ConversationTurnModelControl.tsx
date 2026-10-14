import { Bot, Layers, RotateCcw, Save, SlidersHorizontal, Zap } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import type { SessionLlmModelOption } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { VButton, VIconButton, VInput, VNativeInput, VPopover } from "../vui";
import styles from "./ConversationTurnModelControl.styles";

export type ConversationModelParameters = {
  contextWindow: number;
  reasoningEffort: string;
};

export function validateModelContextWindow(value: string, maximum: number, lang: "zh" | "en") {
  const parsed = Number(value);
  if (value.trim() === "" || !Number.isSafeInteger(parsed) || parsed <= 0) {
    return { value: parsed, valid: false, error: lang === "zh" ? "请输入正整数" : "Enter a positive integer" };
  }
  if (parsed > maximum) {
    const maximumLabel = maximum.toLocaleString(lang === "zh" ? "zh-CN" : "en-US");
    return {
      value: parsed,
      valid: false,
      error: lang === "zh" ? `不能超过 ${maximumLabel}` : `Must not exceed ${maximumLabel}`,
    };
  }
  return { value: parsed, valid: true, error: "" };
}

const MODEL_NAME_SEPARATOR = /^[\s·•\u00b7\-/|:：,，]+/;

function modelNames(model: SessionLlmModelOption) {
  const fullName = model.label.trim() || model.model.trim() || model.modelRef.trim() || model.modelId.trim();
  const provider = model.providerLabel.trim();
  if (provider && fullName.toLocaleLowerCase().startsWith(provider.toLocaleLowerCase())) {
    const modelName = fullName.slice(provider.length).replace(MODEL_NAME_SEPARATOR, "").trim();
    if (modelName) return { fullName, shortName: modelName };
  }
  const upstream = model.model.trim() || model.modelId.trim() || model.modelRef.trim();
  return { fullName, shortName: upstream || fullName };
}

function modelContextStops(maximum: number, custom: number) {
  if (!Number.isSafeInteger(maximum) || maximum <= 0) return [];
  return [...new Set([
    ...[8_000, 16_000, 32_000, 64_000, 128_000, 256_000, 512_000, 1_000_000, 2_000_000]
      .filter((value) => value < maximum),
    maximum,
    ...(Number.isSafeInteger(custom) && custom > 0 && custom <= maximum ? [custom] : []),
  ])].sort((a, b) => a - b);
}

type ConversationTurnModelControlProps = {
  /** The current Agent-bound dialogue model; this control never accepts model choices. */
  sessionId: string;
  agentId?: string;
  configRevision?: number;
  model: SessionLlmModelOption | null;
  contextWindow?: number;
  maxContextWindow?: number;
  currentReasoningEffort: string;
  loading?: boolean;
  error?: boolean;
  pending?: boolean;
  errorMessage?: string;
  onSave: (parameters: ConversationModelParameters) => void;
};

export function ConversationTurnModelControl({
  sessionId,
  agentId = "",
  configRevision,
  model,
  contextWindow = 0,
  maxContextWindow = 0,
  currentReasoningEffort,
  loading = false,
  error = false,
  pending = false,
  errorMessage = "",
  onSave,
}: ConversationTurnModelControlProps) {
  const { lang } = useAppI18n({ domains: ["chat"] });
  const contextWindowErrorId = useId();
  const zh = lang === "zh";
  const [open, setOpen] = useState(false);
  const [contextWindowDraft, setContextWindowDraft] = useState(String(contextWindow || ""));
  const [reasoningEffortDraft, setReasoningEffortDraft] = useState(currentReasoningEffort);
  const [dirty, setDirty] = useState(false);
  const [editingContext, setEditingContext] = useState(false);
  const [editingContextStart, setEditingContextStart] = useState(contextWindow);
  const [contextStops, setContextStops] = useState(() => modelContextStops(maxContextWindow, contextWindow));
  const cancelledNumberEditRef = useRef(false);
  const previousPendingRef = useRef(pending);
  const statusLabel = error
    ? (zh ? "模型读取失败" : "Model unavailable")
    : loading
      ? (zh ? "读取模型…" : "Loading model…")
      : "";
  const names = model ? modelNames(model) : { fullName: "", shortName: "" };
  const fullName = statusLabel || names.fullName || (zh ? "未绑定模型" : "No model bound");
  const shortName = statusLabel || names.shortName || fullName;
  const supportedEfforts = model?.reasoningEffortValues ?? [];
  const normalizedEffort = supportedEfforts.includes(currentReasoningEffort)
    ? currentReasoningEffort
    : "";
  const effectiveEffort = normalizedEffort;
  const effortOptions = supportedEfforts.map((value) => ({
    id: value,
    label: value,
  }));
  const contextValidation = validateModelContextWindow(contextWindowDraft, maxContextWindow, lang);
  const parsedContextWindow = contextValidation.value;
  const contextWindowValid = contextValidation.valid;
  const contextWindowError = dirty ? contextValidation.error : "";
  const visibleContextStops = [...new Set([
    ...contextStops.filter((value) => value > 0 && value <= maxContextWindow),
    ...(maxContextWindow > 0 ? [maxContextWindow] : []),
  ])].sort((a, b) => a - b);
  const sliderContextWindow = editingContext ? editingContextStart : (contextWindowValid ? parsedContextWindow : contextWindow);
  const contextIndex = Math.max(0, visibleContextStops.indexOf(sliderContextWindow));
  const effortIndex = Math.max(0, supportedEfforts.indexOf(reasoningEffortDraft || model?.defaultReasoningEffort || ""));
  const effortLabel = reasoningEffortDraft ? (effortOptions[effortIndex]?.label || reasoningEffortDraft) : (zh ? "默认" : "Default");
  const displayContext = sliderContextWindow % 1_000 === 0
    ? `${sliderContextWindow / 1_000}K`
    : sliderContextWindow.toLocaleString(zh ? "zh-CN" : "en-US");
  const reasoningEffortValid = supportedEfforts.length === 0
    || reasoningEffortDraft === ""
    || supportedEfforts.includes(reasoningEffortDraft);
  const canConfigure = Boolean(
    agentId
      && model?.modelRef
      && configRevision !== undefined
      && Number.isSafeInteger(contextWindow)
      && contextWindow > 0
      && Number.isSafeInteger(maxContextWindow)
      && maxContextWindow >= contextWindow,
  );
  const saveDisabled = !canConfigure
    || pending
    || !contextWindowValid
    || !reasoningEffortValid
    || (parsedContextWindow === contextWindow && reasoningEffortDraft === effectiveEffort);

  useEffect(() => {
    setOpen(false);
    setContextWindowDraft(String(contextWindow || ""));
    setReasoningEffortDraft(effectiveEffort);
    setDirty(false);
    setEditingContext(false);
    setContextStops(modelContextStops(maxContextWindow, contextWindow));
    cancelledNumberEditRef.current = false;
  // Identity changes start a new Agent/model editing scope. Revision refreshes
  // are intentionally excluded so an optimistic user's draft survives 409s.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, model?.modelRef, sessionId]);

  useEffect(() => {
    if (
      !dirty
      || (Number(contextWindowDraft) === contextWindow && reasoningEffortDraft === effectiveEffort)
    ) {
      setContextWindowDraft(String(contextWindow || ""));
      setReasoningEffortDraft(effectiveEffort);
      setContextStops(modelContextStops(maxContextWindow, contextWindow));
      setDirty(false);
    }
  }, [contextWindow, maxContextWindow, contextWindowDraft, dirty, effectiveEffort, reasoningEffortDraft]);

  useEffect(() => {
    const saved = previousPendingRef.current && !pending && !errorMessage;
    previousPendingRef.current = pending;
    if (saved) {
      setContextWindowDraft(String(contextWindow || ""));
      setReasoningEffortDraft(effectiveEffort);
      setContextStops(modelContextStops(maxContextWindow, contextWindow));
      setEditingContext(false);
      setDirty(false);
    }
  }, [pending, errorMessage, contextWindow, maxContextWindow, effectiveEffort]);

  function commitContextNumber() {
    if (pending || cancelledNumberEditRef.current || !contextWindowValid) return;
    setContextStops((current) => [...new Set([...current, parsedContextWindow])].sort((a, b) => a - b));
    setEditingContext(false);
  }

  return (
    <div className={styles.root} data-testid="conversation-turn-model-control" data-vui="conversation-agent-model-display">
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (!canConfigure) {
            setOpen(false);
            return;
          }
          if (pending) return;
          if (nextOpen && !open) {
            setContextStops(modelContextStops(maxContextWindow, contextWindowValid ? parsedContextWindow : contextWindow));
            setEditingContext(false);
          }
          setOpen(nextOpen);
        }}
        side="top"
        align="end"
        sideOffset={6}
        onEscapeKeyDown={(event) => {
          if (!editingContext) return;
          event.preventDefault();
          cancelledNumberEditRef.current = true;
          setContextWindowDraft(String(editingContextStart));
          setEditingContext(false);
        }}
        aria-label={zh ? "模型参数" : "Model settings"}
        contentClassName={styles.popover}
        data-vui="conversation-model-parameters"
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.trigger}
            isDisabled={!canConfigure || loading || error || pending}
            aria-haspopup="dialog"
            aria-expanded={open}
            aria-label={`${zh ? "Agent 模型" : "Agent model"}: ${fullName}`}
            aria-busy={loading || pending || undefined}
            data-open={open ? "true" : "false"}
            title={fullName}
          >
            <Bot className={styles.icon} size={12} aria-hidden="true" />
            <span className={styles.label}>{shortName}</span>
            <SlidersHorizontal className={styles.settingsIcon} size={12} aria-hidden="true" />
          </VButton>
        )}
      >
        <div className={styles.fields} data-testid="conversation-model-parameters-panel">
          <p className={styles.fullName} data-testid="conversation-model-full-name">{fullName}</p>
          {effortOptions.length ? (
            <div className={styles.field}>
              <div className={styles.fieldHeader}>
                <Zap className={styles.fieldIcon} size={14} aria-hidden="true" />
                <output className={styles.fieldValue} aria-label={zh ? "当前思考强度" : "Current reasoning effort"}>{effortLabel}</output>
                <VIconButton
                  label={zh ? "恢复默认思考强度" : "Reset reasoning effort to default"}
                  variant="ghost"
                  className={styles.resetButton}
                  icon={<RotateCcw size={15} aria-hidden="true" />}
                  isDisabled={pending || !reasoningEffortDraft}
                  onPress={() => { setReasoningEffortDraft(""); setDirty(true); }}
                />
              </div>
              <VNativeInput
                type="range"
                rangeVariant="capsule"
                rangeTickCount={effortOptions.length}
                min={0}
                max={Math.max(1, effortOptions.length - 1)}
                step={1}
                value={effortIndex}
                disabled={pending || effortOptions.length < 2}
                aria-label={zh ? "思考强度" : "Reasoning effort"}
                aria-valuetext={effortLabel}
                data-vui="model-reasoning-effort-slider"
                onChange={(event) => {
                  setReasoningEffortDraft(supportedEfforts[Number(event.target.value)]);
                  setDirty(true);
                }}
              />
            </div>
          ) : null}
          <div className={styles.field}>
            <div className={styles.fieldHeader}>
              <Layers className={styles.fieldIcon} size={14} aria-hidden="true" />
              {editingContext ? (
                <VInput
                  type="number"
                  min={1}
                  max={maxContextWindow || undefined}
                  step={1}
                  required
                  autoFocus
                  className={styles.numberInput}
                  value={contextWindowDraft}
                  disabled={pending}
                  aria-label={zh ? "精确上下文大小" : "Exact context window"}
                  aria-invalid={Boolean(contextWindowError)}
                  aria-describedby={contextWindowError ? contextWindowErrorId : undefined}
                  data-vui="model-context-window-input"
                  onChange={(event) => { setContextWindowDraft(event.target.value); setDirty(true); }}
                  onBlur={commitContextNumber}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") { event.preventDefault(); commitContextNumber(); }
                  }}
                />
              ) : (
                <VButton
                  type="button"
                  variant="ghost"
                  contentLayout="plain"
                  className={styles.numberTrigger}
                  aria-label={zh ? `精确设置上下文，当前 ${sliderContextWindow} tokens` : `Set exact context window, currently ${sliderContextWindow} tokens`}
                  isDisabled={pending}
                  onPress={() => { cancelledNumberEditRef.current = false; setEditingContextStart(sliderContextWindow); setEditingContext(true); }}
                >
                  {displayContext}
                </VButton>
              )}
              <VIconButton
                label={zh ? "恢复模型上下文上限" : "Reset context window to model limit"}
                variant="ghost"
                className={styles.resetButton}
                icon={<RotateCcw size={15} aria-hidden="true" />}
                isDisabled={pending || (contextWindowValid && parsedContextWindow === maxContextWindow)}
                onPress={() => { setContextWindowDraft(String(maxContextWindow)); setEditingContext(false); setDirty(true); }}
              />
            </div>
            <span className={styles.fieldCaption}>{zh ? "上下文上限" : "Context window"}</span>
            <VNativeInput
              type="range"
              rangeVariant="capsule"
              rangeTickCount={visibleContextStops.length}
              min={0}
              max={Math.max(1, visibleContextStops.length - 1)}
              step={1}
              value={contextIndex}
              disabled={pending || visibleContextStops.length < 2}
              aria-label={zh ? "上下文大小" : "Context window"}
              aria-valuetext={`${sliderContextWindow.toLocaleString(zh ? "zh-CN" : "en-US")} tokens`}
              data-vui="model-context-window-slider"
              onChange={(event) => { setContextWindowDraft(String(visibleContextStops[Number(event.target.value)])); setEditingContext(false); setDirty(true); }}
            />
            {contextWindowError ? <span id={contextWindowErrorId} className={styles.error} role="alert">{contextWindowError}</span> : null}
          </div>
          {errorMessage ? <p className={styles.error} role="alert">{errorMessage}</p> : null}
          <div className={styles.actions}>
            <VIconButton
              type="button"
              label={zh ? "保存模型参数" : "Save model settings"}
              title={zh ? "保存" : "Save"}
              variant="ghost"
              className={styles.saveButton}
              icon={<Save size={14} aria-hidden="true" />}
              isPending={pending}
              isDisabled={saveDisabled}
              onPress={() => {
                if (saveDisabled) return;
                onSave({
                  contextWindow: parsedContextWindow,
                  reasoningEffort: reasoningEffortDraft,
                });
              }}
              data-testid="conversation-model-parameters-save"
            />
          </div>
        </div>
      </VPopover>
    </div>
  );
}
