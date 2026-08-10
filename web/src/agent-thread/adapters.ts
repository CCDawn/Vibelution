import type { ConversationMessage, SessionTurnItem } from "../api/types";
import type {
  AgentMentalPart,
  AgentMentalSnapshot,
  AgentMessage,
  AgentMessagePart,
  AgentRuntimeEventPart,
  AgentThoughtPart,
  AgentToolCallPart,
} from "./types";
import { isInternalStreamingStatusContent, isInternalStreamingStatusStage } from "../components/conversation/conversationInternalStatus";

export function conversationMessageToAgentMessage(message: ConversationMessage): AgentMessage {
  const parts = conversationMessageToAgentParts(message);
  return {
    id: message.id,
    role: message.role,
    createdAt: message.timestamp,
    streaming: message.role === "assistant" && message.status === "running",
    turnId: message.role === "assistant" ? message.turnId : messageTurnId(message),
    source: {
      kind: "conversation-message",
      id: message.id,
      metadata: message.metadata,
    },
    parts,
    metadata: message.metadata,
  };
}

export function conversationMessageToAgentParts(message: ConversationMessage): AgentMessagePart[] {
  if (message.role === "user") {
    return [
      ...textPartForMessage(message),
      ...attachmentPartsForMessage(message),
      ...referencePartsForMessage(message),
    ];
  }

  return assistantTurnItemsToAgentParts(message.turnItems);
}

function assistantTurnItemsToAgentParts(items: readonly SessionTurnItem[]): AgentMessagePart[] {
  return [...items]
    .sort((left, right) => (
      normalizedSequence(left.sequence) - normalizedSequence(right.sequence)
      || normalizedSequence(left.revision) - normalizedSequence(right.revision)
    ))
    .flatMap((item): AgentMessagePart[] => {
      if (item.type === "status" && (
        isInternalStreamingStatusStage(item.code)
        || isInternalStreamingStatusContent(item.text)
      )) {
        return [];
      }
      if (item.type === "agent_message") {
        const text = compactText(item.text);
        return text ? [{
          id: item.id,
          type: "text",
          channel: "answer",
          text,
        }] : [];
      }
      if (item.type === "reasoning") {
        const text = compactText(item.text);
        const summary = compactText(item.summary);
        return text && !isInternalThoughtPlaceholder(text, summary) ? [{
          id: item.id,
          type: "thought",
          text,
          summary,
          status: item.status,
          sequence: item.sequence,
          timestamp: item.updatedAt ?? item.createdAt,
        } satisfies AgentThoughtPart] : [];
      }
      if (item.type === "status" && item.code === "mental_snapshot") {
        return [{
          id: item.id,
          type: "mental",
          status: item.status,
          snapshot: mentalSnapshotFromTurnItem(item.metadata?.mentalSnapshot),
          summary: compactText(item.text || item.summary),
          sequence: item.sequence,
          timestamp: item.updatedAt ?? item.createdAt,
        } satisfies AgentMentalPart];
      }
      if (item.type === "tool_call") {
        return [{
          id: item.id,
          type: "tool-call",
          name: compactText(item.toolName) || "tool",
          status: item.status,
          summary: compactText(item.summary),
          resultPreview: compactText(item.output),
          sequence: item.sequence,
          timestamp: item.updatedAt ?? item.createdAt,
          source: "feedback-event",
        } satisfies AgentToolCallPart];
      }
      const retry = item.type === "retry";
      return [{
        id: item.id,
        type: "runtime-event",
        kind: "status",
        name: retry ? "model_retry" : item.type === "error" ? item.code : item.code,
        status: item.status,
        summary: retry ? item.reason : item.text,
        error: item.type === "error" ? item.text : undefined,
        sequence: item.sequence,
        timestamp: item.updatedAt ?? item.createdAt,
      } satisfies AgentRuntimeEventPart];
    });
}

function mentalSnapshotFromTurnItem(value: unknown): AgentMentalSnapshot | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const snapshot = value as Record<string, unknown>;
  const number = (raw: unknown) => {
    const parsed = Number(raw ?? 0);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  return {
    mood: String(snapshot.mood ?? ""),
    feeling: String(snapshot.feeling ?? ""),
    whisper: String(snapshot.whisper ?? ""),
    summary: String(snapshot.summary ?? ""),
    cognitiveState: String(snapshot.cognitiveState ?? ""),
    confidence: number(snapshot.confidence),
    sampleSize: number(snapshot.sampleSize),
    interventionCount: number(snapshot.interventionCount),
    updatedAt: String(snapshot.updatedAt ?? ""),
    source: String(snapshot.source ?? ""),
    intervention: typeof snapshot.intervention === "string" ? snapshot.intervention : undefined,
    metrics: snapshot.metrics && typeof snapshot.metrics === "object" && !Array.isArray(snapshot.metrics)
      ? snapshot.metrics as Record<string, unknown>
      : undefined,
    historyTail: Array.isArray(snapshot.historyTail)
      ? snapshot.historyTail.flatMap((entry) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
          return [];
        }
        const item = entry as Record<string, unknown>;
        return [{
          cognitiveState: String(item.cognitiveState ?? ""),
          confidence: number(item.confidence),
          timestamp: String(item.timestamp ?? ""),
        }];
      })
      : undefined,
  };
}

function textPartForMessage(message: ConversationMessage): AgentMessagePart[] {
  if (message.role !== "user") {
    return [];
  }
  const text = compactText(message.content);
  if (!text) {
    return [];
  }
  return [{
    id: `${message.id}-text`,
    type: "text",
    channel: "user",
    text,
  }];
}

function attachmentPartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  if (message.role !== "user") {
    return [];
  }
  return (message.attachments ?? []).map((attachment, index) => ({
    id: `${message.id}-attachment-${attachment.artifactId || index}`,
    type: "attachment",
    attachment,
  }));
}

function referencePartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  if (message.role !== "user") {
    return [];
  }
  return (message.references ?? []).map((reference, index) => ({
    id: `${message.id}-reference-${reference.referenceId || reference.sessionId || index}`,
    type: "reference",
    reference,
  }));
}

function messageTurnId(message: ConversationMessage) {
  const value = message.metadata?.turnId;
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  return trimmed.startsWith("live:") ? trimmed.slice("live:".length) : trimmed;
}

function normalizedSequence(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function isInternalThoughtPlaceholder(text: string, summary: string) {
  const normalizedText = text.trim().toLowerCase();
  const normalizedSummary = summary.trim().toLowerCase();
  if (!normalizedText) {
    return true;
  }
  if (["internal", "internal_thought", "internal reasoning", "internal process"].includes(normalizedText)) {
    return true;
  }
  return normalizedText === normalizedSummary && normalizedText.startsWith("internal");
}
