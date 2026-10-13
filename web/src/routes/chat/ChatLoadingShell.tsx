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
      <div className={styles.indexShell} aria-hidden="true">
        {Array.from({ length: 5 }, (_, cardIndex) => (
          <div key={cardIndex} className={styles.indexCard}>
            <Pulse className={styles.indexAvatar} />
            <span className={styles.indexCopy}>
              <Pulse className={styles.indexTitle} />
              <Pulse className={styles.indexMeta} />
            </span>
          </div>
        ))}
      </div>
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
          <Pulse className={styles.composerTool} />
          <Pulse className={styles.composerSend} />
        </div>
      </div>
    </section>
  );
}
