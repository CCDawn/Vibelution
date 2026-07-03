export type AgentThreadStatus = "idle" | "streaming";

export type AgentThreadSource = {
  kind: "conversation" | "session" | "chat-room" | string;
  id?: string;
};

export type AgentMessageRole = "user" | "assistant";

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

export type AgentMentalSnapshot = {
  mood: string;
  feeling: string;
  whisper: string;
  summary: string;
  cognitiveState: string;
  confidence: number;
  sampleSize: number;
  interventionCount: number;
  updatedAt: string;
  source: string;
  intervention?: string;
  metrics?: Record<string, unknown>;
  historyTail?: Array<{
    cognitiveState: string;
    confidence: number;
    timestamp: string;
  }>;
};

export type AgentMentalPart = {
  id: string;
  type: "mental";
  status: string;
  snapshot?: AgentMentalSnapshot;
  summary: string;
  sequence?: number;
  timestamp?: string;
};

export type AgentRuntimeEventKind = "thought" | "mental" | "tool" | "status" | (string & {});

export type AgentRuntimeEventPart = {
  id: string;
  type: "runtime-event";
  kind: AgentRuntimeEventKind;
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
};

export type AgentAttachment = {
  artifactId?: string;
  filename?: string;
  url?: string;
  imageUrl?: string;
  downloadUrl?: string;
  contentType?: string;
  sizeBytes?: number;
  kind?: string;
  status?: string;
};

export type AgentReference = {
  referenceId?: string;
  kind?: "session" | string;
  sessionId?: string;
  title?: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  summary?: string;
  createdAt?: string;
};

export type AgentAttachmentPart = {
  id: string;
  type: "attachment";
  attachment: AgentAttachment;
};

export type AgentReferencePart = {
  id: string;
  type: "reference";
  reference: AgentReference;
};

export type AgentMessagePart =
  | AgentTextPart
  | AgentThoughtPart
  | AgentMentalPart
  | AgentRuntimeEventPart
  | AgentToolCallPart
  | AgentAttachmentPart
  | AgentReferencePart;

export type AgentMessageSectionKind = "process" | "content" | "context";

export type AgentMessageSection = {
  id: string;
  kind: AgentMessageSectionKind;
  parts: AgentMessagePart[];
};
