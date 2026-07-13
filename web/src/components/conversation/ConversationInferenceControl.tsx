import { Check, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SessionLlmModelOption } from "../../api/types";
import { VButton } from "../vui";
import styles from "./ConversationInferenceControl.styles";

type ConversationInferenceControlProps = {
  model: SessionLlmModelOption | null;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onReasoningEffortChange: (reasoningEffort: string) => void;
};

export function resolveConversationInferenceEffort(
  model: SessionLlmModelOption | null,
  reasoningEffort: string,
) {
  const values = model?.reasoningEffortValues ?? [];
  const effort = values.includes(reasoningEffort)
    ? reasoningEffort
    : values.includes(model?.defaultReasoningEffort ?? "")
      ? model?.defaultReasoningEffort ?? ""
      : values[0] ?? "";
  return {
    effort,
    option: model?.reasoningEffortOptions?.find((item) => item.value === effort),
  };
}

export function ConversationInferenceControl({
  model,
  currentReasoningEffort,
  disabled,
  pending,
  onReasoningEffortChange,
}: ConversationInferenceControlProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const current = useMemo(
    () => resolveConversationInferenceEffort(model, currentReasoningEffort),
    [currentReasoningEffort, model],
  );

  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        requestAnimationFrame(() => triggerRef.current?.focus());
      }
    }
    window.addEventListener("pointerdown", closeOnOutsidePointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsidePointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  if (!model) return null;
  if (!model.reasoningEffortValues?.length) {
    return <span className={styles.fixedLabel}>{model.label || model.model}</span>;
  }

  return (
    <div ref={rootRef} className={styles.root} data-testid="conversation-inference-control">
      <VButton
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        isDisabled={disabled || pending}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`${model.label || model.model} · ${current.option?.label || current.effort}`}
        onPress={() => setOpen((value) => !value)}
      >
        <span className={styles.triggerModel}>{model.label || model.model}</span>
        <span className={styles.triggerEffort}>{current.option?.label || current.effort}</span>
        <ChevronDown size={13} aria-hidden="true" />
      </VButton>
      {open ? (
        <div role="listbox" className={styles.menu} aria-label="选择推理强度">
          {model.reasoningEffortOptions.map((option) => (
            <VButton
              key={option.value}
              type="button"
              className={styles.option}
              role="option"
              aria-selected={option.value === current.effort}
              onPress={() => {
                onReasoningEffortChange(option.value);
                setOpen(false);
                requestAnimationFrame(() => triggerRef.current?.focus());
              }}
            >
              <span className={styles.optionCopy}>
                <span className={styles.optionLabel}>{option.label || option.value}</span>
                <small className={styles.optionDescription}>{option.description}</small>
              </span>
              {option.value === current.effort ? <Check className={styles.check} size={15} aria-hidden="true" /> : null}
            </VButton>
          ))}
        </div>
      ) : null}
    </div>
  );
}
