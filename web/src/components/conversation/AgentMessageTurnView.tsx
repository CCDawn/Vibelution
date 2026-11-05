import React, { ReactNode } from "react";

import styles from "./AgentMessageTurnView.styles";

type AgentMessageTurnViewProps = {
  rowKey: string;
  messageKey: string;
  agentMessageId: string;
  sectionCount: number;
  sectionKinds?: string;
  className: string;
  compactHeader: boolean;
  /** Single-speaker conversations keep identity in their page title. */
  minimalIdentity?: boolean;
  avatar: ReactNode;
  speakerLabel: ReactNode;
  identityAccessory?: ReactNode;
  metaActions?: ReactNode;
  turnLabel?: string;
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
  minimalIdentity = false,
  avatar,
  speakerLabel,
  identityAccessory,
  metaActions,
  turnLabel,
  children,
}: AgentMessageTurnViewProps) {
  const speakerId = `agent-turn-speaker-${messageKey}`;
  const visibleSpeakerLabel = typeof speakerLabel === "string"
    ? (/^\d+$/.test(speakerLabel.trim()) ? "" : speakerLabel.trim())
    : speakerLabel;
  const hasIdentity = Boolean(visibleSpeakerLabel || identityAccessory);
  return (
    <article
      className={className}
      aria-label={minimalIdentity && typeof visibleSpeakerLabel === "string"
        ? [turnLabel, visibleSpeakerLabel].filter(Boolean).join(" · ")
        : turnLabel}
      data-conversation-row-key={rowKey}
      data-conversation-message-key={messageKey}
      data-agent-message-id={agentMessageId}
      data-agent-section-count={sectionCount}
      data-agent-section-kinds={sectionKinds || undefined}
      data-conversation-identity={minimalIdentity ? "minimal" : "speaker"}
    >
      {!minimalIdentity ? <div className={styles.turnAvatar} aria-hidden="true">
        {compactHeader ? null : avatar}
      </div> : null}
      <div className={styles.turnContent}>
        {compactHeader || minimalIdentity ? null : (
          <div className={styles.turnMeta}>
            {hasIdentity ? (
              <div className={styles.turnMetaIdentity}>
                {visibleSpeakerLabel ? (
                  <span
                    id={speakerId}
                    className={styles.turnSpeaker}
                    title={typeof visibleSpeakerLabel === "string" ? visibleSpeakerLabel : undefined}
                  >
                    {visibleSpeakerLabel}
                  </span>
                ) : null}
                {identityAccessory}
              </div>
            ) : null}
            <span className={styles.turnMetaActions}>
              {metaActions}
            </span>
          </div>
        )}
        {minimalIdentity && identityAccessory ? <div>{identityAccessory}</div> : null}
        {children}
        {minimalIdentity && metaActions ? (
          <div className={styles.turnFooter} data-conversation-turn-actions="true">
            {metaActions}
          </div>
        ) : null}
      </div>
    </article>
  );
}
