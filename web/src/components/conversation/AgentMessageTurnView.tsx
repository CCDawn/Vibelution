import React, { ReactNode } from "react";

import styles from "./ConversationView.styles";

type AgentMessageTurnViewProps = {
  rowKey: string;
  messageKey: string;
  agentMessageId: string;
  sectionCount: number;
  sectionKinds?: string;
  className: string;
  compactHeader: boolean;
  avatar: ReactNode;
  speakerLabel: ReactNode;
  identityAccessory?: ReactNode;
  metaActions?: ReactNode;
  children: ReactNode;
};

export function AgentMessageTurnView({
  rowKey,
  messageKey,
  agentMessageId,
  sectionCount,
  sectionKinds,
  className,
  compactHeader,
  avatar,
  speakerLabel,
  identityAccessory,
  metaActions,
  children,
}: AgentMessageTurnViewProps) {
  return (
    <article
      className={className}
      data-conversation-row-key={rowKey}
      data-conversation-message-key={messageKey}
      data-agent-message-id={agentMessageId}
      data-agent-section-count={sectionCount}
      data-agent-section-kinds={sectionKinds || undefined}
    >
      <div className={styles.turnAvatar} aria-hidden="true">
        {compactHeader ? null : avatar}
      </div>
      <div className={styles.turnContent}>
        {compactHeader ? null : (
          <div className={styles.turnMeta}>
            <div className={styles.turnMetaIdentity}>
              <span className={styles.turnSpeaker}>
                {speakerLabel}
              </span>
              {identityAccessory}
            </div>
            <span className={styles.turnMetaActions}>
              {metaActions}
            </span>
          </div>
        )}
        {children}
      </div>
    </article>
  );
}
