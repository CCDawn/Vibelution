import { Check, ChevronDown, Bot } from "lucide-react";
import { useEffect, useState } from "react";

import type { SessionLlmModelOption, SessionModelSelection } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { VButton, VPopover } from "../vui";
import {
  groupComposerModelChoices,
  modelMatchesComposerId,
} from "./composerModelEffort";
import styles from "./ConversationTurnModelControl.styles";

type ConversationTurnModelControlProps = {
  /** Full selectable list from the session llm-options endpoint. */
  choices: SessionLlmModelOption[];
  /** Session default model id (modelRef preferred) shown when no override is pinned. */
  sessionDefaultModelId: string;
  /** Sticky override for later sends; null follows the session default. */
  selection: SessionModelSelection | null;
  disabled: boolean;
  /**
   * Change-to-open channel for the /模型 builtin: a fresh non-empty value pops
   * the menu once (empty initial value never auto-opens).
   */
  openSignal?: string;
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
  openSignal = "",
  onSelectionChange,
}: ConversationTurnModelControlProps) {
  const { lang, t } = useAppI18n({ domains: ["chat"] });
  const [open, setOpen] = useState(false);
  const overrideActive = Boolean(selection?.modelId);
  const overrideLeavesDefault = overrideActive && selection?.modelId !== sessionDefaultModelId;
  const effectiveModelId = effectiveTurnModelId(sessionDefaultModelId, selection);
  const effectiveLabel = resolveTurnModelSelectionLabel(choices, effectiveModelId);
  const modelTriggerLabel = lang === "zh" ? "模型" : "Model";
  const turnModelLabel = `${modelTriggerLabel}: ${effectiveLabel}`;
  const turnModelTooltip = overrideLeavesDefault
    ? t("turnModelOverrideTooltip").replace("{model}", effectiveLabel)
    : t("turnModelFollowTooltip").replace("{model}", effectiveLabel);
  const groups = groupComposerModelChoices(choices);

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

  useEffect(() => {
    if (openSignal && !disabled) {
      setOpen(true);
    }
  }, [disabled, openSignal]);

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
          {groups.map((group) => (
            <div
              key={group.key}
              role="group"
              aria-label={group.label}
              className={styles.providerGroup}
              data-provider={group.key}
            >
              <div className={styles.providerLabel}>{group.label}</div>
              {group.choices.map((choice) => {
                const choiceId = choice.modelRef || choice.modelId;
                const selected = overrideActive && selection?.modelId === choiceId;
                const isSessionDefault = modelMatchesComposerId(choice, sessionDefaultModelId);
                const meta = [
                  isSessionDefault ? t("turnModelSessionDefaultBadge") : "",
                  choice.missingApiKey ? t("turnModelMissingKeyBadge") : "",
                ].filter(Boolean).join(" · ");
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
                      // The parent attaches a level this model supports.
                      // Picking the session default clears the pin.
                      onSelectionChange(isSessionDefault ? null : { modelId: choiceId });
                      setOpen(false);
                    }}
                  >
                    <span className={styles.optionCopy}>
                      <span className={styles.optionLabel}>{choice.label || choice.model}</span>
                      {meta ? <small className={styles.optionMeta}>{meta}</small> : null}
                    </span>
                    {selected
                      ? <Check className={styles.check} size={14} aria-hidden="true" />
                      : <span className={styles.checkSlot} aria-hidden="true" />}
                  </VButton>
                );
              })}
            </div>
          ))}
        </div>
      </VPopover>
    </div>
  );
}
