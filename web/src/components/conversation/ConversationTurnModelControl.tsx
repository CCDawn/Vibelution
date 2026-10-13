import { Bot, Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { SessionLlmModelOption } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { VButton, VIconButton, VInput, VPopover, VSelect } from "../vui";
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
  const label = error
    ? (zh ? "模型读取失败" : "Model unavailable")
    : loading
      ? (zh ? "读取模型…" : "Loading model…")
      : model?.label || model?.model || model?.modelRef || model?.modelId || (zh ? "未绑定模型" : "No model bound");
  const supportedEfforts = model?.reasoningEffortValues ?? [];
  const normalizedEffort = supportedEfforts.includes(currentReasoningEffort)
    ? currentReasoningEffort
    : supportedEfforts.includes(model?.defaultReasoningEffort ?? "")
      ? model?.defaultReasoningEffort ?? ""
      : supportedEfforts[0] ?? "";
  const effectiveEffort = normalizedEffort || currentReasoningEffort;
  const effortOptions = supportedEfforts.map((value) => ({
    id: value,
    label: model?.reasoningEffortOptions?.find((option) => option.value === value)?.label || value,
  }));
  const maximumLabel = maxContextWindow > 0
    ? maxContextWindow.toLocaleString(zh ? "zh-CN" : "en-US")
    : "";
  const contextValidation = validateModelContextWindow(contextWindowDraft, maxContextWindow, lang);
  const parsedContextWindow = contextValidation.value;
  const contextWindowValid = contextValidation.valid;
  const contextWindowError = dirty ? contextValidation.error : "";
  const reasoningEffortValid = supportedEfforts.length === 0
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
      setDirty(false);
    }
  }, [contextWindow, contextWindowDraft, dirty, effectiveEffort, reasoningEffortDraft]);

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
          setOpen(nextOpen);
        }}
        side="top"
        align="end"
        sideOffset={6}
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
            aria-label={`${zh ? "Agent 模型" : "Agent model"}: ${label}`}
            aria-busy={loading || pending || undefined}
            data-open={open ? "true" : "false"}
            title={label}
          >
            <Bot className={styles.icon} size={12} aria-hidden="true" />
            <span className={styles.label}>{label}</span>
            <SlidersHorizontal className={styles.settingsIcon} size={12} aria-hidden="true" />
          </VButton>
        )}
      >
        <div className={styles.fields} data-testid="conversation-model-parameters-panel">
          <label className={styles.field}>
            <span className={styles.fieldHeader}>
              <span>{zh ? "上下文上限" : "Context window"}</span>
              {maximumLabel ? <span className={styles.fieldLimit}>{zh ? `最大 ${maximumLabel}` : `Max ${maximumLabel}`}</span> : null}
            </span>
            <span className={styles.inputRow}>
              <VInput
                type="number"
                min={1}
                max={maxContextWindow || undefined}
                step={1}
                required
                value={contextWindowDraft}
                disabled={pending}
                aria-label={zh ? "上下文上限" : "Context window"}
                aria-invalid={Boolean(contextWindowError)}
                aria-describedby={contextWindowError ? contextWindowErrorId : undefined}
                data-vui="model-context-window-input"
                onChange={(event) => {
                  setContextWindowDraft(event.target.value);
                  setDirty(true);
                }}
              />
              <span className={styles.unit}>tokens</span>
            </span>
            {contextWindowError ? (
              <span id={contextWindowErrorId} className={styles.error} role="alert">
                {contextWindowError}
              </span>
            ) : null}
          </label>
          {effortOptions.length ? (
            <label className={styles.field}>
              <span className={styles.fieldHeader}>{zh ? "思考强度" : "Reasoning effort"}</span>
              <VSelect
                options={effortOptions}
                selectedKey={reasoningEffortDraft || effectiveEffort}
                isDisabled={pending}
                aria-label={zh ? "思考强度" : "Reasoning effort"}
                data-vui="model-reasoning-effort-select"
                onSelectionChange={(key) => {
                  if (key === null) return;
                  setReasoningEffortDraft(String(key));
                  setDirty(true);
                }}
              />
            </label>
          ) : null}
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
                  reasoningEffort: reasoningEffortDraft || effectiveEffort,
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
