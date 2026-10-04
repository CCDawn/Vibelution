import { Check, ChevronDown, Bot } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { SessionLlmModelOption, SessionModelSelection } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { VButton, VPopover } from "../vui";
import styles from "./ConversationTurnModelControl.styles";

type ConversationTurnModelControlProps = {
  /** Full selectable list from the session llm-options endpoint. */
  choices: SessionLlmModelOption[];
  /** Session default model id (modelRef preferred) shown when no override is pinned. */
  sessionDefaultModelId: string;
  /** Sticky override for the next send; null follows the session default. */
  selection: SessionModelSelection | null;
  disabled: boolean;
  /** Change channel: null restores "follow the session default". */
  onSelectionChange: (selection: SessionModelSelection | null) => void;
};

export function resolveTurnModelSelectionLabel(
  choices: SessionLlmModelOption[],
  modelId: string,
): string {
  const candidate = choices.find(
    (choice) =>
      choice.modelRef === modelId
      || choice.modelId === modelId,
  );
  return candidate?.label || candidate?.model || modelId;
}

/** The model the next send would use: the pinned override, else the session default. */
export function effectiveTurnModelId(
  sessionDefaultModelId: string,
  selection: SessionModelSelection | null,
): string {
  return selection?.modelId || sessionDefaultModelId;
}

