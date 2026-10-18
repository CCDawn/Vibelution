import { RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { VButton, VDialog, VIconButton, VNativeInput } from "../../components/vui";
import styles from "./ChatComposerBudgetDialog.styles";

/** Server validation domain for per-turn tool-call quota. */
export const SESSION_BUDGET_MAX_CALLS_LIMITS = { min: 1, max: 200 } as const;
/** Server validation domain for the thinking budget, in characters. */
export const SESSION_BUDGET_THINKING_CHARS_LIMITS = { min: 50, max: 4000 } as const;

/** PATCH payload the dialog hands to the workbench mutation. */
export type ChatComposerBudgetParametersPatch = {
  revision: number;
  maxCallsPerTurn: number | null;
  thinkingBudgetChars: number | null;
};

export type ChatComposerBudgetDialogLabels = {
  composerBudgetTitle: string;
  composerBudgetDescription: string;
  composerBudgetMaxCallsLabel: string;
  composerBudgetMaxCallsPlaceholder: string;
  composerBudgetClearMaxCalls: string;
  composerBudgetThinkingLabel: string;
  composerBudgetThinkingPlaceholder: string;
  composerBudgetClearThinking: string;
  composerBudgetSave: string;
  composerBudgetCancel: string;
  composerBudgetLoading: string;
  composerBudgetLoadFailed: string;
};

/** Workbench-injected budget control state; presence gates the plus-menu entry. */
export type ChatComposerBudgetControl = {
  sessionId: string;
  /** Server revision guard; saves are blocked until it is known. */
  revision?: number;
  maxCallsPerTurn: number | null;
  thinkingBudgetChars: number | null;
  loading?: boolean;
  error?: boolean;
  pending?: boolean;
  errorMessage?: string;
  onSave: (parameters: ChatComposerBudgetParametersPatch) => void;
};

/**
 * Shared draft validation: an empty draft is valid and means "clear to null"
 * (back to defaults); otherwise the value must be a safe integer inside
 * [minimum, maximum], mirroring the server's 422 domain.
 */
export function validateSessionBudgetField(
  value: string,
  limits: { min: number; max: number },
  lang: "zh" | "en",
): { value: number | null; valid: boolean; error: string } {
  const trimmed = value.trim();
  if (trimmed === "") {
    return { value: null, valid: true, error: "" };
  }
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed)) {
    return { value: null, valid: false, error: lang === "zh" ? "请输入整数" : "Enter a whole number" };
  }
  if (parsed < limits.min) {
    return {
      value: parsed,
      valid: false,
      error: lang === "zh" ? `不能小于 ${limits.min}` : `Must be at least ${limits.min}`,
    };
  }
  if (parsed > limits.max) {
    return {
      value: parsed,
      valid: false,
      error: lang === "zh" ? `不能超过 ${limits.max}` : `Must not exceed ${limits.max}`,
    };
  }
  return { value: parsed, valid: true, error: "" };
}

type ChatComposerBudgetDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lang: "zh" | "en";
  labels: ChatComposerBudgetDialogLabels;
  /** Draft scope resets when the session identity changes. */
  sessionId: string;
  /** Server revision guard; saves are blocked until it is known. */
  revision?: number;
  maxCallsPerTurn: number | null;
  thinkingBudgetChars: number | null;
  loading?: boolean;
  error?: boolean;
  pending?: boolean;
  errorMessage?: string;
  onSave: (parameters: ChatComposerBudgetParametersPatch) => void;
};

/**
 * Composer "budget and quota" dialog: per-session tool-call quota and thinking
 * budget with explicit draft + save semantics, modeled on
 * ConversationTurnModelControl (draft survives revision refreshes / 409s;
 * a settled successful save re-syncs the drafts from the server truth).
 */
