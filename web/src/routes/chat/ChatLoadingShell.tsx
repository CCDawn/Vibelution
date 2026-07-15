import styles from "./ChatLoadingShell.styles";

type LoadingShellProps = {
  label: string;
};

function Pulse({ className }: { className: string }) {
  return <span aria-hidden="true" className={`${styles.pulse} ${className}`} />;
}

export function ConversationIndexLoadingShell({ label }: LoadingShellProps) {
  return (
    <section className={styles.indexShell} role="status" aria-label={label} data-testid="conversation-index-loading-shell">
      <span className="sr-only">{label}</span>
      {[2, 1, 1].map((cardCount, groupIndex) => (
        <div key={groupIndex} className={styles.indexGroup} aria-hidden="true">
          <div className={styles.indexGroupHeader}>
            <Pulse className={styles.indexGroupTitle} />
            <Pulse className={styles.indexGroupCount} />
          </div>
          {Array.from({ length: cardCount }, (_, cardIndex) => (
            <div key={cardIndex} className={styles.indexCard}>
              <Pulse className={styles.indexAvatar} />
              <span className={styles.indexCopy}>
                <Pulse className={styles.indexTitle} />
                <Pulse className={styles.indexMeta} />
              </span>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

export function ConversationWorkspaceLoadingShell({ label }: LoadingShellProps) {
  return (
    <section className={styles.workspaceShell} role="status" aria-label={label} data-testid="conversation-workspace-loading-shell">
      <span className="sr-only">{label}</span>
      <div className={styles.transcript} aria-hidden="true">
        <div className={styles.assistantTurn}>
          <Pulse className={styles.avatar} />
          <span className={styles.messageCopy}>
            <Pulse className={styles.messageHeading} />
            <Pulse className={styles.messageLineWide} />
            <Pulse className={styles.messageLine} />
          </span>
        </div>
        <div className={styles.userTurn}>
          <Pulse className={styles.userBubble} />
        </div>
        <div className={styles.assistantTurn}>
          <Pulse className={styles.avatar} />
          <span className={styles.messageCopy}>
            <Pulse className={styles.messageHeading} />
            <Pulse className={styles.messageLineWide} />
            <Pulse className={styles.messageLine} />
          </span>
        </div>
      </div>
      <div className={styles.composerWrap} aria-hidden="true">
        <Pulse className={styles.composerInput} />
        <div className={styles.composerToolbar}>
          <span className={styles.composerTools}>
            <Pulse className={styles.composerToolSmall} />
            <Pulse className={styles.composerTool} />
          </span>
          <Pulse className={styles.composerSend} />
        </div>
      </div>
    </section>
  );
}
