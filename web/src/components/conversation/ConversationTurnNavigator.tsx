import { Fragment } from "react";

import { VButton, VHoverCard } from "../vui";
import {
  CONVERSATION_TURN_NAV_MIN_TURNS,
  type ConversationTurnNavEntry,
} from "./conversationTurnNavigation";
import styles from "./ConversationTurnNavigator.styles";

type ConversationTurnNavigatorProps = {
  entries: ConversationTurnNavEntry[];
  currentIndex: number;
  ariaLabel: string;
  onNavigate: (entry: ConversationTurnNavEntry) => void;
};

/**
 * Timeline minimap rail (pattern: zai-org/ZCode ConversationTurnNavigator,
 * Apache-2.0): one dot per conversation turn on the timeline area's right
 * edge. Mounts only for long sessions (>= 6 turns); the active turn is
 * highlighted and each dot jumps the timeline to its turn.
 *
 * Dots whose turn carries previews are wrapped in a VHoverCard (user prompt
 * clamped to two lines over the assistant answer clamped to three); the
 * native title tooltip is replaced by that card. Turns without any preview
 * keep a bare dot — no empty hover shells.
 */
export function ConversationTurnNavigator({
  entries,
  currentIndex,
  ariaLabel,
  onNavigate,
}: ConversationTurnNavigatorProps) {
  if (entries.length < CONVERSATION_TURN_NAV_MIN_TURNS) {
    return null;
  }
  return (
    <nav
      className={styles.turnNavigatorRail}
      aria-label={ariaLabel}
      data-conversation-turn-navigator="1"
    >
      {entries.map((entry) => {
        const active = entry.turnIndex === currentIndex;
        const userPreviewText = entry.userPreviewText.trim();
        const assistantPreviewText = entry.assistantPreviewText.trim();
        const hasPreview = Boolean(userPreviewText || assistantPreviewText);
        const dot = (
          <VButton
            type="button"
            contentLayout="plain"
            className={
              active
                ? `${styles.turnNavigatorDot} ${styles.turnNavigatorDotActive}`
                : styles.turnNavigatorDot
            }
            onClick={() => onNavigate(entry)}
            aria-label={entry.label}
            aria-current={active ? "true" : undefined}
          >
            <span className={styles.turnNavigatorDotMark} aria-hidden="true" />
          </VButton>
        );
        if (!hasPreview) {
          return <Fragment key={entry.turnIndex}>{dot}</Fragment>;
        }
        return (
          <VHoverCard
            key={entry.turnIndex}
            side="left"
            content={
              <div className={styles.turnNavigatorHoverBody}>
                {userPreviewText ? (
                  <p className={styles.turnNavigatorHoverUser}>{userPreviewText}</p>
                ) : null}
                {assistantPreviewText ? (
                  <p className={styles.turnNavigatorHoverAssistant}>{assistantPreviewText}</p>
                ) : null}
              </div>
            }
          >
            {dot}
          </VHoverCard>
        );
      })}
    </nav>
  );
}
