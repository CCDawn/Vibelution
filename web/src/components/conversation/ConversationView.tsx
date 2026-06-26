import {
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Download,
  ExternalLink,
  ImagePlus,
  Link2,
  LoaderCircle,
  MessageSquarePlus,
  Pencil,
  Square,
  X,
  Search,
  Sparkles,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import { DragEvent, ReactNode, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  ChatNextStateSignalSummary,
  ConversationMessage,
  MentalStateSnapshot,
  SessionReferenceAttachment,
  SessionTurnError,
} from "../../api/types";
import { fetchJson } from "../../api/client";
import { useAppI18n } from "../../i18n/useAppI18n";
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import { COMPOSER_SESSION_REFERENCE_MIME } from "./conversationConstants";
import {
  buildConversationOperationGroups,
  buildConversationReActOperationGroups,
  type ConversationOperation,
  type ConversationOperationKind,
  type ConversationReActOperationGroup,
} from "./conversationOperations";
import {
  buildConversationTimelineItems,
  type ConversationTimelineItem,
} from "./conversationTimeline";
import {
  hasResponseBlock,
  hasThoughtBlock,
  hasMentalBlock,
  hasToolBlock,
  hasUserContent,
  imageArtifactForMessage,
  isAgentInboxMessage,
  isGroupRoomTranscriptMessage,
  isRuntimeNoticeMessage,
  isTurnErrorMessage,
  researchOrgMessageChips,
} from "./messageSections";
import { parseResponseSegments, ResponseSegment } from "./messageResponseSegments";
import styles from "./ConversationView.module.css";

const RUNNING_OPERATION_STATUSES = new Set(["queued", "pending", "running", "thinking", "tooling", "answering"]);
const DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT = 1;
const INITIAL_VISIBLE_MESSAGE_COUNT = 14;
const INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT = 36;
const RESPONSE_PARSE_CACHE_LIMIT = 80;
const MARKDOWN_PARSE_CACHE_LIMIT = 160;
const RESPONSE_PREWARM_MESSAGE_LIMIT = 8;
const COMPUTER_USE_TOOL_NAME = "computer_use_task_tool";

export type ConversationProcessDisplayMode = "answer" | "trace";

type OperationDetailKind = "thought" | "status" | "tool";
type OperationDetailRow = { label: string; value: string };

type ComposerDragData = {
  files?: ArrayLike<File> | Iterable<File> | null;
  items?: ArrayLike<DataTransferItem> | Iterable<DataTransferItem> | null;
  types?: ArrayLike<string> | Iterable<string> | null;
  getData?: (format: string) => string;
} | null | undefined;

export { COMPOSER_SESSION_REFERENCE_MIME } from "./conversationConstants";

export function extractComposerImageDropFiles(data: ComposerDragData): File[] {
  const files = data?.files;
  if (!files) {
    return [];
  }
  return Array.from(files).filter((file) => file.type.startsWith("image/"));
}

export function hasComposerImageDragPayload(data: ComposerDragData): boolean {
  if (extractComposerImageDropFiles(data).length > 0) {
    return true;
  }
  const items = data?.items;
  if (!items) {
    return false;
  }
  return Array.from(items).some((item) => item.kind === "file" && item.type.startsWith("image/"));
}

export function extractComposerSessionReferenceDrop(data: ComposerDragData): SessionReferenceAttachment | null {
  const types = data?.types ? Array.from(data.types) : [];
  if (!types.includes(COMPOSER_SESSION_REFERENCE_MIME) || !data?.getData) {
    return null;
  }
  try {
    const raw = data.getData(COMPOSER_SESSION_REFERENCE_MIME);
    const parsed = JSON.parse(raw) as Partial<SessionReferenceAttachment>;
    const sessionId = String(parsed.sessionId ?? "").trim();
    if (!sessionId) {
      return null;
    }
    return {
      referenceId: String(parsed.referenceId ?? "").trim() || `ref-${sessionId}`,
      kind: "session",
      sessionId,
      title: String(parsed.title ?? "").trim(),
      agentId: String(parsed.agentId ?? "").trim(),
      agentCode: String(parsed.agentCode ?? "").trim(),
      agentDisplayName: String(parsed.agentDisplayName ?? "").trim(),
      summary: String(parsed.summary ?? "").trim(),
      createdAt: String(parsed.createdAt ?? "").trim(),
    };
  } catch {
    return null;
  }
}

export function hasComposerSessionReferenceDragPayload(data: ComposerDragData): boolean {
  return Boolean(extractComposerSessionReferenceDrop(data));
}

type MarkdownBlock =
  | { type: "heading"; level: 1 | 2 | 3 | 4; content: string }
  | { type: "paragraph"; content: string }
  | { type: "image"; alt: string; url: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "unorderedList"; items: string[] }
  | { type: "orderedList"; items: string[] }
  | { type: "divider" };

type ComputerUseResult = {
  status: string;
  sessionId: string;
  summary: string;
  steps: Array<{ index?: number; action?: string; summary?: string; status?: string }>;
  screenshotUrl: string;
  needsConfirmation: boolean;
  error: string;
};

const STREAMING_STATUS_CONTENT_MARKERS = [
  "正在请求模型",
  "等待首个响应片段",
  "上下文已组装完成",
  "正在进入 llm 调用",
  "requesting the model",
  "waiting for the first response chunk",
  "context is assembled",
  "llm call is starting",
];

function StreamingResponseContent({ content }: { content: string }) {
  const visibleContent = String(content ?? "");
  if (!visibleContent) {
    return null;
  }
  return (
    <div className={`${styles.markdownBody} ${styles.streamingResponseText}`}>
      <p className={styles.streamingResponseParagraph}>{visibleContent}</p>
    </div>
  );
}

function lightweightJsonSignal(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return `s:${value.length}:${value.slice(0, 64)}`;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `a:${value.length}:${value.slice(0, 6).map((item) => lightweightJsonSignal(item)).join(",")}`;
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .slice(0, 12)
      .map(([key, item]) => `${key}:${lightweightJsonSignal(item)}`)
      .join(",");
  }
  return String(value);
}

function lightweightTextSignal(value: unknown): string {
  const text = String(value ?? "");
  if (!text) {
    return "";
  }
  return `${text.length}:${text.slice(0, 96)}:${text.slice(-32)}`;
}

function operationDetailsKind(operation: ConversationOperation): OperationDetailKind {
  if (operation.kind === "thought") {
    return "thought";
  }
  if (operation.kind === "status") {
    return "status";
  }
  return "tool";
}

function DeferredOperationDetails({
  operation,
  expanded,
  detailsId,
  kind,
  buildDetailRows,
  className,
}: {
  operation: ConversationOperation;
  expanded: boolean;
  detailsId: string;
  kind: OperationDetailKind;
  buildDetailRows: (operation: ConversationOperation) => OperationDetailRow[];
  className?: string;
}) {
  const deferredExpanded = useDeferredValue(expanded);
  const detailRows = deferredExpanded ? buildDetailRows(operation) : [];
  if (!deferredExpanded) {
    return null;
  }
  return (
    <div
      id={detailsId}
      className={
        kind === "thought"
          ? `${styles.operationDetails} ${styles.operationDetails_thought} ${className || ""}`.trim()
          : `${styles.operationDetails} ${className || ""}`.trim()
      }
    >
      {detailRows.map((row) => (
        <div key={`${operation.id}-${row.label}`} className={styles.operationDetailRow}>
          <span className={styles.operationDetailLabel}>{row.label}</span>
          <pre className={styles.operationDetailValue}>{row.value}</pre>
        </div>
      ))}
    </div>
  );
}

export function buildTimelineScrollSignal(messages: ConversationMessage[]) {
  return messages
    .map((message) => {
      const contentSignal = message.streaming
        ? ""
        : [message.content.length, message.thought?.length ?? 0].join(":");
      const mentalSnapshot = message.mentalSnapshot;
      const mentalSignal = mentalSnapshot
        ? [
            mentalSnapshot.mood,
            mentalSnapshot.feeling,
            mentalSnapshot.whisper,
            mentalSnapshot.summary,
            mentalSnapshot.cognitiveState,
            mentalSnapshot.confidence,
            mentalSnapshot.sampleSize,
            mentalSnapshot.interventionCount,
            mentalSnapshot.updatedAt,
            mentalSnapshot.source,
            mentalSnapshot.intervention ?? "",
            JSON.stringify(mentalSnapshot.metrics ?? {}),
          ].join(":")
        : "";
      const toolSignal = (message.toolCalls ?? [])
        .map((toolCall) =>
          [
            toolCall.name,
            toolCall.status,
            toolCall.summary ?? "",
            lightweightJsonSignal(toolCall.arguments ?? {}),
            lightweightTextSignal(toolCall.resultPreview ?? ""),
            toolCall.error ?? "",
            toolCall.durationMs ?? "",
            toolCall.timeoutSeconds ?? "",
            toolCall.tracePath ?? "",
          ].join(":"),
        )
        .join("|");
      const feedbackSignal = (message.feedbackEvents ?? [])
        .map((event) =>
          [
            event.sequence,
            event.kind,
            event.status,
            event.name ?? "",
            event.summary ?? "",
            lightweightTextSignal(event.resultPreview ?? ""),
            event.error ?? "",
            event.relatedThoughtSequence ?? "",
          ].join(":"),
        )
        .join("|");
      const metadataSignal = message.metadata
        ? [
            String(message.metadata.kind ?? ""),
            String(message.metadata.status ?? ""),
            String(message.metadata.artifactId ?? ""),
            String(message.metadata.imageUrl ?? ""),
            String(message.metadata.downloadUrl ?? ""),
          ].join(":")
        : "";
      return [
        message.id,
        contentSignal,
        feedbackSignal,
        toolSignal,
        mentalSignal,
        metadataSignal,
        message.streaming ? 1 : 0,
      ].join(":");
    })
    .join("|");
}

export function buildStreamingTimelineScrollSignal(messages: ConversationMessage[]) {
  return messages
    .filter((message) => message.streaming)
    .map((message) => [message.id, message.content.length, message.thought?.length ?? 0].join(":"))
    .join("|");
}

function isBusyConversationPhase(phase: string) {
  return ["queued", "running", "stopping"].includes(String(phase || "").trim().toLowerCase());
}

function userAvatarSymbol(preset: string | undefined, label: string) {
  const normalized = String(preset ?? "").trim().toLowerCase();
  if (normalized === "spark") {
    return "*";
  }
  if (normalized === "codex") {
    return "C";
  }
  if (normalized === "minimal") {
    return ".";
  }
  return label.trim().slice(0, 1).toUpperCase() || "U";
}

export type TurnAvatarResolution = {
  imageUrl?: string;
  fallback: string;
};

type TurnAvatarContent =
  | TurnAvatarResolution
  | { icon: "groupTranscript" };

function renderTurnAvatarContent(resolution: TurnAvatarContent) {
  if ("icon" in resolution) {
    return <MessageSquarePlus size={17} />;
  }
  if (resolution.imageUrl) {
    return <img src={resolution.imageUrl} alt="" className={styles.turnAvatarImage} />;
  }
  return resolution.fallback;
}

function resolveMessageTurnAvatar(
  message: ConversationMessage,
  options: {
    resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
    assistantAvatarImageUrl?: string;
    assistantAvatarFallback?: string;
    assistantLabel: string;
    userAvatarImageUrl?: string;
    userAvatarLabel: string;
    agentInboxMessage: boolean;
    groupTranscriptMessage: boolean;
  },
): TurnAvatarContent {
  if (options.groupTranscriptMessage) {
    return { icon: "groupTranscript" };
  }
  if (options.agentInboxMessage) {
    const resolved = options.resolveTurnAvatar?.(message);
    if (resolved) {
      return resolved;
    }
    return { fallback: "?" };
  }
  if (message.role === "assistant") {
    return {
      imageUrl: options.assistantAvatarImageUrl,
      fallback: options.assistantAvatarFallback || options.assistantLabel.trim().slice(0, 2) || "AI",
    };
  }
  return {
    imageUrl: options.userAvatarImageUrl,
    fallback: options.userAvatarLabel,
  };
}

function metadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

function isCliAgentLifecycleMessage(message: ConversationMessage) {
  return metadataText(message.metadata, "kind") === "cli_agent_lifecycle";
}

function cliAgentLifecycleLabel(message: ConversationMessage, lang: "zh" | "en") {
  const label = metadataText(message.metadata, "label") || metadataText(message.metadata, "adapterId") || "CLI Agent";
  const event = metadataText(message.metadata, "event") || metadataText(message.metadata, "status");
  if (event === "closed") {
    return lang === "zh" ? `终端已关闭 · ${label}` : `Terminal closed · ${label}`;
  }
  return lang === "zh" ? `终端状态 · ${label}` : `Terminal status · ${label}`;
}

function cliAgentLifecycleDetail(message: ConversationMessage) {
  return metadataText(message.metadata, "cliRunId")
    || metadataText(message.metadata, "terminalSessionId")
    || message.content;
}

function agentInboxSourceLabel(message: ConversationMessage) {
  const metadata = message.metadata;
  const sourceLabel = [
    metadataText(metadata, "sourceAgentCode"),
    metadataText(metadata, "sourceAgentName"),
  ].filter(Boolean).join(" · ");
  if (sourceLabel) {
    return `Agent 私信 · ${sourceLabel}`;
  }
  const fallback = String(message.content ?? "").match(/^来源 Agent:\s*(.+)$/m)?.[1]?.trim();
  return fallback ? `Agent 私信 · ${fallback}` : "Agent 私信";
}

function agentInboxSummary(message: ConversationMessage) {
  const metadataSummary = metadataText(message.metadata, "summary");
  if (metadataSummary) {
    return metadataSummary;
  }
  const content = String(message.content ?? "");
  const summaryMatch = content.match(/^摘要:\s*([\s\S]*?)(?:\n\s*消息内容:|$)/m);
  const summary = summaryMatch?.[1]?.trim();
  if (summary) {
    return summary;
  }
  const bodyMatch = content.match(/^消息内容:\s*([\s\S]*)$/m);
  const body = bodyMatch?.[1]?.trim();
  if (body) {
    return body.replace(/\s+/g, " ").trim();
  }
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("[Agent 私信") && !line.startsWith("来源 Agent") && !line.startsWith("消息ID"))
    ?? "";
}

function turnErrorType(message: ConversationMessage) {
  const raw = message.metadata?.errorType ?? message.metadata?.error_type;
  return typeof raw === "string" ? raw.trim() : "";
}