export function ConversationTurnModelControl({
  choices,
  sessionDefaultModelId,
  selection,
  disabled,
  onSelectionChange,
}: ConversationTurnModelControlProps) {
  const { lang, t } = useAppI18n({ domains: ["chat"] });
  const [open, setOpen] = useState(false);
  const overrideActive = Boolean(selection?.modelId);
  const overrideLeavesDefault = overrideActive && selection?.modelId !== sessionDefaultModelId;
  const effectiveModelId = effectiveTurnModelId(sessionDefaultModelId, selection);
  const effectiveLabel = resolveTurnModelSelectionLabel(choices, effectiveModelId);
  const turnModelScopeLabel = lang === "zh" ? "本轮模型" : "Model for this turn";
  const turnModelLabel = `${turnModelScopeLabel}: ${effectiveLabel}`;
  const turnModelStatusTooltip = overrideLeavesDefault
    ? t("turnModelOverrideTooltip").replace("{model}", effectiveLabel)
    : t("turnModelFollowTooltip").replace("{model}", effectiveLabel);
  const turnModelTooltip = `${turnModelScopeLabel} · ${turnModelStatusTooltip}`;
  const overrideModel = useMemo(
    () => (overrideActive
      ? choices.find((choice) => choice.modelRef === selection?.modelId || choice.modelId === selection?.modelId)
      : undefined),
    [choices, overrideActive, selection?.modelId],
  );
  const overrideEffort = selection?.reasoningEffort || "";

  // Session switch closes the menu so a popover opened on the previous
  // session never applies a click to the new one.
  useEffect(() => {
    setOpen((wasOpen) => (wasOpen ? false : wasOpen));
  }, [sessionDefaultModelId, choices.length]);

  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  const followRow = (
    <VButton
      key="follow-session"
      type="button"
      contentLayout="plain"
      className={styles.option}
      role="option"
      aria-selected={!overrideActive}
      data-selected={!overrideActive ? "true" : "false"}
      onPress={() => {
        onSelectionChange(null);
        setOpen(false);
      }}
    >
      <span className={styles.optionCopy}>
        <span className={styles.followLabel}>{t("turnModelFollowSession")}</span>
        <small className={styles.optionMeta}>
          {resolveTurnModelSelectionLabel(choices, sessionDefaultModelId)}
        </small>
      </span>
      {!overrideActive
        ? <Check className={styles.check} size={14} aria-hidden="true" />
        : <span className={styles.checkSlot} aria-hidden="true" />}
    </VButton>
  );

  const effortRows = overrideModel?.supportsReasoningEffort
    ? [
      <VButton
        key="effort-follow"
        type="button"
        contentLayout="plain"
        className={styles.effortOption}
        role="option"
        aria-selected={!overrideEffort}
        data-selected={!overrideEffort ? "true" : "false"}
        onPress={() => {
          onSelectionChange({ modelId: overrideModel.modelRef || overrideModel.modelId });
          setOpen(false);
        }}
      >
        <span className={styles.effortLabel}>{t("turnModelEffortFollowSession")}</span>
        {!overrideEffort
          ? <Check className={styles.check} size={12} aria-hidden="true" />
          : <span className={styles.checkSlotSmall} aria-hidden="true" />}
      </VButton>,
      ...(overrideModel.reasoningEffortOptions ?? []).map((option) => (
        <VButton
          key={`effort-${option.value}`}
          type="button"
          contentLayout="plain"
          className={styles.effortOption}
          role="option"
          aria-selected={overrideEffort === option.value}
          data-selected={overrideEffort === option.value ? "true" : "false"}
          onPress={() => {
            onSelectionChange({
              modelId: overrideModel.modelRef || overrideModel.modelId,
              reasoningEffort: option.value,
            });
            setOpen(false);
          }}
        >
          <span className={styles.effortLabel}>{option.label || option.value}</span>
          {overrideEffort === option.value
            ? <Check className={styles.check} size={12} aria-hidden="true" />
            : <span className={styles.checkSlotSmall} aria-hidden="true" />}
        </VButton>
      )),
    ]
    : [];

  return (
    <div className={styles.root} data-testid="conversation-turn-model-control">
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (disabled) {
            setOpen(false);
            return;
          }
          setOpen(nextOpen);
        }}
        side="top"
        align="end"
        sideOffset={6}
        aria-label={t("turnModelMenuLabel")}
        contentClassName={styles.menu}
        data-vui="conversation-turn-model-menu"
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={overrideLeavesDefault
              ? `${styles.trigger} ${styles.triggerOverride}`
              : styles.trigger}
            isDisabled={disabled}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label={turnModelLabel}
            data-open={open ? "true" : "false"}
            data-override={overrideLeavesDefault ? "true" : "false"}
            tooltip={turnModelTooltip}
          >
            <Bot className={styles.triggerIcon} size={12} aria-hidden="true" />
            <span className="shrink-0 whitespace-nowrap">{turnModelScopeLabel}</span>
            <span aria-hidden="true">·</span>
            <span className={`${styles.triggerModel} max-w-32 truncate`} title={effectiveLabel}>{effectiveLabel}</span>
            {overrideLeavesDefault ? (
              <span className={styles.overrideDot} aria-label={t("turnModelOverrideBadge")} />
            ) : null}
            <ChevronDown className={styles.triggerChevron} data-open={open ? "true" : "false"} size={12} aria-hidden="true" />
          </VButton>
        )}
      >
        <div
          role="listbox"
          aria-label={t("turnModelMenuLabel")}
          data-testid="conversation-turn-model-menu"
        >
          {followRow}
          {choices.map((choice) => {
            const choiceId = choice.modelRef || choice.modelId;
            const selected = overrideActive && selection?.modelId === choiceId;
            const isSessionDefault = choiceId === sessionDefaultModelId;
            return (
              <VButton
                key={choiceId}
                type="button"
                contentLayout="plain"
                className={styles.option}
                role="option"
                aria-selected={selected}
                data-selected={selected ? "true" : "false"}
                title={choice.modelRef}
                onPress={() => {
                  // A model pick clears any effort pin: the new model's
                  // effort surface is chosen (or left to the session) next.
                  onSelectionChange({ modelId: choiceId });
                  setOpen(false);
                }}
              >
                <span className={styles.optionCopy}>
                  <span className={styles.optionLabel}>{choice.label || choice.model}</span>
                  <small className={styles.optionMeta}>
                    {choice.providerLabel || choice.providerId}
                    {isSessionDefault ? ` · ${t("turnModelSessionDefaultBadge")}` : ""}
                    {!isSessionDefault && choice.missingApiKey ? ` · ${t("turnModelMissingKeyBadge")}` : ""}
                  </small>
                </span>
                {selected
                  ? <Check className={styles.check} size={14} aria-hidden="true" />
                  : <span className={styles.checkSlot} aria-hidden="true" />}
              </VButton>
            );
          })}
          {effortRows.length ? (
            <div className={styles.effortSection} role="group" aria-label={t("turnModelEffortSectionLabel")}>
              {effortRows}
            </div>
          ) : null}
        </div>
      </VPopover>
    </div>
  );
}
