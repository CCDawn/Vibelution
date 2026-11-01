import { AlertCircle, CheckCheck, Clock3, LoaderCircle, Reply } from "lucide-react";

import { ConversationTurnAvatarContent } from "../conversation/ConversationTurnAvatarContent";
import type { AgentMessageActor } from "./types";
import styles from "./AgentMessages.styles";

export function MessageAvatar({ actor, compact = false }: { actor: AgentMessageActor; compact?: boolean }) {
  return <span className={compact ? styles.compactAvatar : styles.avatar} aria-hidden="true">
      <ConversationTurnAvatarContent content={{ imageUrl: actor.avatarImageUrl, fallback: Array.from(actor.name || actor.agentId).slice(0, 2).join("") }} imageClassName={styles.avatarImage} />
    </span>;
}

export function MessageActor({ actor, compact = false }: { actor: AgentMessageActor; compact?: boolean }) {
  return <span className={compact ? styles.compactActor : styles.actor} title={actor.name || actor.agentId}>
    <MessageAvatar actor={actor} compact={compact} />
    <span className={compact ? styles.compactName : styles.actorName}>{actor.name || actor.agentId}</span>
  </span>;
}

export function MessageState({ label, state, danger = false }: { label: string; state: string; danger?: boolean }) {
  const active = state === "processing" || state === "sending";
  const Icon = danger ? AlertCircle : active ? LoaderCircle : state === "replied" ? Reply : state === "delivered" || state === "received" ? CheckCheck : Clock3;
  return <span className={styles.state} data-tone={danger ? "danger" : active ? "active" : "neutral"}>
    <Icon size={13} aria-hidden="true" className={active ? "animate-spin motion-reduce:animate-none" : undefined} />{label}
  </span>;
}
