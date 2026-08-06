import { VSkeleton } from "../vui";
import styles from "./ConversationTranscriptLoadingState.styles";

export type ConversationTranscriptLoadingStateProps = {
  label: string;
};

/** Preserves transcript geometry without turning the whole conversation into a tinted state panel. */
export function ConversationTranscriptLoadingState({
  label,
}: ConversationTranscriptLoadingStateProps) {
  return (
    <section
      aria-label={label}
      aria-busy="true"
      data-testid="conversation-transcript-loading-state"
      role="status"
      className={styles.root}
    >
      <span className={styles.visuallyHidden}>{label}</span>
      <div aria-hidden="true" className={styles.transcript}>
        <div className={styles.assistantTurn}>
          <VSkeleton shape="circle" className={styles.avatar} />
          <div className={styles.message}>
            <VSkeleton className={styles.messageHeadingWide} />
            <VSkeleton className={styles.messageLineWide} />
            <VSkeleton className={styles.messageLineCompact} />
          </div>
        </div>
        <div className={styles.userTurn}>
          <span className={styles.userBubble} />
        </div>
        <div className={styles.assistantTurn}>
          <VSkeleton shape="circle" className={styles.avatar} />
          <div className={styles.message}>
            <VSkeleton className={styles.messageHeadingCompact} />
            <VSkeleton className={styles.messageLineMedium} />
            <VSkeleton className={styles.messageLineShort} />
          </div>
        </div>
      </div>
    </section>
  );
}