export function ChatComposerBudgetDialog({
  open,
  onOpenChange,
  lang,
  labels,
  sessionId,
  revision,
  maxCallsPerTurn,
  thinkingBudgetChars,
  loading = false,
  error = false,
  pending = false,
  errorMessage = "",
  onSave,
}: ChatComposerBudgetDialogProps) {
  const [maxCallsDraft, setMaxCallsDraft] = useState(() => budgetDraft(maxCallsPerTurn));
  const [thinkingDraft, setThinkingDraft] = useState(() => budgetDraft(thinkingBudgetChars));
  const [dirty, setDirty] = useState(false);
  const previousPendingRef = useRef(pending);

  const maxCallsValidation = validateSessionBudgetField(maxCallsDraft, SESSION_BUDGET_MAX_CALLS_LIMITS, lang);
  const thinkingValidation = validateSessionBudgetField(thinkingDraft, SESSION_BUDGET_THINKING_CHARS_LIMITS, lang);
  const maxCallsError = dirty ? maxCallsValidation.error : "";
  const thinkingError = dirty ? thinkingValidation.error : "";
  const valuesChanged = (
    maxCallsValidation.value !== (maxCallsPerTurn ?? null)
    || thinkingValidation.value !== (thinkingBudgetChars ?? null)
  );
  const saveDisabled = Boolean(
    pending
      || loading
      || error
      || revision === undefined
      || !maxCallsValidation.valid
      || !thinkingValidation.valid
      || !valuesChanged,
  );

  function resetDraft() {
    setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
    setThinkingDraft(budgetDraft(thinkingBudgetChars));
    setDirty(false);
  }

  useEffect(() => {
    setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
    setThinkingDraft(budgetDraft(thinkingBudgetChars));
    setDirty(false);
  // Identity change starts a new editing scope. Revision refreshes are
  // intentionally excluded so an optimistic operator's draft survives 409s.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (
      !dirty
      || (
        maxCallsValidation.value === (maxCallsPerTurn ?? null)
        && thinkingValidation.value === (thinkingBudgetChars ?? null)
      )
    ) {
      setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
      setThinkingDraft(budgetDraft(thinkingBudgetChars));
      setDirty(false);
    }
  // Validation results are derived from the drafts; recompute inline instead
  // of depending on unstable derived objects.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxCallsPerTurn, thinkingBudgetChars, maxCallsDraft, thinkingDraft, dirty]);

  useEffect(() => {
    const saved = previousPendingRef.current && !pending && !errorMessage;
    previousPendingRef.current = pending;
    if (saved) {
      setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
      setThinkingDraft(budgetDraft(thinkingBudgetChars));
      setDirty(false);
    }
  }, [pending, errorMessage, maxCallsPerTurn, thinkingBudgetChars]);

  return (
    <VDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !pending) {
          resetDraft();
        }
        onOpenChange(nextOpen);
      }}
      title={labels.composerBudgetTitle}
      description={labels.composerBudgetDescription}
      size="md"
      data-vui="chat-composer-budget-dialog"
      footer={(
        <>
          <VButton
            type="button"
            variant="secondary"
            isDisabled={pending}
            onPress={() => onOpenChange(false)}
          >
            {labels.composerBudgetCancel}
          </VButton>
          <VButton
            type="button"
            variant="primary"
            isPending={pending}
            isDisabled={saveDisabled}
            data-testid="chat-composer-budget-save"
            onPress={() => {
              if (saveDisabled || revision === undefined) {
                return;
              }
              onSave({
                revision,
                maxCallsPerTurn: maxCallsValidation.value,
                thinkingBudgetChars: thinkingValidation.value,
              });
            }}
          >
            {labels.composerBudgetSave}
          </VButton>
        </>
      )}
    >
      <div className={styles.body} data-testid="chat-composer-budget-dialog-body">
        {loading ? <p className={styles.statusLine}>{labels.composerBudgetLoading}</p> : null}
        {error ? <p className={styles.error} role="alert">{labels.composerBudgetLoadFailed}</p> : null}
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="chat-composer-budget-max-calls">
            {labels.composerBudgetMaxCallsLabel}
          </label>
          <div className={styles.fieldRow}>
            <VNativeInput
              id="chat-composer-budget-max-calls"
              className={styles.fieldInput}
              type="number"
              inputMode="numeric"
              min={SESSION_BUDGET_MAX_CALLS_LIMITS.min}
              max={SESSION_BUDGET_MAX_CALLS_LIMITS.max}
              step={1}
              placeholder={labels.composerBudgetMaxCallsPlaceholder}
              aria-label={labels.composerBudgetMaxCallsLabel}
              aria-invalid={Boolean(maxCallsError)}
              disabled={pending || loading || error}
              data-vui="chat-composer-budget-max-calls-input"
              value={maxCallsDraft}
              onChange={(event) => {
                setMaxCallsDraft(event.target.value);
                setDirty(true);
              }}
            />
            <VIconButton
              label={labels.composerBudgetClearMaxCalls}
              variant="ghost"
              className={styles.clearButton}
              icon={<RotateCcw size={15} aria-hidden="true" />}
              isDisabled={pending || loading || error || maxCallsDraft.trim() === ""}
              onPress={() => {
                setMaxCallsDraft("");
                setDirty(true);
              }}
            />
          </div>
          {maxCallsError ? <span className={styles.error} role="alert">{maxCallsError}</span> : null}
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="chat-composer-budget-thinking">
            {labels.composerBudgetThinkingLabel}
          </label>
          <div className={styles.fieldRow}>
            <VNativeInput
              id="chat-composer-budget-thinking"
              className={styles.fieldInput}
              type="number"
              inputMode="numeric"
              min={SESSION_BUDGET_THINKING_CHARS_LIMITS.min}
              max={SESSION_BUDGET_THINKING_CHARS_LIMITS.max}
              step={1}
              placeholder={labels.composerBudgetThinkingPlaceholder}
              aria-label={labels.composerBudgetThinkingLabel}
              aria-invalid={Boolean(thinkingError)}
              disabled={pending || loading || error}
              data-vui="chat-composer-budget-thinking-input"
              value={thinkingDraft}
              onChange={(event) => {
                setThinkingDraft(event.target.value);
                setDirty(true);
              }}
            />
            <VIconButton
              label={labels.composerBudgetClearThinking}
              variant="ghost"
              className={styles.clearButton}
              icon={<RotateCcw size={15} aria-hidden="true" />}
              isDisabled={pending || loading || error || thinkingDraft.trim() === ""}
              onPress={() => {
                setThinkingDraft("");
                setDirty(true);
              }}
            />
          </div>
          {thinkingError ? <span className={styles.error} role="alert">{thinkingError}</span> : null}
        </div>
        {errorMessage ? <p className={styles.error} role="alert">{errorMessage}</p> : null}
      </div>
    </VDialog>
  );
}

function budgetDraft(value: number | null | undefined): string {
  return typeof value === "number" && Number.isSafeInteger(value) ? String(value) : "";
}
