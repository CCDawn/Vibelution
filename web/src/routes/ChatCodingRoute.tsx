import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  ArrowUpRight,
  BellRing,
  BookPlus,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  HeartHandshake,
  MessageCircleHeart,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Square,
  Trash2,
  UsersRound,
  RotateCcw,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import {
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  revokeProjectAgentBusMessage,
  sendProjectAgentBusMessage,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMessage,
  ChatRoomParticipant,
  ChatRoomRoundAcceptedResponse,
  ChatRoomMode,
  ChatRoomPurpose,
  ConfigSummary,
  ChatRoomStreamEvent,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionChatReviewCandidateResponse,
  SessionCacheCompositionSegment,
  SessionContextCompositionSegment,
  SessionDeleteResponse,
  SessionGuidanceMode,
  ConversationSummary,
  SessionDetail,
  SessionRuntimeNotice,
  SessionSummary,
  SessionStreamEvent,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
  SessionTurnError,
  TeamListPayload,
  ConversationMessage,
  ConversationAttachment,
} from "../api/types";
import type { TurnAvatarResolution } from "../components/conversation/ConversationView";
import { COMPOSER_SESSION_REFERENCE_MIME } from "../components/conversation/conversationConstants";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import { isAgentInboxMessage, isTurnErrorMessage } from "../components/conversation/messageSections";
import { LazyFilePreview } from "../components/preview/LazyFilePreview";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../app/browserTelemetry";
import { getPageInstanceId } from "../app/pageInstance";
import { resolvePollingInterval, usePageVisibility, useStartupWarmup } from "../app/pollingPolicy";
import type { TranslationKey } from "../i18n/dictionary";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { useShellStore } from "../store/shellStore";
import {
  clampPercent,
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "./chatShellFormat";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  appendOptimisticUserMessage,
  markSessionDetailRunning,
  markSessionSummaryRunning,
  mergeSessionDetailIntoSummaries,
  renameSessionDetail,
  renameSessionInSummaries,
  removeDeletedSessionFromSummaries,
  removeOptimisticUserMessage,
  shouldAcceptSessionStreamEvent,
} from "./chatSessionState";
import {
  captureSessionIndexCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateSessionSummaryCaches,
  useSessionIndexQuery,
} from "./chatSessionIndexQuery";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "./chatComposerState";
import { buildVisiblePanelRows, getPetAvatarPresetKey, getPetAvatarSymbol } from "./chatCompactPanel";
import {
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  type TokenSpeedTrackerState,
} from "./chatTokenSpeed";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "./agentDisplay";
import {
  DirectSessionIndexItem,
  isAgentRootSession,
  isChildSession,
  sessionAgentMetaLabel,
  sessionListTitle,
} from "./DirectSessionIndexItem";
import {
  GroupConversationIndexItem,
  TeamConversationIndexItem,
} from "./GroupSessionIndexItems";
import {
  buildChatMentionTargets,
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "./chatMentionTokens";
import styles from "./ChatCodingRoute.module.css";

function encodeUtf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function clearSessionImageAttachments(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
) {
  const attachments = current[sessionId] ?? [];
  attachments.forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

function clearSessionReferenceAttachments(
  current: Record<string, SessionReferenceAttachment[]>,
  sessionId: string,
) {
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

function sessionReferenceId(reference: SessionReferenceAttachment) {
  return String(reference.referenceId || reference.sessionId || "").trim();
}

function buildSessionReferencePayload(
  session: SessionSummary,
  displayName: string,
  summary: string,
): SessionReferenceAttachment {
  const sessionId = String(session.id || "").trim();
  return {
    referenceId: `session:${sessionId}`,
    kind: "session",
    sessionId,
    title: String(session.taskTitle || session.resultCard?.title || session.title || sessionId).trim(),
    agentId: String(session.agentId || "").trim(),
    agentCode: String(session.agentCode || "").trim(),
    agentDisplayName: String(displayName || session.agentDisplayName || "").trim(),
    summary: String(summary || session.taskSummary || "").trim(),
    createdAt: new Date().toISOString(),
  };
}

function startSessionReferenceDrag(
  event: DragEvent<HTMLElement>,
  reference: SessionReferenceAttachment,
) {
  const payload = JSON.stringify(reference);
  event.dataTransfer.setData(COMPOSER_SESSION_REFERENCE_MIME, payload);
  event.dataTransfer.setData("text/plain", `[Session Reference] ${reference.title || reference.sessionId}`);
  event.dataTransfer.effectAllowed = "copy";
}

function clearSessionDraftForSubmittedTurn(
  current: Record<string, string>,
  sessionId: string,
) {
  if ((current[sessionId] ?? "") === "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: "",
  };
}

function restoreSubmittedDraftIfComposerStillEmpty(
  current: Record<string, string>,
  sessionId: string,
  content: string,
) {
  if (!content || (current[sessionId] ?? "") !== "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: content,
  };
}

function chatRoomModeLabel(mode: ChatRoomMode, lang: "zh" | "en") {
  if (mode.id === "round_robin") {
    return lang === "zh" ? "轮询讨论" : "Round robin";
  }
  if (mode.id === "opportunistic") {
    return lang === "zh" ? "抢占式讨论" : "Opportunistic";
  }
  if (mode.id === "medical_consultation_panel") {
    return lang === "zh" ? "协同问诊会诊" : "Medical consultation";
  }
  return mode.label || mode.id;
}

function chatRoomPurposeLabel(purpose: ChatRoomPurpose, lang: "zh" | "en") {
  if (purpose.id === "chat") {
    return lang === "zh" ? "聊天" : "Chat";
  }
  if (purpose.id === "discussion") {
    return lang === "zh" ? "讨论" : "Discussion";
  }
  if (purpose.id === "meeting") {
    return lang === "zh" ? "会议" : "Meeting";
  }
  if (purpose.id === "medical_triage") {
    return lang === "zh" ? "医疗分诊建议" : "Medical triage";
  }
  return purpose.label || purpose.id;
}

function contextCompositionSegmentClass(key: string) {
  switch (key) {
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "active_task":
      return styles.contextCompositionSegmentTask;
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function cacheCompositionSegmentClass(key: string) {
  switch (key) {
    case "cached":
      return styles.contextCompositionSegmentCached;
    case "cache_write":
      return styles.contextCompositionSegmentCacheWrite;
    case "uncached":
      return styles.contextCompositionSegmentUncached;
    case "missing":
      return styles.contextCompositionSegmentMissing;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function contextCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `contextSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function cacheCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `cacheSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function compositionSegmentWidth(value: number, total: number) {
  if (total <= 0) {
    return "100%";
  }
  return `${Math.max(4, Math.round((Math.max(0, value) / total) * 1000) / 10)}%`;
}

function contextWindowSegmentWidth(value: number, total: number) {
  if (total <= 0 || value <= 0) {
    return "0%";
  }
  return `${Math.round((Math.max(0, value) / total) * 1000) / 10}%`;
}

function removeSessionImageAttachment(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
  attachmentId: string,
) {
  const attachments = current[sessionId] ?? [];
  const removed = attachments.find((attachment) => attachment.id === attachmentId);
  if (removed) {
    URL.revokeObjectURL(removed.previewUrl);
  }
  return {
    ...current,
    [sessionId]: attachments.filter((attachment) => attachment.id !== attachmentId),
  };
}

async function uploadSessionImageAttachment(sessionId: string, attachment: ComposerImageAttachment) {
  return fetchJson<ConversationAttachment>(`/api/sessions/${sessionId}/attachments`, {
    method: "POST",
    headers: {
      "Content-Type": attachment.contentType || "application/octet-stream",
      "X-Vibelution-Filename": encodeURIComponent(attachment.filename),
    },
    body: attachment.file,
  });
}

const RESIZE_HANDLE_WIDTH = 10;
const MIN_LEFT_PANEL_WIDTH = 192;
const MAX_LEFT_PANEL_WIDTH = 520;
const MIN_RIGHT_PANEL_WIDTH = 244;
const MAX_RIGHT_PANEL_WIDTH = 560;
const TARGET_CENTER_PANE_WIDTH = 520;
const KEYBOARD_RESIZE_STEP = 24;
const MENTAL_MODEL_TOGGLE_STORAGE_KEY = "vibelution.chat.mentalModelEnabled";
const MAX_COMPOSER_IMAGE_ATTACHMENTS = 4;
const MAX_COMPOSER_IMAGE_BYTES = 8 * 1024 * 1024;
const ACTIVE_INDEX_POLL_MS = 3_000;
const ACTIVE_BACKGROUND_SYNC_POLL_MS = 5_000;
const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350;
const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000;
const CHAT_CENTER_FIRST_MEDIA_QUERY = "(max-width: 980px)";

type ResizableSide = "left" | "right";
type PetInteractionAction = "feed" | "talk" | "care";
type FeaturePresetKey = "planningMode" | "goalMode" | "toolBoost";
type RightIndexPanel = "conversations" | "members";
type ConversationGroupKey =
  | "user"
  | "group"
  | "research"
  | "selfEvolution"
  | "supervisedEvolution"
  | "teams"
  | "standaloneGroups"
  | "other";
type ComposerImageAttachment = {
  id: string;
  file: File;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

type DragState = {
  side: ResizableSide;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
};

type SessionContextMenuState = {
  sessionId: string;
  session: SessionSummary;
  x: number;
  y: number;
};

const CHAT_FEATURE_PRESETS: Array<{
  key: FeaturePresetKey;
  labelKey: TranslationKey;
  hintKey: TranslationKey;
}> = [
  {
    key: "planningMode",
    labelKey: "chatFeaturePlanningMode",
    hintKey: "chatFeaturePlanningModeHint",
  },
  {
    key: "goalMode",
    labelKey: "chatFeatureGoalMode",
    hintKey: "chatFeatureGoalModeHint",
  },
  {
    key: "toolBoost",
    labelKey: "chatFeatureToolBoost",
    hintKey: "chatFeatureToolBoostHint",
  },
];

const DEFAULT_CHAT_FEATURE_PRESETS: Record<FeaturePresetKey, boolean> = {
  planningMode: false,
  goalMode: false,
  toolBoost: false,
};

const DEFAULT_COLLAPSED_CONVERSATION_GROUPS: Record<ConversationGroupKey, boolean> = {
  user: false,
  group: false,
  research: true,
  selfEvolution: true,
  supervisedEvolution: true,
  teams: false,
  standaloneGroups: true,
  other: true,
};

const CONVERSATION_GROUP_ORDER: ConversationGroupKey[] = [
  "user",
  "group",
  "research",
  "selfEvolution",
  "supervisedEvolution",
  "other",
];

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getDesiredCenterWidth(layoutWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  return Math.min(
    TARGET_CENTER_PANE_WIDTH,
    Math.max(0, usableWidth - MIN_LEFT_PANEL_WIDTH - MIN_RIGHT_PANEL_WIDTH),
  );
}

function normalizePanelWidths(layoutWidth: number, leftWidth: number, rightWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const availableForPanels = Math.max(
    MIN_LEFT_PANEL_WIDTH + MIN_RIGHT_PANEL_WIDTH,
    usableWidth - getDesiredCenterWidth(layoutWidth),
  );

  let nextLeft = clamp(leftWidth, MIN_LEFT_PANEL_WIDTH, MAX_LEFT_PANEL_WIDTH);
  let nextRight = clamp(rightWidth, MIN_RIGHT_PANEL_WIDTH, MAX_RIGHT_PANEL_WIDTH);
  let overflow = nextLeft + nextRight - availableForPanels;

  if (overflow > 0) {
    const rightSlack = nextRight - MIN_RIGHT_PANEL_WIDTH;
    const leftSlack = nextLeft - MIN_LEFT_PANEL_WIDTH;

    if (rightSlack >= leftSlack) {
      const reduceRight = Math.min(overflow, rightSlack);
      nextRight -= reduceRight;
      overflow -= reduceRight;

      const reduceLeft = Math.min(overflow, nextLeft - MIN_LEFT_PANEL_WIDTH);
      nextLeft -= reduceLeft;
    } else {
      const reduceLeft = Math.min(overflow, leftSlack);
      nextLeft -= reduceLeft;
      overflow -= reduceLeft;

      const reduceRight = Math.min(overflow, nextRight - MIN_RIGHT_PANEL_WIDTH);
      nextRight -= reduceRight;
    }
  }

  return {
    leftPanelWidth: Math.round(nextLeft),
    rightPanelWidth: Math.round(nextRight),
  };
}

function getResizeBounds(side: ResizableSide, layoutWidth: number, siblingWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const maxWidth = usableWidth - getDesiredCenterWidth(layoutWidth) - siblingWidth;

  if (side === "left") {
    return {
      min: MIN_LEFT_PANEL_WIDTH,
      max: Math.max(MIN_LEFT_PANEL_WIDTH, Math.min(MAX_LEFT_PANEL_WIDTH, maxWidth)),
    };
  }

  return {
    min: MIN_RIGHT_PANEL_WIDTH,
    max: Math.max(MIN_RIGHT_PANEL_WIDTH, Math.min(MAX_RIGHT_PANEL_WIDTH, maxWidth)),
  };
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function submitTelemetryFields(
  sessionId: string,
  options: {
    content?: string;
    attachmentCount?: number;
    referenceCount?: number;
    mentalModelEnabled?: boolean;
    editTargetId?: string;
    composerDisabled?: boolean;
    sessionBusy?: boolean;
    activePhase?: string;
    guardReason?: string;
    uploadedAttachmentCount?: number;
    error?: unknown;
  } = {},
) {
  const fields: Record<string, unknown> = {
    sessionId,
  };
  if (options.content !== undefined) {
    fields.contentLength = options.content.length;
    fields.hasContent = options.content.trim().length > 0;
  }
  if (options.attachmentCount !== undefined) {
    fields.attachmentCount = options.attachmentCount;
  }
  if (options.referenceCount !== undefined) {
    fields.referenceCount = options.referenceCount;
  }
  if (options.uploadedAttachmentCount !== undefined) {
    fields.uploadedAttachmentCount = options.uploadedAttachmentCount;
  }
  if (options.mentalModelEnabled !== undefined) {
    fields.mentalModelEnabled = options.mentalModelEnabled;
  }
  if (options.editTargetId !== undefined) {
    fields.editTargetId = options.editTargetId;
  }
  if (options.composerDisabled !== undefined) {
    fields.composerDisabled = options.composerDisabled;
  }
  if (options.sessionBusy !== undefined) {
    fields.sessionBusy = options.sessionBusy;
  }
  if (options.activePhase !== undefined) {
    fields.activePhase = options.activePhase;
  }
  if (options.guardReason !== undefined) {
    fields.guardReason = options.guardReason;
  }
  if (options.error instanceof Error) {
    fields.errorName = options.error.name;
    fields.errorMessage = options.error.message;
  } else if (options.error !== undefined) {
    fields.errorMessage = String(options.error);
  }
  return fields;
}

function postSubmitTelemetry(
  eventCode: string,
  message: string,
  sessionId: string,
  options?: Parameters<typeof submitTelemetryFields>[1],
  level: "info" | "warning" | "error" = "info",
) {
  postBrowserTelemetry({
    phase: "chat_submit",
    eventCode,
    message,
    level,
    fields: submitTelemetryFields(sessionId, options),
  });
}

function comparableErrorText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function latestVisibleTurnErrorMessage(messages: ConversationMessage[] | undefined) {
  const latestMessage = messages?.[messages.length - 1];
  return latestMessage && isTurnErrorMessage(latestMessage) ? String(latestMessage.content ?? "") : "";
}

function shouldSuppressComposerErrorForTurnError(
  composerError: string,
  latestTurnErrorMessage: string,
  turnError: SessionTurnError | null | undefined,
) {
  const composer = comparableErrorText(composerError);
  const latestMessage = comparableErrorText(latestTurnErrorMessage);
  const turnErrorMessage = comparableErrorText(turnError?.message);
  const turnErrorType = comparableErrorText(turnError?.errorType);
  if (!composer || !latestMessage) {
    return false;
  }
  return (
    (turnErrorMessage && (composer.includes(turnErrorMessage) || turnErrorMessage.includes(composer)))
    || composer.includes(latestMessage)
    || latestMessage.includes(composer)
    || (turnErrorType && composer.includes(turnErrorType))
  );
}

function isRunningPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return ["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"].includes(phase);
}

function isStoppingPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return phase === "stopping";
}

function isBusyPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return isRunningPhase(phase) || phase === "stopping";
}

function readStoredMentalModelToggle(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY);
  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }
  return null;
}

function writeStoredMentalModelToggle(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY, enabled ? "true" : "false");
}

function formatAgentIdentityWithRole(name: string, role: string, fallback = "Agent") {
  const cleanName = String(name || fallback || "Agent").trim() || "Agent";
  const cleanRole = String(role || "").trim();
  return cleanRole ? `${cleanName} · ${cleanRole}` : cleanName;
}

function compactAgentRoleLabel(role: string, fallback = "") {
  const cleanRole = String(role || "").trim();
  if (!cleanRole) {
    return String(fallback || "").trim();
  }
  const beforeSlash = cleanRole.split("/")[0]?.trim() || cleanRole;
  const beforePunctuation = beforeSlash.split(/[，,。；;：:]/)[0]?.trim() || beforeSlash;
  return beforePunctuation.length > 14 ? `${beforePunctuation.slice(0, 14)}...` : beforePunctuation;
}

function shouldCollapseGroupMessage(content: string) {
  const text = String(content || "").trim();
  return text.length > 260 || text.split(/\r?\n/).length > 8;
}

function shouldDefaultCollapseGroupMessage(message: ChatRoomMessage) {
  return message.audience === "internal" || message.visibility === "collapsed_by_default";
}

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const code = String(agentCode ?? "").trim();
  const numericTail = code.match(/\d{2,}$/)?.[0];
  if (numericTail) {
    return numericTail.slice(-2);
  }
  const compactCode = code.replace(/[^A-Za-z0-9]/g, "");
  if (compactCode && compactCode.length <= 3) {
    return compactCode.slice(0, 2).toUpperCase();
  }
  const title = String(name ?? "").trim();
  return title.slice(0, 2) || fallback;
}

function avatarImageUrlFrom(...sources: unknown[]) {
  for (const source of sources) {
    if (!source || typeof source !== "object") {
      continue;
    }
    const record = source as { avatarImageUrl?: unknown; agentAvatarImageUrl?: unknown };
    const url = String(record.avatarImageUrl ?? record.agentAvatarImageUrl ?? "").trim();
    if (url) {
      return url;
    }
  }
  return "";
}

function conversationMetadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripGroupSpeakerPrefix(message: ChatRoomMessage, identityName = "") {
  let content = String(message.content || message.summary || "").trim();
  if (!content) {
    return "";
  }
  const code = String(message.speakerCode ?? "").trim();
  const labels = [
    message.speakerTitle,
    identityName,
    code,
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
  labels.forEach((label) => {
    content = content.replace(new RegExp(`^\\s*${escapeRegExp(label)}\\s*[:：]\\s*`), "").trim();
  });
  if (code) {
    content = content.replace(
      new RegExp(`^\\s*${escapeRegExp(code)}\\s*[·\\-]\\s*[^\\n:：]{1,40}\\s*[:：]\\s*`),
      "",
    ).trim();
  }
  return content;
}

function isAvailableGroupParticipant(participant: ChatRoomParticipant) {
  return !participant.agentMissing && participant.enabled !== false;
}

function sessionToConversationSummary(session: SessionSummary): ConversationSummary {
  return {
    conversationId: session.id,
    type: "direct_agent",
    title: sessionListTitle(session),
    agentId: session.agentId,
    agentCode: session.agentCode,
    agentDisplayName: session.agentDisplayName,
    agentAvatarImagePath: session.agentAvatarImagePath,
    agentAvatarImageUrl: session.agentAvatarImageUrl,
    directSessionId: session.id,
    roomId: "",
    status: session.status,
    summary: session.taskSummary,
    updatedAt: session.updatedAt || session.lastActive,
    workspacePath: session.agentWorkspacePath || session.workspacePath || "",
    agentPrimaryMode: session.agentPrimaryMode,
    agentRoleKey: session.agentRoleKey,
    agentPromptTemplateId: session.agentPromptTemplateId,
    dialogueModelId: session.dialogueModelId,
  };
}

function isVisibleDirectSession(session: SessionSummary | undefined | null) {
  if (!session) {
    return false;
  }
  if (session.agentMissing) {
    return false;
  }
  if (!String(session.agentId ?? "").trim()) {
    return true;
  }
  return true;
}

function rootSessionIdFor(session: SessionSummary | undefined | null) {
  if (!session) {
    return "";
  }
  if (isChildSession(session)) {
    return String(session.rootSessionId || session.parentSessionId || "").trim();
  }
  return String(session.rootSessionId || session.id || "").trim();
}

function isRepresentedInAgentSessionTabs(session: SessionSummary | undefined | null) {
  return isChildSession(session);
}

function hasInvalidChildSessionLink(session: SessionSummary | undefined | null) {
  return isChildSession(session) && !rootSessionIdFor(session);
}

function isVisibleConversation(
  conversation: ConversationSummary,
  sessionsById?: Map<string, SessionSummary>,
) {
  if (conversation.type !== "direct_agent") {
    return true;
  }
  const sessionId = conversation.directSessionId || conversation.conversationId;
  const session = sessionId && sessionsById ? sessionsById.get(sessionId) : undefined;
  if (session) {
    return isVisibleDirectSession(session);
  }
  if (conversation.agentMissing) {
    return false;
  }
  if (!String(conversation.agentId ?? "").trim()) {
    return true;
  }
  return true;
}

function removeDeletedSessionFromConversations(
  conversations: ConversationSummary[] | undefined,
  deletedSessionId: string,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  return conversations.filter((conversation) => {
    if (conversation.type !== "direct_agent") {
      return true;
    }
    return conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId;
  });
}

function mergeSessionDetailIntoConversations(
  conversations: ConversationSummary[] | undefined,
  detail: SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  const nextConversation = sessionToConversationSummary(detail);
  const existingIndex = conversations.findIndex(
    (conversation) =>
      conversation.type === "direct_agent"
      && (conversation.directSessionId === detail.id || conversation.conversationId === detail.id),
  );
  if (existingIndex < 0) {
    return [nextConversation, ...conversations];
  }
  return conversations.map((conversation, index) =>
    index === existingIndex
      ? {
          ...conversation,
          ...nextConversation,
        }
      : conversation,
  );
}

function renameSessionInConversations(
  conversations: ConversationSummary[] | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
  session?: SessionSummary | SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations || !sessionId) {
    return conversations;
  }

  return conversations.map((conversation) => {
    const directSessionId = String(conversation.directSessionId || conversation.conversationId || "").trim();
    if (conversation.type !== "direct_agent" || directSessionId !== sessionId) {
      return conversation;
    }
    if (session && isAgentRootSession(session)) {
      return {
        ...conversation,
        title,
        agentDisplayName: title,
        updatedAt,
      };
    }
    return {
      ...conversation,
      title,
      updatedAt,
    };
  });
}

function mergeVisibleSessionsIntoConversations(
  conversations: ConversationSummary[] | undefined,
  sessions: SessionSummary[],
): ConversationSummary[] {
  const merged = [...(conversations ?? [])];
  const directSessionIds = new Set(
    merged
      .filter((conversation) => conversation.type === "direct_agent")
      .map((conversation) => String(conversation.directSessionId || conversation.conversationId || "").trim())
      .filter(Boolean),
  );
  for (const session of sessions) {
    if (directSessionIds.has(session.id)) {
      continue;
    }
    merged.push(sessionToConversationSummary(session));
    directSessionIds.add(session.id);
  }
  return merged.sort((left, right) =>
    String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")),
  );
}

function latestSessionMessageId(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  return messages[messages.length - 1]?.id ?? "";
}

function latestSessionMessageSignal(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  const message = messages[messages.length - 1];
  if (!message) {
    return "";
  }
  return [
    message.id ?? "",
    message.streaming ? "streaming" : "settled",
    message.content?.length ?? 0,
    message.toolCalls?.length ?? 0,
    message.feedbackEvents?.length ?? 0,
  ].join(":");
}

function sessionDetailSnapshotKey(detail: SessionDetail): string {
  return [
    detail.id,
    detail.status ?? "",
    detail.currentPhase ?? "",
    detail.updatedAt ?? "",
    detail.messages?.length ?? 0,
    latestSessionMessageId(detail),
    latestSessionMessageSignal(detail),
  ].join("|");
}

function mergeAssistantDeltaIntoSessionDetail(
  detail: SessionDetail | undefined,
  payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
): SessionDetail | undefined {
  if (!detail || detail.id !== payload.sessionId) {
    return detail;
  }
  const liveMessageId = `${payload.sessionId}-message-live`;
  const now = payload.updatedAt || new Date().toISOString();
  const messages = detail.messages ?? [];
  if (!payload.content && !payload.thought && !payload.stage) {
    return {
      ...detail,
      updatedAt: now,
      messages: messages.filter((message) => message.id !== liveMessageId),
    };
  }
  const nextLiveMessage: ConversationMessage = {
    id: liveMessageId,
    role: "assistant",
    content: payload.content || "",
    timestamp: now,
    streaming: !payload.done,
    streamStage: payload.stage || undefined,
    thought: payload.thought || undefined,
    feedbackEvents: payload.feedbackEvents ?? [],
  };
  const liveIndex = messages.findIndex((message) => message.id === liveMessageId);
  if (liveIndex >= 0) {
    const previous = messages[liveIndex];
    const merged: ConversationMessage = {
      ...previous,
      ...nextLiveMessage,
      mentalSnapshot: previous.mentalSnapshot,
      toolCalls: previous.toolCalls,
    };
    return {
      ...detail,
      updatedAt: now,
      messages: [
        ...messages.slice(0, liveIndex),
        merged,
        ...messages.slice(liveIndex + 1),
      ],
    };
  }
  return {
    ...detail,
    updatedAt: now,
    messages: [...messages, nextLiveMessage],
  };
}

function classifyConversation(conversation: ConversationSummary): ConversationGroupKey {
  if (conversation.type === "group_room") {
    return "group";
  }
  const primaryMode = String(conversation.agentPrimaryMode ?? "").trim().toLowerCase();
  const roleKey = String(conversation.agentRoleKey ?? "").trim().toLowerCase();
  const promptTemplateId = String(conversation.agentPromptTemplateId ?? "").trim().toLowerCase();
  const title = String(conversation.title ?? "").trim().toLowerCase();
  const combined = `${primaryMode} ${roleKey} ${promptTemplateId} ${title}`;
  if (
    primaryMode === "research"
    || roleKey.startsWith("research_")
    || promptTemplateId.startsWith("prompt-research-")
    || combined.includes("research")
    || combined.includes("广撒网 agent")
    || combined.includes("定向深搜 agent")
    || combined.includes("证据审查 agent")
    || combined.includes("主题生成 agent")
    || combined.includes("主题卡 agent")
  ) {
    return "research";
  }
  if (combined.includes("self_evolution") || combined.includes("自进化")) {
    return "selfEvolution";
  }
  if (combined.includes("supervised") || combined.includes("监督进化")) {
    return "supervisedEvolution";
  }
  if (title.includes("agent")) {
    return "other";
  }
  return "user";
}

function conversationGroupLabel(groupKey: ConversationGroupKey, lang: "zh" | "en") {
  const labels: Record<ConversationGroupKey, { zh: string; en: string }> = {
    user: { zh: "用户会话", en: "User chats" },
    group: { zh: "群聊", en: "Group chats" },
    research: { zh: "科研 Agent", en: "Research agents" },
    selfEvolution: { zh: "自进化 Agent", en: "Self-evolution agents" },
    supervisedEvolution: { zh: "监督进化 Agent", en: "Supervised agents" },
    teams: { zh: "团队", en: "Teams" },
    standaloneGroups: { zh: "未归属群聊", en: "Standalone groups" },
    other: { zh: "其他 Agent", en: "Other agents" },
  };
  return labels[groupKey][lang];
}

function latestMentalSnapshot(messages: ConversationMessage[] | undefined): MentalStateSnapshot | undefined {
  return [...(messages ?? [])].reverse().find((message) => message.role === "assistant" && message.mentalSnapshot)?.mentalSnapshot;
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

export function ChatCodingRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const location = useLocation();
  const chatPanelWidths = useShellStore((state) => state.chatPanelWidths);
  const setChatPanelWidths = useShellStore((state) => state.setChatPanelWidths);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false);
  const [centerFirstLayout, setCenterFirstLayout] = useState(false);
  const centerFirstAutoCollapseRef = useRef(false);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const [tokenSpeedTracker, setTokenSpeedTracker] = useState<TokenSpeedTrackerState | null>(null);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [featurePresetState, setFeaturePresetState] = useState<Record<FeaturePresetKey, boolean>>(
    DEFAULT_CHAT_FEATURE_PRESETS,
  );
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<ConversationGroupKey, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [expandedGroupAgentSessionIds, setExpandedGroupAgentSessionIds] = useState<string[]>([]);
  const [expandedGroupMessageIds, setExpandedGroupMessageIds] = useState<string[]>([]);
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamApplyStatsRef = useRef<Record<string, { received: number; applied: number; dropped: number }>>({});
  const groupStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const requestedRoomId = useMemo(() => {
    return new URLSearchParams(location.search).get("room") ?? "";
  }, [location.search]);
  const pageVisible = usePageVisibility();
  const [chatStartupDataReady, setChatStartupDataReady] = useState(false);
  const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady);
  const chatPollingVisible = pageVisible || chatStartupWarmupActive;
  const projectBusActive = activeGroupRoomId === "__project_agent_bus__";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const legacyGroupRoomActive = groupPanelActive && !projectBusActive;
  const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive;
  const sessionQueryText = sessionFilter.trim();
  const [directSessionBackgroundSyncActive, setDirectSessionBackgroundSyncActive] = useState(false);
  const [groupBackgroundSyncActive, setGroupBackgroundSyncActive] = useState(false);
  const sessionStreamRouteTargetMatches = Boolean(
    activeSessionId
    && !groupPanelActive
    && (!requestedSessionId || requestedSessionId === activeSessionId),
  );

  useEffect(() => {
    if (!sessionContextMenu) {
      return;
    }
    function closeSessionContextMenu() {
      setSessionContextMenu(null);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeSessionContextMenu();
      }
    }
    window.addEventListener("pointerdown", closeSessionContextMenu);
    window.addEventListener("scroll", closeSessionContextMenu, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeSessionContextMenu);
      window.removeEventListener("scroll", closeSessionContextMenu, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [sessionContextMenu]);
  const sessionStreamRouteSettling = Boolean(
    activeSessionId
    && !groupPanelActive
    && requestedSessionId
    && requestedSessionId !== activeSessionId,
  );
  const sessionStreamGraceSessionRef = useRef("");
  const sessionStreamGraceUntilRef = useRef(0);
  if (activeSessionId && sessionStreamGraceSessionRef.current !== activeSessionId) {
    sessionStreamGraceSessionRef.current = activeSessionId;
    sessionStreamGraceUntilRef.current = Date.now() + SESSION_STREAM_ROUTE_SWITCH_GRACE_MS;
  }
  const sessionStreamRouteSwitchGraceActive = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && sessionStreamGraceSessionRef.current === activeSessionId
    && Date.now() < sessionStreamGraceUntilRef.current,
  );
  const sessionStreamShouldConnect = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && (chatPollingVisible || sessionStreamRouteSwitchGraceActive),
  );
  const groupStreamShouldConnect = Boolean(
    legacyGroupRoomActive
    && activeGroupRoomId
    && (chatPollingVisible || groupBackgroundSyncActive),
  );
  useEffect(() => {
    if (!legacyGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [legacyGroupRoomActive, rightIndexPanel]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, 5_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, 10_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    staleTime: 30_000,
  });
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const rawSessionsQuery = useSessionIndexQuery({
    queryClient,
    queryText: sessionQueryText,
    refetchInterval: resolvePollingInterval(
      chatPollingVisible,
      sessionStreamConnected && directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS,
      { backgroundMs: directSessionBackgroundSyncActive && !sessionStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
    ),
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter(isVisibleDirectSession),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = {
    ...rawSessionsQuery,
    data: visibleSessionsData,
  };
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => fetchJson<ConversationSummary[]>("/api/conversations"),
    refetchInterval: resolvePollingInterval(
      chatPollingVisible,
      (sessionStreamConnected && directSessionPanelActive) || (groupStreamConnected && legacyGroupRoomActive)
        ? false
        : ACTIVE_INDEX_POLL_MS,
      {
        backgroundMs:
          (directSessionBackgroundSyncActive && !sessionStreamConnected)
          || (groupBackgroundSyncActive && !groupStreamConnected)
            ? ACTIVE_BACKGROUND_SYNC_POLL_MS
            : false,
      },
    ),
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive || groupBackgroundSyncActive,
  });
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: groupComposerOpen || Boolean(activeSessionId),
  });
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: legacyGroupRoomActive,
    refetchInterval: legacyGroupRoomActive
      ? resolvePollingInterval(
          chatPollingVisible,
          groupStreamConnected ? false : 3_000,
          { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: () => listProjectAgentBusTimeline(),
    enabled: projectBusActive,
    refetchInterval: projectBusActive ? resolvePollingInterval(chatPollingVisible, 3_000) : false,
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const expandedGroupAgentDetailQueries = useQueries({
    queries: expandedGroupAgentSessionIds.map((sessionId) => ({
      queryKey: queryKeys.session(sessionId || "none"),
      queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${sessionId}`),
      enabled: legacyGroupRoomActive && Boolean(sessionId),
      refetchInterval: legacyGroupRoomActive && sessionId
        ? resolvePollingInterval(
            chatPollingVisible,
            3_000,
            { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
          )
        : false,
      refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
    })),
  });
  const syncSessionDetail = useCallback(
    (detail: SessionDetail) => {
      let shouldSyncSummaries = true;
      queryClient.setQueryData<SessionDetail>(queryKeys.session(detail.id), (previous) => {
        if (previous && sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(detail)) {
          shouldSyncSummaries = false;
          return previous;
        }
        return detail;
      });
      if (!shouldSyncSummaries) {
        return;
      }
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, detail),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        mergeSessionDetailIntoConversations(conversations, detail),
      );
    },
    [queryClient],
  );
  const syncChatRoomDetail = useCallback(
    (room: ChatRoomDetail) => {
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
      }
    },
    [chatWorkspaceCache, queryClient],
  );
  const directSessionActiveSummary = useMemo(
    () => (activeSessionId ? sessionsQuery.data?.find((session) => session.id === activeSessionId) : undefined),
    [activeSessionId, sessionsQuery.data],
  );
  useEffect(() => {
    setGroupBackgroundSyncActive(Boolean(
      legacyGroupRoomActive
      && isBusyPhase(activeGroupRoomQuery.data?.status),
    ));
  }, [activeGroupRoomQuery.data?.status, legacyGroupRoomActive]);
  useEffect(() => {
    if (requestedRoomId && activeGroupRoomId !== requestedRoomId) {
      setActiveGroupRoomId(requestedRoomId);
      setRightIndexPanel("members");
      setRightPaneCollapsed(false);
      setGroupRoomActionError("");
      return;
    }
    if (
      requestedSessionId
      && !requestedRoomId
      && sessionsQuery.data?.some((session) => session.id === requestedSessionId)
      && activeSessionId !== requestedSessionId
    ) {
      setActiveGroupRoomId("");
      setActiveSession(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setActiveSession(sessionsQuery.data[0].id);
      return;
    }
    if (
      activeSessionId
      && !requestedRoomId
      && sessionsQuery.data
      && sessionsQuery.data.length > 0
      && !sessionsQuery.data.some((session) => session.id === activeSessionId)
    ) {
      setActiveSession(sessionsQuery.data[0].id);
    }
  }, [activeGroupRoomId, activeSessionId, requestedRoomId, requestedSessionId, sessionsQuery.data, setActiveSession]);

  useEffect(() => {
    const pendingHandoff = loadPendingSelfEvolutionHandoff();
    if (!pendingHandoff || !sessionsQuery.data || sessionsQuery.data.length === 0) {
      return;
    }
    const matchedSession = sessionsQuery.data.find((item) => item.id === pendingHandoff.sessionId);
    const targetSessionId = matchedSession?.id || activeSessionId || sessionsQuery.data[0]?.id || "";
    if (!targetSessionId) {
      return;
    }
    if (activeSessionId !== targetSessionId) {
      setActiveSession(targetSessionId);
    }
    setSessionDrafts((current) => ({
      ...current,
      [targetSessionId]: pendingHandoff.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [targetSessionId]: "",
    }));
    clearPendingSelfEvolutionHandoff();
  }, [activeSessionId, sessionsQuery.data, setActiveSession]);

  const sessionDetailQuery = useQuery({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    enabled: Boolean(activeSessionId),
    queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${activeSessionId}`),
    refetchInterval: activeSessionId
      ? resolvePollingInterval(
          chatPollingVisible,
          sessionStreamConnected ? false : 3_000,
          { backgroundMs: directSessionBackgroundSyncActive && !sessionStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive,
  });
  useEffect(() => {
    const directReady = Boolean(activeSessionId ? sessionDetailQuery.data : sessionsQuery.data);
    const groupReady = !legacyGroupRoomActive || Boolean(activeGroupRoomQuery.data);
    if (runtimeQuery.data && sessionsQuery.data && conversationsQuery.data && teamsQuery.data && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    conversationsQuery.data,
    legacyGroupRoomActive,
    runtimeQuery.data,
    sessionDetailQuery.data,
    sessionsQuery.data,
    teamsQuery.data,
  ]);
  useEffect(() => {
    setDirectSessionBackgroundSyncActive(Boolean(
      activeSessionId
      && directSessionPanelActive
      && isBusyPhase(sessionDetailQuery.data?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status),
    ));
  }, [
    activeSessionId,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
    directSessionPanelActive,
    sessionDetailQuery.data?.currentPhase,
  ]);

  const submitTurnMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds,
        references,
      }: {
        sessionId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
        references?: SessionReferenceAttachment[];
      },
    ) => {
      postSubmitTelemetry(
        "browser.chat_submit.request_started",
        "Direct chat submit request started.",
        sessionId,
        {
          content,
          attachmentCount: attachmentIds?.length ?? 0,
          referenceCount: references?.length ?? 0,
          mentalModelEnabled,
        },
      );
      return fetchJson<SessionTurnAcceptedResponse>(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Prefer": "respond-async",
        },
        body: JSON.stringify({
          content,
          contentUtf8Base64: encodeUtf8Base64(content),
          attachmentIds: attachmentIds ?? [],
          references: references ?? [],
          mentalModelEnabled,
        }),
      });
    },
    onMutate: async (variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.mutate_called",
        "Direct chat submit mutation started.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
        },
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detail, variables)),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (acceptedTurn, variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.accepted",
        "Direct chat submit was accepted by the backend.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
        },
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, variables.sessionId));
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      void chatWorkspaceCache.afterDirectTurnAccepted(acceptedTurn.sessionId || variables.sessionId);
    },
    onError: (error, variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.request_failed",
        "Direct chat submit request failed before the backend accepted the turn.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          error,
        },
        "error",
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        removeOptimisticUserMessage(detail, variables),
      );
      setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content));
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("submitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const editResubmitMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        content,
        mentalModelEnabled,
        attachmentIds: _attachmentIds,
      }: {
        sessionId: string;
        messageId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/messages/edit-resubmit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messageId, content, contentUtf8Base64: encodeUtf8Base64(content), mentalModelEnabled }),
      }),
    onMutate: async (variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionEditTargets((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/stop`, {
        method: "POST",
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const sessionGuidanceMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mode,
      }: {
        sessionId: string;
        content: string;
        mode: SessionGuidanceMode;
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/guidance`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, mode }),
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("guidanceFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: async () =>
      fetchJson<SessionDetail>("/api/sessions", {
        method: "POST",
      }),
    onSuccess: (nextDetail) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setActiveSession(nextDetail.id);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("createSessionFailed")),
      }));
      void chatWorkspaceCache.refreshConversationIndex();
    },
  });

  const createGroupRoomMutation = useMutation({
    mutationFn: async (
      { title, agentIds, mode, purpose }: { title: string; agentIds: string[]; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomDetail>("/api/chat-rooms", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title, agentIds, mode, purpose }),
      }),
    onSuccess: (room) => {
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupPurposeDraft("discussion");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          lang === "zh" ? "创建群聊失败" : "Create group chat failed",
        ),
      }));
    },
  });

  const startGroupRoundMutation = useMutation({
    mutationFn: async (
      { roomId, topic, mode, purpose }: { roomId: string; topic: string; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomRoundAcceptedResponse>(`/api/chat-rooms/${roomId}/rounds`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Prefer": "respond-async",
        },
        body: JSON.stringify({ topic, mode, purpose }),
      }),
    onSuccess: (accepted) => {
      setActiveGroupRoomId(accepted.roomId);
      setRightIndexPanel("members");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const stopGroupRoundMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/stop`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterGroupRoundStopped(room.roomId);
    },
    onError: (error, variables) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void chatWorkspaceCache.afterGroupRoundStopped(variables.roomId);
    },
  });

  const sendProjectBusMessageMutation = useMutation({
    mutationFn: async (
      {
        content,
        interruptTargets,
      }: {
        content: string;
        interruptTargets: boolean;
      },
    ) =>
      sendProjectAgentBusMessage({ content, interruptTargets }),
    onSuccess: () => {
      setProjectBusDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const revokeProjectBusMessageMutation = useMutation({
    mutationFn: async ({ eventId }: { eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "user_recalled_project_bus_message",
      }),
    onSuccess: () => {
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const updateGroupRoomMutation = useMutation({
    mutationFn: async (
      { roomId, title, sessionIds, mode, purpose }: {
        roomId: string;
        title: string;
        sessionIds: string[];
        mode: string;
        purpose: string;
      },
    ) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title,
          participantSessionIds: sessionIds,
          mode,
          purpose,
        }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupManageTitleDraft(room.title || "");
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
      setGroupManagePurposeDraft(room.purpose || "discussion");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<{ deleted: boolean; roomId: string }>(`/api/chat-rooms/${roomId}`, {
        method: "DELETE",
      }),
    onSuccess: (_payload, variables) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      setGroupManageTitleDraft("");
      setGroupManageSessionIds([]);
      setGroupManageModeDraft("round_robin");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      void chatWorkspaceCache.afterChatRoomChanged(variables.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const resetGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/reset`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "重置群聊失败" : "Reset group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`, {
        method: "DELETE",
        headers: {
          "Prefer": "respond-async",
        },
      }),
    onSuccess: (deleteResult, variables) => {
      const nextActiveSessionId = deleteResult.nextActiveSessionId || "";
      removeSessionWorkspace(variables.sessionId, nextActiveSessionId);
      setActiveSession(nextActiveSessionId);
      setSessionDrafts((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      delete imageUploadInFlightRef.current[variables.sessionId];
      setSessionImageUploadPending((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return nextActiveSessionId
          ? {
              ...remaining,
              [nextActiveSessionId]: "",
            }
          : remaining;
      });
      queryClient.removeQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.filter((session) => session.id !== variables.sessionId),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        removeDeletedSessionFromConversations(conversations, variables.sessionId),
      );
      setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));
      void chatWorkspaceCache.afterChatRoomsChanged();
      if (nextActiveSessionId) {
        void chatWorkspaceCache.refreshSessionRuntime(nextActiveSessionId);
      }
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("deleteSessionFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const renameSessionMutation = useMutation({
    mutationFn: async ({ sessionId, title }: { sessionId: string; title: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title }),
      }),
    onMutate: (variables) => {
      const updatedAt = new Date().toISOString();
      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const targetSession = previousDetail ?? previousSessions?.find((session) => session.id === variables.sessionId);
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, variables.title, updatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, variables.title, updatedAt, targetSession),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, variables.title, updatedAt),
      );
      return { previousSessions, previousSessionIndexCaches, previousConversations, previousDetail };
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      const confirmedTitle = String(nextDetail.title || variables.title).trim() || variables.title;
      const confirmedUpdatedAt = String(nextDetail.updatedAt || new Date().toISOString()).trim();
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, confirmedTitle, confirmedUpdatedAt, nextDetail),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) => ({
        ...(detail ?? nextDetail),
        ...nextDetail,
      }));
    },
    onError: (error, variables, context) => {
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), context.previousDetail);
      }
      setEditingSessionId(variables.sessionId);
      setEditingSessionTitle(variables.title);
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("renameSessionFailed")),
      }));
    },
  });

  const addSessionToReviewMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionChatReviewCandidateResponse>(
        `/api/sessions/${sessionId}/chat-review-candidate`,
        {
          method: "POST",
        },
      ),
    onSuccess: (payload, variables) => {
      const detail = payload.summary
        ? `${t("addSessionToReviewSucceeded")} ${payload.summary}`
        : t("addSessionToReviewSucceeded");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: detail,
        __sessions__: "",
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("addSessionToReviewFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
  });

  const petActionMutation = useMutation({
    mutationFn: async ({ action }: { action: PetInteractionAction }) =>
      fetchJson<PetActionResponse>("/api/pet/actions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      }),
    onSuccess: (payload) => {
      setPetActionFeedback(payload.message);
      queryClient.setQueryData(queryKeys.petSummary(), payload.summary);
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
    onError: (error) => {
      setPetActionFeedback(describeError(error, lang === "zh" ? "宠物互动失败" : "Pet interaction failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
  });

  const activeGroupRoom = activeGroupRoomQuery.data;
  const teams = teamsQuery.data?.teams ?? [];
  const linkedTeamRoomIds = useMemo(() => {
    return new Set(teams.map((team) => String(team.linkedChatRoomId ?? "").trim()).filter(Boolean));
  }, [teams]);
  const activeGroupTeam = useMemo(() => {
    const roomId = String(activeGroupRoom?.roomId || activeGroupRoomId || "").trim();
    const configTeamId = String((activeGroupRoom?.config ?? {}).teamId ?? "").trim();
    return teams.find((team) => {
      const teamId = String(team.teamId ?? "").trim();
      const linkedRoomId = String(team.linkedChatRoomId ?? team.linkedChatRoom?.roomId ?? "").trim();
      return (configTeamId && teamId === configTeamId) || (roomId && linkedRoomId === roomId);
    }) ?? null;
  }, [activeGroupRoom?.config, activeGroupRoom?.roomId, activeGroupRoomId, teams]);
  const activeGroupTeamOwned = Boolean(activeGroupTeam);
  const availableGroupParticipants = useMemo(
    () => (activeGroupRoom?.participants ?? []).filter(isAvailableGroupParticipant),
    [activeGroupRoom?.participants],
  );
  const availableGroupParticipantCount = availableGroupParticipants.length;

  useEffect(() => {
    if (activeSessionId && sessionDetailQuery.data) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data]);

  useEffect(() => {
    if (!activeGroupRoom) {
      return;
    }
    const existingSessionIds = new Set((sessionsQuery.data ?? []).map((session) => session.id));
    setGroupManageSessionIds(
      activeGroupRoom.participants
        .map((participant) => participant.sessionId)
        .filter((sessionId) => existingSessionIds.has(sessionId)),
    );
    setGroupManageTitleDraft(activeGroupRoom.title || "");
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
    setGroupManagePurposeDraft(activeGroupRoom.purpose || "discussion");
  }, [activeGroupRoom, sessionsQuery.data]);

  useEffect(() => {
    if (!sessionStreamShouldConnect || typeof EventSource === "undefined") {
      setSessionStreamConnected(false);
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.skipped",
        message: "Session detail stream connection was skipped.",
        level: "info",
        fields: {
          sessionId: activeSessionId || "",
          shouldConnect: sessionStreamShouldConnect,
          pageVisible,
          chatStartupWarmupActive,
          chatPollingVisible,
          directSessionBackgroundSyncActive,
          routeTargetMatches: sessionStreamRouteTargetMatches,
          routeSettling: sessionStreamRouteSettling,
          routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
          visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
          eventSourceAvailable: typeof EventSource !== "undefined",
          pageInstanceId: getPageInstanceId(),
          ...collectBrowserPageSnapshot(),
        },
      });
      return;
    }

    let disposed = false;
    let pendingDetail: SessionDetail | null = null;
    let applyTimer: ReturnType<typeof window.setTimeout> | null = null;
    let lastAppliedAt = 0;
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId) {
      setSessionStreamConnected(false);
      return;
    }
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.effect_started",
      message: "Session detail stream effect started.",
      level: "info",
      fields: {
        sessionId: streamSessionId,
        shouldConnect: sessionStreamShouldConnect,
        pageVisible,
        chatStartupWarmupActive,
        chatPollingVisible,
        directSessionBackgroundSyncActive,
        routeTargetMatches: sessionStreamRouteTargetMatches,
        routeSettling: sessionStreamRouteSettling,
        routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
        routeSwitchGraceMsRemaining: Math.max(0, sessionStreamGraceUntilRef.current - Date.now()),
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
        pageInstanceId: getPageInstanceId(),
        ...collectBrowserPageSnapshot(),
      },
    });
    const stream = new EventSource(`/api/sessions/${streamSessionId}/events`);

    function applyPendingDetail(reason: "timer" | "close" | "final") {
      if (!pendingDetail || disposed) {
        return;
      }
      const detail = pendingDetail;
      pendingDetail = null;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      lastAppliedAt = Date.now();
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.applied += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      if (stats.applied === 1 || (stats.dropped > 0 && stats.applied % 20 === 0)) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_applied",
          message: "Session detail stream snapshot was applied to the UI cache.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            reason,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            messageCount: detail.messages?.length ?? 0,
            currentPhase: detail.currentPhase || detail.status || "",
          },
        });
      }
      syncSessionDetail(detail);
    }

    function queueSessionDetail(detail: SessionDetail, payloadLength: number) {
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      if (pendingDetail) {
        stats.dropped += 1;
      }
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      pendingDetail = detail;
      const phase = String(detail.currentPhase || detail.status || "").trim().toLowerCase();
      if (phase && !isBusyPhase(phase)) {
        applyPendingDetail("final");
        return;
      }
      const elapsed = Date.now() - lastAppliedAt;
      const delayMs = Math.max(0, SESSION_STREAM_MIN_APPLY_INTERVAL_MS - elapsed);
      if (!applyTimer) {
        applyTimer = window.setTimeout(() => {
          applyTimer = null;
          applyPendingDetail("timer");
        }, delayMs);
      }
      if (stats.received === 1 || stats.received % 20 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_queued",
          message: "Session detail stream snapshot was queued before UI cache apply.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            payloadLength,
            messageCount: detail.messages?.length ?? 0,
            currentPhase: detail.currentPhase || detail.status || "",
            minApplyIntervalMs: SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
          },
        });
      }
    }

    stream.onopen = () => {
      if (!disposed) {
        setSessionStreamConnected(true);
        sessionStreamErrorLoggedRef.current[streamSessionId] = false;
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.opened",
          message: "Session detail stream opened.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setSessionStreamConnected(false);
        if (!sessionStreamErrorLoggedRef.current[streamSessionId]) {
          sessionStreamErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.error",
            message: "Session detail stream reported an error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
            },
          });
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message: "Session detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (!shouldAcceptSessionStreamEvent(payload, streamSessionId) || payload.type !== "session_detail") {
        return;
      }
      setSessionStreamConnected(true);
      queueSessionDetail(payload.detail, event.data.length);
    }

    function handleAssistantDelta(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message: "Session assistant delta stream payload could not be parsed.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (!shouldAcceptSessionStreamEvent(payload, streamSessionId) || payload.type !== "assistant_delta") {
        return;
      }
      setSessionStreamConnected(true);
      queryClient.setQueryData<SessionDetail>(queryKeys.session(streamSessionId), (detail) =>
        mergeAssistantDeltaIntoSessionDetail(detail, payload),
      );
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      stats.applied += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      if (stats.applied === 1 || stats.applied % 50 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_applied",
          message: "Session assistant delta stream was applied to the UI cache.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            turnId: payload.turnId,
            stage: payload.stage,
            appliedCount: stats.applied,
            payloadLength: event.data.length,
            contentLength: payload.content.length,
            thoughtLength: payload.thought.length,
            done: payload.done,
          },
        });
      }
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);
    stream.addEventListener("assistant_delta", handleAssistantDelta as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      applyPendingDetail("close");
      disposed = true;
      setSessionStreamConnected(false);
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.removeEventListener("assistant_delta", handleAssistantDelta as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.closed",
        message: "Session detail stream closed.",
        fields: {
          sessionId: streamSessionId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [
    activeSessionId,
    chatPollingVisible,
    chatStartupWarmupActive,
    directSessionBackgroundSyncActive,
    pageVisible,
    sessionStreamRouteSettling,
    sessionStreamRouteSwitchGraceActive,
    sessionStreamRouteTargetMatches,
    sessionStreamShouldConnect,
    syncSessionDetail,
  ]);

  useEffect(() => {
    if (!groupStreamShouldConnect || typeof EventSource === "undefined") {
      setGroupStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamRoomId = String(activeGroupRoomId || "");
    if (!streamRoomId) {
      setGroupStreamConnected(false);
      return;
    }
    const stream = new EventSource(`/api/chat-rooms/${streamRoomId}/events`);

    stream.onopen = () => {
      if (!disposed) {
        setGroupStreamConnected(true);
        groupStreamErrorLoggedRef.current[streamRoomId] = false;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.opened",
          message: "Chat room detail stream opened.",
          level: "info",
          fields: {
            roomId: streamRoomId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setGroupStreamConnected(false);
        if (!groupStreamErrorLoggedRef.current[streamRoomId]) {
          groupStreamErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.error",
            message: "Chat room detail stream reported an error.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              readyState: stream.readyState,
            },
          });
        }
      }
    };

    function handleChatRoomDetail(event: MessageEvent<string>) {
      let payload: ChatRoomStreamEvent;
      try {
        payload = JSON.parse(event.data) as ChatRoomStreamEvent;
      } catch {
        if (!groupStreamPayloadErrorLoggedRef.current[streamRoomId]) {
          groupStreamPayloadErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.bad_payload",
            message: "Chat room detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (payload.roomId !== streamRoomId || payload.detail?.roomId !== streamRoomId) {
        return;
      }
      setGroupStreamConnected(true);
      syncChatRoomDetail(payload.detail);
    }

    stream.addEventListener("chat_room_detail", handleChatRoomDetail as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      disposed = true;
      setGroupStreamConnected(false);
      stream.removeEventListener("chat_room_detail", handleChatRoomDetail as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "chat_room_stream",
        eventCode: "browser.chat_room_stream.closed",
        message: "Chat room detail stream closed.",
        fields: {
          roomId: streamRoomId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [activeGroupRoomId, groupStreamShouldConnect, syncChatRoomDetail]);

  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeFilePath = workspace.activeTab !== "agent" ? workspace.activeTab : null;
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () =>
      fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(activeFilePath ?? "")}`),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);
  const leftPanelWidth = chatPanelWidths.leftPanelWidth;
  const rightPanelWidth = chatPanelWidths.rightPanelWidth;

  const syncPanelWidthsToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizePanelWidths(layoutWidth, leftPanelWidth, rightPanelWidth);
    if (
      normalized.leftPanelWidth !== leftPanelWidth ||
      normalized.rightPanelWidth !== rightPanelWidth
    ) {
      setChatPanelWidths(normalized);
    }
  }, [leftPanelWidth, rightPanelWidth, setChatPanelWidths]);

  useEffect(() => {
    syncPanelWidthsToLayout();
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncPanelWidthsToLayout();
    });
    observer.observe(layoutElement);

    return () => observer.disconnect();
  }, [syncPanelWidthsToLayout]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY);
    function applyCenterFirstState(matches: boolean) {
      setCenterFirstLayout(matches);
      if (matches && !centerFirstAutoCollapseRef.current) {
        centerFirstAutoCollapseRef.current = true;
        setLeftRailCollapsed(true);
        setRightPaneCollapsed(true);
      }
      if (!matches) {
        centerFirstAutoCollapseRef.current = false;
      }
    }
    applyCenterFirstState(mediaQuery.matches);
    const handleChange = (event: MediaQueryListEvent) => {
      applyCenterFirstState(event.matches);
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!dragState) {
      return;
    }
    const activeDrag = dragState;

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }

      const delta = event.clientX - activeDrag.startX;

      if (activeDrag.side === "left") {
        if (leftRailCollapsed) {
          return;
        }
        const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : activeDrag.startRightWidth);
        const nextLeftWidth = clamp(activeDrag.startLeftWidth + delta, bounds.min, bounds.max);
        setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
        return;
      }

      if (rightPaneCollapsed) {
        return;
      }
      const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : activeDrag.startLeftWidth);
      const nextRightWidth = clamp(activeDrag.startRightWidth - delta, bounds.min, bounds.max);
      setChatPanelWidths({ rightPanelWidth: Math.round(nextRightWidth) });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [dragState, leftRailCollapsed, rightPaneCollapsed, setChatPanelWidths]);

  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale), [locale]);

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  const rawSessionDetail = sessionDetailQuery.data;
  const selectedSessionDetail =
    rawSessionDetail && rawSessionDetail.id === activeSessionId ? rawSessionDetail : undefined;
  const detail = selectedSessionDetail;
  const sessionDetailLoadingForActiveSession = Boolean(
    activeSessionId
    && (!rawSessionDetail || rawSessionDetail.id !== activeSessionId)
    && sessionDetailQuery.isFetching,
  );
  const runtimeActiveChatTurnSessionIds = new Set(
    [
      ...(runtime?.workRuns?.activeItems?.chat_turn ?? []),
      runtime?.workRuns?.active?.chat_turn,
    ]
      .map((run) => String(run?.sessionId ?? "").trim())
      .filter(Boolean),
  );
  const runtimeMatchesSelectedSession = Boolean(
    activeSessionId && runtimeActiveChatTurnSessionIds.has(activeSessionId),
  );
  const runtimeActiveChatTurnSessionId = runtimeActiveChatTurnSessionIds.values().next().value ?? "";
  const runtimeActiveSessionLabel = runtimeActiveChatTurnSessionId
    ? sessionsQuery.data?.find((session) => session.id === runtimeActiveChatTurnSessionId)?.title
      || runtime?.sessionTitle
      || runtimeActiveChatTurnSessionId
    : "";
  const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession
    ? (lang === "zh"
      ? `运行器正在处理：${runtimeActiveSessionLabel}`
      : `Runtime is processing: ${runtimeActiveSessionLabel}`)
    : "";
  const lastContextComposition = detail?.lastContextComposition ?? null;
  const lastCacheComposition = detail?.lastCacheComposition ?? null;
  const projectBusTimeline = projectAgentBusQuery.data;
  const projectBusEvents = projectBusTimeline?.events ?? [];
  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const activeGroupRoomStatus = String(activeGroupRoom?.status ?? "").trim().toLowerCase();
  const groupRoundRunning = activeGroupRoomStatus === "running";
  const groupRoundStopping = activeGroupRoomStatus === "stopping";
  const groupRoundActive = groupRoundRunning || groupRoundStopping;
  const activeGroupParticipantById = useMemo(() => {
    const entries = (activeGroupRoom?.participants ?? []).map((participant) => [participant.participantId, participant] as const);
    return new Map(entries);
  }, [activeGroupRoom?.participants]);
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);
  const activeGroupParticipantSessionSet = useMemo(
    () => new Set(availableGroupParticipants.map((participant) => participant.sessionId)),
    [availableGroupParticipants],
  );
  const expandedGroupAgentDetailsBySessionId = useMemo(() => {
    const entries = expandedGroupAgentSessionIds.map((sessionId, index) => {
      const query = expandedGroupAgentDetailQueries[index];
      return [sessionId, query] as const;
    });
    return new Map(entries);
  }, [expandedGroupAgentDetailQueries, expandedGroupAgentSessionIds]);
  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionIds.length) {
        setExpandedGroupAgentSessionIds([]);
      }
      return;
    }
    const nextExpanded = expandedGroupAgentSessionIds.filter((sessionId) => activeGroupParticipantSessionSet.has(sessionId));
    if (nextExpanded.length !== expandedGroupAgentSessionIds.length) {
      setExpandedGroupAgentSessionIds(nextExpanded);
    }
  }, [activeGroupParticipantSessionSet, expandedGroupAgentSessionIds, groupPanelActive]);
  const groupManageChanged = Boolean(
    legacyGroupRoomActive
    &&
    activeGroupRoom
    && (
      groupManageTitleDraft.trim() !== (activeGroupRoom.title || "").trim()
      || groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManagePurposeDraft !== (activeGroupRoom.purpose || "discussion")
      || groupManageSessionIds.length !== activeGroupParticipantSessionSet.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionSet.has(sessionId))
    ),
  );
  const groupManageDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || updateGroupRoomMutation.isPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || deleteGroupRoomMutation.isPending;
  const groupResetDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || resetGroupRoomMutation.isPending
    || (activeGroupRoom?.rounds ?? []).length < 1;
  const groupStopDisabled =
    !legacyGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundMutation.isPending;
  const activeSurfaceTitle = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "Agent 通知流" : "Agent notice stream")
        : activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    )
    : detail?.agentDisplayName ?? detail?.title ?? directSessionActiveSummary?.agentDisplayName ?? directSessionActiveSummary?.title ?? t("loadingSession");
  const activeSurfaceStatus = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "全局广播" : "global broadcast")
        : statusLabel(activeGroupRoom?.status ?? "ready")
    )
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      projectBusActive
        ? `${projectBusTimeline?.activeAgentCount ?? 0} ${lang === "zh" ? "位 active Agent · 全局广播/私信投递记录" : "active agents · broadcast/private delivery log"}`
        : (
          activeGroupRound?.summary
          || `${availableGroupParticipantCount} ${lang === "zh" ? "位可用 Agent" : "available agents"} · ${activeGroupRoom?.mode ?? "round_robin"} · ${activeGroupRoom?.purpose ?? "discussion"}`
        )
    )
    : "";
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError);
  const sessionDetailErrorMessage = sessionDetailQuery.isError
    ? describeError(sessionDetailQuery.error, t("loadFailed"))
    : "";
  const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(directSessionActiveSummary)
    ? (
      lang === "zh"
        ? "child_session_link_invalid: 子对话缺少 parentSessionId/rootSessionId，无法挂载到顶部 Agent 会话轨道。本轮已停止展示，请修复会话索引数据。"
        : "child_session_link_invalid: child session is missing parentSessionId/rootSessionId and cannot be mounted in the top Agent session strip. Fix the session index data."
    )
    : "";
  const sessionsErrorMessage = sessionsQuery.isError
    ? describeError(sessionsQuery.error, t("loadFailed"))
    : "";
  const contextCompositionSegments = useMemo(() => {
    const segments = lastContextComposition?.segments ?? [];
    return segments.filter((segment: SessionContextCompositionSegment) => (segment.tokens ?? 0) > 0 || (segment.chars ?? 0) > 0 || (segment.itemCount ?? 0) > 0);
  }, [lastContextComposition]);
  const contextCompositionTotalTokens = Math.max(
    lastContextComposition?.totalTokens ?? 0,
    contextCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const contextCompositionLimitTokens = Math.max(
    lastContextComposition?.limitTokens ?? 0,
    contextCompositionTotalTokens,
  );
  const contextCompositionUsedPercent = contextCompositionLimitTokens > 0
    ? Math.round(Math.min(1, contextCompositionTotalTokens / contextCompositionLimitTokens) * 100)
    : 0;
  const contextCompositionRemainingTokens = Math.max(0, contextCompositionLimitTokens - contextCompositionTotalTokens);
  const contextCompositionSummary = lastContextComposition
    ? `${numberFormatter.format(contextCompositionTotalTokens)} / ${numberFormatter.format(contextCompositionLimitTokens)} · ${contextCompositionUsedPercent}%`
    : t("noPreviousContextComposition");
  const contextCompositionTitle = lastContextComposition
    ? [
      `${t("previousContextComposition")} ${numberFormatter.format(contextCompositionTotalTokens)} / ${numberFormatter.format(contextCompositionLimitTokens)} tokens`,
      `${contextCompositionUsedPercent}%`,
      `${numberFormatter.format(lastContextComposition.totalChars ?? 0)} chars`,
      lastContextComposition.recordedAt ? formatTime(lastContextComposition.recordedAt) : "",
      lastContextComposition.source || "",
    ].filter(Boolean).join(" · ")
    : t("noPreviousContextComposition");
  const cacheCompositionSegments = useMemo(() => {
    const segments = lastCacheComposition?.segments ?? [];
    return segments.filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "missing");
  }, [lastCacheComposition]);
  const cacheCompositionTotalTokens = Math.max(
    lastCacheComposition?.inputTokens ?? 0,
    cacheCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const cacheCompositionPercent = Math.round(Math.max(0, Math.min(1, lastCacheComposition?.cacheHitRate ?? 0)) * 100);
  const cacheCompositionSummary = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? `${numberFormatter.format(lastCacheComposition.cachedInputTokens)} / ${numberFormatter.format(lastCacheComposition.inputTokens)} · ${cacheCompositionPercent}%`
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const cacheCompositionTitle = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? [
        `${t("previousCacheHit")} ${numberFormatter.format(lastCacheComposition.cachedInputTokens)} / ${numberFormatter.format(lastCacheComposition.inputTokens)} · ${cacheCompositionPercent}%`,
        `write ${numberFormatter.format(lastCacheComposition.cacheCreationInputTokens ?? 0)}`,
        `uncached ${numberFormatter.format(lastCacheComposition.uncachedInputTokens ?? 0)}`,
      ].join(" · ")
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeComposerRawError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const activeLatestTurnErrorMessage = useMemo(
    () => latestVisibleTurnErrorMessage(detail?.messages),
    [detail?.messages],
  );
  const activeComposerError = shouldSuppressComposerErrorForTurnError(
    activeComposerRawError,
    activeLatestTurnErrorMessage,
    detail?.lastTurnError,
  )
    ? ""
    : activeComposerRawError;
  const activeEditTarget = activeSessionId ? sessionEditTargets[activeSessionId] ?? null : null;
  const activeImageAttachments = activeSessionId ? sessionImageAttachments[activeSessionId] ?? [] : [];
  const activeReferenceAttachments = activeSessionId ? sessionReferenceAttachments[activeSessionId] ?? [] : [];
  const activeImageUploadPending = activeSessionId ? Boolean(sessionImageUploadPending[activeSessionId]) : false;
  const activeAgentId = detail?.agentId || "";
  const activeSessionAgent = activeAgentId ? (agentsQuery.data ?? []).find((agent) => agent.agentId === activeAgentId) : undefined;
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang, resolveModelLabel)
    : { name: pet?.name || "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
  const activeAgentDisplayName = activeAgentDisplay.name;
  const activeAgentAvatarImageUrl = avatarImageUrlFrom(activeSessionAgent, detail);
  const activeAgentAvatarFallback = avatarInitials(detail?.agentCode, activeAgentDisplayName);
  const activeAgentStatusMessage = detail?.agentMissing
    ? detail.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，部分内容无法继续运行。" : "Missing valid Agent. Some content cannot keep running.")
    : "";
  const activeRuntimeNotices = useMemo<SessionRuntimeNotice[]>(() => {
    return (detail?.runtimeNotices ?? [])
      .filter((notice) => String(notice.message ?? "").trim())
      .slice(-1);
  }, [detail?.runtimeNotices]);
  const latestUserMessageId = useMemo(() => deriveLatestUserMessageId(detail?.messages), [detail?.messages]);
  const resolvedEditTarget = resolveLatestEditTarget(activeEditTarget, latestUserMessageId);
  const activeDraftEffective = resolveComposerDraftValue(activeDraft, activeEditTarget, resolvedEditTarget);
  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const editResubmitMutationMatchesActiveSession =
    editResubmitMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const guidanceMutationMatchesActiveSession =
    sessionGuidanceMutation.variables?.sessionId === activeSessionId;
  const submitPending =
    (submitTurnMutation.isPending && submitMutationMatchesActiveSession)
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession)
    || activeImageUploadPending;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopMode = sessionBusy;
  const composerGuidance = sessionBusy && !sessionStopping ? t("sessionBusyComposerGuidance") : "";
  const composerPending =
    composerStopMode ? (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping : submitPending;
  const composerSafeGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "safe";
  const composerInterruptGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "interrupt";
  const composerDisabled = !activeSessionId || submitPending;
  const composerActionDisabled = !activeSessionId || (
    composerStopMode
      ? composerPending
      : submitPending || (!activeDraftEffective.trim() && !activeImageAttachments.length && !activeReferenceAttachments.length)
  );
  const composerPlaceholder =
    !activeSessionId
      ? t("loadingSession")
      : sessionStopping
        ? t("sessionStoppingPlaceholder")
        : sessionBusy
          ? t("sessionBusyPlaceholder")
          : resolvedEditTarget
            ? t("editMessagePlaceholder")
          : t("messageInputPlaceholder");
  const sessionContextUsage = detail?.contextUsage;
  const panelContextUsed = lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0;
  const panelContextLimit = lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0;
  const contextPercent = contextUsagePercent(panelContextUsed, panelContextLimit);
  const contextUsageLabel = formatContextUsage(panelContextUsed, panelContextLimit, locale);
  const contextSourceLine = lastContextComposition
    ? t("previousContextComposition")
    : sessionContextUsage
      ? t("sessionContextEstimate")
      : sessionDetailLoadingForActiveSession
        ? t("loadingContext")
        : t("sessionContextEstimate");
  const petVitals = useMemo(
    () => [
      { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
      { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
      { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
      { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
    ],
    [pet?.energy, pet?.health, pet?.hunger, pet?.love, t],
  );
  const petCompanionLine = petQuery.isError
    ? describeError(petQuery.error, t("loadFailed"))
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");
  const petPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);
  const petAvatarPresetKey = getPetAvatarPresetKey(pet?.avatarPreset);
  const petAvatarSkinClass = styles[`petShowcaseAvatar_${petAvatarPresetKey}`] ?? styles.petShowcaseAvatar_default;
  const petAvatarSymbol = getPetAvatarSymbol(pet?.avatarPreset, pet?.name);
  const petInteractionLabels = {
    group: lang === "zh" ? "宠物互动" : "Pet interactions",
    pending: petActionMutation.isPending
      ? lang === "zh" ? "处理中" : "Working"
      : lang === "zh" ? "即时生效" : "Live",
    feed: lang === "zh" ? "喂食" : "Feed",
    talk: lang === "zh" ? "沟通" : "Talk",
    care: lang === "zh" ? "照看" : "Care",
    feedTitle: lang === "zh" ? "喂食并刷新宠物状态" : "Feed and refresh pet state",
    talkTitle: lang === "zh" ? "和宠物沟通并刷新状态" : "Talk and refresh pet state",
    careTitle: lang === "zh" ? "照看宠物并刷新状态" : "Care and refresh pet state",
  };
  const contextStatusLine = sessionDetailErrorState.blockingError
    ? sessionDetailErrorMessage
    : detail
      ? contextUsageLabel
      : t("loadingContext");
  const contextUsageMetaLine = sessionContextUsage
    ? `${numberFormatter.format(sessionContextUsage.messageCount)} ${lang === "zh" ? "条消息" : "messages"} · ${numberFormatter.format(sessionContextUsage.userMessageCount)} ${lang === "zh" ? "用户" : "user"} / ${numberFormatter.format(sessionContextUsage.assistantMessageCount)} Agent`
    : lastContextComposition
      ? `${numberFormatter.format(lastContextComposition.totalChars ?? 0)} chars · ${lastContextComposition.source || "session_detail"}`
      : t("loadingContext");
  const sessionCacheUsage = detail?.cacheUsage;
  const sessionLlmUsage = detail?.llmUsage ?? null;
  const hasProviderLlmUsage = sessionLlmUsage?.source === "provider_usage";
  const hasProviderCacheUsage = sessionCacheUsage?.source === "provider_usage";
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = hasProviderCacheUsage && sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : t("cacheHitMissing");
  const llmUsageLine = hasProviderLlmUsage
    ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} tokens · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`
    : t("llmUsageMissing");
  const llmUsageTitle = hasProviderLlmUsage
    ? [
      `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
      `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
      `${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`,
      `${numberFormatter.format(sessionLlmUsage.cacheCreationInputTokens ?? 0)} write`,
      `${numberFormatter.format(sessionLlmUsage.uncachedInputTokens ?? 0)} uncached`,
    ].join(" · ")
    : t("llmUsageMissing");
  const compression = runtimeMatchesSelectedSession ? runtime?.contextCompression : undefined;
  const compressionCurrentPercent = compression
    ? Math.round(Math.max(0, Math.min(1, compression.usageRatio || 0)) * 100)
    : contextPercent;
  const compressionLevelLabel = compression?.enabled === false
    ? t("compressionDisabled")
    : compression?.currentLevel
      ? compression.currentLevel === "normal"
        ? (lang === "zh" ? "未到阈值" : "below threshold")
        : (lang === "zh" ? `${compression.currentLevel} 档` : `${compression.currentLevel} level`)
      : "--";
  const compressionCurrentLine = compression
    ? (lang === "zh"
      ? `当前 ${compressionCurrentPercent}% · ${compressionLevelLabel}`
      : `Current ${compressionCurrentPercent}% · ${compressionLevelLabel}`)
    : `-- · ${compressionLevelLabel}`;
  const compressionMainLine = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)} · ${compressionCurrentPercent}%`
    : t("loadingContext");
  const compressionScopeLine = compression
    ? `${t("compressionScopeRuntime")} · ${t("compressionLimitBasisEffective")}`
    : t("loadingContext");
  const compressionModelWindowLine = compression
    ? numberFormatter.format(compression.contextWindowLimit)
    : "--";
  const compressionTitleLine = compression
    ? `${compressionMainLine} · ${compressionScopeLine} · window ${numberFormatter.format(compression.contextWindowLimit)} · source ${compression.source || "runtime_state"}`
    : t("loadingContext");
  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionSourceText = (() => {
    if (!lastCompression) {
      return "";
    }
    switch (lastCompression.triggerSource) {
      case "manual":
        return lang === "zh" ? "Agent 主动请求" : "Agent requested";
      case "provider_limit":
        return lang === "zh" ? "上下文上限触发" : "Context limit triggered";
      case "auto":
        return lang === "zh" ? "阈值自动触发" : "Threshold triggered";
      default:
        return String(lastCompression.triggerSource || "").trim() || (lang === "zh" ? "未知来源" : "Unknown source");
    }
  })();
  const lastCompressionLine = lastCompression
    ? (lang === "zh"
      ? `${lastCompressionSourceText}，${lastCompression.level || "--"} 档：${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}，节省 ${numberFormatter.format(lastCompression.savedTokens)} token`
      : `${lastCompressionSourceText}, ${lastCompression.level || "--"} level: ${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}, saved ${numberFormatter.format(lastCompression.savedTokens)} tokens`)
    : t("compressionNoRecord");
  const compressionUpdatedLine = lastCompression?.timestamp
    ? formatRelativeTime(lastCompression.timestamp, Date.now(), locale) || formatTime(lastCompression.timestamp)
    : compression?.updatedAt
      ? formatRelativeTime(compression.updatedAt, Date.now(), locale) || formatTime(compression.updatedAt)
      : "";
  const sessionStateLabel = (() => {
    if (groupPanelActive) {
      return activeSurfaceStatus;
    }
    const runtimeSessionState = runtimeMatchesSelectedSession ? runtime?.sessionState : "";
    switch (runtimeSessionState) {
      case "thinking":
        return t("sessionStateThinking");
      case "tooling":
        return t("sessionStateTooling");
      case "answering":
        return t("sessionStateAnswering");
      default:
        return statusLabel(runtimeSessionState || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle");
    }
  })();
  const sessionStateLine = groupPanelActive
    ? activeSurfaceLine
    : runtimeMatchesSelectedSession && runtime?.sessionStateLine
      ? runtime.sessionStateLine
      : runtimeMismatchLine || (sessionDetailErrorState.blockingError
        ? sessionDetailErrorMessage
        : activeAgentStatusMessage || detail?.taskSummary || directSessionActiveSummary?.taskSummary || (sessionDetailLoadingForActiveSession ? t("loadingSession") : t("preparingShell")));
  const activeTask = detail?.activeTask ?? null;
  const sessionStateValue = String(groupPanelActive ? (projectBusActive ? "ready" : activeGroupRoom?.status ?? "ready") : (runtimeMatchesSelectedSession ? runtime?.sessionState : "") || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle")
    .trim()
    .toLowerCase();
  useEffect(() => {
    const sample = groupPanelActive
      ? null
      : tokenSpeedSampleFromMessages(
        detail?.id ?? activeSessionId,
        detail?.messages,
        sessionStateValue,
        Date.now(),
      );
    setTokenSpeedTracker((previous) => updateTokenSpeedTracker(previous, sample));
  }, [activeSessionId, detail?.id, detail?.messages, groupPanelActive, sessionStateValue]);
  const currentTaskSummary =
    activeTask?.goal
    || activeTask?.title
    || activeTask?.nextAction
    || activeTask?.latestSummary
    || detail?.taskSummary
    || directSessionActiveSummary?.taskSummary
    || (runtimeMatchesSelectedSession ? runtime?.taskSummary : "")
    || t("preparingShell");
  const fileContextValue = detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtime?.defaultRoute : undefined) ?? "workspace";
  const tokenSpeedValue = tokenSpeedTracker
    ? tokenSpeedTracker.tokensPerSecond === null
      ? t("tokenSpeedSampling")
      : `${tokenSpeedTracker.tokensPerSecond >= 10 ? Math.round(tokenSpeedTracker.tokensPerSecond) : tokenSpeedTracker.tokensPerSecond.toFixed(1)} tok/s`
    : "";
  const tokenSpeedTitle = tokenSpeedTracker
    ? `${t("tokenSpeedEstimated")} · ${numberFormatter.format(tokenSpeedTracker.tokenCount)} tokens`
    : "";
  const sessionCompactRows = buildVisiblePanelRows(
    [
      ...(tokenSpeedTracker ? [{
        label: t("tokenSpeed"),
        value: tokenSpeedValue,
        title: tokenSpeedTitle,
      }] : []),
      {
        label: t("llmInputTokens"),
        value: llmUsageLine,
        title: llmUsageTitle,
      },
      {
        label: t("fileContext"),
        value: fileContextValue,
        title: fileContextValue,
      },
      {
        label: t("currentTask"),
        value: currentTaskSummary,
        title: currentTaskSummary,
      },
      {
        label: t("promptCache"),
        value: cacheHitLine,
        title: sessionCacheUsage
          ? `${t("promptCacheLast")} ${numberFormatter.format(sessionCacheUsage.lastCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.lastInputTokens)} · ${t("promptCacheTotal")} ${numberFormatter.format(sessionCacheUsage.totalCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.totalInputTokens)}`
          : t("cacheObservationPending"),
      },
    ],
    [t("preparingShell"), t("loadingSession"), t("loadingContext")],
  );
  const mental = runtime?.mentalState;
  const mentalCognitiveStateValue = String(mental?.cognitiveState ?? "unknown").trim().toLowerCase() || "unknown";
  const mentalSourceValue = String(mental?.source ?? "unavailable").trim().toLowerCase() || "unavailable";
  const mentalCognitiveStateLabel = (() => {
    switch (mentalCognitiveStateValue) {
      case "normal":
        return t("mentalCognitiveState_normal");
      case "productive":
        return t("mentalCognitiveState_productive");
      case "looping":
        return t("mentalCognitiveState_looping");
      case "thrashing":
        return t("mentalCognitiveState_thrashing");
      case "tunnel_vision":
        return t("mentalCognitiveState_tunnel_vision");
      case "disoriented":
        return t("mentalCognitiveState_disoriented");
      default:
        return t("mentalCognitiveState_unknown");
    }
  })();
  const mentalSourceLabel = (() => {
    switch (mentalSourceValue) {
      case "state":
        return t("mentalSourceState");
      case "diagnosis":
        return t("mentalSourceDiagnosis");
      default:
        return t("mentalSourceUnavailable");
    }
  })();
  const mentalStateLabel = mental?.mood?.trim() || mentalCognitiveStateLabel;
  const mentalSummary = mental?.feeling?.trim() || mental?.summary || t("mentalStatePending");
  const mentalWhisper = mental?.whisper?.trim() || t("mentalStatePending");
  const mentalConfidence =
    Number.isFinite(mental?.confidence)
      ? `${Math.round((mental?.confidence ?? 0) * 100)}%`
      : "--";
  const mentalRelativeTime = formatRelativeTime(mental?.updatedAt ?? "", Date.now(), locale) || "--";
  const mentalCompactLine = [
    mentalSourceLabel,
    mentalConfidence !== "--" ? `${t("mentalConfidence")} ${mentalConfidence}` : "",
    mentalRelativeTime !== "--" ? mentalRelativeTime : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const petCompactLine = [
    petCompanionLine,
    pet?.heartActive ? t("heartActive") : t("heartIdle"),
    pet?.inDream ? t("dreamSleeping") : t("dreamAwake"),
    `${t("tokens")} ${numberFormatter.format(pet?.totalTokens ?? 0)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const agentsById = useMemo(() => {
    return new Map((agentsQuery.data ?? []).map((agent) => [agent.agentId, agent]));
  }, [agentsQuery.data]);

  const agentsByCode = useMemo(() => {
    const map = new Map<string, AgentInstance>();
    for (const agent of agentsQuery.data ?? []) {
      const code = String(agent.agentCode ?? "").trim();
      if (code) {
        map.set(code, agent);
      }
    }
    return map;
  }, [agentsQuery.data]);

  const resolveConversationTurnAvatar = useCallback((message: ConversationMessage): TurnAvatarResolution | undefined => {
    if (!isAgentInboxMessage(message)) {
      return undefined;
    }
    const metadata = message.metadata;
    const sourceAgentId = conversationMetadataText(metadata, "sourceAgentId");
    const sourceAgentCode = conversationMetadataText(metadata, "sourceAgentCode");
    const sourceAgentName = conversationMetadataText(metadata, "sourceAgentName");
    const agent =
      (sourceAgentId ? agentsById.get(sourceAgentId) : undefined)
      ?? (sourceAgentCode ? agentsByCode.get(sourceAgentCode) : undefined);
    return {
      imageUrl: avatarImageUrlFrom(agent),
      fallback: avatarInitials(sourceAgentCode, sourceAgentName),
    };
  }, [agentsByCode, agentsById]);

  const chatMentionTargets = useMemo(() => {
    return buildChatMentionTargets(agentsQuery.data ?? []);
  }, [agentsQuery.data]);

  const allVisibleSessions = useMemo(() => {
    return (sessionsQuery.data ?? []).filter(isVisibleDirectSession);
  }, [sessionsQuery.data]);

  const sessionsById = useMemo(() => {
    return new Map(allVisibleSessions.map((session) => [session.id, session]));
  }, [allVisibleSessions]);

  const rawSessionsById = useMemo(() => {
    return new Map((rawSessionsQuery.data ?? []).map((session) => [session.id, session]));
  }, [rawSessionsQuery.data]);

  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) {
      return undefined;
    }
    return sessionsById.get(sessionContextMenu.sessionId) ?? sessionContextMenu.session;
  }, [sessionContextMenu, sessionsById]);

  const rightIndexSessions = useMemo(() => {
    return allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session));
  }, [allVisibleSessions]);

  const activeRootSessionId = rootSessionIdFor(directSessionActiveSummary);
  const agentSessionTabs = useMemo(() => {
    if (!activeRootSessionId) {
      return [];
    }
    const rootSession = sessionsById.get(activeRootSessionId);
    const childSessions = allVisibleSessions
      .filter((session) => isChildSession(session) && rootSessionIdFor(session) === activeRootSessionId)
      .sort((left, right) =>
        String(left.updatedAt || left.lastActive || "").localeCompare(String(right.updatedAt || right.lastActive || "")),
      );
    return [rootSession, ...childSessions]
      .filter((session): session is SessionSummary => Boolean(session))
      .filter((session, index, sessions) => sessions.findIndex((item) => item.id === session.id) === index);
  }, [activeRootSessionId, allVisibleSessions, sessionsById]);

  const groupCandidateAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && String(agent.directSessionId ?? "").trim()
      );
    });
  }, [agentsQuery.data]);

  const readyChatRoomModes = useMemo(() => {
    const modes = (chatRoomModesQuery.data ?? []).filter((mode) => String(mode.status ?? "").trim() === "ready");
    return modes.length ? modes : [{ id: "round_robin", label: "Round robin", status: "ready" }];
  }, [chatRoomModesQuery.data]);
  const availableChatRoomPurposes = useMemo(() => {
    const purposes = chatRoomPurposesQuery.data ?? [];
    return purposes.length
      ? purposes
      : [
          { id: "chat", label: "Chat", description: "" },
          { id: "discussion", label: "Discussion", description: "" },
          { id: "meeting", label: "Meeting", description: "" },
          { id: "medical_triage", label: "Medical triage", description: "" },
        ];
  }, [chatRoomPurposesQuery.data]);

  const activeGroupTeamMemberByAgentId = useMemo(() => {
    return new Map(
      (activeGroupTeam?.members ?? [])
        .map((member) => [String(member.agentId ?? "").trim(), member] as const)
        .filter(([agentId]) => Boolean(agentId)),
    );
  }, [activeGroupTeam?.members]);
  const groupParticipantIdentity = useCallback(
    (
      participant: ChatRoomParticipant | undefined,
      fallback: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string } = {},
    ) => {
      const agentId = String(participant?.agentId || fallback.agentId || "").trim();
      const participantLike = participant ?? {
        participantId: String(fallback.participantId || agentId || "agent").trim(),
        kind: "session_agent",
        agentId,
        agentCode: String(fallback.agentCode || "").trim(),
        agentAvatarImageUrl: String(fallback.agentAvatarImageUrl || "").trim(),
        sessionId: "",
        title: String(fallback.title || fallback.participantId || agentId || "Agent").trim(),
        enabled: true,
        status: "",
      };
      const participantAgent = agentId ? agentsById.get(agentId) : undefined;
      const display = participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel);
      const member = agentId ? activeGroupTeamMemberByAgentId.get(agentId) : undefined;
      const participantTeamRole = String(participant?.teamMemberPurpose || participant?.teamRole || "").trim();
      const role = String(participantTeamRole || member?.purpose || member?.role || display.functionLabel || "").trim();
      const name = String(display.name || fallback.title || fallback.participantId || "Agent").trim();
      const compactRole = compactAgentRoleLabel(role || display.functionLabel);
      return {
        ...display,
        name,
        functionLabel: role || display.functionLabel,
        compactRole,
        avatarImageUrl: avatarImageUrlFrom(participantAgent, participantLike, fallback),
        identityLabel: formatAgentIdentityWithRole(name, compactRole, fallback.participantId || "Agent"),
        fullIdentityLabel: [
          formatAgentIdentityWithRole(name, role || display.functionLabel, fallback.participantId || "Agent"),
          display.modelLabel,
        ].filter(Boolean).join(" · "),
      };
    },
    [activeGroupTeamMemberByAgentId, agentsById, lang, resolveModelLabel],
  );
  const filteredConversations = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    const conversations = mergeVisibleSessionsIntoConversations(conversationsQuery.data, rightIndexSessions);
    const visibleConversations = conversations
      .filter((conversation) => conversation.type !== "group_room")
      .filter((conversation) => {
        const sessionId = conversation.directSessionId || conversation.conversationId;
        const session = sessionId ? sessionsById.get(sessionId) : undefined;
        const rawSession = sessionId ? rawSessionsById.get(sessionId) : undefined;
        if (isRepresentedInAgentSessionTabs(session)) {
          return false;
        }
        if (!isVisibleConversation(conversation, rawSessionsById)) {
          return false;
        }
        if (rawSession && !session) {
          return false;
        }
        return true;
      });
    if (!term) {
      return visibleConversations;
    }
    return visibleConversations.filter((conversation) => {
      const sessionId = conversation.directSessionId || conversation.conversationId;
      const session = sessionsById.get(sessionId);
      const sessionSearchValues = session ? [
        session.title,
        session.taskTitle ?? "",
        session.taskSummary,
        session.status,
        session.currentPhase ?? "",
        session.childStatus ?? "",
        session.resultCard?.summary ?? "",
        session.resultCard?.status ?? "",
        session.parentSessionId ?? "",
        session.rootSessionId ?? "",
      ] : [];
      return [conversation.title, conversation.summary, conversation.status, conversation.type, conversation.agentCode ?? "", conversation.agentDisplayName ?? "", conversation.agentPrimaryMode ?? "", conversation.agentRoleKey ?? "", conversation.agentPromptTemplateId ?? "", ...sessionSearchValues].some((value) =>
        String(value ?? "").toLowerCase().includes(term),
      );
    });
  }, [conversationsQuery.data, rawSessionsById, rightIndexSessions, sessionFilter, sessionsById]);
  const filteredStandaloneGroupConversations = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    const conversations = conversationsQuery.data ?? [];
    const groups = conversations.filter((conversation) => {
      if (conversation.type !== "group_room") {
        return false;
      }
      const roomId = String(conversation.roomId || conversation.conversationId || "").trim();
      return Boolean(roomId) && !linkedTeamRoomIds.has(roomId);
    });
    if (!term) {
      return groups;
    }
    return groups.filter((conversation) =>
      [conversation.title, conversation.summary, conversation.status, conversation.type].some((value) =>
        String(value ?? "").toLowerCase().includes(term),
      ),
    );
  }, [conversationsQuery.data, linkedTeamRoomIds, sessionFilter]);
  const filteredTeams = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    if (!term) {
      return teams;
    }
    return teams.filter((team) =>
      [
        team.name,
        team.purpose,
        team.status,
        team.teamKind,
        team.teamCategory,
        team.teamSource,
        team.teamTemplateId,
        team.linkedChatRoom?.title ?? "",
        ...(team.members ?? []).flatMap((member) => [member.agentName, member.agentCode, member.role, member.purpose]),
      ].some((value) => String(value ?? "").toLowerCase().includes(term)),
    );
  }, [sessionFilter, teams]);
  const groupedConversations = useMemo(() => {
    const buckets = new Map<ConversationGroupKey, ConversationSummary[]>(
      CONVERSATION_GROUP_ORDER.map((groupKey) => [groupKey, []]),
    );
    filteredConversations.forEach((conversation) => {
      const groupKey = classifyConversation(conversation);
      buckets.get(groupKey)?.push(conversation);
    });
    return CONVERSATION_GROUP_ORDER
      .map((groupKey) => ({
        groupKey,
        label: conversationGroupLabel(groupKey, lang === "zh" ? "zh" : "en"),
        items: buckets.get(groupKey) ?? [],
      }))
      .filter((group) => group.items.length > 0);
  }, [filteredConversations, lang]);
  const searchHasTerm = sessionFilter.trim().length > 0;
  const sessionIndexLoadedCount = rawSessionsQuery.loadedCount;
  const sessionIndexTotalEstimate = rawSessionsQuery.totalEstimate;
  const sessionIndexHasMore = rawSessionsQuery.hasMore;
  const sessionIndexLoadMoreLabel = rawSessionsQuery.isLoadingMore
    ? (lang === "zh" ? "加载中" : "Loading")
    : (lang === "zh" ? "加载更多" : "Load more");
  const sessionIndexProgressLabel =
    sessionIndexTotalEstimate > sessionIndexLoadedCount
      ? `${numberFormatter.format(sessionIndexLoadedCount)} / ${numberFormatter.format(sessionIndexTotalEstimate)}`
      : numberFormatter.format(sessionIndexLoadedCount);

  function formatTime(value: string) {
    if (!value) {
      return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return timeFormatter.format(parsed);
  }

  function toggleConversationGroup(groupKey: ConversationGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !current[groupKey],
    }));
  }

  function handleComposerChange(value: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleMentalModelEnabledChange(enabled: boolean) {
    setMentalModelEnabledForNextTurn(enabled);
    writeStoredMentalModelToggle(enabled);
  }

  function handleAddComposerAttachments(files: FileList | File[]) {
    if (!activeSessionId) {
      return;
    }
    const incoming = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
    if (!incoming.length) {
      return;
    }
    const accepted: ComposerImageAttachment[] = [];
    const rejected: string[] = [];
    for (const file of incoming) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        rejected.push(file.name);
        continue;
      }
      if (file.size > MAX_COMPOSER_IMAGE_BYTES) {
        rejected.push(file.name);
        continue;
      }
      accepted.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        filename: file.name || "image",
        previewUrl: URL.createObjectURL(file),
        sizeBytes: file.size,
        contentType: file.type,
      });
    }
    setSessionImageAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const merged = [...existing, ...accepted].slice(0, MAX_COMPOSER_IMAGE_ATTACHMENTS);
      return {
        ...current,
        [activeSessionId]: merged,
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejected.length
        ? (lang === "zh" ? "部分图片格式或大小不支持。" : "Some images were rejected by type or size.")
        : "",
    }));
  }

  function handleRemoveComposerAttachment(attachmentId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionImageAttachments((current) => removeSessionImageAttachment(current, activeSessionId, attachmentId));
  }

  function handleAddComposerReference(reference: SessionReferenceAttachment) {
    if (!activeSessionId) {
      return;
    }
    const referenceId = sessionReferenceId(reference);
    if (!referenceId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "会话引用缺少有效 id。" : "Session reference is missing a valid id.",
      }));
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.some((item) => sessionReferenceId(item) === referenceId)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, reference].slice(-6),
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleRemoveComposerReference(referenceId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((reference) => sessionReferenceId(reference) !== referenceId);
      if (next.length === existing.length) {
        return current;
      }
      if (!next.length) {
        return clearSessionReferenceAttachments(current, activeSessionId);
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }

  async function submitTurnWithAttachments(
    sessionId: string,
    content: string,
    attachments: ComposerImageAttachment[],
    references: SessionReferenceAttachment[],
    mentalModelEnabled: boolean,
  ) {
    if (imageUploadInFlightRef.current[sessionId]) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked while image upload was already in flight.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          guardReason: "image_upload_in_flight",
        },
        "warning",
      );
      return;
    }
    imageUploadInFlightRef.current[sessionId] = true;
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    if (content || references.length) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detail) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detail, { sessionId, content, references })),
      );
    }
    try {
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_started",
          "Direct chat submit image upload started.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
          },
        );
      }
      const uploaded = await Promise.all(attachments.map((attachment) => uploadSessionImageAttachment(sessionId, attachment)));
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_succeeded",
          "Direct chat submit image upload succeeded.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: uploaded.length,
            referenceCount: references.length,
            mentalModelEnabled,
          },
        );
      }
      postSubmitTelemetry(
        "browser.chat_submit.submit_mutate_requested",
        "Direct chat submit mutation was requested.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          uploadedAttachmentCount: uploaded.length,
          referenceCount: references.length,
          mentalModelEnabled,
        },
      );
      submitTurnMutation.mutate({
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds: uploaded.map((attachment) => attachment.artifactId).filter(Boolean),
        references,
      });
    } catch (error) {
      postSubmitTelemetry(
        "browser.chat_submit.upload_failed",
        "Direct chat submit image upload failed before message POST.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          error,
        },
        "error",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
      if (content || references.length) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detail) =>
          removeOptimisticUserMessage(detail, { sessionId, content, references }),
        );
        setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content));
      }
    } finally {
      imageUploadInFlightRef.current[sessionId] = false;
      setSessionImageUploadPending((current) => ({
        ...current,
        [sessionId]: false,
      }));
    }
  }

  function handleSubmitTurn() {
    if (!activeSessionId) {
      return;
    }
    const content = activeDraftEffective.trim();
    postSubmitTelemetry(
      "browser.chat_submit.requested",
      "Direct chat submit was requested from the composer.",
      activeSessionId,
      {
        content,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        editTargetId: resolvedEditTarget?.messageId,
        composerDisabled,
        sessionBusy,
        activePhase: detail?.currentPhase,
      },
    );
    const guardReason = composerDisabled
      ? "composer_disabled"
      : !content && !activeImageAttachments.length && !activeReferenceAttachments.length
        ? "empty_content"
        : "";
    if (guardReason) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked by the composer guard.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: detail?.currentPhase,
          guardReason,
        },
        "warning",
      );
      return;
    }
    if (resolvedEditTarget) {
      postSubmitTelemetry(
        "browser.chat_submit.edit_resubmit_requested",
        "Edit-resubmit mutation was requested from the composer.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: detail?.currentPhase,
        },
      );
      editResubmitMutation.mutate({
        sessionId: activeSessionId,
        messageId: resolvedEditTarget.messageId,
        content,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
      });
      return;
    }
    void submitTurnWithAttachments(
      activeSessionId,
      content,
      activeImageAttachments,
      activeReferenceAttachments,
      mentalModelEnabledForNextTurn,
    );
  }

  function handleEditUserMessage(message: ConversationMessage) {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    if (message.id !== latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
        original: message.content,
      },
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: message.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget || activeEditTarget.messageId === latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeEditTarget, activeSessionId, latestUserMessageId, setSessionDrafts, setSessionEditTargets]);

  function handleCancelEditMessage() {
    if (!activeSessionId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
  }

  function handleStopTurn() {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
    });
  }

  function handleSubmitGuidance(mode: SessionGuidanceMode) {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    const content = activeDraftEffective.trim();
    if (!content) {
      return;
    }
    sessionGuidanceMutation.mutate({
      sessionId: activeSessionId,
      content,
      mode,
    });
  }

  function handlePetInteraction(action: PetInteractionAction) {
    setPetActionFeedback("");
    petActionMutation.mutate({ action });
  }

  function handleCreateSession() {
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate();
  }

  function handleOpenProjectAgentBus() {
    setSessionContextMenu(null);
    navigate("/chat", { replace: false });
    setActiveGroupRoomId("__project_agent_bus__");
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterProjectBusFailed();
  }

  function handleOpenDirectSession(sessionId: string) {
    if (!sessionId) {
      return;
    }
    setSessionContextMenu(null);
    setActiveSession(sessionId);
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    navigate(`/chat?session=${encodeURIComponent(sessionId)}`, { replace: false });
  }

  function handleOpenMentionTarget(target: ChatMentionTarget) {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      setActiveGroupRoomId("__project_agent_bus__");
      setRightIndexPanel("conversations");
      setSessionFilter("");
      void chatWorkspaceCache.afterProjectBusFailed();
      return;
    }
    if (target.directSessionId) {
      setSessionFilter("");
      handleOpenDirectSession(target.directSessionId);
      return;
    }
    const fallbackFilter = target.agentCode || target.displayName || target.agentId || "";
    if (fallbackFilter) {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setSessionFilter(fallbackFilter);
    }
  }

  function renderMentionedText(content: string, fallback = "") {
    const text = content || fallback;
    return tokenizeChatMentions(text, chatMentionTargets).map((segment, index) => {
      if (segment.type === "text") {
        return <span key={`text-${index}`}>{segment.text}</span>;
      }
      const mentionLabel = segment.target.kind === "all"
        ? (lang === "zh" ? "全体成员" : "All agents")
        : [segment.target.displayName, segment.target.agentCode].filter(Boolean).join(" · ");
      return (
        <button
          key={`mention-${index}-${segment.text}`}
          type="button"
          className={styles.agentMention}
          onClick={() => handleOpenMentionTarget(segment.target)}
          aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
          title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
        >
          {segment.text}
        </button>
      );
    });
  }

  function renderGroupMessageBody(message: ChatRoomMessage, identityName: string) {
    const content = stripGroupSpeakerPrefix(message, identityName);
    const expanded = expandedGroupMessageIds.includes(message.messageId);
    const defaultCollapsed = shouldDefaultCollapseGroupMessage(message);
    const collapsible = defaultCollapsed || shouldCollapseGroupMessage(content);
    const collapsed = collapsible && !expanded;
    const collapseLabel = defaultCollapsed
      ? (lang === "zh" ? "展开讨论" : "Show discussion")
      : (lang === "zh" ? "展开全文" : "Show full");
    return (
      <>
        <p className={collapsed ? `${styles.groupBubbleBody} ${styles.groupBubbleBodyCollapsed}` : styles.groupBubbleBody}>
          {renderMentionedText(content, lang === "zh" ? "暂无内容" : "No content yet")}
        </p>
        {collapsible ? (
          <button
            type="button"
            className={styles.groupBubbleToggle}
            onClick={() =>
              setExpandedGroupMessageIds((current) =>
                current.includes(message.messageId)
                  ? current.filter((messageId) => messageId !== message.messageId)
                  : [...current, message.messageId],
              )}
          >
            {expanded ? (lang === "zh" ? "收起" : "Collapse") : collapseLabel}
          </button>
        ) : null}
      </>
    );
  }

  function handleOpenGroupRoom(roomId: string) {
    if (!roomId) {
      return;
    }
    navigate(`/chat?room=${encodeURIComponent(roomId)}`, { replace: false });
    setActiveGroupRoomId(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterChatRoomChanged(roomId);
  }

  function handleToggleGroupManageSession(sessionId: string) {
    if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending) {
      return;
    }
    setGroupRoomActionError("");
    setGroupManageSessionIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }

  function handleToggleGroupComposer() {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupComposerOpen((open) => {
      const nextOpen = !open;
      if (nextOpen && !groupTitleDraft.trim()) {
        setGroupTitleDraft(lang === "zh" ? "Agent 群聊" : "Agent group");
      }
      return nextOpen;
    });
  }

  function handleToggleGroupAgent(agentId: string) {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupSelectedAgentIds((current) =>
      current.includes(agentId) ? current.filter((item) => item !== agentId) : [...current, agentId],
    );
  }

  function handleCreateGroupRoom() {
    const title = groupTitleDraft.trim();
    const agentIds = groupSelectedAgentIds.filter(Boolean);
    if (!title || agentIds.length < 2 || createGroupRoomMutation.isPending) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: lang === "zh" ? "请输入群聊名称，并至少选择两个 Agent。" : "Enter a group name and choose at least two agents.",
      }));
      return;
    }
    createGroupRoomMutation.mutate({
      title,
      agentIds,
      mode: groupModeDraft || "round_robin",
      purpose: groupPurposeDraft || "discussion",
    });
  }

  function handleStartGroupRound() {
    const topic = groupTopicDraft.trim();
    if (!legacyGroupRoomActive || !activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
      purpose: activeGroupRoom?.purpose || "discussion",
    });
  }

  function handleStopGroupRound() {
    if (!legacyGroupRoomActive || !activeGroupRoomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
      return;
    }
    stopGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
    });
  }

  function handleSendProjectBusMessage() {
    const content = projectBusDraft.trim();
    if (!content || sendProjectBusMessageMutation.isPending) {
      return;
    }
    sendProjectBusMessageMutation.mutate({
      content,
      interruptTargets: projectBusInterruptTargets,
    });
  }

  function handleRevokeProjectBusMessage(eventId: string) {
    if (!eventId || revokeProjectBusMessageMutation.isPending) {
      return;
    }
    revokeProjectBusMessageMutation.mutate({ eventId });
  }

  function handleApplyGroupRoomManagement() {
    if (!legacyGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoomId,
      title: groupManageTitleDraft.trim(),
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
      purpose: groupManagePurposeDraft || "discussion",
    });
  }

  function handleDeleteActiveGroupRoom() {
    if (!legacyGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleResetActiveGroupRoom() {
    if (!legacyGroupRoomActive || !activeGroupRoomId || groupResetDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    resetGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleDeleteSession(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const sessionConfirmMessage = t("deleteSessionConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(sessionConfirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    deleteSessionMutation.mutate({ sessionId: session.id });
  }

  function handleAddSessionToReview(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("addSessionToReviewBusy"),
        __sessions__: "",
      }));
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    addSessionToReviewMutation.mutate({ sessionId: session.id });
  }

  function beginRenameSession(session: SessionSummary) {
    setSessionContextMenu(null);
    setEditingSessionId(session.id);
    setEditingSessionTitle(
      isAgentRootSession(session)
        ? (session.agentDisplayName || session.title)
        : isChildSession(session)
          ? (session.taskTitle || session.resultCard?.title || session.title)
          : session.title,
    );
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }

  function cancelRenameSession() {
    setSessionContextMenu(null);
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }

  function openSessionContextMenu(event: ReactMouseEvent<HTMLElement>, session: SessionSummary) {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu({
      sessionId: session.id,
      session,
      x: event.clientX,
      y: event.clientY,
    });
  }

  function submitRenameSession(session: SessionSummary) {
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t(isAgentRootSession(session) ? "renameAgentEmpty" : isChildSession(session) ? "renameTaskEmpty" : "renameSessionEmpty"),
      }));
      return;
    }
    const currentTitle = isAgentRootSession(session)
      ? (session.agentDisplayName || session.title)
      : isChildSession(session)
        ? (session.taskTitle || session.resultCard?.title || session.title)
        : session.title;
    if (title === currentTitle) {
      cancelRenameSession();
      return;
    }
    renameSessionMutation.mutate({ sessionId: session.id, title });
  }

  function handleResizeStart(side: ResizableSide, event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }
    event.preventDefault();
    setDragState({
      side,
      startX: event.clientX,
      startLeftWidth: leftPanelWidth,
      startRightWidth: rightPanelWidth,
    });
  }

  function handleResizeKeyDown(side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) {
    if (!layoutRef.current) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : rightPanelWidth);
      const nextLeftWidth =
        direction === "min"
          ? bounds.min
          : direction === "max"
            ? bounds.max
            : clamp(leftPanelWidth + Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
      setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : leftPanelWidth);
    const delta =
      direction === "min"
        ? bounds.min
        : direction === "max"
          ? bounds.max
          : clamp(rightPanelWidth - Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
    setChatPanelWidths({ rightPanelWidth: Math.round(delta) });
  }

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const layoutStyle = useMemo(
    () =>
      ({
        "--chat-left-pane-width": leftRailCollapsed ? "0px" : `${leftPanelWidth}px`,
        "--chat-right-pane-width": rightPaneCollapsed ? "0px" : `${rightPanelWidth}px`,
      }) as CSSProperties,
    [leftPanelWidth, leftRailCollapsed, rightPanelWidth, rightPaneCollapsed],
  );

  const contextMenuSessionIsBusy = contextMenuSession
    ? isBusyPhase(contextMenuSession.currentPhase || contextMenuSession.status)
    : false;
  const contextMenuDeletePending = Boolean(
    contextMenuSession
    && deleteSessionMutation.isPending
    && deleteSessionMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuAddToReviewPending = Boolean(
    contextMenuSession
    && addSessionToReviewMutation.isPending
    && addSessionToReviewMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuDeleteDisabled = contextMenuDeletePending || contextMenuSessionIsBusy;
  const contextMenuAddToReviewDisabled = contextMenuAddToReviewPending || contextMenuSessionIsBusy;
  const sessionContextMenuStyle: CSSProperties | undefined =
    sessionContextMenu && contextMenuSession
      ? {
          left: Math.min(
            sessionContextMenu.x,
            typeof window === "undefined" ? sessionContextMenu.x : Math.max(12, window.innerWidth - 188),
          ),
          top: Math.min(
            sessionContextMenu.y,
            typeof window === "undefined" ? sessionContextMenu.y : Math.max(12, window.innerHeight - 132),
          ),
        }
      : undefined;

  return (
    <div
      ref={layoutRef}
      className={centerFirstLayout ? `${styles.layout} ${styles.layoutCenterFirst}` : styles.layout}
      style={layoutStyle}
    >
      <aside className={leftRailCollapsed ? `${styles.leftRail} ${styles.paneCollapsed}` : styles.leftRail} aria-hidden={leftRailCollapsed}>
        {legacyGroupRoomActive ? (
          <section className={`${styles.leftBlock} ${styles.groupProfileBlock}`}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionIdentity}>
                <p className={styles.blockEyebrow}>{lang === "zh" ? "群资料与设置" : "Group profile"}</p>
                <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
              </div>
              <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${String(activeGroupRoom?.status ?? "ready").trim().toLowerCase()}`]}`}>
                {statusLabel(activeGroupRoom?.status ?? "ready")}
              </span>
            </div>
            <p className={styles.contextLineCompact}>
              {activeGroupTeamOwned
                ? (lang === "zh"
                  ? "这是团队关联群聊；成员、角色和同步关系由团队页维护，这里只负责讨论运行与成员状态观察。"
                  : "This room is owned by a Team. Membership, roles, and sync stay in Teams; Chat only runs discussion and shows member status.")
                : (lang === "zh"
                  ? "这里管理当前普通群聊的资料、成员和调度；成员状态索引放在右侧独立分栏。"
                  : "Manage this standalone group's info, members, and scheduling here. Member status lives in the right index.")}
            </p>
            <div className={styles.resourceSplit}>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "可用成员" : "Available"}</span>
                <strong>{numberFormatter.format(availableGroupParticipantCount)}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "调度" : "Mode"}</span>
                <strong>{activeGroupRoom?.mode ?? "round_robin"}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <strong>{activeGroupRoom?.purpose ?? "discussion"}</strong>
              </div>
            </div>
            <section className={styles.groupManagementPanel} aria-label={lang === "zh" ? "群聊管理" : "Group management"}>
              <div className={styles.groupManagementHeader}>
                <div>
                  <strong>{activeGroupTeamOwned ? (lang === "zh" ? "团队群聊引用" : "Team room reference") : (lang === "zh" ? "群设置" : "Group settings")}</strong>
                  <span title={activeGroupRoom?.title ?? ""}>
                    {activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}
                  </span>
                </div>
                <div className={styles.groupManagementActions}>
                  {activeGroupTeamOwned && activeGroupTeam ? (
                    <button
                      type="button"
                      className={styles.groupSecondaryButton}
                      onClick={() => navigate(`/teams?team=${encodeURIComponent(activeGroupTeam.teamId)}`)}
                    >
                      <ArrowUpRight size={14} />
                      <span>{lang === "zh" ? "打开团队" : "Open team"}</span>
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={groupManageChanged ? styles.groupApplyButton : styles.groupSecondaryButton}
                    disabled={groupManageDisabled || !groupManageChanged}
                    onClick={handleApplyGroupRoomManagement}
                  >
                    <Check size={14} />
                    <span>
                      {updateGroupRoomMutation.isPending
                        ? (lang === "zh" ? "应用中" : "Applying")
                        : (lang === "zh" ? "应用变更" : "Apply")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={styles.groupDeleteButton}
                    disabled={groupDeleteDisabled}
                    onClick={handleDeleteActiveGroupRoom}
                  >
                    <Trash2 size={14} />
                    <span>
                      {deleteGroupRoomMutation.isPending
                        ? (lang === "zh" ? "删除中" : "Deleting")
                        : (lang === "zh" ? "删除" : "Delete")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={styles.groupSecondaryButton}
                    disabled={groupResetDisabled}
                    onClick={handleResetActiveGroupRoom}
                  >
                    <RotateCcw size={14} />
                    <span>
                      {resetGroupRoomMutation.isPending
                        ? (lang === "zh" ? "重置中" : "Resetting")
                        : (lang === "zh" ? "重置消息" : "Reset messages")}
                    </span>
                  </button>
                </div>
              </div>
              {groupRoomActionError ? (
                <div className={styles.panelNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupManagementControls}>
                <label className={styles.groupTitleField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    value={groupManageTitleDraft}
                    maxLength={80}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageTitleDraft(event.target.value);
                    }}
                  />
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    value={groupManageModeDraft}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageModeDraft(event.target.value);
                    }}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    value={groupManagePurposeDraft}
                    disabled={activeGroupTeamOwned || groupRoundRunning || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManagePurposeDraft(event.target.value);
                    }}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupManagementCount}>
                  <span>{lang === "zh" ? "已选" : "Selected"}</span>
                  <strong>
                    {groupManageSessionIds.length}/{sessionsQuery.data?.length ?? 0}
                  </strong>
                </div>
                <div className={styles.groupMemberPicker}>
                  {(sessionsQuery.data ?? []).map((session) => {
                    const selected = groupManageSessionSet.has(session.id);
                    const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                    const display = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
                    const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
                    const missingMessage = session.agentMissing
                      ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent" : "Missing valid Agent")
                      : "";
                    return (
                      <label
                        key={session.id}
                        className={
                          selected
                            ? `${styles.groupMemberChip} ${styles.groupMemberChipSelected}`
                            : styles.groupMemberChip
                        }
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                          onChange={() => handleToggleGroupManageSession(session.id)}
                        />
                        {renderAgentAvatar(
                          styles.agentOptionAvatar,
                          sessionAvatarImageUrl,
                          avatarInitials(session.agentCode, display.name),
                        )}
                        <span className={styles.groupMemberCopy}>
                          <strong>{display.name}</strong>
                          <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                            {display.functionLabel}
                          </small>
                        </span>
                        {missingMessage ? (
                          <span className={styles.agentMissingInline} title={missingMessage}>
                            {lang === "zh" ? "缺少有效 Agent" : "Missing Agent"}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              {activeGroupTeamOwned ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh"
                    ? "团队关联群聊的成员来自团队组织画布；如需调整成员、角色或同步关系，请打开团队页。"
                    : "Team-owned room members come from the Team canvas. Open Teams to change members, roles, or sync."}
                </p>
              ) : groupRoundActive ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}
                </p>
              ) : groupManageSessionIds.length < 2 ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊至少需要保留 2 位 Agent。" : "A group needs at least 2 agents."}
                </p>
              ) : null}
            </section>
          </section>
        ) : (
          <>
        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("currentSession")}</p>
              <h3 className={styles.sectionTitle}>{activeSurfaceTitle}</h3>
            </div>
            <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${sessionStateValue}`]}`}>
              {sessionStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{sessionStateLine}</p>
          {sessionCompactRows.length > 0 ? (
            <div className={styles.inlineMetaList}>
              {sessionCompactRows.map((row) => (
                <span key={row.label} className={styles.inlineMetaPill} title={row.title ?? row.value}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
          <details className={styles.sessionDiagnosticsDetails}>
            <summary className={styles.sessionDiagnosticsSummary}>
              <span className={styles.sessionDiagnosticsSummaryText}>
                <ChevronRight size={14} />
                <span>{t("contextDiagnostics")}</span>
              </span>
              <span className={styles.sessionDiagnosticsSnapshot}>
                {contextPercent}% · {cacheHitLine}
              </span>
            </summary>
            <div className={styles.sessionDiagnosticsBody}>
              <section className={styles.contextCompositionPanel} aria-label={lang === "zh" ? "状态栏上一轮上下文与缓存事实" : "Status bar previous turn context and cache facts"}>
                <div className={styles.contextCompositionItem} title={contextCompositionTitle}>
                  <div className={styles.contextCompositionHeader}>
                    <span>{t("previousContextComposition")}</span>
                    <strong>{contextCompositionSummary}</strong>
                  </div>
                  <div className={styles.contextCompositionBar} aria-hidden="true">
                    {contextCompositionSegments.length ? (
                      contextCompositionSegments.map((segment) => (
                        <span
                          key={`${segment.key}-${segment.source}`}
                          className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentExact} ${contextCompositionSegmentClass(segment.key)}`}
                          style={{ width: contextWindowSegmentWidth(segment.tokens ?? 0, contextCompositionLimitTokens) }}
                        />
                      ))
                    ) : (
                      <span className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentMissing}`} />
                    )}
                    {contextCompositionRemainingTokens > 0 ? (
                      <span
                        className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentExact} ${styles.contextCompositionSegmentUnused}`}
                        style={{ width: contextWindowSegmentWidth(contextCompositionRemainingTokens, contextCompositionLimitTokens) }}
                      />
                    ) : null}
                  </div>
                  {contextCompositionSegments.length ? (
                    <div className={styles.contextCompositionLegend}>
                      {contextCompositionSegments.map((segment) => (
                        <span key={`${segment.key}-${segment.source}-legend`} title={segment.description || segment.source}>
                          <i className={contextCompositionSegmentClass(segment.key)} />
                          {contextCompositionSegmentLabel(segment.key, segment.label, t)}
                          {" "}
                          {numberFormatter.format(segment.tokens ?? 0)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className={styles.contextCompositionItem} title={cacheCompositionTitle}>
                  <div className={styles.contextCompositionHeader}>
                    <span>{t("previousCacheHit")}</span>
                    <strong>{cacheCompositionSummary}</strong>
                  </div>
                  <div className={styles.contextCompositionBar} aria-hidden="true">
                    {cacheCompositionSegments.length ? (
                      cacheCompositionSegments.map((segment) => (
                        <span
                          key={`${segment.key}-${segment.status}`}
                          className={`${styles.contextCompositionSegment} ${cacheCompositionSegmentClass(segment.key)}`}
                          style={{ width: compositionSegmentWidth(segment.tokens ?? 0, cacheCompositionTotalTokens || 1) }}
                        />
                      ))
                    ) : (
                      <span className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentMissing}`} />
                    )}
                  </div>
                  {cacheCompositionSegments.length ? (
                    <div className={styles.contextCompositionLegend}>
                      {cacheCompositionSegments.map((segment) => (
                        <span key={`${segment.key}-${segment.status}-legend`}>
                          <i className={cacheCompositionSegmentClass(segment.key)} />
                          {cacheCompositionSegmentLabel(segment.key, segment.label, t)}
                          {" "}
                          {segment.key === "missing" ? "" : numberFormatter.format(segment.tokens ?? 0)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </section>

              <section className={`${styles.resourceBlock} ${styles.sessionResourceDiagnostics}`}>
                <div className={styles.sectionHeader}>
                  <p className={styles.blockEyebrow}>{t("sessionContextEstimate")}</p>
                  <span className={styles.metricValue}>{contextPercent}%</span>
                </div>
                <div className={styles.resourceSplit}>
                  <div className={styles.resourceMetric}>
                    <span>{contextSourceLine}</span>
                    <strong title={contextStatusLine}>{contextStatusLine}</strong>
                  </div>
                  <div className={styles.resourceMetric}>
                    <span>{t("contextCompression")}</span>
                    <strong title={compressionTitleLine}>{compressionCurrentLine}</strong>
                  </div>
                </div>
                <div className={styles.compressionFactGrid} title={compressionTitleLine}>
                  <div className={styles.compressionFact}>
                    <span>{t("runtimeContextEstimate")}</span>
                    <strong>{compressionMainLine}</strong>
                  </div>
                  <div className={styles.compressionFact}>
                    <span>{t("compressionModelWindow")}</span>
                    <strong>{compressionModelWindowLine}</strong>
                  </div>
                  <div className={`${styles.compressionFact} ${styles.compressionFactWide}`}>
                    <span>{t("compressionThresholdBasis")}</span>
                    <strong>{compressionScopeLine}</strong>
                  </div>
                </div>
                <p className={styles.oneLineValue} title={lastCompression?.reason || lastCompressionLine}>
                  <span>{t("compressionLastRun")}</span>
                  {lastCompressionLine}
                </p>
                <details className={styles.compactDetails}>
                  <summary>
                    <ChevronRight size={14} />
                    <span className={styles.compactDetailsClosedLabel}>{t("compressionStrategy")}</span>
                    <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
                  </summary>
                  <div className={styles.compressionStrategyList}>
                    {(compression?.strategy.levels ?? []).map((level) => (
                      <div key={level.level} className={styles.compressionStrategyRow}>
                        <strong>{level.level}</strong>
                        <span>{t("compressionThreshold")} {Math.round(level.thresholdRatio * 100)}% / {numberFormatter.format(level.thresholdTokens)}</span>
                        <span>{t("compressionKeepAi")} {level.keepAiMessages}</span>
                        <span>{t("compressionSummary")} {numberFormatter.format(level.summaryMaxChars)}</span>
                      </div>
                    ))}
                  </div>
                  <p className={styles.detailNote}>
                    <span>{t("compressionErrorProtection")}</span>
                    {(compression?.strategy.errorProtectionKeywords ?? []).join(" / ") || "--"}
                  </p>
                </details>
              </section>
            </div>
          </details>
        </section>

        <section className={`${styles.leftBlock} ${styles.featurePresetBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("chatFeaturePanel")}</p>
              <h3 className={styles.sectionTitle}>{t("chatFeaturePanelTitle")}</h3>
            </div>
            <span className={styles.featurePresetScope}>{t("chatFeaturePanelScope")}</span>
          </div>
          <div className={styles.featurePrimarySlot}>
            <button
              type="button"
              className={
                mentalModelEnabledForNextTurn
                  ? `${styles.featureToggle} ${styles.featureToggleActive} ${styles.featureTogglePrimary}`
                  : `${styles.featureToggle} ${styles.featureTogglePrimary}`
              }
              aria-pressed={mentalModelEnabledForNextTurn}
              disabled={!activeSessionId}
              onClick={() => handleMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}
            >
              <span className={styles.featureToggleText}>
                <strong>{t("chatFeatureMentalModel")}</strong>
                <span>{t("mentalModelForNextTurn")}</span>
              </span>
              <span className={styles.featureToggleState}>
                {mentalModelEnabledForNextTurn ? t("mentalModelNextTurnOn") : t("mentalModelNextTurnOff")}
              </span>
            </button>
          </div>
          <div className={styles.featureChipRow}>
            {CHAT_FEATURE_PRESETS.map((item) => {
              const enabled = featurePresetState[item.key];
              return (
                <button
                  key={item.key}
                  type="button"
                  className={enabled ? `${styles.featureChip} ${styles.featureChipActive}` : styles.featureChip}
                  aria-pressed={enabled}
                  onClick={() => toggleFeaturePreset(item.key)}
                  title={t(item.hintKey)}
                >
                  <strong>{t(item.labelKey)}</strong>
                  <span aria-hidden="true" />
                </button>
              );
            })}
          </div>
          <p className={styles.featurePresetNote}>{t("chatFeaturePanelHint")}</p>
        </section>

        <section className={`${styles.leftBlock} ${styles.companionBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("mentalState")} / {t("petSpace")}</p>
              <p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>
            </div>
            <span className={`${styles.mentalStateBadge} ${styles[`mentalStateBadge_${mentalCognitiveStateValue}`]}`}>
              {mentalStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{mentalSummary}</p>
          <div className={styles.companionCompact}>
            <div className={styles.petMiniAvatar} aria-hidden="true">
              <div className={`${styles.petShowcaseAvatar} ${petAvatarSkinClass}`}>
                <span className={styles.petShowcaseEarLeft} />
                <span className={styles.petShowcaseEarRight} />
                <span className={styles.petShowcaseFace}>
                  <span className={styles.petShowcaseEye} />
                  <span className={styles.petShowcaseMuzzle} />
                  <span className={styles.petShowcaseEye} />
                </span>
                <span className={styles.petShowcaseSymbol}>{petAvatarSymbol}</span>
                <span className={styles.petShowcaseFootLeft} />
                <span className={styles.petShowcaseFootRight} />
              </div>
            </div>
            <div className={styles.companionCopy}>
              <div className={styles.companionTopLine}>
                <strong>{pet?.name ?? t("loadingPetState")}</strong>
                <span>{t("level")} {pet?.level ?? 0} · {petPresetLabel}</span>
              </div>
              <p title={petCompactLine}>{petCompactLine}</p>
            </div>
          </div>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("expandSection")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            <p className={styles.oneLineValue} title={mentalWhisper}>
              <span>{t("mentalWhisper")}</span>
              {mentalWhisper}
            </p>
            <div className={styles.inlineStatGrid}>
              <div className={styles.inlineStat}>
                <span>{t("state")}</span>
                <strong>{mentalCognitiveStateLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalConfidence")}</span>
                <strong>{mentalConfidence}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalSource")}</span>
                <strong>{mentalSourceLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalLastUpdated")}</span>
                <strong title={formatTime(mental?.updatedAt ?? "")}>{mentalRelativeTime}</strong>
              </div>
            </div>
            <div className={styles.inlineMetaList}>
              <span className={styles.inlineMetaPill}>
                <span>{t("dailyTokens")}</span>
                <strong>{numberFormatter.format(pet?.dailyTokens ?? 0)}</strong>
              </span>
              {petVitals.map((vital) => (
                <span key={vital.key} className={styles.inlineMetaPill}>
                  <span>{vital.label}</span>
                  <strong>{vital.value}</strong>
                </span>
              ))}
            </div>
            <div className={styles.petShowcaseActions} aria-label={petInteractionLabels.group}>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("feed")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.feedTitle}
              >
                <Apple size={14} />
                <span>{petInteractionLabels.feed}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("talk")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.talkTitle}
              >
                <MessageCircleHeart size={14} />
                <span>{petInteractionLabels.talk}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("care")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.careTitle}
              >
                <HeartHandshake size={14} />
                <span>{petInteractionLabels.care}</span>
              </button>
              <span className={styles.petShowcaseActionHint}>
                <Sparkles size={13} />
                <span>{petInteractionLabels.pending}</span>
              </span>
            </div>
            {petActionFeedback ? <p className={styles.petShowcaseFeedback}>{petActionFeedback}</p> : null}
          </details>
        </section>
          </>
        )}
      </aside>

      <PaneCollapseHandle
        side="left"
        collapsed={leftRailCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起左栏" : "Collapse left pane"}
        expandLabel={lang === "zh" ? "展开左栏" : "Expand left pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "left"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      />

      <section className={styles.centerPane}>
        <div className={styles.tabStrip}>
          {groupPanelActive ? (
            <button
              type="button"
              className={`${styles.tab} ${styles.tabActive}`}
              onClick={() => undefined}
            >
              {projectBusActive ? (lang === "zh" ? "通知流" : "Notice stream") : (lang === "zh" ? "群聊" : "Group")}
            </button>
          ) : agentSessionTabs.length > 1 ? (
            <div className={styles.agentSessionTabGroup} aria-label={lang === "zh" ? "Agent 会话" : "Agent sessions"}>
              {agentSessionTabs.map((session) => {
                const sessionIsChild = isChildSession(session);
                const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
                const sessionStatus = sessionIsChild ? (session.childStatus || session.currentPhase || session.status) : session.status;
                const sessionTitle =
                  (sessionIsChild ? (session.taskTitle || session.resultCard?.title || session.title) : sessionDisplay.name)
                  || sessionDisplay.name
                  || t("agentSession");
                const sessionSummary =
                  (sessionIsChild ? (session.resultCard?.summary || session.taskSummary) : session.taskSummary)
                  || sessionDisplay.modelLabel
                  || "";
                const tabActive = activeSessionId === session.id && workspace.activeTab === "agent";
                const tabEditing = editingSessionId === session.id;
                const tabClassName = [
                  styles.agentSessionTab,
                  sessionIsChild ? styles.agentSessionTabChild : styles.agentSessionTabRoot,
                  tabActive ? styles.agentSessionTabActive : "",
                  tabEditing ? styles.agentSessionTabEditing : "",
                ].filter(Boolean).join(" ");
                if (tabEditing) {
                  const renamePending =
                    renameSessionMutation.isPending &&
                    renameSessionMutation.variables?.sessionId === session.id;
                  return (
                    <div
                      key={session.id}
                      className={tabClassName}
                      aria-current={tabActive ? "true" : undefined}
                      onContextMenu={(event) => openSessionContextMenu(event, session)}
                      title={[sessionTitle, sessionSummary].filter(Boolean).join(" · ")}
                    >
                      <span className={styles.agentSessionTabIcon} aria-hidden="true">
                        {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
                      </span>
                      <span className={styles.agentSessionTabCopy}>
                        <span className={styles.agentSessionTabKicker}>
                          {sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : t("agentSession")}
                        </span>
                        <input
                          className={styles.agentSessionTabTitleInput}
                          value={editingSessionTitle}
                          maxLength={120}
                          autoFocus
                          onChange={(event) => setEditingSessionTitle(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              submitRenameSession(session);
                            }
                            if (event.key === "Escape") {
                              event.preventDefault();
                              cancelRenameSession();
                            }
                          }}
                          aria-label={t(sessionIsChild ? "renameTask" : "renameAgent")}
                        />
                      </span>
                      <span className={styles.agentSessionTabEditActions}>
                        <button
                          type="button"
                          className={styles.agentSessionTabEditButton}
                          onClick={() => submitRenameSession(session)}
                          disabled={renamePending}
                          title={t(sessionIsChild ? "saveTaskName" : "saveAgentName")}
                          aria-label={`${t(sessionIsChild ? "saveTaskName" : "saveAgentName")} ${sessionTitle}`}
                        >
                          <Check size={13} />
                        </button>
                        <button
                          type="button"
                          className={styles.agentSessionTabEditButton}
                          onClick={cancelRenameSession}
                          disabled={renamePending}
                          title={t("cancelRenameSession")}
                          aria-label={t("cancelRenameSession")}
                        >
                          <X size={13} />
                        </button>
                      </span>
                    </div>
                  );
                }
                return (
                  <button
                    key={session.id}
                    type="button"
                    className={tabClassName}
                    aria-current={tabActive ? "true" : undefined}
                    draggable
                    onDragStart={(event) =>
                      startSessionReferenceDrag(
                        event,
                        buildSessionReferencePayload(session, sessionDisplay.name, sessionSummary),
                      )}
                    onContextMenu={(event) => openSessionContextMenu(event, session)}
                    onClick={() => {
                      if (activeSessionId === session.id) {
                        setActiveTab(session.id, "agent");
                        return;
                      }
                      handleOpenDirectSession(session.id);
                    }}
                    title={[sessionTitle, sessionSummary].filter(Boolean).join(" · ")}
                  >
                    <span className={styles.agentSessionTabIcon} aria-hidden="true">
                      {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
                    </span>
                    <span className={styles.agentSessionTabCopy}>
                      <span className={styles.agentSessionTabKicker}>
                        {sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : t("agentSession")}
                      </span>
                      <span className={styles.agentSessionTabTitle}>{sessionTitle}</span>
                    </span>
                    <span className={styles.agentSessionTabMeta}>
                      {statusLabel(sessionStatus)}
                      {sessionDisplay.modelLabel ? ` · ${sessionDisplay.modelLabel}` : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <button
              type="button"
              className={workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              onClick={() => {
                activeSessionId && setActiveTab(activeSessionId, "agent");
              }}
            >
              {t("agentSession")}
            </button>
          )}
          {!groupPanelActive && workspace.openTabs.map((tabPath) => (
            <div
              key={tabPath}
              className={
                workspace.activeTab === tabPath
                  ? `${styles.fileTab} ${styles.fileTabActive}`
                  : styles.fileTab
              }
            >
              <button
                type="button"
                className={styles.fileTabButton}
                onClick={() => activeSessionId && setActiveTab(activeSessionId, tabPath)}
              >
                {tabPath.split("/").at(-1)}
              </button>
              <button
                type="button"
                className={styles.fileTabClose}
                onClick={() => activeSessionId && closePreviewTab(activeSessionId, tabPath)}
                title={t("closePreviewTab")}
                aria-label={`${t("closePreviewTab")} ${tabPath.split("/").at(-1)}`}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className={styles.centerSurface}>
          {projectBusActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{lang === "zh" ? "Agent 通知流" : "Agent notice stream"}</h2>
                  <span>
                    {projectBusTimeline?.activeAgentCount ?? availableGroupParticipantCount} {lang === "zh" ? "位 active Agent" : "active agents"}
                    {" · "}
                    {lang === "zh" ? "全局广播与投递观察" : "broadcasts and delivery observation"}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => void projectAgentBusQuery.refetch()}
                  disabled={projectAgentBusQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
              </header>
              {projectAgentBusQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(projectAgentBusQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              {groupRoomActionError ? (
                <div className={styles.inlineNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={sendProjectBusMessageMutation.isPending ? "polite" : undefined}>
                {projectBusEvents.length ? (
                  projectBusEvents.map((event) => {
                    const revoked = isProjectAgentBusEventRevoked(event);
                    const targetLabel = event.targetScope === "all"
                      ? (lang === "zh" ? "全体成员" : "All agents")
                      : event.targetAgentNames.length
                        ? event.targetAgentNames.join(", ")
                        : (lang === "zh" ? "仅观察" : "Observe only");
                    const deliveryLabel = event.deliveries.length
                      ? `${event.deliveries.length} ${lang === "zh" ? "次投递" : "deliveries"}`
                      : (lang === "zh" ? "未投递" : "no delivery");
                    const interruptionLabel = event.interruptions.length
                      ? `${event.interruptions.filter((item) => item.status === "interrupted").length}/${event.interruptions.length} ${lang === "zh" ? "已打断" : "interrupted"}`
                      : "";
                    return (
                      <article key={event.eventId} className={revoked ? `${styles.projectBusEvent} ${styles.projectBusEventRevoked}` : styles.projectBusEvent}>
                        <header className={styles.projectBusEventHeader}>
                          <div>
                            <strong>{event.createdBy === "user" ? runtime?.userName || (lang === "zh" ? "我" : "Me") : event.createdBy}</strong>
                            <span>{targetLabel}</span>
                          </div>
                          <div className={styles.projectBusEventActions}>
                            <time>{formatTime(event.createdAt)}</time>
                            {event.createdBy === "user" && !revoked ? (
                              <button
                                type="button"
                                onClick={() => handleRevokeProjectBusMessage(event.eventId)}
                                disabled={revokeProjectBusMessageMutation.isPending}
                              >
                                {lang === "zh" ? "撤回" : "Recall"}
                              </button>
                            ) : null}
                          </div>
                        </header>
                        <p className={styles.projectBusEventBody}>
                          {revoked
                            ? (lang === "zh" ? "这条消息已撤回，相关 Agent 已请求停止。" : "This message was recalled. Target agents were asked to stop.")
                            : renderMentionedText(event.content)}
                        </p>
                        <div className={styles.projectBusEventMeta}>
                          <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                          <span>{deliveryLabel}</span>
                          {interruptionLabel ? <span>{interruptionLabel}</span> : null}
                          {event.unresolvedMentions.length ? (
                            <span>{lang === "zh" ? "未识别" : "unresolved"} @{event.unresolvedMentions.join(", @")}</span>
                          ) : null}
                        </div>
                      </article>
                    );
                  })
                ) : (activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <BellRing size={28} />
                    <p>{lang === "zh" ? "Agent 通知流会显示用户引导、Agent 私聊和广播投递结果；它不是团队群聊。" : "The Agent notice stream shows guidance, private messages, broadcasts, and delivery results. It is not a team room."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <input
                  value={projectBusDraft}
                  onChange={(event) => setProjectBusDraft(event.target.value)}
                  disabled={sendProjectBusMessageMutation.isPending}
                  placeholder={lang === "zh" ? "输入广播；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Write a broadcast; no @ sends to all, @AgentCode targets one"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSendProjectBusMessage();
                    }
                  }}
                />
                <label className={styles.projectBusInterruptToggle}>
                  <input
                    type="checkbox"
                    checked={projectBusInterruptTargets}
                    onChange={(event) => setProjectBusInterruptTargets(event.target.checked)}
                  />
                  <span>{lang === "zh" ? "打断目标 Agent" : "Interrupt targets"}</span>
                </label>
                <button
                  type="button"
                  onClick={handleSendProjectBusMessage}
                  disabled={
                    !projectBusDraft.trim()
                    || sendProjectBusMessageMutation.isPending
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {sendProjectBusMessageMutation.isPending
                      ? (lang === "zh" ? "发送中" : "Sending")
                      : (lang === "zh" ? "发送广播" : "Send")}
                  </span>
                </button>
              </div>
            </div>
          ) : legacyGroupRoomActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h2>
                  <span>
                    {availableGroupParticipantCount} {lang === "zh" ? "位可用 Agent" : "available agents"}
                    {" · "}
                    {statusLabel(activeGroupRoom?.status ?? "ready")}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => activeGroupRoomId && void activeGroupRoomQuery.refetch()}
                  disabled={activeGroupRoomQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
              </header>
              {activeGroupRoomQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(activeGroupRoomQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={groupRoundActive ? "polite" : undefined}>
                {(activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <UsersRound size={28} />
                    <p>{lang === "zh" ? "群聊已创建，输入议题后开始第一轮讨论。" : "The group is ready. Enter a topic to start the first round."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <input
                  value={groupTopicDraft}
                  onChange={(event) => setGroupTopicDraft(event.target.value)}
                  disabled={startGroupRoundMutation.isPending}
                  placeholder={lang === "zh" ? "输入下一轮群聊议题" : "Topic for the next group round"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleStartGroupRound();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={handleStartGroupRound}
                  disabled={
                    !groupTopicDraft.trim()
                    || startGroupRoundMutation.isPending
                    || groupRoundActive
                    || !activeGroupRoom
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {startGroupRoundMutation.isPending || groupRoundActive
                      ? (groupRoundStopping ? (lang === "zh" ? "停止中" : "Stopping") : (lang === "zh" ? "讨论中" : "Running"))
                      : (lang === "zh" ? "启动一轮" : "Run round")}
                  </span>
                </button>
                {groupRoundActive ? (
                  <button
                    type="button"
                    className={styles.groupStopButton}
                    onClick={handleStopGroupRound}
                    disabled={groupStopDisabled}
                    title={lang === "zh" ? "停止当前群聊轮次" : "Stop current group round"}
                  >
                    <Square size={15} />
                    <span>
                      {stopGroupRoundMutation.isPending
                        ? (lang === "zh" ? "停止中" : "Stopping")
                        : (lang === "zh" ? "停止" : "Stop")}
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          ) : !activeSessionId && !sessionsQuery.isPending ? (
            <div className={styles.emptySurface}>{t("noSessionsYet")}</div>
          ) : sessionDetailErrorState.blockingError ? (
            <div className={styles.emptySurface}>
              {sessionDetailErrorMessage}
            </div>
          ) : invalidChildSessionLinkMessage ? (
            <div className={styles.emptySurface}>
              {invalidChildSessionLinkMessage}
            </div>
          ) : workspace.activeTab === "agent" ? (
            detail ? (
              <div className={styles.conversationFrame}>
                {sessionDetailErrorState.transientError ? (
                  <div className={styles.inlineNotice} role="status">
                    {sessionDetailErrorMessage}
                  </div>
                ) : null}
                {activeRuntimeNotices.length > 0 ? (
                  <div className={styles.runtimeNoticeStack} role="status" aria-live="polite">
                    {activeRuntimeNotices.map((notice) => (
                      <div
                        key={notice.id || `${notice.kind}-${notice.timestamp}-${notice.message}`}
                        className={[
                          styles.runtimeNotice,
                          styles[`runtimeNotice_${notice.level || "info"}`],
                        ].filter(Boolean).join(" ")}
                      >
                        <CircleDot size={13} />
                        <div className={styles.runtimeNoticeBody}>
                          <span className={styles.runtimeNoticeLabel}>
                            {lang === "zh" ? "运行状态" : "Runtime"}
                            {notice.source ? ` · ${notice.source}` : ""}
                          </span>
                          <span className={styles.runtimeNoticeMessage}>{notice.message}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
                <LazyConversationView
                  sessionId={activeSessionId ?? detail.id}
                  title={detail.title}
                  phase={detail.currentPhase}
                  messages={detail.messages}
                  assistantDisplayName={activeAgentDisplayName}
                  assistantAvatarImageUrl={activeAgentAvatarImageUrl}
                  assistantAvatarFallback={activeAgentAvatarFallback}
                  resolveTurnAvatar={resolveConversationTurnAvatar}
                  userDisplayName={runtime?.userName}
                  userAvatarPreset={runtime?.userProfile?.avatarPreset}
                  userAvatarImageUrl={runtime?.userProfile?.avatarImageUrl}
                  taskSummary={currentTaskSummary}
                  defaultFileContext={detail.defaultFileContext}
                  showHeader={false}
                  showSessionOverview={false}
                  showMentalSnapshots={mentalModelEnabledForNextTurn}
                  composerValue={activeDraftEffective}
                  composerPlaceholder={composerPlaceholder}
                  composerDisabled={composerDisabled}
                  composerActionDisabled={composerActionDisabled}
                  composerActionMode={composerStopMode ? "stop" : "send"}
                  composerPending={composerPending}
                  composerSafeGuidancePending={composerSafeGuidancePending}
                  composerInterruptGuidancePending={composerInterruptGuidancePending}
                  composerError={activeComposerError}
                  composerGuidance={composerGuidance}
                  composerAttachments={activeImageAttachments.map((attachment) => ({
                    id: attachment.id,
                    filename: attachment.filename,
                    previewUrl: attachment.previewUrl,
                    sizeBytes: attachment.sizeBytes,
                    contentType: attachment.contentType,
                  }))}
                  composerReferences={activeReferenceAttachments}
                  composerAttachmentInputDisabled={composerDisabled || Boolean(resolvedEditTarget)}
                  composerModeNotice={resolvedEditTarget ? t("editMessageModeNotice") : ""}
                  cancelComposerModeLabel={t("cancelEditMessage")}
                  turnError={detail.lastTurnError}
                  nextStateSignals={detail.nextStateSignals ?? []}
                  stopLabel={t("stop")}
                  stopPendingLabel={t("stopPending")}
                  safeGuidanceLabel={t("safeGuidance")}
                  safeGuidancePendingLabel={t("safeGuidancePending")}
                  interruptGuidanceLabel={t("interruptGuidance")}
                  interruptGuidancePendingLabel={t("interruptGuidancePending")}
                  editingMessageId={resolvedEditTarget?.messageId}
                  editUserMessageLabel={t("editAndResendMessage")}
                  editUserMessageDisabled={submitPending}
                  onComposerChange={handleComposerChange}
                  onAddComposerAttachments={handleAddComposerAttachments}
                  onRemoveComposerAttachment={handleRemoveComposerAttachment}
                  onAddComposerReference={handleAddComposerReference}
                  onRemoveComposerReference={handleRemoveComposerReference}
                  onEditUserMessage={handleEditUserMessage}
                  onCancelComposerMode={resolvedEditTarget ? handleCancelEditMessage : undefined}
                  onSubmit={handleSubmitTurn}
                  onStop={handleStopTurn}
                  onSafeGuidance={() => handleSubmitGuidance("safe")}
                  onInterruptGuidance={() => handleSubmitGuidance("interrupt")}
                  fallback={<div className={styles.emptySurface}>{t("loadingSession")}</div>}
                />
              </div>
            ) : (
              <div className={styles.emptySurface}>{t("loadingSession")}</div>
            )
          ) : fileContentQuery.isError ? (
            <div className={styles.emptySurface}>
              {describeError(fileContentQuery.error, t("loadFailed"))}
            </div>
          ) : fileContentQuery.data ? (
            <LazyFilePreview
              file={fileContentQuery.data}
              changed={changedFiles.has(fileContentQuery.data.path)}
              sourceLabel={detail?.title ?? t("currentSession")}
              fallback={<div className={styles.emptySurface}>{t("loadingFilePreview")}</div>}
            />
          ) : (
            <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
          )}
        </div>
      </section>

      <PaneCollapseHandle
        side="right"
        collapsed={rightPaneCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起右栏" : "Collapse right pane"}
        expandLabel={lang === "zh" ? "展开右栏" : "Expand right pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "right"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />

      <aside className={rightPaneCollapsed ? `${styles.rightPane} ${styles.paneCollapsed}` : styles.rightPane} aria-hidden={rightPaneCollapsed}>
        {legacyGroupRoomActive ? (
          <div
            className={styles.rightIndexTabs}
            role="tablist"
            aria-label={lang === "zh" ? "右侧索引" : "Right index"}
          >
            <button
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "conversations"}
              className={rightIndexPanel === "conversations" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("conversations")}
            >
              <MessageCircleHeart size={14} />
              <span>{lang === "zh" ? "会话" : "Chats"}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "members"}
              className={rightIndexPanel === "members" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("members")}
            >
              <UsersRound size={14} />
              <span>{lang === "zh" ? "成员" : "Members"}</span>
            </button>
          </div>
        ) : null}

        {rightIndexPanel === "members" && legacyGroupRoomActive ? (
          <div className={styles.memberIndexSummary}>
            <UsersRound size={15} />
            <span>
              {availableGroupParticipantCount} {lang === "zh" ? "位可用 Agent" : "available agents"}
            </span>
            <strong>{statusLabel(activeGroupRoom?.status ?? "ready")}</strong>
          </div>
        ) : (
          <div className={styles.panelSearch}>
            <Search size={15} />
            <input
              className={styles.panelSearchInput}
              type="text"
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              placeholder={t("searchSessionsPlaceholder")}
            />
          </div>
        )}

        <div className={styles.panelBody}>
          {rightIndexPanel === "members" && legacyGroupRoomActive ? (
            <section className={styles.agentIndexRoster} aria-label={lang === "zh" ? "群成员状态索引" : "Group member status index"}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionIdentity}>
                  <p className={styles.blockEyebrow}>{lang === "zh" ? "成员状态" : "Member status"}</p>
                  <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
                </div>
              </div>
              <p className={styles.contextLineCompact}>
                {lang === "zh"
                  ? "只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。"
                  : "Only available members are shown here; archived or broken historical members stay in diagnostics."}
              </p>
              {availableGroupParticipants.length ? (
                <div className={styles.agentIndexList}>
                  {availableGroupParticipants.map((participant: ChatRoomParticipant) => {
                  const expanded = expandedGroupAgentSessionIds.includes(participant.sessionId);
                  const participantSession = sessionsById.get(participant.sessionId);
                  const expandedDetailQuery = expandedGroupAgentDetailsBySessionId.get(participant.sessionId);
                  const memberDetail = expanded ? expandedDetailQuery?.data : undefined;
                  const memberContext = memberDetail?.contextUsage;
                  const memberContextUsed = memberContext?.used ?? 0;
                  const memberContextLimit = memberContext?.limit ?? 0;
                  const memberContextPercent = contextUsagePercent(memberContextUsed, memberContextLimit);
                  const memberMental = mentalModelEnabledForNextTurn ? latestMentalSnapshot(memberDetail?.messages) : undefined;
                  const memberMentalState = memberMental?.mood?.trim()
                    || memberMental?.cognitiveState?.trim()
                    || (lang === "zh" ? "未记录" : "No snapshot");
                  const memberMentalSummary = memberMental?.feeling?.trim()
                    || memberMental?.summary?.trim()
                    || (lang === "zh" ? "该 Agent 尚未形成可展示的心智快照。" : "This agent has no visible mental snapshot yet.");
                  const participantDisplay = groupParticipantIdentity(participant);
                  const participantAgent = participant.agentId ? agentsById.get(participant.agentId) : undefined;
                  const participantAvatarImageUrl = avatarImageUrlFrom(participantAgent, participant);
                  const memberUpdated = formatRelativeTime(
                    memberMental?.updatedAt || memberDetail?.updatedAt || participantSession?.updatedAt || "",
                    Date.now(),
                    locale,
                  );
                  return (
                    <article key={participant.participantId || participant.sessionId} className={styles.agentIndexCard}>
                      <div className={styles.agentIndexHeader}>
                        <button
                          type="button"
                          className={styles.agentIndexExpandButton}
                          aria-expanded={expanded}
                          aria-label={expanded
                            ? (lang === "zh" ? `收起 ${participantDisplay.name} 状态` : `Collapse ${participantDisplay.name} status`)
                            : (lang === "zh" ? `展开 ${participantDisplay.name} 状态` : `Expand ${participantDisplay.name} status`)}
                          onClick={() =>
                            setExpandedGroupAgentSessionIds((current) =>
                              current.includes(participant.sessionId)
                                ? current.filter((sessionId) => sessionId !== participant.sessionId)
                                : [...current, participant.sessionId],
                            )}
                        >
                          <ChevronRight size={14} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className={styles.agentIndexOpenButton}
                          onClick={() => handleOpenDirectSession(participant.sessionId)}
                          aria-label={lang === "zh" ? `打开 ${participantDisplay.name} 单聊` : `Open direct chat with ${participantDisplay.name}`}
                          title={lang === "zh" ? "打开该 Agent 的单聊" : "Open this Agent direct chat"}
                        >
                          {renderAgentAvatar(
                            styles.agentIndexAvatar,
                            participantAvatarImageUrl,
                            avatarInitials(participant.agentCode, participant.title),
                          )}
                          <span className={styles.agentIndexCopy}>
                            <strong className={styles.agentIndexNameLine}>
                              <span>{participantDisplay.name}</span>
                              <em className={`${styles.agentRoleTag} ${styles[agentRoleClass(participantDisplay.tone)]}`}>
                                {participantDisplay.functionLabel}
                              </em>
                            </strong>
                            {participantDisplay.modelLabel ? (
                              <span className={styles.agentModelLine} title={participantDisplay.modelLabel}>
                                {participantDisplay.modelLabel}
                              </span>
                            ) : null}
                          </span>
                        </button>
                        <span className={styles.agentIndexStatus}>
                          {statusLabel(participant.status || participantSession?.status || "ready")}
                        </span>
                      </div>
                      {expanded ? (
                        <div className={styles.agentIndexDetails}>
                          {expandedDetailQuery?.isPending ? (
                            <p className={styles.contextLineCompact}>{t("loadingSession")}</p>
                          ) : expandedDetailQuery?.isError ? (
                            <p className={styles.panelNotice}>{describeError(expandedDetailQuery.error, t("loadFailed"))}</p>
                          ) : (
                            <>
                              <div className={styles.resourceSplit}>
                                <div className={styles.resourceMetric}>
                                  <span>{t("contextInUse")}</span>
                                  <strong>{formatContextUsage(memberContextUsed, memberContextLimit, locale)}</strong>
                                </div>
                                <div className={styles.resourceMetric}>
                                  <span>{lang === "zh" ? "上下文占比" : "Context ratio"}</span>
                                  <strong>{memberContextPercent}%</strong>
                                </div>
                              </div>
                              <p className={styles.oneLineValue}>
                                <span>{lang === "zh" ? "消息" : "Messages"}</span>
                                {memberContext
                                  ? `${numberFormatter.format(memberContext.messageCount)} ${lang === "zh" ? "条" : "messages"} · ${numberFormatter.format(memberContext.assistantMessageCount)} Agent`
                                  : (lang === "zh" ? "暂无上下文统计" : "No context stats yet")}
                              </p>
                              <div className={styles.agentIndexMentalBlock}>
                                <div className={styles.sectionHeader}>
                                  <div className={styles.sectionIdentity}>
                                    <p className={styles.blockEyebrow}>{t("mentalState")}</p>
                                    <p className={styles.sectionMetaLine}>
                                      {memberUpdated || (lang === "zh" ? "尚未更新" : "Not updated yet")}
                                    </p>
                                  </div>
                                  <span className={styles.mentalStateBadge}>{memberMentalState}</span>
                                </div>
                                <p className={styles.contextLineCompact}>{memberMentalSummary}</p>
                              </div>
                              <p className={styles.featurePresetNote}>
                                {lang === "zh"
                                  ? "群聊成员由群聊调度驱动；需要单独调整下一轮功能时，请打开该 Agent 的单聊。"
                                  : "Group members are driven by group scheduling. Open the direct chat to tune next-turn features."}
                              </p>
                            </>
                          )}
                        </div>
                      ) : null}
                    </article>
                  );
                  })}
                </div>
              ) : (
                <div className={styles.agentIndexEmptyState}>
                  <UsersRound size={24} />
                  <p>
                    {lang === "zh"
                      ? "暂无可用群成员。请在左侧群设置中选择成员并应用变更。"
                      : "No available group members. Choose members in the left group settings and apply the change."}
                  </p>
                </div>
              )}
            </section>
          ) : (
            <>
            <div className={styles.sessionActionRow}>
              <button
                type="button"
                className={styles.newSessionButton}
                onClick={handleCreateSession}
                disabled={createSessionMutation.isPending}
              >
                <Plus size={15} />
                <span>{createSessionMutation.isPending ? t("creatingSession") : t("newSession")}</span>
              </button>
              <button
                type="button"
                className={styles.newGroupButton}
                onClick={handleToggleGroupComposer}
                aria-expanded={groupComposerOpen}
                disabled={createGroupRoomMutation.isPending}
              >
                <UsersRound size={15} />
                <span>{groupComposerOpen ? (lang === "zh" ? "收起" : "Close") : (lang === "zh" ? "新建群聊" : "New group")}</span>
              </button>
            </div>
            <section className={styles.systemEntryGroup} aria-label={lang === "zh" ? "系统入口" : "System entries"}>
              <div className={styles.conversationTreeRootHeader}>
                <span>{lang === "zh" ? "系统入口" : "System"}</span>
                <strong>1</strong>
              </div>
              <button
                type="button"
                aria-current={projectBusActive ? "true" : undefined}
                className={
                  projectBusActive
                    ? `${styles.systemEntryButton} ${styles.systemEntryButtonActive}`
                    : styles.systemEntryButton
                }
                onClick={handleOpenProjectAgentBus}
              >
                <span className={styles.systemEntryIcon} aria-hidden="true">
                  <BellRing size={16} />
                </span>
                <span className={styles.systemEntryCopy}>
                  <span className={styles.systemEntryTitleRow}>
                    <span className={styles.systemEntryTitle}>{lang === "zh" ? "Agent 通知流" : "Agent notice stream"}</span>
                    {projectBusActive ? <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span> : null}
                  </span>
                  <span className={styles.systemEntryMeta}>
                    {lang === "zh" ? "全局广播 · 私信投递记录" : "Global broadcast · private delivery log"}
                  </span>
                </span>
              </button>
            </section>
            {groupComposerOpen ? (
              <section className={styles.groupComposerPanel} aria-label={lang === "zh" ? "新建群聊" : "New group chat"}>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    className={styles.groupComposerInput}
                    value={groupTitleDraft}
                    maxLength={80}
                    onChange={(event) => setGroupTitleDraft(event.target.value)}
                  />
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupModeDraft}
                    onChange={(event) => setGroupModeDraft(event.target.value)}
                    disabled={chatRoomModesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupPurposeDraft}
                    onChange={(event) => setGroupPurposeDraft(event.target.value)}
                    disabled={chatRoomPurposesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupAgentPicker} aria-label={lang === "zh" ? "选择参与 Agent" : "Choose agents"}>
                  {agentsQuery.isPending ? (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "正在读取 Agent..." : "Loading agents..."}</p>
                  ) : groupCandidateAgents.length ? (
                    groupCandidateAgents.map((agent) => {
                      const selected = groupSelectedAgentIds.includes(agent.agentId);
                      const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
                      return (
                        <label key={agent.agentId} className={selected ? `${styles.groupAgentOption} ${styles.groupAgentOptionSelected}` : styles.groupAgentOption}>
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={createGroupRoomMutation.isPending}
                            onChange={() => handleToggleGroupAgent(agent.agentId)}
                          />
                          {renderAgentAvatar(
                            styles.agentOptionAvatar,
                            agent.avatarImageUrl,
                            avatarInitials(agent.agentCode, display.name),
                          )}
                          <span>
                            <strong>{display.name}</strong>
                            <span className={styles.agentOptionMeta}>
                              <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                                {display.functionLabel}
                              </small>
                              {display.modelLabel ? (
                                <small className={styles.agentModelTag} title={display.modelLabel}>
                                  {display.modelLabel}
                                </small>
                              ) : null}
                            </span>
                          </span>
                        </label>
                      );
                    })
                  ) : (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "暂无可加入群聊的持久 Agent。" : "No persistent agents are available."}</p>
                  )}
                </div>
                <button
                  type="button"
                  className={styles.createGroupButton}
                  onClick={handleCreateGroupRoom}
                  disabled={createGroupRoomMutation.isPending || groupSelectedAgentIds.length < 2 || !groupTitleDraft.trim()}
                >
                  <UsersRound size={15} />
                  <span>{createGroupRoomMutation.isPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建群聊" : "Create group")}</span>
                </button>
              </section>
            ) : null}
            {sessionComposerErrors.__sessions__ ? (
              <div className={styles.panelState}>{sessionComposerErrors.__sessions__}</div>
            ) : null}
            {sessionsErrorState.transientError ? (
              <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
            ) : null}
            {sessionsErrorState.blockingError ? (
              <div className={styles.panelState}>{sessionsErrorMessage}</div>
            ) : conversationsQuery.isPending && !conversationsQuery.data && sessionsQuery.isPending && !sessionsQuery.data ? (
              <div className={styles.panelState}>{t("loadingSession")}</div>
            ) : filteredConversations.length === 0 && filteredTeams.length === 0 && filteredStandaloneGroupConversations.length === 0 ? (
              <div className={styles.panelState}>
                {sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
              </div>
            ) : (
              <>
              {filteredConversations.length ? groupedConversations.map((group) => {
                const collapsed = !searchHasTerm && collapsedConversationGroups[group.groupKey];
                return (
                  <section key={group.groupKey} className={styles.conversationGroup}>
                    <button
                      type="button"
                      className={styles.conversationGroupHeader}
                      onClick={() => toggleConversationGroup(group.groupKey)}
                      aria-expanded={!collapsed}
                    >
                      <ChevronRight size={14} aria-hidden="true" />
                      <span>{group.label}</span>
                      <strong>{group.items.length}</strong>
                    </button>
                    {!collapsed ? (
                      <div className={styles.conversationGroupList}>
                        {group.items.map((conversation) => {
                if (conversation.type === "group_room") {
                  const roomId = conversation.roomId || conversation.conversationId;
                  return (
                    <GroupConversationIndexItem
                      key={`group-${roomId}`}
                      active={activeGroupRoomId === roomId}
                      conversation={conversation}
                      kindLabel={lang === "zh" ? "群聊" : "Group"}
                      fallbackSummary={lang === "zh" ? "群聊会话" : "Group conversation"}
                      lang={lang}
                      roomId={roomId}
                      statusLabel={statusLabel}
                      formatTime={formatTime}
                      onOpen={handleOpenGroupRoom}
                    />
                  );
                }
                const sessionId = conversation.directSessionId || conversation.conversationId;
                const session: SessionSummary = sessionsById.get(sessionId) ?? {
                  id: sessionId,
                  title: conversation.title,
                  agentId: conversation.agentId,
                  agentCode: conversation.agentCode,
                  agentPrimaryMode: conversation.agentPrimaryMode,
                  agentRoleKey: conversation.agentRoleKey,
                  agentPromptTemplateId: conversation.agentPromptTemplateId,
                  agentDisplayName: conversation.agentDisplayName,
                  workspacePath: conversation.workspacePath,
                  status: conversation.status,
                  taskSummary: conversation.summary,
                  lastActive: conversation.updatedAt,
                  updatedAt: conversation.updatedAt,
                  currentPhase: conversation.status,
                };
                const sessionIsBusy = isBusyPhase(session.currentPhase || session.status);
                const renamePending =
                  renameSessionMutation.isPending &&
                  renameSessionMutation.variables?.sessionId === session.id;
                const isEditingTitle = editingSessionId === session.id;
                const itemError = sessionComposerErrors[session.id] ?? "";
                const deleteBusyReason = sessionIsBusy ? t("deleteSessionBusy") : "";
                const itemMessage = itemError || deleteBusyReason;
                const itemIsNotice = itemError
                  ? itemError.startsWith(t("addSessionToReviewSucceeded"))
                  : Boolean(deleteBusyReason);
                const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
                const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
                const sessionAgentMeta = sessionAgentMetaLabel(session);
                const missingAgentMessage = session.agentMissing
                  ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，当前会话缺少可运行内容。" : "Missing valid Agent. This session has no runnable Agent content.")
                  : "";
                const sessionIsChild = isChildSession(session);
                const sessionTitle = sessionListTitle(session) || sessionDisplay.name;
                const sessionSummary =
                  (sessionIsChild ? (session.resultCard?.summary || session.taskSummary) : session.taskSummary)
                  || (sessionIsChild
                    ? (lang === "zh" ? "子对话独立工作中" : "Independent child session")
                    : (lang === "zh" ? "暂无摘要" : "No summary yet"));
                return (
                  <DirectSessionIndexItem
                    key={session.id}
                    active={!groupPanelActive && activeSessionId === session.id}
                    editing={isEditingTitle}
                    editingTitle={editingSessionTitle}
                    itemMessage={itemMessage}
                    itemIsNotice={itemIsNotice}
                    missingAgentMessage={missingAgentMessage}
                    renamePending={renamePending}
                    session={session}
                    sessionAvatarFallback={avatarInitials(session.agentCode, sessionTitle)}
                    sessionAvatarImageUrl={sessionAvatarImageUrl}
                    sessionDisplay={sessionDisplay}
                    sessionSummary={sessionSummary}
                    sessionTitle={sessionTitle}
                    lang={lang}
                    statusLabel={statusLabel}
                    formatTime={formatTime}
                    t={t}
                    onCancelRename={cancelRenameSession}
                    onContextMenu={openSessionContextMenu}
                    onDragStart={(event) =>
                      startSessionReferenceDrag(
                        event,
                        buildSessionReferencePayload(session, sessionAgentMeta || sessionDisplay.name, sessionSummary),
                      )}
                    onOpen={handleOpenDirectSession}
                    onRenameTitleChange={setEditingSessionTitle}
                    onSubmitRename={submitRenameSession}
                  />
                );
              })}
                      </div>
                    ) : null}
                  </section>
                );
              }) : null}
              {filteredTeams.length ? (
                <section className={`${styles.conversationGroup} ${styles.teamTreeGroup}`}>
                  <button
                    type="button"
                    className={styles.conversationGroupHeader}
                    onClick={() => toggleConversationGroup("teams")}
                    aria-expanded={searchHasTerm || !collapsedConversationGroups.teams}
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                    <span>{conversationGroupLabel("teams", lang === "zh" ? "zh" : "en")}</span>
                    <strong>{filteredTeams.length}</strong>
                  </button>
                  {searchHasTerm || !collapsedConversationGroups.teams ? (
                    <div className={styles.conversationGroupList}>
                    {filteredTeams.map((team) => {
                      const roomId = String(team.linkedChatRoomId ?? "").trim();
                      const teamRoute = `/teams?team=${encodeURIComponent(team.teamId)}`;
                      return (
                        <TeamConversationIndexItem
                          key={team.teamId}
                          active={Boolean(roomId && activeGroupRoomId === roomId)}
                          lang={lang}
                          roomId={roomId}
                          team={team}
                          teamRoute={teamRoute}
                          statusLabel={statusLabel}
                          onOpen={handleOpenGroupRoom}
                        />
                      );
                    })}
                    </div>
                  ) : null}
                </section>
              ) : null}
              {filteredStandaloneGroupConversations.length ? (
                <section className={styles.conversationGroup}>
                  <button
                    type="button"
                    className={styles.conversationGroupHeader}
                    onClick={() => toggleConversationGroup("standaloneGroups")}
                    aria-expanded={searchHasTerm || !collapsedConversationGroups.standaloneGroups}
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                    <span>{conversationGroupLabel("standaloneGroups", lang === "zh" ? "zh" : "en")}</span>
                    <strong>{filteredStandaloneGroupConversations.length}</strong>
                  </button>
                  {searchHasTerm || !collapsedConversationGroups.standaloneGroups ? (
                    <div className={styles.conversationGroupList}>
                    {filteredStandaloneGroupConversations.map((conversation) => {
                      const roomId = conversation.roomId || conversation.conversationId;
                      return (
                        <GroupConversationIndexItem
                          key={`standalone-group-${roomId}`}
                          active={activeGroupRoomId === roomId}
                          conversation={conversation}
                          kindLabel={lang === "zh" ? "群" : "Group"}
                          fallbackSummary={lang === "zh" ? "未绑定团队的群聊" : "Group without a Team"}
                          lang={lang}
                          roomId={roomId}
                          statusLabel={statusLabel}
                          formatTime={formatTime}
                          onOpen={handleOpenGroupRoom}
                        />
                      );
                    })}
                    </div>
                  ) : null}
                </section>
              ) : null}
              {sessionIndexHasMore ? (
                <button
                  type="button"
                  className={styles.sessionLoadMoreButton}
                  onClick={() => rawSessionsQuery.loadMore()}
                  disabled={rawSessionsQuery.isLoadingMore}
                  aria-label={sessionIndexLoadMoreLabel}
                >
                  <span>{sessionIndexLoadMoreLabel}</span>
                  <strong>{sessionIndexProgressLabel}</strong>
                </button>
              ) : null}
              {sessionContextMenu && contextMenuSession && sessionContextMenuStyle ? (
                <div
                  className={styles.sessionContextMenu}
                  style={sessionContextMenuStyle}
                  role="menu"
                  aria-label={lang === "zh" ? "会话操作" : "Session actions"}
                  onPointerDown={(event) => event.stopPropagation()}
                >
                  <button
                    type="button"
                    role="menuitem"
                    className={styles.sessionContextMenuItem}
                    onClick={() => handleAddSessionToReview(contextMenuSession)}
                    disabled={contextMenuAddToReviewDisabled}
                    title={
                      contextMenuAddToReviewPending
                        ? t("addingSessionToReview")
                        : contextMenuAddToReviewDisabled
                          ? t("addSessionToReviewBusy")
                          : t("addSessionToReview")
                    }
                  >
                    <BookPlus size={14} />
                    <span>{contextMenuAddToReviewPending ? t("addingSessionToReview") : t("addSessionToReview")}</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className={styles.sessionContextMenuItem}
                    onClick={() => beginRenameSession(contextMenuSession)}
                  >
                    <Pencil size={14} />
                    <span>{t("renameSession")}</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className={`${styles.sessionContextMenuItem} ${styles.sessionContextMenuDanger}`}
                    onClick={() => handleDeleteSession(contextMenuSession)}
                    disabled={contextMenuDeleteDisabled}
                    title={contextMenuDeleteDisabled ? t("deleteSessionBusy") : t("deleteSession")}
                  >
                    <Trash2 size={14} />
                    <span>{t("deleteSession")}</span>
                  </button>
                </div>
              ) : null}
              </>
            )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
