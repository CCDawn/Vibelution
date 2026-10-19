import { RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { VButton, VIconButton, VNativeInput, VPopover } from "../../components/vui";
import styles from "./ChatComposerBudgetPopover.styles";

/** Server validation domain for per-turn tool-call quota. */
export const SESSION_BUDGET_MAX_CALLS_LIMITS = { min: 1, max: 200 } as const;

/** PATCH payload the popover hands to the workbench mutation. */
export type ChatComposerBudgetParametersPatch = {
  revision: number;
  maxCallsPerTurn: number | null;
};

export type ChatComposerBudgetPanelLabels = {
  composerBudgetTitle: string;
  composerBudgetDescription: string;
  composerBudgetMaxCallsLabel: string;
  composerBudgetMaxCallsPlaceholder: string;
  composerBudgetClearMaxCalls: string;
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

type ChatComposerBudgetPopoverProps = {
  lang: "zh" | "en";
  labels: ChatComposerBudgetPanelLabels;
  /**
   * Menu-row trigger button rendered inside the plus menu; the popover owns
   * its press handling, so the trigger carries no onPress of its own.
   */
  trigger: ReactNode;
  /** Draft scope resets when the session identity changes. */
  sessionId: string;
  /** Server revision guard; saves are blocked until it is known. */
  revision?: number;
  maxCallsPerTurn: number | null;
  loading?: boolean;
  error?: boolean;
  pending?: boolean;
  errorMessage?: string;
  onSave: (parameters: ChatComposerBudgetParametersPatch) => void;
};

/**
 * Composer "budget and quota" side panel: opens from the plus-menu row via a
 * right-side VPopover instead of a modal dialog. Draft + save semantics are
 * unchanged from the dialog era (modeled on ConversationTurnModelControl):
 * the draft survives revision refreshes / 409s and re-syncs only when the
 * session identity changes or a settled save confirms the server truth.
 */
export function ChatComposerBudgetPopover({
  lang,
  labels,
  trigger,
  sessionId,
  revision,
  maxCallsPerTurn,
  loading = false,
  error = false,
  pending = false,
  errorMessage = "",
  onSave,
}: ChatComposerBudgetPopoverProps) {
  const [open, setOpen] = useState(false);
  const [maxCallsDraft, setMaxCallsDraft] = useState(() => budgetDraft(maxCallsPerTurn));
  const [dirty, setDirty] = useState(false);
  const previousPendingRef = useRef(pending);

  const maxCallsValidation = validateSessionBudgetField(maxCallsDraft, SESSION_BUDGET_MAX_CALLS_LIMITS, lang);
  const maxCallsError = dirty ? maxCallsValidation.error : "";
  const valuesChanged = maxCallsValidation.value !== (maxCallsPerTurn ?? null);
  const saveDisabled = Boolean(
    pending
      || loading
      || error
      || revision === undefined
      || !maxCallsValidation.valid
      || !valuesChanged,
  );

  function resetDraft() {
    setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
    setDirty(false);
  }

  useEffect(() => {
    setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
    setDirty(false);
  // Identity change starts a new editing scope. Revision refreshes are
  // intentionally excluded so an optimistic operator's draft survives 409s.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!dirty || maxCallsValidation.value === (maxCallsPerTurn ?? null)) {
      setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
      setDirty(false);
    }
  // Validation results are derived from the drafts; recompute inline instead
  // of depending on unstable derived objects.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxCallsPerTurn, maxCallsDraft, dirty]);

  useEffect(() => {
    const saved = previousPendingRef.current && !pending && !errorMessage;
    previousPendingRef.current = pending;
    if (saved) {
      setMaxCallsDraft(budgetDraft(maxCallsPerTurn));
      setDirty(false);
    }
  }, [pending, errorMessage, maxCallsPerTurn]);

  return (
    <VPopover
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !pending) {
          resetDraft();
        }
        setOpen(nextOpen);
      }}
      side="right"
      align="start"
      sideOffset={6}
      aria-label={labels.composerBudgetTitle}
      contentClassName={styles.panel}
      data-vui="chat-composer-budget-popover"
      trigger={trigger}
    >
      <div className={styles.body} data-testid="chat-composer-budget-popover-body">
        <header className={styles.header}>
          <h3 className={styles.title}>{labels.composerBudgetTitle}</h3>
          <p className={styles.description}>{labels.composerBudgetDescription}</p>
        </header>
        {loading ? <p className={styles.statusLine}>{labels.composerBudgetLoading}</p> : null}
        {error ? <p className={styles.error} role="alert">{labels.composerBudgetLoadFailed}</p> : null}
        <div className={styles.fields}>
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
        </div>
        {errorMessage ? <p className={styles.error} role="alert">{errorMessage}</p> : null}
        <div className={styles.footer}>
          <VButton
            type="button"
            variant="secondary"
            isDisabled={pending}
            onPress={() => setOpen(false)}
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
              });
            }}
          >
            {labels.composerBudgetSave}
          </VButton>
        </div>
      </div>
    </VPopover>
  );
}

function budgetDraft(value: number | null | undefined): string {
  return typeof value === "number" && Number.isSafeInteger(value) ? String(value) : "";
}
