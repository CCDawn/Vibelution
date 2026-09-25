import { VButton } from "../vui";
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
        return (
          <VButton
            key={entry.turnIndex}
            type="button"
            contentLayout="plain"
            className={
              active
                ? `${styles.turnNavigatorDot} ${styles.turnNavigatorDotActive}`
                : styles.turnNavigatorDot
            }
            onClick={() => onNavigate(entry)}
            title={entry.label}
            aria-label={entry.label}
            aria-current={active ? "true" : undefined}
          >
            <span className={styles.turnNavigatorDotMark} aria-hidden="true" />
          </VButton>
        );
      })}
    </nav>
  );
}
