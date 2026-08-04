import { Check, ChevronDown } from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
} from "react";

import type { SessionLlmModelOption } from "../../api/types";
import { VButton, VPopover } from "../vui";
import styles from "./ConversationInferenceControl.styles";

type ConversationInferenceControlProps = {
  model: SessionLlmModelOption | null;
  /** Active session id — menu closes when this changes after a session switch. */
  sessionId?: string | null;
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
  sessionId = "",
  currentReasoningEffort,
  disabled,
  pending,
  onReasoningEffortChange,
}: ConversationInferenceControlProps) {
  const [open, setOpen] = useState(false);
  const current = useMemo(
    () => resolveConversationInferenceEffort(model, currentReasoningEffort),
    [currentReasoningEffort, model],
  );

  // Avoid applying effort clicks from a menu opened on a previous session.
  useEffect(() => {
    setOpen((wasOpen) => (wasOpen ? false : wasOpen));
  }, [sessionId, model?.modelRef, model?.modelId]);

  useEffect(() => {
    if (disabled || pending) {
      setOpen(false);
    }
  }, [disabled, pending]);

  if (!model) return null;
  if (!model.reasoningEffortValues?.length) {
    return <span className={styles.fixedLabel}>{model.label || model.model}</span>;
  }

  return (
    <div className={styles.root} data-testid="conversation-inference-control">
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (disabled || pending) {
            setOpen(false);
            return;
          }
          setOpen(nextOpen);
        }}
        side="top"
        align="end"
        sideOffset={6}
        aria-label="选择推理强度"
        contentClassName={styles.menu}
        data-vui="conversation-inference-menu"
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.trigger}
            isDisabled={disabled || pending}
            aria-haspopup="listbox"
            aria-expanded={open}
            data-open={open ? "true" : "false"}
            title={`${model.label || model.model} · ${current.option?.label || current.effort}`}
          >
            <span className={styles.triggerModel}>{model.label || model.model}</span>
            <span className={styles.triggerSeparator} aria-hidden="true">·</span>
            <span className={styles.triggerEffort}>{current.option?.label || current.effort}</span>
            <ChevronDown className={styles.triggerChevron} data-open={open ? "true" : "false"} size={12} aria-hidden="true" />
          </VButton>
        )}
      >
        <div
          role="listbox"
          aria-label="选择推理强度"
          data-testid="conversation-inference-menu"
        >
          {model.reasoningEffortOptions.map((option) => {
            const selected = option.value === current.effort;
            return (
              <VButton
                key={option.value}
                type="button"
                contentLayout="plain"
                className={styles.option}
                role="option"
                aria-selected={selected}
                data-selected={selected ? "true" : "false"}
                onPress={() => {
                  onReasoningEffortChange(option.value);
                  setOpen(false);
                }}
              >
                <span className={styles.optionCopy}>
                  <span className={styles.optionLabel}>{option.label || option.value}</span>
                  {option.description ? (
                    <small className={styles.optionDescription}>{option.description}</small>
                  ) : null}
                </span>
                {selected
                  ? <Check className={styles.check} size={14} aria-hidden="true" />
                  : <span className={styles.checkSlot} aria-hidden="true" />}
              </VButton>
            );
          })}
        </div>
      </VPopover>
    </div>
  );
}
