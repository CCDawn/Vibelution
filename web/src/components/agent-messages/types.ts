export interface AgentMessageActor {
  agentId: string;
  name: string;
  avatarImageUrl?: string;
}

export interface AgentMessageReceipt extends AgentMessageActor {
  delivery: "unknown" | "sending" | "delivered" | "failed" | "revoked";
  handling: "unknown" | "waiting" | "received" | "queued" | "processing" | "replied" | "wake_failed";
  error?: string;
  sessionId?: string;
}

/** A projection of existing message events; never a second session transcript. */
export interface AgentMessageRecord {
  id: string;
  /** Existing event, inbox-message and tool-call identities used by the read model. */
  aliases?: string[];
  sourceSessionId?: string;
  sourceEventId?: string;
  sourceTaskId?: string;
  sender: AgentMessageActor;
  type: "notification" | "request" | "reply";
  createdAt: string;
  title: string;
  body: string;
  recipients: AgentMessageReceipt[];
  replyToId?: string;
}

export type AgentMessageScope = "current" | "all";
export type AgentMessageLang = "zh" | "en";
