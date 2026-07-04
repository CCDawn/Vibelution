import { ExternalLink, Users } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentReferencesPanel.styles";

export type AgentReferenceStatusTone = "active" | "stale";

export type AgentReferenceRoomView = {
  id: string;
  statusLabel: string;
  statusTone: AgentReferenceStatusTone;
  title: string;
  meta: string;
  route: string;
  actionLabel: string;
};

export type AgentReferenceItemView = {
  id: string;
  label: string;
  statusLabel: string;
  statusTone: AgentReferenceStatusTone;
  sourceLabel: string;
  meta: string;
  route: string;
  actionLabel: string;
};

export type AgentReferencesPanelCopy = {
  chatRoomMembership: string;
  references: string;
  noChatRooms: string;
  selectAgent: string;
  readOnlyLabel: string;
  membershipHelp: string;
};

export type AgentReferencesPanelProps = {
  copy: AgentReferencesPanelCopy;
  showChatRoomMembership: boolean;
  chatRoomSummary: string;
  referenceCount: number;
  chatRooms: AgentReferenceRoomView[];
  references: AgentReferenceItemView[];
  onOpenRoute: (route: string) => void;
};

function statusClass(tone: AgentReferenceStatusTone) {
  return tone === "stale" ? styles.referenceStatusStale : styles.referenceStatusActive;
}

export function AgentReferencesPanel({
  copy,
  showChatRoomMembership,
  chatRoomSummary,
  referenceCount,
  chatRooms,
  references,
  onOpenRoute,
}: AgentReferencesPanelProps) {
  return (
    <>
      {showChatRoomMembership ? (
        <section className={styles.configEditor}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.chatRoomMembership}</p>
              <h3>{chatRoomSummary}</h3>
            </div>
            <span className={styles.cleanPill}>{copy.readOnlyLabel}</span>
          </div>
          {chatRooms.length ? (
            <div className={styles.roomMembershipList}>
              {chatRooms.map((room) => (
                <div key={room.id} className={styles.roomCheckField}>
                  <span className={statusClass(room.statusTone)}>{room.statusLabel}</span>
                  <span>
                    <strong>{room.title}</strong>
                    <small>{room.meta}</small>
                  </span>
                  <VButton
                    type="button"
                    variant="ghost"
                    icon={<ExternalLink size={12} />}
                    onPress={() => onOpenRoute(room.route)}
                  >
                    {room.actionLabel}
                  </VButton>
                </div>
              ))}
            </div>
          ) : (
            <p className={styles.emptyText}>{copy.noChatRooms}</p>
          )}
          <p className={styles.emptyText}>{copy.membershipHelp}</p>
        </section>
      ) : null}

      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.references}</p>
            <h3>{referenceCount}</h3>
          </div>
          <Users size={16} />
        </div>
        {references.length ? (
          <div className={styles.referenceList}>
            {references.map((reference) => (
              <div key={reference.id} className={styles.referenceItem}>
                <div className={styles.referenceHeader}>
                  <strong>{reference.label}</strong>
                  <span className={statusClass(reference.statusTone)}>{reference.statusLabel}</span>
                </div>
                <span>{reference.sourceLabel}</span>
                <div className={styles.referenceMetaRow}>
                  <small>{reference.meta}</small>
                  {reference.route ? (
                    <VButton
                      type="button"
                      variant="ghost"
                      icon={<ExternalLink size={12} />}
                      onPress={() => onOpenRoute(reference.route)}
                    >
                      {reference.actionLabel}
                    </VButton>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.emptyText}>{copy.selectAgent}</p>
        )}
      </section>
    </>
  );
}
