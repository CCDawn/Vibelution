import { Check, ChevronDown, ChevronLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SessionLlmModelOption } from "../../api/types";
import { VButton } from "../vui";
import styles from "./ConversationModelSelector.styles";

type ConversationModelSelectorProps = {
  models: SessionLlmModelOption[];
  currentModelId: string;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onSelectionChange: (modelId: string, reasoningEffort: string) => void;
};

type Panel = "models" | "efforts" | null;

export function resolveConversationModelSelection(
  models: SessionLlmModelOption[],
  modelId: string,
  reasoningEffort: string,
) {
  const model = models.find((item) => item.modelId === modelId) ?? models[0];
  const values = model?.reasoningEffortValues ?? [];
  const effort = values.includes(reasoningEffort)
    ? reasoningEffort
    : values.includes(model?.defaultReasoningEffort ?? "")
      ? model?.defaultReasoningEffort ?? ""
      : values[0] ?? "";
  const effortOption = model?.reasoningEffortOptions?.find((item) => item.value === effort);
  return { model, effort, effortOption };
}

export function ConversationModelSelector({
  models,
  currentModelId,
  currentReasoningEffort,
  disabled,
  pending,
  onSelectionChange,
}: ConversationModelSelectorProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [candidateModelId, setCandidateModelId] = useState("");
  const current = useMemo(
    () => resolveConversationModelSelection(models, currentModelId, currentReasoningEffort),
    [currentModelId, currentReasoningEffort, models],
  );
  const candidate = useMemo(
    () => resolveConversationModelSelection(models, candidateModelId || current.model?.modelId || "", ""),
    [candidateModelId, current.model?.modelId, models],
  );

  useEffect(() => {
    if (!panel) {
      return;
    }
    function closeOnOutsidePointer(event: PointerEvent) {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setPanel(null);
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setPanel(null);
      }
    }
    window.addEventListener("pointerdown", closeOnOutsidePointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsidePointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [panel]);

  function chooseModel(model: SessionLlmModelOption) {
    const efforts = model.reasoningEffortValues ?? [];
    if (!efforts.length) {
      onSelectionChange(model.modelId, "");
      setPanel(null);
      return;
    }
    if (efforts.length === 1) {
      onSelectionChange(model.modelId, efforts[0]);
      setPanel(null);
      return;
    }
    setCandidateModelId(model.modelId);
    setPanel("efforts");
  }

  const controlsDisabled = disabled || pending || !models.length;
  return (
    <div ref={rootRef} className={styles.root} data-testid="conversation-llm-controls">
      <VButton
        type="button"
        className={styles.trigger}
        isDisabled={controlsDisabled}
        aria-expanded={panel === "models"}
        aria-haspopup="listbox"
        title={current.model?.label || current.model?.modelId || "Model"}
        onClick={() => setPanel((value) => value === "models" ? null : "models")}
      >
        <span className={styles.triggerLabel}>{current.model?.label || current.model?.modelId || "选择模型"}</span>
        <ChevronDown size={13} aria-hidden="true" />
      </VButton>
      {current.model?.reasoningEffortValues?.length ? (
        <VButton
          type="button"
          className={styles.trigger}
          isDisabled={controlsDisabled}
          aria-expanded={panel === "efforts"}
          aria-haspopup="listbox"
          title={current.effortOption?.description || current.effortOption?.label || current.effort}
          onClick={() => {
            setCandidateModelId(current.model?.modelId || "");
            setPanel((value) => value === "efforts" ? null : "efforts");
          }}
        >
          <span className={styles.triggerLabel}>{current.effortOption?.label || current.effort}</span>
          <ChevronDown size={13} aria-hidden="true" />
        </VButton>
      ) : null}
      {panel ? (
        <div className={styles.panel} role="dialog" aria-label={panel === "models" ? "选择模型" : "选择推理强度"}>
          <div className={styles.panelHeader}>
            {panel === "efforts" ? (
              <VButton type="button" className={styles.backButton} onClick={() => setPanel("models")} aria-label="返回模型列表">
                <ChevronLeft size={15} aria-hidden="true" />
              </VButton>
            ) : <span />}
            <strong>{panel === "models" ? "选择模型与推理强度" : `${candidate.model?.label || "模型"} · 推理强度`}</strong>
            <span />
          </div>
          <div className={styles.list} role="listbox">
            {panel === "models" ? models.map((model) => {
              const unavailable = model.missingApiKey;
              return (
                <VButton
                  key={model.modelId}
                  type="button"
                  className={`${styles.option} ${unavailable ? styles.unavailable : ""}`}
                  isDisabled={unavailable}
                  role="option"
                  aria-selected={model.modelId === current.model?.modelId}
                  onClick={() => chooseModel(model)}
                >
                  <span className={styles.optionCopy}>
                    <span className={styles.optionTitle}>
                      <span>{model.label || model.model}</span>
                      {model.isDefault ? <span className={styles.badge}>默认</span> : null}
                    </span>
                    <span className={styles.optionMeta}>
                      {[model.providerLabel || model.providerId, unavailable ? "未配置 API Key" : model.model].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  {model.modelId === current.model?.modelId ? <Check className={styles.check} size={15} aria-hidden="true" /> : null}
                </VButton>
              );
            }) : candidate.model?.reasoningEffortOptions?.map((effort) => (
              <VButton
                key={effort.value}
                type="button"
                className={styles.option}
                role="option"
                aria-selected={candidate.model?.modelId === current.model?.modelId && effort.value === current.effort}
                onClick={() => {
                  onSelectionChange(candidate.model?.modelId || "", effort.value);
                  setPanel(null);
                }}
              >
                <span className={styles.optionCopy}>
                  <span className={styles.optionTitle}>
                    <span>{effort.label || effort.value}</span>
                    {effort.value === candidate.model?.defaultReasoningEffort ? <span className={styles.badge}>默认</span> : null}
                  </span>
                  <span className={styles.optionMeta}>{effort.description}</span>
                </span>
                {candidate.model?.modelId === current.model?.modelId && effort.value === current.effort ? <Check className={styles.check} size={15} aria-hidden="true" /> : null}
              </VButton>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