function turnErrorReasonRows(message: ConversationMessage, lang: "zh" | "en") {
  const summary = metadataText(message.metadata, "reasonSummary") || metadataText(message.metadata, "reason_summary");
  const detail = metadataText(message.metadata, "reasonDetail") || metadataText(message.metadata, "reason_detail");
  const code = metadataText(message.metadata, "reasonCode") || metadataText(message.metadata, "reason_code");
  const httpStatus = metadataText(message.metadata, "httpStatus") || metadataText(message.metadata, "http_status");
  const providerErrorType = metadataText(message.metadata, "providerErrorType") || metadataText(message.metadata, "provider_error_type");
  const providerErrorMessage = metadataText(message.metadata, "providerErrorMessage") || metadataText(message.metadata, "provider_error_message");
  const provider = metadataText(message.metadata, "provider");
  const providerHost = metadataText(message.metadata, "providerHost") || metadataText(message.metadata, "provider_host");
  const model = metadataText(message.metadata, "model");
  return [
    httpStatus ? { label: lang === "zh" ? "状态码" : "Status", value: httpStatus } : null,
    summary ? { label: lang === "zh" ? "原因" : "Reason", value: summary } : null,
    detail ? { label: lang === "zh" ? "详情" : "Detail", value: detail } : null,
    providerErrorType ? { label: lang === "zh" ? "类型" : "Type", value: providerErrorType } : null,
    providerErrorMessage ? { label: lang === "zh" ? "上游" : "Upstream", value: providerErrorMessage } : null,
    provider || providerHost ? { label: lang === "zh" ? "通道" : "Provider", value: [provider, providerHost].filter(Boolean).join(" · ") } : null,
    model ? { label: lang === "zh" ? "模型" : "Model", value: model } : null,
    code ? { label: lang === "zh" ? "代码" : "Code", value: code } : null,
  ].filter((row): row is { label: string; value: string } => Boolean(row));
}

function turnErrorBannerRows(turnError: SessionTurnError, lang: "zh" | "en") {
  return [
    turnError.httpStatus ? { label: lang === "zh" ? "状态码" : "Status", value: String(turnError.httpStatus) } : null,
    turnError.reasonSummary ? { label: lang === "zh" ? "原因" : "Reason", value: turnError.reasonSummary } : null,
    turnError.reasonDetail ? { label: lang === "zh" ? "详情" : "Detail", value: turnError.reasonDetail } : null,
    turnError.providerErrorType ? { label: lang === "zh" ? "类型" : "Type", value: turnError.providerErrorType } : null,
    turnError.providerErrorMessage ? { label: lang === "zh" ? "上游" : "Upstream", value: turnError.providerErrorMessage } : null,
    turnError.provider || turnError.providerHost ? { label: lang === "zh" ? "通道" : "Provider", value: [turnError.provider, turnError.providerHost].filter(Boolean).join(" · ") } : null,
    turnError.model ? { label: lang === "zh" ? "模型" : "Model", value: turnError.model } : null,
    turnError.reasonCode ? { label: lang === "zh" ? "代码" : "Code", value: turnError.reasonCode } : null,
  ].filter((row): row is { label: string; value: string } => Boolean(row));
}

function groupRoomTranscriptLabel(message: ConversationMessage) {
  const metadata = message.metadata;
  const roomTitle = metadataText(metadata, "sourceRoomTitle");
  return roomTitle ? `群聊同步记录 · ${roomTitle}` : "群聊同步记录";
}

function mergeAdjacentTurnErrorMessages(previous: ConversationMessage, next: ConversationMessage): ConversationMessage {
  const previousThought = String(previous.thought ?? "").trim();
  const nextThought = String(next.thought ?? "").trim();
  const thought = [previousThought, nextThought]
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .join("\n\n");
  const toolCalls = [...(previous.toolCalls ?? [])];
  const seenToolCalls = new Set(toolCalls.map((toolCall) => JSON.stringify(toolCall)));
  for (const toolCall of next.toolCalls ?? []) {
    const key = JSON.stringify(toolCall);
    if (seenToolCalls.has(key)) {
      continue;
    }
    seenToolCalls.add(key);
    toolCalls.push(toolCall);
  }
  const feedbackEvents = [...(previous.feedbackEvents ?? [])];
  const seenFeedbackEvents = new Set(feedbackEvents.map((event) => JSON.stringify(event)));
  for (const event of next.feedbackEvents ?? []) {
    const key = JSON.stringify(event);
    if (seenFeedbackEvents.has(key)) {
      continue;
    }
    seenFeedbackEvents.add(key);
    feedbackEvents.push(event);
  }
  return {
    ...previous,
    thought: thought || undefined,
    mentalSnapshot: next.mentalSnapshot,
    toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
    feedbackEvents: feedbackEvents.length > 0 ? feedbackEvents : undefined,
    metadata: {
      ...(next.metadata ?? {}),
      ...(previous.metadata ?? {}),
    },
  };
}

type PreviewImageState = {
  src: string;
  alt: string;
  downloadUrl: string;
  downloadName: string | true;
};

