import type {
  ConversationAttachment,
  ConversationFeedbackEvent,
  ConversationMessage,
  MentalStateSnapshot,
  SessionReferenceAttachment,
  ToolCall,
} from "../api/types";

export type AgentThreadStatus = "idle" | "streaming";

export type AgentThreadSource = {
  kind: "conversation" | "session" | "chat-room" | string;
  id?: string;
};

export type AgentMessageRole = ConversationMessage["role"];

export type AgentMessageSource = {
  kind: "conversation-message";
  id: string;
  metadata?: Record<string, unknown>;
};

export type AgentThread = {
  id: string;
  source: AgentThreadSource;
  status: AgentThreadStatus;
  messages: AgentMessage[];
};

export type AgentMessage = {
  id: string;
  role: AgentMessageRole;
  createdAt: string;
  streaming: boolean;
  turnId?: string;
  source: AgentMessageSource;
  parts: AgentMessagePart[];
  metadata?: Record<string, unknown>;
};

export type AgentTextPart = {
  id: string;
  type: "text";
  channel: "user" | "answer";
  text: string;
};

export type AgentThoughtPart = {
  id: string;
  type: "thought";
  text: string;
  status: string;
  summary?: string;
  sequence?: number;
  timestamp?: string;
};

export type AgentMentalPart = {
  id: string;
  type: "mental";
  status: string;
  snapshot?: MentalStateSnapshot;
  summary: string;
  sequence?: number;
  timestamp?: string;
};

export type AgentRuntimeEventPart = {
  id: string;
  type: "runtime-event";
  kind: ConversationFeedbackEvent["kind"] | "status";
  name?: string;
  status: string;
  summary: string;
  resultPreview?: string;
  error?: string;
  sequence?: number;
  timestamp?: string;
  tracePath?: string;
};

export type AgentToolCallPart = {
  id: string;
  type: "tool-call";
  name: string;
  status: string;
  summary?: string;
  arguments?: Record<string, unknown>;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number;
  error?: string;
  durationMs?: number;
  durationSeconds?: number;
  timeoutSeconds?: number;
  transportStatus?: string;
  semanticStatus?: string;
  exitCode?: number | null;
  timedOut?: boolean;
  failureClass?: string;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number;
  tracePath?: string;
  sequence?: number;
  timestamp?: string;
  relatedThoughtSequence?: number;
  source?: "feedback-event" | "legacy-tool-call";
  original?: ToolCall | ConversationFeedbackEvent;
};

export type AgentAttachmentPart = {
  id: string;
  type: "attachment";
  attachment: ConversationAttachment;
};

export type AgentReferencePart = {
  id: string;
  type: "reference";
  reference: SessionReferenceAttachment;
};

export type AgentMessagePart =
  | AgentTextPart
  | AgentThoughtPart
  | AgentMentalPart
  | AgentRuntimeEventPart
  | AgentToolCallPart
  | AgentAttachmentPart
  | AgentReferencePart;