type ComposerAttachment = {
  id: string;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

export function shouldShowNextStateSignalInConversation(
  signal: ChatNextStateSignalSummary,
  phase: string,
) {
  if (signal.kind === "user_continues") {
    return isBusyConversationPhase(phase);
  }
  return true;
}

export function safeConversationMarkdownUrl(rawUrl: string): string | null {
  const trimmed = String(rawUrl ?? "").trim();
  if (!trimmed || /[\u0000-\u001f\u007f]/.test(trimmed) || /\s/.test(trimmed)) {
    return null;
  }
  if (trimmed.startsWith("//")) {
    return null;
  }
  if (trimmed.startsWith("/") || trimmed.startsWith("./") || trimmed.startsWith("../") || trimmed.startsWith("#")) {
    return trimmed;
  }
  const schemeMatch = trimmed.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
  if (!schemeMatch) {
    return trimmed;
  }
  const scheme = schemeMatch[1].toLowerCase();
  return scheme === "http" || scheme === "https" ? trimmed : null;
}

export type ConversationViewProps = {
  sessionId: string;
  title: string;
  phase: string;
  messages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
  className?: string;
  density?: "default" | "compact";
  eyebrowLabel?: string;
  assistantDisplayName?: string;
  assistantAvatarImageUrl?: string;
  assistantAvatarFallback?: string;
  resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
  userDisplayName?: string;
  userAvatarPreset?: string;
  userAvatarImageUrl?: string;
  taskSummary?: string;
  defaultFileContext: string;
  summaryItems?: Array<{
    label: string;
    value: string;
  }>;
  stats?: Array<{
    label: string;
    value: string | number;
  }>;
  headerActions?: ReactNode;
  supplementalContent?: ReactNode;
  showHeader?: boolean;
  showSessionOverview?: boolean;
  showMentalSnapshots?: boolean;
  showComposer?: boolean;
  processDisplayMode?: ConversationProcessDisplayMode;
  autoScrollToLatest?: boolean;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerSafeGuidancePending?: boolean;
  composerInterruptGuidancePending?: boolean;
  composerError?: string;
  composerGuidance?: string;
  composerAttachments?: ComposerAttachment[];
  composerReferences?: SessionReferenceAttachment[];
  composerAttachmentInputDisabled?: boolean;
  turnError?: SessionTurnError | null;
  nextStateSignals?: ChatNextStateSignalSummary[];
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  safeGuidanceLabel?: string;
  safeGuidancePendingLabel?: string;
  interruptGuidanceLabel?: string;
  interruptGuidancePendingLabel?: string;
  editingMessageId?: string;
  editUserMessageLabel?: string;
  editUserMessageDisabled?: boolean;
  composerModeNotice?: string;
  cancelComposerModeLabel?: string;
  onComposerChange: (value: string) => void;
  onAddComposerAttachments?: (files: FileList | File[]) => void;
  onRemoveComposerAttachment?: (attachmentId: string) => void;
  onAddComposerReference?: (reference: SessionReferenceAttachment) => void;
  onRemoveComposerReference?: (referenceId: string) => void;
  onEditUserMessage?: (message: ConversationMessage) => void;
  onCancelComposerMode?: () => void;
  onSubmit: () => void;
  onStop?: () => void;
  onSafeGuidance?: () => void;
  onInterruptGuidance?: () => void;
};

export function ConversationView({
  sessionId,
  title,
  phase,
  messages,
  activeTurnMessage,
  className,
  density = "default",
  eyebrowLabel,
  assistantDisplayName,
  assistantAvatarImageUrl,
  assistantAvatarFallback,
  resolveTurnAvatar,
  userDisplayName,
  userAvatarPreset,
  userAvatarImageUrl,
  taskSummary,
  defaultFileContext,
  summaryItems,
  stats,
  headerActions,
  supplementalContent,
  showHeader = true,
  showSessionOverview = true,
  showMentalSnapshots = true,
  showComposer = true,
  processDisplayMode = "answer",
  autoScrollToLatest = true,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerSafeGuidancePending = false,
  composerInterruptGuidancePending = false,
  composerError,
  composerGuidance,
  composerAttachments = [],
  composerReferences = [],
  composerAttachmentInputDisabled,
  turnError,
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  safeGuidanceLabel,
  safeGuidancePendingLabel,
  interruptGuidanceLabel,
  interruptGuidancePendingLabel,
  editingMessageId,
  editUserMessageLabel,
  editUserMessageDisabled,
  composerModeNotice,
  cancelComposerModeLabel,
  onComposerChange,
  onAddComposerAttachments,
  onRemoveComposerAttachment,
  onAddComposerReference,
  onRemoveComposerReference,
  onEditUserMessage,
  onCancelComposerMode,
  onSubmit,
  onStop,
  onSafeGuidance,
  onInterruptGuidance,
}: ConversationViewProps) {
  void composerGuidance;
  void interruptGuidanceLabel;
  void interruptGuidancePendingLabel;
  void onInterruptGuidance;
  const { lang, t, statusLabel } = useAppI18n();
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const initializedSessionRef = useRef("");
  const atBottomRef = useRef(true);
  const lastComposerFocusSignalRef = useRef("");
  const defaultExpansionRef = useRef<Record<string, Record<string, boolean>>>({});
  const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map());
  const markdownBlockCacheRef = useRef<Map<string, MarkdownBlock[]>>(new Map());
  const [sectionExpansion, setSectionExpansion] = useState<Record<string, Record<string, boolean>>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [previewImage, setPreviewImage] = useState<PreviewImageState | null>(null);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const [allMessagesVisible, setAllMessagesVisible] = useState(false);
  const [computerUseSessionResults, setComputerUseSessionResults] = useState<Record<string, ComputerUseResult>>({});
  const [computerUseSessionPending, setComputerUseSessionPending] = useState<Record<string, "confirm" | "cancel" | undefined>>({});
  const resolvedActionMode = composerActionMode ?? "send";
  const hasComposerAttachments = composerAttachments.length > 0;
  const hasComposerReferences = composerReferences.length > 0;
  const attachmentInputDisabled = composerAttachmentInputDisabled ?? composerDisabled;
  const resolvedActionDisabled =
    composerActionDisabled
    ?? (resolvedActionMode === "stop" ? composerDisabled : composerDisabled || (!composerValue.trim() && !hasComposerAttachments && !hasComposerReferences));
  const resolvedActionLabel =
    resolvedActionMode === "stop" ? (stopLabel ?? t("stop")) : (submitLabel ?? t("send"));
  const resolvedPendingLabel =
    resolvedActionMode === "stop"
      ? (stopPendingLabel ?? t("stopPending"))
      : (submitPendingLabel ?? t("sendPending"));
  const assistantLabel = assistantDisplayName?.trim() || t("agent");
  const userLabel = userDisplayName?.trim() || t("operator");
  const userAvatarLabel = userAvatarSymbol(userAvatarPreset, userLabel);
  const handlePrimaryAction = resolvedActionMode === "stop" ? onStop ?? onSubmit : onSubmit;
  const runningGuidanceActionsEnabled = resolvedActionMode === "stop";
  const guidanceActionDisabled =
    !composerValue.trim() || composerDisabled || composerSafeGuidancePending || composerInterruptGuidancePending;
  const guidanceDraftReady = Boolean(composerValue.trim());
  const showSafeGuidanceAction = runningGuidanceActionsEnabled && guidanceDraftReady;
  const composerCanAcceptImageDrop = Boolean(onAddComposerAttachments) && !attachmentInputDisabled;
  const composerCanAcceptReferenceDrop = Boolean(onAddComposerReference) && !composerDisabled;
  const answerOnlyProcessMode = processDisplayMode === "answer";
  const timestampFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    [lang],
  );

  useEffect(() => {
    if (!composerCanAcceptImageDrop && !composerCanAcceptReferenceDrop && composerDragActive) {
      setComposerDragActive(false);
    }
  }, [composerCanAcceptImageDrop, composerCanAcceptReferenceDrop, composerDragActive]);

  function handleComposerDragEnter(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragOver(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }
    setComposerDragActive(false);
  }

  function handleComposerDrop(event: DragEvent<HTMLDivElement>) {
    const reference = composerCanAcceptReferenceDrop ? extractComposerSessionReferenceDrop(event.dataTransfer) : null;
    if (reference && onAddComposerReference) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      setComposerDragActive(false);
      onAddComposerReference(reference);
      return;
    }
    if (!composerCanAcceptImageDrop || !onAddComposerAttachments) {
      setComposerDragActive(false);
      return;
    }
    const files = extractComposerImageDropFiles(event.dataTransfer);
    if (!files.length) {
      setComposerDragActive(false);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(false);
    onAddComposerAttachments(files);
  }

  const latestUserMessage = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.content ?? "",
    [messages],
  );
  const latestUserMessageId = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.id ?? "",
    [messages],
  );
  const lastMessageTimestamp = useMemo(
    () => [...messages].reverse().find((message) => message.timestamp)?.timestamp ?? "",
    [messages],
  );

  const taskFocus = compactPreview(taskSummary || latestUserMessage || title);
  const fileContext = defaultFileContext || "workspace";
  const resolvedSummaryItems = summaryItems ?? [
    { label: t("taskFocus"), value: taskFocus },
    { label: t("fileContext"), value: fileContext },
    { label: t("status"), value: statusLabel(phase) },
    { label: t("lastUpdated"), value: lastMessageTimestamp ? formatTimestamp(lastMessageTimestamp) : "--" },
  ];
  const resolvedStats = stats ?? [];
  const displayMessages = useMemo(
    () => {
      const visibleMessages = messages.filter((message) => !isRuntimeNoticeMessage(message));
      const mergedMessages: ConversationMessage[] = [];
      for (const message of visibleMessages) {
        const previous = mergedMessages[mergedMessages.length - 1];
        if (
          previous
          && isTurnErrorMessage(previous)
          && isTurnErrorMessage(message)
          && normalizeNoticeText(previous.content) === normalizeNoticeText(message.content)
        ) {
          mergedMessages[mergedMessages.length - 1] = mergeAdjacentTurnErrorMessages(previous, message);
          continue;
        }
        mergedMessages.push(message);
      }
      return mergedMessages;
    },
    [messages],
  );
  const hasVisibleTurnErrorMessage = useMemo(
    () => displayMessages.some((message) => isTurnErrorMessage(message)),
    [displayMessages],
  );
  const visibleMessageCount = allMessagesVisible
    ? displayMessages.length
    : Math.min(displayMessages.length, INITIAL_VISIBLE_MESSAGE_COUNT);
  const hiddenMessageCount = Math.max(0, displayMessages.length - visibleMessageCount);
  const timelineMessages = useMemo(
    () => displayMessages.slice(displayMessages.length - visibleMessageCount),
    [displayMessages, visibleMessageCount],
  );
  const activeTimelineMessages = useMemo(
    () => activeTurnMessage ? [...timelineMessages, activeTurnMessage] : timelineMessages,
    [activeTurnMessage, timelineMessages],
  );
  const imageArtifactUrlsBeforeMessage = useMemo(() => {
    const urlsByMessageId = new Map<string, Set<string>>();
    const seenImageUrls = new Set<string>();
    for (const message of displayMessages) {
      urlsByMessageId.set(message.id, new Set(seenImageUrls));
      const artifact = imageArtifactForMessage(message);
      if (!artifact) {
        continue;
      }
      addComparableImageUrl(seenImageUrls, artifact.imageUrl);
      addComparableImageUrl(seenImageUrls, artifact.downloadUrl);
    }
    return urlsByMessageId;
  }, [displayMessages]);
  const latestToolCalls = useMemo(
    () =>
      [...displayMessages]
        .reverse()
        .find((message) => !isTurnErrorMessage(message) && (message.toolCalls?.length ?? 0) > 0)?.toolCalls ?? [],
    [displayMessages],
  );
  const defaultExpandedResponseIds = useMemo(() => {
    const ids: string[] = [];
    for (let index = timelineMessages.length - 1; index >= 0; index -= 1) {
      const message = timelineMessages[index];
      if (!hasResponseBlock(message)) {
        continue;
      }
      ids.push(message.id);
      if (ids.length >= DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT) {
        break;
      }
    }
    return new Set(ids);
  }, [timelineMessages]);
  const timelineSignalMessages = useMemo(
    () =>
      showMentalSnapshots
        ? timelineMessages
        : timelineMessages.map((message) => ({ ...message, mentalSnapshot: undefined })),
    [showMentalSnapshots, timelineMessages],
  );
  const activeTimelineSignalMessages = useMemo(
    () =>
      showMentalSnapshots
        ? activeTimelineMessages
        : activeTimelineMessages.map((message) => ({ ...message, mentalSnapshot: undefined })),
    [activeTimelineMessages, showMentalSnapshots],
  );
  const timelineScrollSignal = useMemo(() => buildTimelineScrollSignal(timelineSignalMessages), [timelineSignalMessages]);
  const streamingTimelineScrollSignal = useMemo(
    () => buildStreamingTimelineScrollSignal(activeTimelineSignalMessages),
    [activeTimelineSignalMessages],
  );
  const hasSessionMeta = resolvedStats.length > 0 || latestToolCalls.length > 0;
  const hasMetaSection = showSessionOverview && (hasSessionMeta || Boolean(supplementalContent));
  const operationLabels = useMemo(
    () => ({
      thought: t("thoughtProcess"),
      mental: t("mentalProcess"),
      status: lang === "zh" ? "运行状态" : "Runtime status",
    }),
    [lang, t],
  );

  function formatTimestamp(timestamp: string) {
    if (!timestamp) {
      return "";
    }
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) {
      return timestamp;
    }
    return timestampFormatter.format(value);
  }

  function compactPreview(value: string, maxLength = 180) {
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return "";
    }
    if (normalized.length <= maxLength) {
      return normalized;
    }
    return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
  }

  function normalizeNoticeText(value: string) {
    return value.replace(/\s+/g, " ").trim().toLowerCase();
  }

  function addComparableImageUrl(target: Set<string>, url: string) {
    const normalized = comparableImageUrl(url);
    if (normalized) {
      target.add(normalized);
    }
  }

  function comparableImageUrl(url: string) {
    return previewUrlForImage(url).trim();
  }

  function openImagePreview(image: PreviewImageState) {
    setPreviewImage(image);
  }

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedSessionRef.current !== sessionId) {
      initializedSessionRef.current = sessionId;
      timeline.scrollTop = timeline.scrollHeight;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return;
    }
    if (autoScrollToLatest && atBottomRef.current) {
      timeline.scrollTop = timeline.scrollHeight;
      setIsAtBottom(true);
    }
  }, [autoScrollToLatest, sessionId, timelineScrollSignal]);

  useEffect(() => {
    if (!streamingTimelineScrollSignal || !autoScrollToLatest || !atBottomRef.current) {
      return undefined;
    }
    const frameId = window.requestAnimationFrame(() => {
      const timeline = timelineRef.current;
      if (!timeline || !atBottomRef.current) {
        return;
      }
      timeline.scrollTop = timeline.scrollHeight;
      setIsAtBottom(true);
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [autoScrollToLatest, sessionId, streamingTimelineScrollSignal]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = () => {
      const distance = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
      const nextAtBottom = distance < 16;
      atBottomRef.current = nextAtBottom;
      setIsAtBottom(nextAtBottom);
    };
    handleScroll();
    timeline.addEventListener("scroll", handleScroll);
    return () => timeline.removeEventListener("scroll", handleScroll);
  }, [sessionId]);

  useEffect(() => {
    if (!previewImage) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewImage]);

  useEffect(() => {
    const focusSignal = String(editingMessageId || "").trim();
    if (!focusSignal || focusSignal === lastComposerFocusSignalRef.current || composerDisabled) {
      return;
    }
    lastComposerFocusSignalRef.current = focusSignal;
    const input = composerInputRef.current;
    if (!input) {
      return;
    }
    input.focus();
    const cursorPosition = input.value.length;
    input.setSelectionRange(cursorPosition, cursorPosition);
  }, [composerDisabled, editingMessageId]);

  useEffect(() => {
    setAllMessagesVisible(false);
    defaultExpansionRef.current = {};
    responseSegmentCacheRef.current.clear();
    markdownBlockCacheRef.current.clear();
    setSectionExpansion({});
  }, [sessionId]);

  useEffect(() => {
    const prewarmMessages = timelineMessages
      .filter((message) => message.role === "assistant" && !message.streaming && hasResponseBlock(message))
      .slice(-RESPONSE_PREWARM_MESSAGE_LIMIT);
    if (!prewarmMessages.length) {
      return undefined;
    }
    let cancelled = false;
    let timeoutId: number | undefined;
    let index = 0;
    const prewarmNext = () => {
      if (cancelled) {
        return;
      }
      const message = prewarmMessages[index];
      if (message) {
        getCachedResponseSegments(message.content).forEach((segment) => {
          if (
            segment.kind !== "code"
            && !segment.language
            && !(["commit", "verification"].includes(segment.kind) && segment.content.includes("\n"))
          ) {
            getCachedMarkdownBlocks(segment.content);
          }
        });
      }
      index += 1;
      if (index < prewarmMessages.length) {
        timeoutId = window.setTimeout(prewarmNext, 24);
      }
    };
    timeoutId = window.setTimeout(prewarmNext, 48);
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [sessionId, timelineMessages]);

  function getCachedResponseSegments(content: string) {
    const key = String(content ?? "");
    const cached = responseSegmentCacheRef.current.get(key);
    if (cached) {
      responseSegmentCacheRef.current.delete(key);
      responseSegmentCacheRef.current.set(key, cached);
      return cached;
    }
    const parsed = parseResponseSegments(key);
    responseSegmentCacheRef.current.set(key, parsed);
    trimOldestCacheEntries(responseSegmentCacheRef.current, RESPONSE_PARSE_CACHE_LIMIT);
    return parsed;
  }

  function getCachedMarkdownBlocks(content: string) {
    const key = String(content ?? "");
    const cached = markdownBlockCacheRef.current.get(key);
    if (cached) {
      markdownBlockCacheRef.current.delete(key);
      markdownBlockCacheRef.current.set(key, cached);
      return cached;
    }
    const parsed = parseMarkdownBlocks(key);
    markdownBlockCacheRef.current.set(key, parsed);
    trimOldestCacheEntries(markdownBlockCacheRef.current, MARKDOWN_PARSE_CACHE_LIMIT);
    return parsed;
  }

  function trimOldestCacheEntries<T>(cache: Map<string, T>, limit: number) {
    while (cache.size > limit) {
      const oldestKey = cache.keys().next().value;
      if (oldestKey === undefined) {
        return;
      }
      cache.delete(oldestKey);
    }
  }

  function cognitiveStateLabel(snapshot: MentalStateSnapshot | undefined) {
    const value = String(snapshot?.cognitiveState ?? "").trim().toLowerCase() || "unknown";
    const keyMap = {
      unknown: "mentalCognitiveState_unknown",
      normal: "mentalCognitiveState_normal",
      productive: "mentalCognitiveState_productive",
      looping: "mentalCognitiveState_looping",
      thrashing: "mentalCognitiveState_thrashing",
      tunnel_vision: "mentalCognitiveState_tunnel_vision",
      disoriented: "mentalCognitiveState_disoriented",
    } as const;
    const key = keyMap[value as keyof typeof keyMap];
    return key ? t(key) : snapshot?.cognitiveState ?? "";
  }

  function mentalSourceLabel(source: string | undefined) {
    const value = String(source ?? "").trim().toLowerCase();
    if (value === "state") {
      return t("mentalSourceState");
    }
    if (value === "diagnosis") {
      return t("mentalSourceDiagnosis");
    }
    if (value === "runtime") {
      return t("runtime");
    }
    return source ?? "";
  }

  function getExpansionState(messageId: string, section: string, defaultExpanded: boolean) {
    const explicit = sectionExpansion[messageId]?.[section];
    if (explicit !== undefined) {
      return explicit;
    }
    const messageDefaults = defaultExpansionRef.current[messageId] ?? {};
    if (messageDefaults[section] === undefined) {
      defaultExpansionRef.current = {
        ...defaultExpansionRef.current,
        [messageId]: {
          ...messageDefaults,
          [section]: defaultExpanded,
        },
      };
      return defaultExpanded;
    }
    return messageDefaults[section];
  }

  function toggleSection(messageId: string, section: string, defaultExpanded: boolean) {
    setSectionExpansion((current) => ({
      ...current,
      [messageId]: {
        ...(current[messageId] ?? {}),
        [section]: !getExpansionState(messageId, section, defaultExpanded),
      },
    }));
  }

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setIsAtBottom(true);
  }

  function formatDuration(seconds: number | null) {
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
      return "";
    }
    if (seconds >= 60) {
      const minutes = Math.floor(seconds / 60);
      const rest = Math.round(seconds % 60);
      return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
    }
    if (seconds < 10) {
      return `${seconds.toFixed(1)}s`;
    }
    return `${Math.round(seconds)}s`;
  }

  function operationIcon(kind: ConversationOperationKind, label: string) {
    const normalized = label.trim().toLowerCase();
    if (kind === "thought") {
      return <Sparkles size={17} />;
    }
    if (kind === "mental") {
      return <BrainCircuit size={17} />;
    }
    if (normalized.includes("search") || normalized.includes("搜索")) {
      return <Search size={17} />;
    }
    if (normalized.includes("http") || normalized.includes("访问") || normalized.includes("open")) {
      return <ExternalLink size={17} />;
    }
    if (
      normalized.includes("exec")
      || normalized.includes("command")
      || normalized.includes("shell")
      || normalized.includes("powershell")
      || normalized.includes("npm")
      || normalized.includes("pytest")
      || normalized.includes("命令")
    ) {
      return <TerminalSquare size={17} />;
    }
    return <Wrench size={17} />;
  }

  function operationTone(operation: ConversationOperation) {
    if (operation.kind === "thought") {
      return "thought";
    }
    if (operation.kind === "mental") {
      return "mental";
    }
    if (operation.kind === "status") {
      return "status";
    }
    return "tool";
  }

  function operationStatusIcon(operation: ConversationOperation, animateRunning = true) {
    const status = operation.status.trim().toLowerCase();
    if (["done", "success", "completed", "succeeded"].includes(status)) {
      return <CheckCircle2 size={14} />;
    }
    if (isRunningOperationStatus(status)) {
      if (!animateRunning) {
        return <CircleDot size={14} />;
      }
      return (
        <>
          <LoaderCircle className={styles.statusSpinner} size={14} />
          <CircleDot className={styles.statusRunningDot} size={14} />
        </>
      );
    }
    return <CircleDot size={14} />;
  }

  function operationStatusTone(operation: ConversationOperation) {
    const status = operation.status.trim().toLowerCase();
    if (["failed", "error", "timeout"].includes(status)) {
      return "failed";
    }
    if (isRunningOperationStatus(status)) {
      return "running";
    }
    if (["done", "success", "completed", "succeeded"].includes(status)) {
      return "done";
    }
    return "pending";
  }

  function isRunningOperationStatus(status: string) {
    return RUNNING_OPERATION_STATUSES.has(status.trim().toLowerCase());
  }

  function operationLabel(operation: ConversationOperation) {
    if (operation.kind !== "tool") {
      return operation.label;
    }
    const normalized = operation.label.trim();
    if (!normalized) {
      return t("toolProcess");
    }
    if (
      normalized.startsWith("搜索")
      || normalized.startsWith("访问")
      || normalized.toLowerCase().startsWith("search ")
      || normalized.toLowerCase().startsWith("open ")
    ) {
      return normalized;
    }
    return normalized;
  }

  function operationGroupTitle(kind: ConversationOperationKind, count: number) {
    if (kind === "thought") {
      return t("thoughtProcess");
    }
    if (kind === "mental") {
      return t("mentalProcess");
    }
    return `${t("toolProcess")} ${count}`;
  }

  function operationTimelineTitle(operations: ConversationOperation[]) {
    if (operations.length > 0) {
      return lang === "zh" ? "执行过程" : "Execution trace";
    }
    const thoughtCount = operations.filter((operation) => operation.kind === "thought").length;
    const toolCount = operations.filter((operation) => operation.kind === "tool").length;
    const mentalCount = operations.filter((operation) => operation.kind === "mental").length;
    const parts = [
      thoughtCount > 0 ? `${t("thoughtProcess")} ${thoughtCount}` : "",
      toolCount > 0 ? `${t("toolProcess")} ${toolCount}` : "",
      mentalCount > 0 ? `${t("mentalProcess")} ${mentalCount}` : "",
    ].filter(Boolean);
    return parts.length > 0 ? parts.join(" · ") : `${t("toolProcess")} ${operations.length}`;
  }

  function operationCollectionTone(operations: ConversationOperation[]) {
    if (operations.some((operation) => operationStatusTone(operation) === "failed")) {
      return "failed";
    }
    if (operations.some((operation) => operationStatusTone(operation) === "running")) {
      return "running";
    }
    if (operations.length > 0 && operations.every((operation) => operationStatusTone(operation) === "done")) {
      return "done";
    }
    return "pending";
  }

  function reActGroupTone(group: ConversationReActOperationGroup) {
    return operationCollectionTone(group.operations);
  }

  function operationStateLabel(tone: string) {
    const stateLabel = tone === "running"
      ? lang === "zh" ? "执行中" : "Running"
      : tone === "failed"
        ? lang === "zh" ? "执行失败" : "Failed"
        : tone === "done"
          ? lang === "zh" ? "已完成" : "Done"
          : lang === "zh" ? "待处理" : "Pending";
    return stateLabel;
  }

  function compactRequestStateLabel(tone: string) {
    if (tone === "running") {
      return lang === "zh" ? "正在请求" : "Requesting";
    }
    if (tone === "failed") {
      return lang === "zh" ? "请求失败" : "Request failed";
    }
    if (tone === "done") {
      return lang === "zh" ? "已完成" : "Done";
    }
    return lang === "zh" ? "等待请求" : "Pending request";
  }

  function processSummaryTitle(tone: string) {
    if (tone === "running") {
      return lang === "zh" ? "生成中" : "Generating";
    }
    if (tone === "failed") {
      return lang === "zh" ? "过程失败" : "Process failed";
    }
    if (tone === "done") {
      return lang === "zh" ? "过程" : "Process";
    }
    return lang === "zh" ? "过程待处理" : "Process pending";
  }

  function processSummaryMeta(operations: ConversationOperation[]) {
    const thoughtCount = operations.filter((operation) => operation.kind === "thought").length;
    const toolCount = operations.filter((operation) => operation.kind === "tool").length;
    const mentalCount = operations.filter((operation) => operation.kind === "mental").length;
    const visibleStatusCount = operations.filter(
      (operation) => operation.kind === "status" && shouldShowTimelineOperation(operation),
    ).length;
    const parts = [
      thoughtCount > 0 ? `${t("thoughtProcess")} ${thoughtCount}` : "",
      toolCount > 0 ? `${t("toolProcess")} ${toolCount}` : "",
      mentalCount > 0 ? `${t("mentalProcess")} ${mentalCount}` : "",
      visibleStatusCount > 0 ? `${lang === "zh" ? "状态" : "Status"} ${visibleStatusCount}` : "",
    ].filter(Boolean);
    return parts.length > 0 ? parts.join(" · ") : compactRequestStateLabel(operationCollectionTone(operations));
  }

  function processSummaryPreview(operations: ConversationOperation[]) {
    const tone = operationCollectionTone(operations);
    const running = [...operations]
      .reverse()
      .find((operation) => isRunningOperationStatus(operation.status) && shouldShowTimelineOperation(operation));
    const failed = operations.find((operation) => operationStatusTone(operation) === "failed");
    if (tone !== "running" && tone !== "failed") {
      return "";
    }
    const readable = tone === "failed"
      ? operations.find((operation) => shouldShowTimelineOperation(operation) && operation.summary.trim())
      : undefined;
    const fallback = tone === "failed"
      ? operations.find((operation) => operation.summary.trim() || operation.error?.trim())
      : undefined;
    const preview = tone === "running"
      ? running?.summary.trim()
        || running?.resultPreview?.trim()
        || (running ? operationLabel(running).trim() : "")
      : failed?.error?.trim()
        || failed?.summary.trim()
        || readable?.summary.trim()
        || fallback?.error?.trim()
        || fallback?.summary.trim()
        || "";
    return compactPreview(preview || "", 120);
  }

  function isStreamingStatusPlaceholderContent(content: string) {
    const normalized = String(content ?? "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
    if (!normalized || normalized.length > 180) {
      return false;
    }
    return STREAMING_STATUS_CONTENT_MARKERS.some((marker) => normalized.includes(marker));
  }

  function compactStreamingStatusPlaceholder(content: string) {
    return compactPreview(String(content ?? "").replace(/\s+/g, " ").trim(), 92);
  }

  function processSummaryIcon(tone: string) {
    if (tone === "running") {
      return <LoaderCircle className={styles.statusSpinner} size={14} />;
    }
    if (tone === "failed") {
      return <TerminalSquare size={14} />;
    }
    if (tone === "done") {
      return <CheckCircle2 size={14} />;
    }
    return <CircleDot size={14} />;
  }

  function operationMatchesAny(operation: ConversationOperation, markers: string[]) {
    const haystack = [
      operation.rawLabel,
      operation.label,
      operation.summary,
      operation.resultPreview,
    ].map((item) => String(item ?? "").trim().toLowerCase()).join(" ");
    return markers.some((marker) => haystack.includes(marker));
  }

  function isInternalPipelineOperation(operation: ConversationOperation) {
    if (operation.kind !== "status") {
      return false;
    }
    return operationMatchesAny(operation, [
      "context_prepare",
      "agent_prepare",
      "model_request",
      "prepare context",
      "bind agent",
      "request model",
      "准备上下文",
      "准备对话上下文",
      "读取当前会话",
      "绑定 agent",
      "唤起对话 agent",
      "请求模型",
      "llm 调用",
      "首个响应片段等待中",
    ]);
  }

  function shouldShowTimelineOperation(operation: ConversationOperation) {
    if (operation.kind === "status") {
      return Boolean(operation.error?.trim());
    }
    return !isInternalPipelineOperation(operation) || Boolean(operation.error?.trim());
  }

  function reActGroupDurationLabel(group: ConversationReActOperationGroup) {
    const durations = group.operations
      .map((operation) => operation.durationSeconds)
      .filter((duration): duration is number => typeof duration === "number" && Number.isFinite(duration) && duration > 0);
    if (durations.length === 0) {
      return "";
    }
    return formatDuration(durations.reduce((total, duration) => total + duration, 0));
  }

  function reActActionOperations(group: ConversationReActOperationGroup) {
    return group.operations.filter((operation) => operation.kind === "tool");
  }

  function reActThoughtItems(group: ConversationReActOperationGroup) {
    const seen = new Set<string>();
    return group.operations
      .filter((operation) => operation.kind === "thought")
      .map((operation) => {
        const value = String(operation.resultPreview || operation.summary || "").trim();
        if (!value || seen.has(value)) {
          return null;
        }
        seen.add(value);
        return {
          id: `${operation.id}-thought`,
          value,
        };
      })
      .filter((item): item is { id: string; value: string } => item !== null);
  }

  function reActResultItems(group: ConversationReActOperationGroup) {
    return group.operations
      .filter((operation) => operation.kind === "tool" || (operation.kind === "status" && Boolean(operation.error?.trim())))
      .map((operation) => {
        if (operation.error?.trim()) {
          return {
            id: `${operation.id}-error`,
            label: operationLabel(operation),
            value: operation.error.trim(),
            tone: "failed",
          };
        }
        const result = readableOperationResult(operation);
        if (!result || result === operation.summary.trim() || operation.kind === "status") {
          return null;
        }
        return {
          id: `${operation.id}-result`,
          label: operationLabel(operation),
          value: result,
          tone: "default",
        };
      })
      .filter((item): item is { id: string; label: string; value: string; tone: string } => item !== null);
  }

  function readableOperationResult(operation: ConversationOperation) {
    const result = String(operation.resultPreview ?? "").trim();
    if (!result) {
      return "";
    }
    if (shouldKeepResultInDetailsOnly(operation, result)) {
      return "";
    }
    if (!/^[{[]/.test(result)) {
      return result;
    }
    try {
      const parsed = JSON.parse(result) as unknown;
      const summary = structuredResultSummary(parsed);
      if (summary) {
        return summary;
      }
      return lang === "zh" ? "返回结构化结果，可展开详情查看。" : "Structured result returned; expand details to inspect.";
    } catch {
      return result;
    }
  }

  function shouldKeepResultInDetailsOnly(operation: ConversationOperation, result: string) {
    if (operation.kind !== "tool" || operation.status !== "done") {
      return false;
    }
    const rawName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
    const commandLikeTool = [
      "cli_tool",
      "grep_search_tool",
      "read_file_tool",
      "glob_tool",
    ].some((name) => rawName === name || rawName.includes(name));
    if (!commandLikeTool) {
      return false;
    }
    const meaningfulLines = result.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const codeOrTerminalLike = /(^|\n)\s*(def |class |from |import |return |if |for |while |try:|except |const |let |function |\{|\}|\[STD(?:OUT|ERR)\])/.test(result);
    return result.length > 360 || meaningfulLines.length > 3 || codeOrTerminalLike;
  }

  function structuredResultSummary(value: unknown): string {
    if (typeof value === "string") {
      return value.trim();
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    if (Array.isArray(value)) {
      const primitiveItems = value
        .map((item) => structuredResultSummary(item))
        .filter(Boolean);
      return primitiveItems.slice(0, 3).join("\n");
    }
    if (!value || typeof value !== "object") {
      return "";
    }
    const record = value as Record<string, unknown>;
    const summaryKeys = [
      "summary",
      "message",
      "resultPreview",
      "stdoutPreview",
      "stderrPreview",
      "output",
      "text",
      "content",
      "title",
      "error",
      "status",
    ];
    for (const key of summaryKeys) {
      const summary = structuredResultSummary(record[key]);
      if (summary) {
        return summary;
      }
    }
    return "";
  }

  function shouldExpandReActGroupByDefault(group: ConversationReActOperationGroup) {
    const tone = reActGroupTone(group);
    return tone === "running" || tone === "failed" || tone === "pending";
  }

  function hasOperationDetails(operation: ConversationOperation) {
    return Boolean(
      Object.keys(operation.arguments ?? {}).length
      || operation.resultPreview
      || operation.error
      || operation.resultType
      || operation.resultLength !== undefined
      || operation.timeoutSeconds !== undefined
      || operation.tracePath,
    );
  }

  function operationDetailRows(operation: ConversationOperation): OperationDetailRow[] {
    const rows: OperationDetailRow[] = [];
    const args = operation.arguments ?? {};
    if (operation.kind === "status" && operation.resultPreview) {
      rows.push({ label: lang === "zh" ? "完整状态" : "Full status", value: operation.resultPreview });
    }
    if (Object.keys(args).length > 0) {
      rows.push({ label: t("toolCallArguments"), value: naturalRecordText(args) });
    }
    if (operation.resultPreview && operation.kind !== "status") {
      const readableResult = readableOperationResult(operation);
      rows.push({
        label: operation.kind === "thought" ? t("thoughtProcess") : t("toolCallResult"),
        value: readableResult || operation.resultPreview,
      });
    }
    if (operation.error) {
      rows.push({ label: t("toolCallError"), value: operation.error });
    }
    return rows;
  }

  function naturalRecordText(value: unknown): string {
    if (typeof value === "string") {
      return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    if (Array.isArray(value)) {
      return value
        .map((item, index) => {
          const text = naturalRecordText(item);
          return text ? `${index + 1}. ${text}` : "";
        })
        .filter(Boolean)
        .join("\n");
    }
    if (!value || typeof value !== "object") {
      return "";
    }
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = naturalRecordText(item);
        return text ? `${key}: ${text}` : "";
      })
      .filter(Boolean)
      .join("\n");
  }

  function computerUseResultForOperation(operation: ConversationOperation): ComputerUseResult | null {
    if (operation.kind !== "tool" || (operation.rawLabel ?? operation.label) !== COMPUTER_USE_TOOL_NAME) {
      return null;
    }
    const preview = String(operation.resultPreview ?? "").trim();
    if (!preview || !preview.startsWith("{")) {
      return null;
    }
    try {
      const payload = JSON.parse(preview) as Partial<ComputerUseResult>;
      const sessionId = String(payload.sessionId ?? "").trim();
      if (!sessionId) {
        return null;
      }
      const parsedResult = {
        status: String(payload.status ?? ""),
        sessionId,
        summary: String(payload.summary ?? ""),
        steps: Array.isArray(payload.steps) ? payload.steps : [],
        screenshotUrl: String(payload.screenshotUrl ?? ""),
        needsConfirmation: Boolean(payload.needsConfirmation),
        error: String(payload.error ?? ""),
      };
      return computerUseSessionResults[sessionId] ?? parsedResult;
    } catch {
      return null;
    }
  }

  function renderComputerUseResult(operation: ConversationOperation) {
    const result = computerUseResultForOperation(operation);
    if (!result) {
      return null;
    }
    const previewLabel = lang === "zh" ? "预览沙盒截图" : "Preview sandbox screenshot";
    const confirmLabel = lang === "zh" ? "确认继续" : "Confirm";
    const cancelLabel = lang === "zh" ? "停止任务" : "Stop";
    const pendingAction = computerUseSessionPending[result.sessionId];
    const imageAlt = result.summary || (lang === "zh" ? "Computer Use 沙盒截图" : "Computer Use sandbox screenshot");
    const confirmSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "confirm" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "approved_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    const cancelSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "cancel" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "cancelled_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    return (
      <section className={styles.computerUsePanel}>
        <div className={styles.computerUseHeader}>
          <span>{result.status || "computer_use"}</span>
          <code>{result.sessionId}</code>
        </div>
        {result.summary ? <p className={styles.computerUseSummary}>{result.summary}</p> : null}
        {result.screenshotUrl ? (
          <button
            type="button"
            className={`${styles.imageArtifactFrame} ${styles.imagePreviewButton}`}
            onClick={() =>
              openImagePreview({
                src: result.screenshotUrl,
                alt: imageAlt,
                downloadUrl: result.screenshotUrl,
                downloadName: true,
              })
            }
            aria-label={previewLabel}
            title={previewLabel}
          >
            <img className={styles.computerUseScreenshot} src={result.screenshotUrl} alt={imageAlt} loading="lazy" />
          </button>
        ) : null}
        {result.steps.length > 0 ? (
          <ol className={styles.computerUseSteps}>
            {result.steps.slice(0, 6).map((step, index) => (
              <li key={`${result.sessionId}-${step.index ?? index}`}>
                <span>{step.action || step.status || `${index + 1}`}</span>
                <p>{step.summary || step.status || ""}</p>
              </li>
            ))}
          </ol>
        ) : null}
        {result.error ? <p className={styles.computerUseError}>{result.error}</p> : null}
        {result.needsConfirmation || result.status === "running" ? (
          <div className={styles.computerUseActions}>
            {result.needsConfirmation ? (
              <button type="button" onClick={confirmSession} disabled={Boolean(pendingAction)}>
                {pendingAction === "confirm" ? (lang === "zh" ? "确认中" : "Confirming") : confirmLabel}
              </button>
            ) : null}
            <button type="button" onClick={cancelSession} disabled={Boolean(pendingAction)}>
              {pendingAction === "cancel" ? (lang === "zh" ? "停止中" : "Stopping") : cancelLabel}
            </button>
          </div>
        ) : null}
      </section>
    );
  }

  function renderOperationTimeline(operations: ConversationOperation[], options: { limitInitialRows?: boolean } = {}) {
    const shouldLimitRows = options.limitInitialRows && operations.length > INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT;
    const hiddenOperationCount = shouldLimitRows ? operations.length - INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT : 0;
    const visibleOperations = shouldLimitRows
      ? operations.slice(-INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT)
      : operations;
    return (
      <div className={styles.operationTimeline}>
        {hiddenOperationCount > 0 ? (
          <div className={styles.operationTimelineTrimmed}>
            {lang === "zh"
              ? `已折叠更早 ${hiddenOperationCount} 步执行记录`
              : `${hiddenOperationCount} earlier execution steps collapsed`}
          </div>
        ) : null}
        {visibleOperations.map((operation) => {
          const duration = formatDuration(operation.durationSeconds);
          const detailsId = `operation-detail-${operation.id}`;
          const detailsExpanded = getExpansionState(operation.id, "details", false);
          const canExpandDetails = hasOperationDetails(operation);
          const computerUseResult = renderComputerUseResult(operation);
          const detailToggleTitle = operation.kind === "thought"
            ? detailsExpanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden")
            : operation.kind === "status"
              ? detailsExpanded ? t("executionDetailsVisible") : t("executionDetailsHidden")
            : detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden");
          const operationClassName = [
            styles.operationItem,
            styles[`operationItem_${operationTone(operation)}`],
            isRunningOperationStatus(operation.status) ? styles.operationItemActive : "",
          ].filter(Boolean).join(" ");
          return (
            <div key={operation.id} className={styles.operationItemWrap}>
              <div className={operationClassName}>
                <span className={`${styles.operationIcon} ${styles[`operationIcon_${operation.kind}`]}`}>
                  {operationIcon(operation.kind, operation.label)}
                </span>
                <div className={styles.operationText}>
                  <span className={styles.operationName}>{operationLabel(operation)}</span>
                  {operation.summary ? (
                    <span className={styles.operationSummaryText}>{operation.summary}</span>
                  ) : null}
                </div>
                <span className={styles.operationStatus}>
                  {operationStatusIcon(operation)}
                  <span>{statusLabel(operation.status)}</span>
                </span>
                {duration ? <span className={styles.operationDuration}>{duration}</span> : null}
                {canExpandDetails ? (
                  <button
                    type="button"
                    className={styles.operationDetailToggle}
                    aria-expanded={detailsExpanded}
                    aria-controls={detailsId}
                    onClick={() => toggleSection(operation.id, "details", false)}
                    title={detailToggleTitle}
                  >
                    {detailsExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                ) : (
                  <span className={styles.operationChevron} aria-hidden="true">
                    {hasOperationDetails(operation) ? <ChevronRight size={16} /> : null}
                  </span>
                )}
              </div>
              {canExpandDetails ? (
                <DeferredOperationDetails
                  operation={operation}
                  expanded={detailsExpanded}
                  detailsId={detailsId}
                  kind={operationDetailsKind(operation)}
                  buildDetailRows={operationDetailRows}
                />
              ) : null}
              {computerUseResult}
            </div>
          );
        })}
      </div>
    );
  }

  function activeTimelineItemId(message: ConversationMessage, items: ConversationTimelineItem[]) {
    if (!message.streaming) {
      return "";
    }
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index];
      if (item?.kind !== "assistant_text" && item?.status === "running") {
        return item.id;
      }
    }
    return "";
  }

  function renderConversationTimeline(message: ConversationMessage, items: ConversationTimelineItem[]) {
    if (items.length === 0) {
      return null;
    }
    const activeItemId = activeTimelineItemId(message, items);
    return (
      <div className={styles.conversationCellTimeline}>
        {items.map((item) => renderConversationTimelineItem(message, item, item.id === activeItemId))}
      </div>
    );
  }

  function renderConversationTimelineItem(message: ConversationMessage, item: ConversationTimelineItem, isActiveTimelineItem: boolean) {
    if (item.kind === "thought") {
      return renderThoughtTimelineItem(message, item, isActiveTimelineItem);
    }
    if (item.kind === "assistant_text") {
      return renderAssistantTextTimelineItem(message, item);
    }
    if (item.kind === "command_group") {
      return renderCommandGroupTimelineItem(item, isActiveTimelineItem);
    }
    return renderOperationTimelineItem(item, isActiveTimelineItem);
  }

  function renderThoughtTimelineItem(
    message: ConversationMessage,
    item: Extract<ConversationTimelineItem, { kind: "thought" }>,
    isActiveTimelineItem: boolean,
  ) {
    const expanded = getExpansionState(message.id, item.id, item.defaultExpanded);
    return (
      <section key={item.id} className={styles.timelineThoughtCell}>
        <button
          type="button"
          className={styles.timelineCellHeader}
          aria-expanded={expanded}
          onClick={() => toggleSection(message.id, item.id, item.defaultExpanded)}
          title={expanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden")}
        >
          {isActiveTimelineItem && item.status === "running" ? <LoaderCircle className={styles.statusSpinner} size={14} /> : <BrainCircuit size={14} />}
          <span>{lang === "zh" ? "思考" : "Thinking"}</span>
          {!expanded && item.preview ? <span className={styles.timelineCellPreview}>{item.preview}</span> : null}
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {expanded ? <pre className={styles.timelineThoughtText}>{item.text}</pre> : null}
      </section>
    );
  }

  function renderAssistantTextTimelineItem(
    message: ConversationMessage,
    item: Extract<ConversationTimelineItem, { kind: "assistant_text" }>,
  ) {
    const segments = getCachedResponseSegments(item.text);
    return (
      <section key={item.id} className={styles.timelineAssistantTextCell}>
        {segments.map((segment) => renderResponseSegment(segment, imageArtifactUrlsBeforeMessage.get(message.id)))}
      </section>
    );
  }

  function timelineStatusText(status: ConversationTimelineItem["status"]) {
    if (status === "failed") {
      return lang === "zh" ? "执行失败" : "Failed";
    }
    if (status === "running") {
      return lang === "zh" ? "运行中" : "Running";
    }
    if (status === "pending") {
      return lang === "zh" ? "等待中" : "Pending";
    }
    return "";
  }

  function renderCommandGroupTimelineItem(
    item: Extract<ConversationTimelineItem, { kind: "command_group" }>,
    isActiveTimelineItem: boolean,
  ) {
    const expanded = getExpansionState(item.id, "details", false);
    const duration = formatDuration(
      item.operations
        .map((operation) => operation.durationSeconds)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0)
        .reduce((total, value) => total + value, 0),
    );
    const visibleStatus = timelineStatusText(item.status);
    const className = [
      styles.timelineOperationCell,
      item.status === "failed" ? styles.timelineOperationCell_failed : "",
    ].filter(Boolean).join(" ");
    return (
      <section key={item.id} className={className}>
        <button
          type="button"
          className={styles.timelineCellHeader}
          aria-expanded={expanded}
          onClick={() => toggleSection(item.id, "details", false)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          {isActiveTimelineItem && item.status === "running" ? <LoaderCircle className={styles.statusSpinner} size={14} /> : <TerminalSquare size={14} />}
          <span>{item.title}</span>
          {item.summary ? <span className={styles.timelineCellPreview}>{item.summary}</span> : null}
          {visibleStatus ? <span className={styles.timelineCellMeta}>{visibleStatus}</span> : null}
          {duration ? <span className={styles.timelineCellMeta}>{duration}</span> : null}
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {expanded ? (
          <div className={styles.timelineCommandList}>
            {item.operations.map((operation) => (
              <div key={operation.id} className={styles.timelineCommandRow}>
                <span>{operationLabel(operation)}</span>
                {operation.summary ? <span>{operation.summary}</span> : null}
                {operation.error ? <span className={styles.timelineCommandError}>{operation.error}</span> : null}
              </div>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  function renderOperationTimelineItem(
    item: Extract<ConversationTimelineItem, { kind: "operation" }>,
    isActiveTimelineItem: boolean,
  ) {
    const operation = item.operation;
    const detailsId = `timeline-operation-detail-${operation.id}`;
    const detailsExpanded = getExpansionState(operation.id, "details", false);
    const canExpandDetails = hasOperationDetails(operation);
    const duration = formatDuration(operation.durationSeconds);
    const computerUseResult = renderComputerUseResult(operation);
    const readableResult = operation.kind === "tool" ? "" : readableOperationResult(operation);
    const showReadableResult = Boolean(operation.kind !== "tool" && readableResult && readableResult !== item.summary.trim());
    const visibleStatus = timelineStatusText(item.status);
    const className = [
      styles.timelineOperationCell,
      item.status === "failed" ? styles.timelineOperationCell_failed : "",
    ].filter(Boolean).join(" ");
    return (
      <section key={item.id} className={className}>
        <div className={styles.timelineCellHeader}>
          {operationStatusIcon(operation, isActiveTimelineItem)}
          <span>{item.title}</span>
          {item.summary ? <span className={styles.timelineCellPreview}>{item.summary}</span> : null}
          {visibleStatus ? <span className={styles.timelineCellMeta}>{visibleStatus}</span> : null}
          {duration ? <span className={styles.timelineCellMeta}>{duration}</span> : null}
          {canExpandDetails ? (
            <button
              type="button"
              className={styles.timelineCellDetailButton}
              aria-expanded={detailsExpanded}
              aria-controls={detailsId}
              onClick={() => toggleSection(operation.id, "details", false)}
              title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
            >
              {detailsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            </button>
          ) : null}
        </div>
        {canExpandDetails ? (
          <DeferredOperationDetails
            operation={operation}
            expanded={detailsExpanded}
            detailsId={detailsId}
            kind={operationDetailsKind(operation)}
            buildDetailRows={operationDetailRows}
          />
        ) : null}
        {showReadableResult ? <pre className={styles.timelineOperationResult}>{readableResult}</pre> : null}
        {computerUseResult}
      </section>
    );
  }

  function renderReActActionSection(group: ConversationReActOperationGroup) {
    const actions = reActActionOperations(group);
    if (actions.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <span className={styles.reActOperationSectionLabel}>{lang === "zh" ? "工具调用" : "Tool calls"}</span>
        <div className={styles.reActToolList}>
          {actions.map((operation) => {
            const duration = formatDuration(operation.durationSeconds);
            const detailsId = `operation-detail-${operation.id}`;
            const detailsExpanded = getExpansionState(operation.id, "details", false);
            const canExpandDetails = hasOperationDetails(operation);
            const computerUseResult = renderComputerUseResult(operation);
            return (
              <div key={operation.id} className={styles.reActToolItem}>
                <div className={styles.reActToolLine}>
                  <span className={styles.reActToolName}>{operationLabel(operation)}</span>
                  {operation.summary ? (
                    <span className={styles.reActToolSummary}>{operation.summary}</span>
                  ) : null}
                  <span className={styles.reActToolStatus}>
                    {operationStatusIcon(operation)}
                    <span>{statusLabel(operation.status)}</span>
                    {duration ? <span>{duration}</span> : null}
                  </span>
                  {canExpandDetails ? (
                    <button
                      type="button"
                      className={styles.reActToolDetailToggle}
                      aria-expanded={detailsExpanded}
                      aria-controls={detailsId}
                      onClick={() => toggleSection(operation.id, "details", false)}
                      title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
                    >
                      {detailsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                    </button>
                  ) : null}
                </div>
                {canExpandDetails ? (
                  <DeferredOperationDetails
                    operation={operation}
                    expanded={detailsExpanded}
                    detailsId={detailsId}
                    kind="tool"
                    buildDetailRows={operationDetailRows}
                  />
                ) : null}
                {computerUseResult}
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  function renderReActThoughtSection(group: ConversationReActOperationGroup) {
    const thoughts = reActThoughtItems(group);
    if (thoughts.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <span className={styles.reActOperationSectionLabel}>{lang === "zh" ? "思考" : "Thinking"}</span>
        <div className={styles.reActThoughtStack}>
          {thoughts.map((item) => (
            <pre key={item.id} className={styles.reActThoughtText}>{item.value}</pre>
          ))}
        </div>
      </section>
    );
  }

  function renderReActResultSection(messageId: string, group: ConversationReActOperationGroup) {
    const results = reActResultItems(group);
    if (results.length === 0) {
      return null;
    }
    const sectionId = `feedback-react-results-${group.id}`;
    const bodyId = `${sectionId}-body`;
    const expanded = getExpansionState(messageId, sectionId, false);
    const label = lang === "zh"
      ? results.length > 1 ? `结果 ${results.length}` : "结果"
      : results.length > 1 ? `${results.length} results` : "Result";
    return (
      <section className={styles.reActOperationSection}>
        <button
          type="button"
          className={styles.reActResultToggle}
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => toggleSection(messageId, sectionId, false)}
          title={expanded
            ? lang === "zh" ? "折叠工具结果" : "Collapse tool results"
            : lang === "zh" ? "展开工具结果" : "Expand tool results"}
        >
          <span className={styles.reActOperationSectionLabel}>{label}</span>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {expanded ? (
          <div id={bodyId} className={styles.reActResultList}>
            {results.map((item) => (
              <div
                key={item.id}
                className={`${styles.reActResultItem} ${item.tone === "failed" ? styles.reActResultItem_failed : ""}`}
              >
                <span className={styles.reActResultLabel}>{item.label}</span>
                <pre className={styles.reActResultValue}>{item.value}</pre>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  function renderReActOperationGroup(messageId: string, group: ConversationReActOperationGroup) {
    if (group.operations.length === 0) {
      return null;
    }
    const tone = reActGroupTone(group);
    const sectionId = `feedback-react-${tone}-${group.id}`;
    const defaultExpanded = shouldExpandReActGroupByDefault(group);
    const expanded = getExpansionState(messageId, sectionId, defaultExpanded);
    const groupTitle = group.title || operationLabel(group.operations[0]);
    const headerItems = [
      operationStateLabel(tone),
      reActGroupDurationLabel(group),
    ].filter(Boolean);
    return (
      <section className={`${styles.reActOperationGroup} ${styles[`reActOperationGroup_${tone}`]}`}>
        <button
          type="button"
          className={styles.reActOperationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, sectionId, defaultExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          {operationIcon(group.primaryKind ?? group.operations[0]?.kind ?? "tool", groupTitle)}
          <span className={styles.reActOperationTitle}>{groupTitle}</span>
          {headerItems.length > 0 ? (
            <span className={styles.reActOperationMeta}>
              {headerItems.join(" · ")}
            </span>
          ) : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? (
          <div className={styles.reActOperationBody}>
            {renderReActThoughtSection(group)}
            {renderReActActionSection(group)}
            {renderReActResultSection(messageId, group)}
          </div>
        ) : null}
      </section>
    );
  }

  function renderCompactRequestSummary(operations: ConversationOperation[]) {
    const tone = operationCollectionTone(operations);
    const title = compactRequestStateLabel(tone);
    return (
      <section className={`${styles.operationGroup} ${styles.executionTraceGroup}`}>
        <div
          className={`${styles.operationSummary} ${styles.executionRequestSummary}`}
          role="status"
          aria-live={tone === "running" ? "polite" : undefined}
        >
          {tone === "running" ? (
            <LoaderCircle className={styles.statusSpinner} size={14} />
          ) : tone === "done" ? (
            <CheckCircle2 size={14} />
          ) : (
            <CircleDot size={14} />
          )}
          <span>{title}</span>
        </div>
      </section>
    );
  }

  function renderOperationGroup(
    messageId: string,
    section: "thought" | "mental" | "tools",
    operations: ConversationOperation[],
    defaultExpanded: boolean,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const expanded = getExpansionState(messageId, section, defaultExpanded);
    const kind = operations[0]?.kind ?? "tool";
    const title = operationGroupTitle(kind, operations.length);
    const toggleTitle = expanded
      ? section === "thought"
        ? t("thoughtProcessVisible")
        : section === "mental"
          ? t("mentalProcessVisible")
          : t("toolProcessVisible")
      : section === "thought"
        ? t("thoughtProcessHidden")
        : section === "mental"
          ? t("mentalProcessHidden")
          : t("toolProcessHidden");
    return (
      <section className={styles.operationGroup}>
        <button
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, section, defaultExpanded)}
          title={toggleTitle}
        >
          {operationIcon(kind, title)}
          <span>{title}</span>
          {!expanded && operations[0]?.summary ? (
            <span className={styles.operationSummaryPreview}>{operations[0].summary}</span>
          ) : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? renderOperationTimeline(operations) : null}
      </section>
    );
  }

  function renderFeedbackTimelineGroup(
    messageId: string,
    operations: ConversationOperation[],
    defaultExpanded: boolean,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const visibleOperations = operations.filter(shouldShowTimelineOperation);
    if (visibleOperations.length === 0) {
      return renderCompactRequestSummary(operations);
    }
    const reActGroups = buildConversationReActOperationGroups(visibleOperations);
    if (reActGroups.length === 0) {
      return renderCompactRequestSummary(operations);
    }
    const defaultTimelineExpanded = defaultExpanded || reActGroups.some((group) => shouldExpandReActGroupByDefault(group));
    const expanded = getExpansionState(messageId, "feedback", defaultTimelineExpanded);
    const title = operationTimelineTitle(visibleOperations);
    const collectionTone = operationCollectionTone(operations);
    const stateLabel = operations.length > visibleOperations.length && collectionTone === "running"
      ? compactRequestStateLabel(collectionTone)
      : operationStateLabel(operationCollectionTone(visibleOperations));
    return (
      <section className={`${styles.operationGroup} ${styles.executionTraceGroup}`}>
        <button
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "feedback", defaultTimelineExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          {operationIcon(operations[0]?.kind ?? "tool", title)}
          <span>{title}</span>
          <span className={styles.operationSummaryCount}>{stateLabel}</span>
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? (
          <div className={styles.reActOperationList}>
            {reActGroups.map((group) => (
              <div key={group.id}>
                {renderReActOperationGroup(messageId, group)}
              </div>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  function renderAnswerOnlyProcessGroup(
    messageId: string,
    operations: ConversationOperation[],
    defaultExpanded: boolean,
    renderDetails: () => ReactNode,
    inlinePreview?: string,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const tone = operationCollectionTone(operations);
    const toneClass = styles[`answerOnlyProcessGroup_${tone}` as keyof typeof styles] ?? "";
    const expanded = getExpansionState(messageId, "process", defaultExpanded);
    const preview = inlinePreview || processSummaryPreview(operations);
    const title = processSummaryTitle(tone);
    return (
      <section className={[styles.answerOnlyProcessGroup, toneClass].filter(Boolean).join(" ")}>
        <button
          type="button"
          className={styles.answerOnlyProcessToggle}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "process", defaultExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          <span className={styles.answerOnlyProcessIcon} aria-hidden="true">
            {processSummaryIcon(tone)}
          </span>
          <span className={styles.answerOnlyProcessTitle}>{title}</span>
          <span className={styles.answerOnlyProcessMeta}>{processSummaryMeta(operations)}</span>
          {!expanded && preview ? <span className={styles.answerOnlyProcessPreview}>{preview}</span> : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? <div className={styles.answerOnlyProcessDetails}>{renderDetails()}</div> : null}
      </section>
    );
  }

  function shouldExpandToolGroupByDefault(message: ConversationMessage, operations: ConversationOperation[]) {
    return Boolean(message.streaming)
      || operations.some((operation) => operation.kind === "tool" && (operation.rawLabel ?? operation.label) === COMPUTER_USE_TOOL_NAME);
  }

  function mentalSnapshotPreview(snapshot: MentalStateSnapshot | undefined) {
    if (!snapshot) {
      return "";
    }
    return compactPreview(
      [
        snapshot.feeling,
        snapshot.summary,
        snapshot.whisper,
        snapshot.intervention,
        snapshot.cognitiveState ? cognitiveStateLabel(snapshot) : "",
      ].map((item) => String(item ?? "").trim()).find(Boolean) ?? "",
    );
  }

  function mentalFeelingSummaryRow(snapshot: MentalStateSnapshot | undefined) {
    const feeling = String(snapshot?.feeling ?? "").trim();
    const summary = String(snapshot?.summary ?? "").trim();
    if (!feeling && !summary) {
      return null;
    }
    if (!summary || feeling === summary) {
      return { label: t("mentalFeeling"), value: feeling || summary };
    }
    if (!feeling) {
      return { label: t("mentalSummary"), value: summary };
    }
    return { label: `${t("mentalFeeling")} / ${t("mentalSummary")}`, value: `${feeling}\n${summary}` };
  }

  function renderAuxiliaryToggle(
    messageId: string,
    section: "thought" | "mental",
    title: string,
    preview: string,
    defaultExpanded: boolean,
    isRunning: boolean,
    children: ReactNode,
  ) {
    const expanded = getExpansionState(messageId, section, defaultExpanded);
    const toggleTitle = expanded
      ? section === "thought" ? t("thoughtProcessVisible") : t("mentalProcessVisible")
      : section === "thought" ? t("thoughtProcessHidden") : t("mentalProcessHidden");
    return (
      <section className={`${styles.auxiliaryBlock} ${styles[`auxiliaryBlock_${section}`]}`}>
        <button
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, section, defaultExpanded)}
          title={toggleTitle}
        >
          {section === "thought" ? <Sparkles size={17} /> : <BrainCircuit size={17} />}
          <span>{title}</span>
          {!expanded && preview ? (
            <span className={styles.operationSummaryPreview}>{preview}</span>
          ) : null}
          {isRunning ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? children : null}
      </section>
    );
  }

  function renderThoughtPanel(message: ConversationMessage, defaultExpandedOverride?: boolean) {
    if (!hasThoughtBlock(message)) {
      return null;
    }
    const thought = message.thought?.trim() ?? "";
    const hasLaterActiveSection = (showMentalSnapshots && hasMentalBlock(message)) || hasToolBlock(message) || hasResponseBlock(message);
    return renderAuxiliaryToggle(
      message.id,
      "thought",
      t("thoughtProcess"),
      compactPreview(thought),
      defaultExpandedOverride ?? Boolean(message.streaming),
      Boolean(message.streaming) && !hasLaterActiveSection,
      <div className={`${styles.auxiliaryPanel} ${styles.auxiliaryPanel_thought}`}>
        <p className={styles.thoughtText}>{thought}</p>
      </div>,
    );
  }

  function renderMentalPanel(message: ConversationMessage, defaultExpandedOverride?: boolean) {
    if (!showMentalSnapshots || !hasMentalBlock(message)) {
      return null;
    }
    const snapshot = message.mentalSnapshot;
    const metaRows = [
      snapshot?.mood ? { label: t("mentalMood"), value: snapshot.mood } : null,
      snapshot?.cognitiveState ? { label: t("mentalCognitiveState"), value: cognitiveStateLabel(snapshot) } : null,
      snapshot?.source ? { label: t("mentalSource"), value: mentalSourceLabel(snapshot.source) } : null,
      Number.isFinite(snapshot?.confidence) && Number(snapshot?.confidence) > 0
        ? { label: t("mentalConfidence"), value: `${Math.round(Number(snapshot?.confidence) * 100)}%` }
        : null,
      Number(snapshot?.sampleSize) > 0 ? { label: t("mentalSamples"), value: String(snapshot?.sampleSize) } : null,
      snapshot?.updatedAt ? { label: t("mentalLastUpdated"), value: formatTimestamp(snapshot.updatedAt) } : null,
    ].filter(Boolean) as Array<{ label: string; value: string }>;
    const bodyRows = [
      mentalFeelingSummaryRow(snapshot),
      snapshot?.whisper ? { label: t("mentalWhisper"), value: snapshot.whisper } : null,
      snapshot?.intervention ? { label: t("mentalIntervention"), value: snapshot.intervention } : null,
    ].filter(Boolean) as Array<{ label: string; value: string }>;
    return renderAuxiliaryToggle(
      message.id,
      "mental",
      t("mentalProcess"),
      mentalSnapshotPreview(snapshot),
      defaultExpandedOverride ?? true,
      Boolean(message.streaming) && !hasToolBlock(message) && !hasResponseBlock(message),
      <div className={`${styles.auxiliaryPanel} ${styles.auxiliaryPanel_mental}`}>
        {metaRows.length ? (
          <div className={styles.mentalMetaGrid}>
            {metaRows.map((row) => (
              <span key={row.label} className={styles.mentalMetaItem}>
                <small>{row.label}</small>
                <strong>{row.value}</strong>
              </span>
            ))}
          </div>
        ) : null}
        {bodyRows.length ? (
          <div className={styles.mentalBodyList}>
            {bodyRows.map((row) => (
              <p key={row.label} className={styles.mentalBodyRow}>
                <span>{row.label}</span>
                {row.value}
              </p>
            ))}
          </div>
        ) : null}
      </div>,
    );
  }

  function responseSegmentLabel(segment: ResponseSegment) {
    switch (segment.kind) {
      case "status":
        return t("responseSegmentStatus");
      case "commit":
        return t("responseSegmentCommit");
      case "verification":
        return t("responseSegmentVerification");
      case "code":
        return segment.language || t("responseSegmentCode");
      case "files":
        return t("responseSegmentFiles");
      case "logs":
        return t("responseSegmentLogs");
      case "answer":
      default:
        return t("responseSegmentAnswer");
    }
  }

  function renderResponseSegment(segment: ResponseSegment, duplicateImageUrls?: Set<string>) {
    const label = responseSegmentLabel(segment);
    const isCodeLike = segment.kind === "code"
      || Boolean(segment.language)
      || (["commit", "verification"].includes(segment.kind) && segment.content.includes("\n"));
    return (
      <section
        key={segment.id}
        className={`${styles.responseSegment} ${styles[`responseSegment_${segment.kind}`]}`}
      >
        <div className={styles.responseSegmentHeader}>
          <span className={styles.responseSegmentLabel}>{label}</span>
          {segment.language && segment.kind !== "code" ? (
            <span className={styles.responseSegmentMeta}>{segment.language}</span>
          ) : null}
        </div>
        {isCodeLike ? (
          <pre className={styles.responseSegmentPre}>
            <code>{segment.content}</code>
          </pre>
        ) : (
          renderResponseText(segment.content, duplicateImageUrls)
        )}
      </section>
    );
  }

  function shouldShowResponseBlock(message: ConversationMessage, hasFeedbackTimeline: boolean) {
    if (!hasResponseBlock(message)) {
      return false;
    }
    if (!hasFeedbackTimeline) {
      return true;
    }
    if (message.streaming) {
      return true;
    }
    const segments = getCachedResponseSegments(message.content);
    return segments.some((segment) => segment.kind !== "status");
  }

  function renderResponseText(content: string, duplicateImageUrls?: Set<string>) {
    const blocks = getCachedMarkdownBlocks(content);
    if (blocks.length === 0) {
      return null;
    }
    const hasTable = blocks.some((block) => block.type === "table");
    return (
      <div className={`${styles.markdownBody} ${hasTable ? styles.markdownBodyWithTable : ""}`}>
        {blocks.map((block, index) => renderMarkdownBlock(block, index, duplicateImageUrls))}
      </div>
    );
  }

  function renderStreamingResponseText(content: string) {
    if (!content) {
      return null;
    }
    return <StreamingResponseContent content={content} />;
  }

  function renderMarkdownBlock(block: MarkdownBlock, index: number, duplicateImageUrls?: Set<string>) {
    if (block.type === "heading") {
      const HeadingTag = block.level <= 2 ? "h3" : "h4";
      return (
        <HeadingTag
          key={`heading-${index}-${block.content}`}
          className={`${styles.markdownHeading} ${styles[`markdownHeading${block.level}`]}`}
        >
          {renderInlineContent(block.content)}
        </HeadingTag>
      );
    }
    if (block.type === "divider") {
      return <hr key={`divider-${index}`} className={styles.markdownDivider} />;
    }
    if (block.type === "image") {
      const safeUrl = safeConversationMarkdownUrl(block.url);
      if (!safeUrl) {
        return null;
      }
      const previewUrl = previewUrlForImage(safeUrl);
      if (duplicateImageUrls?.has(comparableImageUrl(safeUrl))) {
        return null;
      }
      const imageAlt = block.alt || (lang === "zh" ? "生成图片" : "Generated image");
      const previewLabel = lang === "zh" ? "预览图片" : "Preview image";
      return (
        <figure key={`image-${index}-${safeUrl}`} className={styles.markdownImageFigure}>
          <button
            type="button"
            className={styles.imagePreviewButton}
            onClick={() =>
              openImagePreview({
                src: previewUrl,
                alt: imageAlt,
                downloadUrl: safeUrl,
                downloadName: downloadNameFromUrl(safeUrl) || true,
              })
            }
            aria-label={previewLabel}
            title={previewLabel}
          >
            <img className={styles.markdownImage} src={previewUrl} alt={imageAlt} loading="lazy" />
          </button>
          <figcaption className={styles.markdownImageCaption}>
            {block.alt ? <span>{block.alt}</span> : null}
            <a
              className={styles.markdownImageLink}
              href={safeUrl}
              download={downloadNameFromUrl(safeUrl) || true}
            >
              {lang === "zh" ? "下载图片" : "Download image"}
            </a>
          </figcaption>
        </figure>
      );
    }
    if (block.type === "table") {
      return (
        <div key={`table-${index}`} className={styles.markdownTableWrap}>
          <table className={styles.markdownTable}>
            <thead>
              <tr>
                {block.headers.map((header, headerIndex) => (
                  <th key={`${header}-${headerIndex}`}>{renderInlineContent(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {block.headers.map((_, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>{renderInlineContent(row[cellIndex] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    if (block.type === "unorderedList") {
      return (
        <ul key={`ul-${index}`} className={styles.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineContent(item)}</li>
          ))}
        </ul>
      );
    }
    if (block.type === "orderedList") {
      return (
        <ol key={`ol-${index}`} className={styles.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineContent(item)}</li>
          ))}
        </ol>
      );
    }
    return (
      <p key={`paragraph-${index}`} className={styles.messageBody}>
        {renderInlineContent(block.content)}
      </p>
    );
  }

  function renderInlineContent(content: string) {
    return renderInlineMarkdown(content, "inline");
  }

  function renderInlineMarkdown(content: string, partIndex: number | string) {
    const nodes: ReactNode[] = [];
    const inlinePattern = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|(\*\*|__)(?=\S)([\s\S]*?\S)\4/g;
    let cursor = 0;
    let match: RegExpExecArray | null;
    while ((match = inlinePattern.exec(content)) !== null) {
      if (match.index > cursor) {
        nodes.push(content.slice(cursor, match.index));
      }
      if (match[1]) {
        nodes.push(
          <code key={`code-${partIndex}-${match.index}`} className={styles.inlineCode}>
            {match[1]}
          </code>,
        );
      } else if (match[2] && match[3]) {
        const label = match[2];
        const href = match[3];
        const safeHref = safeConversationMarkdownUrl(href);
        if (safeHref) {
          nodes.push(
            <a
              key={`link-${partIndex}-${match.index}`}
              className={styles.inlineLink}
              href={safeHref}
              download={isLikelyImageUrl(safeHref) ? downloadNameFromUrl(safeHref) || true : undefined}
            >
              {label}
            </a>,
          );
        } else {
          nodes.push(label);
        }
      } else {
        const strongContent = match[5] ?? "";
        nodes.push(
          <strong key={`strong-${partIndex}-${match.index}`} className={styles.inlineStrong}>
            {renderInlineMarkdown(strongContent, `${partIndex}-strong-${match.index}`)}
          </strong>,
        );
      }
      cursor = match.index + match[0].length;
      if (match[2] && match[3] && !safeConversationMarkdownUrl(match[3]) && content[cursor] === ")") {
        cursor += 1;
      }
    }
    if (cursor < content.length) {
      nodes.push(content.slice(cursor));
    }
    return nodes.length > 0 ? nodes : content;
  }

  function renderImageArtifact(message: ConversationMessage) {
    const artifact = imageArtifactForMessage(message);
    if (!artifact) {
      return null;
    }
    const downloadLabel = lang === "zh" ? "下载图片" : "Download image";
    const previewLabel = lang === "zh" ? "预览图片" : "Preview image";
    const imageAlt = artifact.prompt || (lang === "zh" ? "生成图片" : "Generated image");
    const metaItems = [artifact.size, artifact.quality, artifact.model].filter(Boolean);
    return (
      <figure className={styles.imageArtifact}>
        <button
          type="button"
          className={`${styles.imageArtifactFrame} ${styles.imagePreviewButton}`}
          onClick={() =>
            openImagePreview({
              src: artifact.imageUrl,
              alt: imageAlt,
              downloadUrl: artifact.downloadUrl,
              downloadName: artifact.artifactId || true,
            })
          }
          aria-label={previewLabel}
          title={previewLabel}
        >
          <img className={styles.imagePreview} src={artifact.imageUrl} alt={imageAlt} loading="lazy" />
        </button>
        <figcaption className={styles.imageArtifactFooter}>
          <span className={styles.imageArtifactMeta}>
            {artifact.prompt ? <span className={styles.imageArtifactPrompt}>{artifact.prompt}</span> : null}
            {metaItems.length ? <span>{metaItems.join(" · ")}</span> : null}
          </span>
          <a
            className={styles.imageDownloadButton}
            href={artifact.downloadUrl}
            download={artifact.artifactId || true}
            title={downloadLabel}
            aria-label={downloadLabel}
          >
            <Download size={15} />
          </a>
        </figcaption>
      </figure>
    );
  }

  function renderUserAttachments(message: ConversationMessage) {
    const attachments = message.attachments ?? [];
    if (!attachments.length) {
      return null;
    }
    const downloadLabel = lang === "zh" ? "下载图片" : "Download image";
    return (
      <div className={styles.userAttachmentGrid}>
        {attachments.map((attachment) => {
          const imageUrl = attachment.imageUrl || attachment.url;
          if (!imageUrl) {
            return null;
          }
          const filename = attachment.filename || attachment.artifactId || (lang === "zh" ? "图片" : "Image");
          return (
            <figure key={attachment.artifactId || imageUrl} className={styles.userAttachment}>
              <img className={styles.userAttachmentImage} src={imageUrl} alt={filename} loading="lazy" />
              <figcaption className={styles.userAttachmentMeta}>
                <span>{filename}</span>
                <a
                  className={styles.imageDownloadButton}
                  href={attachment.downloadUrl || imageUrl}
                  download={attachment.artifactId || true}
                  title={downloadLabel}
                  aria-label={downloadLabel}
                >
                  <Download size={14} />
                </a>
              </figcaption>
            </figure>
          );
        })}
      </div>
    );
  }

  function parseMarkdownBlocks(content: string): MarkdownBlock[] {
    const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
    const blocks: MarkdownBlock[] = [];
    let paragraphLines: string[] = [];

    function flushParagraph() {
      const paragraph = paragraphLines.join("\n").trim();
      if (paragraph) {
        blocks.push({ type: "paragraph", content: paragraph });
      }
      paragraphLines = [];
    }

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        continue;
      }

      const image = trimmed.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
      if (image) {
        flushParagraph();
        blocks.push({ type: "image", alt: image[1].trim(), url: image[2].trim() });
        continue;
      }

      const heading = trimmed.match(/^(#{1,4})\s+(.+?)\s*#*$/);
      if (heading) {
        flushParagraph();
        blocks.push({
          type: "heading",
          level: Math.min(4, heading[1].length) as 1 | 2 | 3 | 4,
          content: heading[2].trim(),
        });
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushParagraph();
        blocks.push({ type: "divider" });
        continue;
      }

      if (isMarkdownTableHeader(lines, index)) {
        flushParagraph();
        const headers = parseMarkdownTableRow(lines[index]);
        const rows: string[][] = [];
        index += 2;
        for (; index < lines.length; index += 1) {
          if (!isMarkdownTableRow(lines[index])) {
            index -= 1;
            break;
          }
          rows.push(parseMarkdownTableRow(lines[index]));
        }
        blocks.push({ type: "table", headers, rows });
        continue;
      }

      const unorderedMatch = trimmed.match(/^[-*]\s+(.+)$/);
      if (unorderedMatch) {
        flushParagraph();
        const items = [unorderedMatch[1].trim()];
        for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
          const nextMatch = lines[nextIndex].trim().match(/^[-*]\s+(.+)$/);
          if (!nextMatch) {
            break;
          }
          items.push(nextMatch[1].trim());
          index = nextIndex;
        }
        blocks.push({ type: "unorderedList", items });
        continue;
      }

      const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (orderedMatch) {
        flushParagraph();
        const items = [orderedMatch[1].trim()];
        for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
          const nextMatch = lines[nextIndex].trim().match(/^\d+[.)]\s+(.+)$/);
          if (!nextMatch) {
            break;
          }
          items.push(nextMatch[1].trim());
          index = nextIndex;
        }
        blocks.push({ type: "orderedList", items });
        continue;
      }

      paragraphLines.push(line);
    }

    flushParagraph();
    return blocks;
  }

  function isMarkdownTableHeader(lines: string[], index: number) {
    return isMarkdownTableRow(lines[index]) && isMarkdownTableSeparator(lines[index + 1] ?? "");
  }

  function isMarkdownTableRow(line: string) {
    const trimmed = String(line ?? "").trim();
    return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.includes("|", 1);
  }

  function isMarkdownTableSeparator(line: string) {
    const cells = parseMarkdownTableRow(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function parseMarkdownTableRow(line: string) {
    return String(line ?? "")
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  function isLikelyImageUrl(url: string) {
    const normalized = String(url ?? "").toLowerCase();
    return /\.(png|jpe?g|webp|gif)(?:[?#].*)?$/.test(normalized) || normalized.includes("/artifacts/image");
  }

  function previewUrlForImage(url: string) {
    const trimmed = String(url ?? "").trim();
    const [withoutHash, hash = ""] = trimmed.split("#", 2);
    const [path, query = ""] = withoutHash.split("?", 2);
    if (!query) {
      return trimmed;
    }
    const kept = query
      .split("&")
      .filter((param) => !/^download=(1|true)$/i.test(param));
    return `${path}${kept.length ? `?${kept.join("&")}` : ""}${hash ? `#${hash}` : ""}`;
  }

  function downloadNameFromUrl(url: string) {
    const path = String(url ?? "").split(/[?#]/, 1)[0] ?? "";
    return path.split("/").filter(Boolean).pop() ?? "";
  }

  return (
    <div
      className={[
        styles.surface,
        density === "compact" ? styles.surfaceCompact : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      {showHeader ? (
        <div className={styles.header}>
          <div>
            <p className={styles.eyebrow}>{eyebrowLabel ?? t("agentSession")}</p>
            <h2 className={styles.title}>{title}</h2>
          </div>
          <div className={styles.headerControls}>
            {headerActions}
            <span className={styles.phase}>{statusLabel(phase)}</span>
          </div>
        </div>
      ) : null}

      {showSessionOverview && resolvedSummaryItems.length > 0 ? (
        <div className={styles.summaryGrid}>
          {resolvedSummaryItems.map((item) => (
            <section key={item.label} className={styles.summaryCard}>
              <p className={styles.summaryLabel}>{item.label}</p>
              <p className={styles.summaryValue} title={item.value}>
                {item.value}
              </p>
            </section>
          ))}
        </div>
      ) : null}

      {hasMetaSection ? (
        <div className={styles.metaStack}>
          {hasSessionMeta ? (
            <div className={styles.sessionMeta}>
              {resolvedStats.length > 0 ? (
                <div className={styles.statRow}>
                  {resolvedStats.map((item) => (
                    <span key={item.label} className={styles.statPill}>
                      {item.label} {item.value}
                    </span>
                  ))}
                </div>
              ) : null}
              {latestToolCalls.length > 0 ? (
                <div className={styles.toolsBlock}>
                  <span className={styles.toolsLabel}>{t("activeToolsLabel")}</span>
                  <div className={styles.toolRow}>
                    {latestToolCalls.map((toolCall, index) => (
                      <span key={`${toolCall.name}-${index}`} className={styles.toolPill}>
                        {toolCall.name} · {statusLabel(toolCall.status)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {lastMessageTimestamp ? (
                <p className={styles.updateLine}>
                  {t("lastUpdated")} {formatTimestamp(lastMessageTimestamp)}
                </p>
              ) : null}
            </div>
          ) : null}

          {supplementalContent ? <div className={styles.supplemental}>{supplementalContent}</div> : null}
        </div>
      ) : null}

      <div ref={timelineRef} className={styles.timeline}>
        {displayMessages.length === 0 && !activeTurnMessage ? (
          <div className={styles.emptyState}>{t("sessionNoMessages")}</div>
        ) : (
          <>
            {hiddenMessageCount > 0 ? (
              <div className={styles.timelineHistoryGate}>
                <button
                  type="button"
                  className={styles.timelineHistoryButton}
                  onClick={() => setAllMessagesVisible(true)}
                >
                  <ArrowUp size={15} />
                  <span>
                    {lang === "zh"
                      ? `显示更早 ${hiddenMessageCount} 条消息`
                      : `Show ${hiddenMessageCount} earlier messages`}
                  </span>
                </button>
              </div>
            ) : null}
            {activeTimelineMessages.map((message) => {
            if (isCliAgentLifecycleMessage(message)) {
              const detail = cliAgentLifecycleDetail(message);
              return (
                <article key={message.id} className={styles.cliAgentLifecycleTurn}>
                  <span className={styles.cliAgentLifecycleIcon} aria-hidden="true">
                    <TerminalSquare size={14} />
                  </span>
                  <span className={styles.cliAgentLifecycleText}>
                    {cliAgentLifecycleLabel(message, lang)}
                  </span>
                  {detail ? <code className={styles.cliAgentLifecycleMeta}>{detail}</code> : null}
                  {message.timestamp ? (
                    <span className={styles.cliAgentLifecycleTime}>{formatTimestamp(message.timestamp)}</span>
                  ) : null}
                </article>
              );
            }
            const operationGroups = buildConversationOperationGroups(message, operationLabels);
            const hasActiveProcess = operationGroups.timeline.some((operation) => isRunningOperationStatus(operation.status));
            const hasFeedbackTimeline = (message.feedbackEvents?.length ?? 0) > 0;
            const showResponseBlock = shouldShowResponseBlock(message, hasFeedbackTimeline);
            const turnErrorMessage = isTurnErrorMessage(message);
            const agentInboxMessage = isAgentInboxMessage(message);
            const groupTranscriptMessage = isGroupRoomTranscriptMessage(message);
            const conversationTimelineItems = buildConversationTimelineItems(message, operationGroups.timeline, {
              lang,
              includeAssistantText: showResponseBlock && !answerOnlyProcessMode,
            });
            const hasConversationTimeline =
              message.role === "assistant"
              && hasFeedbackTimeline
              && !turnErrorMessage
              && !agentInboxMessage
              && !groupTranscriptMessage
              && conversationTimelineItems.length > 0;
            const userAuthoredMessage = message.role === "user" && !agentInboxMessage;
            const isStreamingStatusPlaceholder = Boolean(message.streaming)
              && showResponseBlock
              && answerOnlyProcessMode
              && hasFeedbackTimeline
              && isStreamingStatusPlaceholderContent(message.content);
            const isResponseStreaming = Boolean(message.streaming) && showResponseBlock && !isStreamingStatusPlaceholder;
            const showResponseSpinner = isResponseStreaming && !hasActiveProcess;
            const defaultResponseExpanded = Boolean(message.streaming) || defaultExpandedResponseIds.has(message.id);
            const responseExpanded = getExpansionState(message.id, "response", defaultResponseExpanded);
            const responseSegments = showResponseBlock && !isStreamingStatusPlaceholder && responseExpanded && !isResponseStreaming
              ? getCachedResponseSegments(message.content)
              : [];
            const isEditingMessage = userAuthoredMessage && message.id === editingMessageId;
            const agentInboxExpanded = getExpansionState(message.id, "agentInbox", false);
            const agentInboxPreview = agentInboxMessage ? compactPreview(agentInboxSummary(message), 140) : "";
            const researchOrgChips = researchOrgMessageChips(message);
            const turnClassName = [
              groupTranscriptMessage
                ? styles.groupTranscriptTurn
                : message.role === "assistant"
                  ? styles.assistantTurn
                  : agentInboxMessage
                  ? styles.agentInboxTurn
                  : styles.userTurn,
              turnErrorMessage ? styles.turnErrorTurn : "",
              isEditingMessage ? styles.turnEditing : "",
            ].filter(Boolean).join(" ");
            const speakerLabel = groupTranscriptMessage
              ? groupRoomTranscriptLabel(message)
              : message.role === "assistant"
                ? assistantLabel
                : agentInboxMessage
                  ? agentInboxSourceLabel(message)
                  : userLabel;
            const editDisabled = Boolean(editUserMessageDisabled);
            const processDefaultExpanded = operationCollectionTone(operationGroups.timeline) === "failed";
            const renderLegacyProcessDetails = (defaultExpandedOverride?: boolean) => (
              <>
                {renderThoughtPanel(message, defaultExpandedOverride)}
                {renderMentalPanel(message, defaultExpandedOverride)}
                {renderOperationGroup(
                  message.id,
                  "tools",
                  operationGroups.tools,
                  defaultExpandedOverride ?? shouldExpandToolGroupByDefault(message, operationGroups.tools),
                )}
              </>
            );
            const renderProcessDetails = () => {
              if (hasConversationTimeline) {
                return renderConversationTimeline(message, conversationTimelineItems);
              }
              if (hasFeedbackTimeline) {
                return renderFeedbackTimelineGroup(
                  message.id,
                  operationGroups.timeline,
                  true,
                );
              }
              return renderLegacyProcessDetails(true);
            };
            const responseSectionNode = showResponseBlock && !isStreamingStatusPlaceholder && (!hasConversationTimeline || answerOnlyProcessMode) ? (
              <section className={styles.responseSection}>
                <button
                  type="button"
                  className={styles.responseToggle}
                  aria-expanded={responseExpanded}
                  onClick={() => toggleSection(message.id, "response", defaultResponseExpanded)}
                  title={responseExpanded ? t("responseHidden") : t("responseVisible")}
                >
                  {responseExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span>{t("responseLabel")}</span>
                  {showResponseSpinner ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
                </button>
                {responseExpanded ? (
                  <div className={styles.responseBody}>
                    {isResponseStreaming
                      ? renderStreamingResponseText(message.content)
                      : responseSegments.map((segment) =>
                        renderResponseSegment(segment, imageArtifactUrlsBeforeMessage.get(message.id)),
                      )}
                  </div>
                ) : null}
              </section>
            ) : null;
            const processNode = answerOnlyProcessMode ? (
              renderAnswerOnlyProcessGroup(
                message.id,
                operationGroups.timeline,
                processDefaultExpanded,
                renderProcessDetails,
                isStreamingStatusPlaceholder ? compactStreamingStatusPlaceholder(message.content) : undefined,
              )
            ) : hasConversationTimeline ? (
              renderConversationTimeline(message, conversationTimelineItems)
            ) : hasFeedbackTimeline ? (
              renderFeedbackTimelineGroup(
                message.id,
                operationGroups.timeline,
                false,
              )
            ) : renderLegacyProcessDetails();
            return (
              <article
                key={message.id}
                className={turnClassName}
              >
                <div className={styles.turnAvatar} aria-hidden="true">
                  {renderTurnAvatarContent(
                    resolveMessageTurnAvatar(message, {
                      resolveTurnAvatar,
                      assistantAvatarImageUrl,
                      assistantAvatarFallback,
                      assistantLabel,
                      userAvatarImageUrl,
                      userAvatarLabel,
                      agentInboxMessage,
                      groupTranscriptMessage,
                    }),
                  )}
                </div>
            <div className={styles.turnContent}>
                  <div className={styles.turnMeta}>
                    <div className={styles.turnMetaIdentity}>
                      <span className={styles.turnSpeaker}>
                        {speakerLabel}
                      </span>
                      {isEditingMessage ? <span className={styles.turnEditBadge}>{t("editMessage")}</span> : null}
                    </div>
                    <span className={styles.turnMetaActions}>
                      {message.timestamp ? <span>{formatTimestamp(message.timestamp)}</span> : null}
                      {userAuthoredMessage && message.id === latestUserMessageId && onEditUserMessage ? (
                        <button
                          type="button"
                          className={
                            isEditingMessage
                              ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                              : styles.turnIconButton
                          }
                          onClick={() => onEditUserMessage(message)}
                          disabled={editDisabled}
                          aria-pressed={isEditingMessage}
                          title={editDisabled ? composerPlaceholder : editUserMessageLabel ?? t("editMessage")}
                          aria-label={editUserMessageLabel ?? t("editMessage")}
                        >
                          <Pencil size={14} />
                        </button>
                      ) : null}
                    </span>
                  </div>

                  {agentInboxMessage ? (
                    <section className={styles.agentInboxSection}>
                      {researchOrgChips.length > 0 ? (
                        <div className={styles.researchOrgChipRow} aria-label={lang === "zh" ? "科研组织消息标签" : "Research organization message labels"}>
                          {researchOrgChips.map((chip) => (
                            <span
                              key={chip.key}
                              className={`${styles.researchOrgChip} ${styles[`researchOrgChip_${chip.tone}`]}`}
                            >
                              {chip.label}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <button
                        type="button"
                        className={styles.agentInboxToggle}
                        aria-expanded={agentInboxExpanded}
                        onClick={() => toggleSection(message.id, "agentInbox", false)}
                        title={agentInboxExpanded ? (lang === "zh" ? "折叠私信内容" : "Collapse private message") : (lang === "zh" ? "展开私信内容" : "Expand private message")}
                      >
                        {agentInboxExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <span>{lang === "zh" ? "私信内容" : "Private message"}</span>
                        {agentInboxPreview ? <span className={styles.agentInboxPreview}>{agentInboxPreview}</span> : null}
                      </button>
                      {agentInboxExpanded ? (
                        <div className={styles.agentInboxMessageBody}>
                          {renderResponseText(message.content)}
                        </div>
                      ) : null}
                    </section>
                  ) : hasUserContent(message) ? (
                    <div className={styles.userMessageBody}>
                      {renderResponseText(message.content)}
                    </div>
                  ) : null}
                  {groupTranscriptMessage ? (
                    <div className={styles.groupTranscriptBody}>{renderResponseText(message.content)}</div>
                  ) : null}
                  {renderUserAttachments(message)}

                  {answerOnlyProcessMode ? responseSectionNode : null}
                  {processNode}
                  {turnErrorMessage ? (
                    <div className={styles.turnErrorNotice} role="status" aria-live="polite">
                      <div className={styles.turnErrorNoticeIcon} aria-hidden="true">
                        <TerminalSquare size={15} />
                      </div>
                      <div className={styles.turnErrorNoticeBody}>
                        <div className={styles.turnErrorNoticeMeta}>
                          <span>{lang === "zh" ? "运行提示" : "Runtime notice"}</span>
                          {turnErrorType(message) ? <span>{turnErrorType(message)}</span> : null}
                        </div>
                        <div className={styles.turnErrorNoticeText}>{renderResponseText(message.content)}</div>
                        {turnErrorReasonRows(message, lang).length > 0 ? (
                          <dl className={styles.turnErrorReasonList}>
                            {turnErrorReasonRows(message, lang).map((row) => (
                              <div key={`${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                                <dt>{row.label}</dt>
                                <dd>{row.value}</dd>
                              </div>
                            ))}
                          </dl>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                  {renderImageArtifact(message)}

                  {!answerOnlyProcessMode ? responseSectionNode : null}
                </div>
              </article>
            );
            })}
          </>
        )}
      </div>

      {!isAtBottom ? (
        <button
          type="button"
          className={styles.backToBottomButton}
          onClick={scrollToBottom}
          title={t("backToBottom")}
          aria-label={t("backToBottom")}
        >
          <ArrowDown size={16} />
          <span>{t("backToBottom")}</span>
        </button>
      ) : null}

      {turnError?.message && !hasVisibleTurnErrorMessage ? (
        <div className={styles.turnError} role="status" aria-live="polite">
          <div className={styles.turnErrorText}>
            <span className={styles.turnErrorLabel}>{t("turnErrorLabel")}</span>
            <span>{turnError.message}</span>
            {turnErrorBannerRows(turnError, lang).map((row) => (
              <span key={`${row.label}-${row.value}`} className={styles.turnErrorDetail}>
                {row.label}: {row.value}
              </span>
            ))}
          </div>
          {turnError.errorType ? <span className={styles.turnErrorType}>{turnError.errorType}</span> : null}
        </div>
      ) : null}

      {showComposer ? (
      <div className={styles.composer}>
        <div
          className={
            composerDragActive ? `${styles.composerField} ${styles.composerFieldDragActive}` : styles.composerField
          }
          onDragEnter={handleComposerDragEnter}
          onDragOver={handleComposerDragOver}
          onDragLeave={handleComposerDragLeave}
          onDrop={handleComposerDrop}
        >
          {composerError ? <p className={styles.composerError}>{composerError}</p> : null}
          {composerModeNotice ? (
            <div className={styles.composerModeNotice} role="status">
              <span className={styles.composerModeNoticeIcon} aria-hidden="true">
                <Pencil size={14} />
              </span>
              <span>{composerModeNotice}</span>
              {onCancelComposerMode ? (
                <button type="button" onClick={onCancelComposerMode}>
                  {cancelComposerModeLabel ?? t("cancelEditMessage")}
                </button>
              ) : null}
            </div>
          ) : null}
          {composerAttachments.length ? (
            <div className={styles.composerAttachmentTray} aria-label={lang === "zh" ? "待发送图片" : "Images to send"}>
              {composerAttachments.map((attachment) => (
                <div key={attachment.id} className={styles.composerAttachmentChip}>
                  <img src={attachment.previewUrl} alt={attachment.filename} />
                  <span title={attachment.filename}>{attachment.filename}</span>
                  {onRemoveComposerAttachment ? (
                    <button
                      type="button"
                      onClick={() => onRemoveComposerAttachment(attachment.id)}
                      title={lang === "zh" ? "移除图片" : "Remove image"}
                      aria-label={lang === "zh" ? "移除图片" : "Remove image"}
                    >
                      <X size={13} />
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          {composerReferences.length ? (
            <div className={styles.composerReferenceTray} aria-label={lang === "zh" ? "待发送会话引用" : "Session references to send"}>
              {composerReferences.map((reference) => {
                const referenceId = reference.referenceId || reference.sessionId;
                const title = reference.title || reference.sessionId;
                const agentLabel = reference.agentDisplayName || reference.agentCode || reference.agentId || "";
                return (
                  <div key={referenceId} className={styles.composerReferenceChip}>
                    <span className={styles.composerReferenceIcon} aria-hidden="true">
                      <Link2 size={13} />
                    </span>
                    <span className={styles.composerReferenceCopy}>
                      <strong title={title}>{title}</strong>
                      {agentLabel ? <small title={agentLabel}>{agentLabel}</small> : null}
                    </span>
                    {onRemoveComposerReference ? (
                      <button
                        type="button"
                        onClick={() => onRemoveComposerReference(referenceId)}
                        title={lang === "zh" ? "移除会话引用" : "Remove session reference"}
                        aria-label={lang === "zh" ? "移除会话引用" : "Remove session reference"}
                      >
                        <X size={13} />
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          <textarea
            ref={composerInputRef}
            className={styles.input}
            value={composerValue}
            disabled={composerDisabled && resolvedActionMode !== "stop"}
            placeholder={composerPlaceholder}
            onChange={(event) => onComposerChange(event.target.value)}
            onPaste={(event) => {
              if (!onAddComposerAttachments || attachmentInputDisabled) {
                return;
              }
              const files = Array.from(event.clipboardData.files || []).filter((file) => file.type.startsWith("image/"));
              if (!files.length) {
                return;
              }
              event.preventDefault();
              onAddComposerAttachments(files);
            }}
            onKeyDown={(event) => {
              if (
                shouldSubmitComposerOnKeydown({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                  isComposing: event.nativeEvent.isComposing,
                })
              ) {
                event.preventDefault();
                if (
                  resolvedActionMode === "send"
                  && !resolvedActionDisabled
                  && (composerValue.trim() || hasComposerAttachments || hasComposerReferences)
                ) {
                  onSubmit();
                }
              }
            }}
          />
        </div>
        <input
          ref={attachmentInputRef}
          className={styles.hiddenAttachmentInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          disabled={attachmentInputDisabled}
          onChange={(event) => {
            if (event.currentTarget.files && onAddComposerAttachments) {
              onAddComposerAttachments(event.currentTarget.files);
            }
            event.currentTarget.value = "";
          }}
        />
        <button
          className={styles.attachButton}
          disabled={attachmentInputDisabled || !onAddComposerAttachments}
          type="button"
          onClick={() => attachmentInputRef.current?.click()}
          title={lang === "zh" ? "添加图片" : "Attach image"}
          aria-label={lang === "zh" ? "添加图片" : "Attach image"}
        >
          <ImagePlus size={16} />
        </button>
        {!runningGuidanceActionsEnabled || showSafeGuidanceAction ? (
          <button
            className={`${styles.sendButton} ${styles.composerRoundButton} ${styles.composerRoundButtonPrimary}`}
            disabled={runningGuidanceActionsEnabled ? guidanceActionDisabled || !onSafeGuidance : resolvedActionDisabled}
            type="button"
            onClick={runningGuidanceActionsEnabled ? onSafeGuidance : handlePrimaryAction}
            title={
              runningGuidanceActionsEnabled
                ? composerSafeGuidancePending
                  ? (safeGuidancePendingLabel ?? t("safeGuidancePending"))
                  : (safeGuidanceLabel ?? t("safeGuidance"))
                : composerPending
                  ? resolvedPendingLabel
                  : resolvedActionLabel
            }
            aria-label={
              runningGuidanceActionsEnabled
                ? composerSafeGuidancePending
                  ? (safeGuidancePendingLabel ?? t("safeGuidancePending"))
                  : (safeGuidanceLabel ?? t("safeGuidance"))
                : composerPending
                  ? resolvedPendingLabel
                  : resolvedActionLabel
            }
          >
            {composerPending || composerSafeGuidancePending ? (
              <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
            ) : (
              <ArrowUp size={18} aria-hidden="true" />
            )}
          </button>
        ) : null}
        {runningGuidanceActionsEnabled ? (
          <button
            className={`${styles.sendButton} ${styles.composerRoundButton} ${styles.stopButton}`}
            disabled={resolvedActionDisabled}
            type="button"
            onClick={handlePrimaryAction}
            title={composerPending ? resolvedPendingLabel : resolvedActionLabel}
            aria-label={composerPending ? resolvedPendingLabel : resolvedActionLabel}
          >
            {composerPending ? (
              <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
            ) : (
              <Square size={14} aria-hidden="true" />
            )}
          </button>
        ) : null}
      </div>
      ) : null}
      {previewImage ? (
        <div
          className={styles.imagePreviewOverlay}
          role="dialog"
          aria-modal="true"
          aria-label={previewImage.alt}
          onClick={() => setPreviewImage(null)}
        >
          <div className={styles.imagePreviewDialog} onClick={(event) => event.stopPropagation()}>
            <div className={styles.imagePreviewToolbar}>
              <span title={previewImage.alt}>{previewImage.alt}</span>
              <div className={styles.imagePreviewActions}>
                <a
                  className={styles.imageDownloadButton}
                  href={previewImage.downloadUrl}
                  download={previewImage.downloadName}
                  title={lang === "zh" ? "下载图片" : "Download image"}
                  aria-label={lang === "zh" ? "下载图片" : "Download image"}
                >
                  <Download size={15} />
                </a>
                <button
                  type="button"
                  className={styles.imagePreviewCloseButton}
                  onClick={() => setPreviewImage(null)}
                  title={lang === "zh" ? "关闭预览" : "Close preview"}
                  aria-label={lang === "zh" ? "关闭预览" : "Close preview"}
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <img className={styles.imagePreviewLarge} src={previewImage.src} alt={previewImage.alt} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
