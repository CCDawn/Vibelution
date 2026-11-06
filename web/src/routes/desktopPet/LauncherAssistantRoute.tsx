import "../../design/route-css/desktop-pet.tailwind.css";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, setLauncherAssistantModel,
  hideLauncherAssistant, sendLauncherAssistantMessage, setLauncherAssistantExpanded,
  launcherConversationApi,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  previewLauncherDispatchApproval, decideLauncherDispatchApproval, declineLauncherDispatchSummary, launcherDispatchDeclineRevisionIsValid, type LauncherDispatchApprovalPreview,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn, switchLauncherAssistantHead,
  regenerateLauncherAssistantMessage, guideLauncherAssistantTurn,
  getLauncherOperatorAsset, getLauncherAssistantAvatar, openLauncherFromAssistant, uploadLauncherAttachment,
  uploadLauncherUserSecret,
  readLauncherAttachment, subscribeLauncherAssistantSessionEvent,
  launcherAssistantBudgetQueryKey,
} from "../../api/launcherAssistant";
import { openLauncherModelConnection } from "../../api/launcher";
import type { ConversationMessage, SessionDetail, SessionReferenceAttachment } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import type { SessionToolApprovalRequest } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import { FollowupQueueTogglePauseContext } from "../../components/conversation/ConversationFollowupQueueBar";
import { useLauncherAssistantFollowupQueue } from "./useLauncherAssistantFollowupQueue";
import { LauncherAssistantWelcome } from "./LauncherAssistantWelcome";
import { LauncherAssistantQuestionCard } from "./LauncherAssistantQuestionCard";
import { VButton, VDenseOpsPage, VNativeButton, VStateSurface } from "../../components/vui";
import { ChatComposerPlusMenu, type ChatComposerSecretAttachmentInput } from "../chat/ChatComposerPlusMenu";
import { LauncherAssistantModelControl } from "./LauncherAssistantModelControl";
import { useShellI18n } from "../../i18n/useShellI18n";
import { hasExecutionOwnership, resolveSessionActivity, sessionActivityStatusLabel } from "../sessionActivityState";
import { continuationSnapshotKey, resolveConversationContinuation } from "../chat/conversationContinuationModel";
import { resolveSessionStopTurnId } from "../chat/chatStopTurnModel";
import { resolveChatUserDisplayName } from "../chatCompactPanel";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence, readbackSubmitAcceptance } from "../chat/chatSubmitAcceptanceReadback";
import { acceptSessionSubmit, beginSessionSubmit, isLocalQueuedSubmit, mergeSessionSubmitDetail, removeSessionSubmitPaint, sameSubmittedReferenceSnapshot } from "../chat/sessionSubmitProjection";
import { sessionReferenceId } from "../chat/chatComposerSubmitModel";
import { appendStoredPromptHistoryEntry } from "../../components/conversation/conversationPromptHistory";
import { applyOptimisticRegenerate, markSessionDetailStopping, clearSessionDetailStopping, type OptimisticUserMessageInput } from "../chatSessionState";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import {
  beginDesktopPetDrag, desktopPetWindowDragBridge, updateDesktopPetDrag,
  type DesktopPetDragPoint, type DesktopPetDragState, type DesktopPetWindowDragBridge
} from "./desktopPetWindowDrag";
import { DEFAULT_PET_PREFERENCES } from "./desktopPetPreferences";
import { ChatToolApprovalDialog } from "../chat/ChatToolApprovalDialog";
import { toolApprovalRiskLabel } from "../chat/toolApprovalLabels";
import { agentArchivePreviewIsValid, agentPurgePreviewIsValid, autonomyActionIsKnown, autonomyApprovalPreviewIsValid, authorizationUpgradePreviewIsValid, browserInteractPreviewIsValid, dispatchWritePreviewIsValid, launcherAgentCreatePreviewIsValid, operatorImageUploadPreviewIsValid, preferenceProposalPreviewIsValid, projectLifecyclePreviewIsValid, recoveryPreviewIsValid, managementApprovalActionIsKnown, platformManagementActionIsKnown, platformManagementPreviewIsValid, toolApprovalActionPreview, toolApprovalDisplayName } from "../chat/toolApprovalPreview";
import { providerModelApprovalPreviewIsValid } from "../chat/providerApprovalPreview";
import { agentConfigurationApprovalActionIsKnown, agentConfigurationApprovalPreviewIsValid } from "../chat/agentConfigurationApprovalPreview";
import { launcherTeamActionIsKnown, launcherTeamPreviewIsValid, launcherTeamActionPreview, launcherTeamActionTitle } from "./teamManagementApprovalPreview";
import { useLauncherThemeControl } from "./useLauncherThemeControl";
import { readStoredWorkbenchTheme, requestWorkbenchTheme, subscribeWorkbenchThemeSync, useAuthorityTheme } from "../../app/themePreference";
import { PersonalAssistantComputerPanel } from "../personalAssistant/PersonalAssistantComputerPanel";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import { useLauncherComputerAccess } from "./useLauncherComputerAccess";
import petStyles from "./DesktopAssistantRoute.styles";
import { useLauncherAttachmentHistory } from "./useLauncherAttachmentHistory";
import { applyComposerAttachmentUploadOutcomes, classifyComposerFiles, mergeComposerAttachmentsWithRejections, type ComposerAttachmentUploadOutcome, type ComposerImageAttachment } from "../chat/chatComposerSubmitModel";
import {
  launcherAssistantActivity, launcherAssistantMessageOverLimit, launcherAssistantPollInterval, launcherAssistantSubmission,
  launcherAssistantQueueReadback, launcherAssistantQueueLabel, launcherAssistantRequestReadback,
  launcherAssistantLifecycleClosing, launcherAssistantSendBusyCode, launcherAssistantSendDefinitelyRejected, launcherAssistantSendRetryableBusy,
  launcherAssistantSseHealthy,
  launcherAssistantStatusDegradeTone, launcherAssistantWaitInterval, launcherAssistantContextRing, launcherAssistantModelDisplay,
  launcherAssistantEditBackfillDraft,
  type LauncherAssistantSubmission, type LauncherAssistantQueuedAcceptance, type LauncherAssistantQuestionDraft,
} from "./launcherAssistantModel";
import { activeTurnLayerToConversationMessage, createLauncherAssistantStream } from "./launcherAssistantStream";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { loadLauncherComposer, restoreLauncherComposerAttachments, saveLauncherComposer, type PersistedLauncherContinuation } from "./launcherAssistantComposerStorage";
import { readLauncherAssistantTaskSource } from "./launcherAssistantTaskReads";
import { readLauncherManagementStatus, useLauncherManagementPermission } from "./useLauncherManagementPermission";
import { LauncherManagementPermissionControl } from "./LauncherManagementPermissionControl";
import { useLauncherAssistantBudget } from "./useLauncherAssistantBudget";
import { composerCacheUsageQueryKey, useComposerCacheUsage } from "../chat/useComposerCacheUsage";
import { agentPurgeBatchPreviewIsValid, launcherAgentPurgeBatchActionPreview } from "./launcherAgentPurgeBatchPreview";
import { usePublishLauncherNotices } from "../../app/LauncherNotifications";
import { launcherAssistantPageNotices, launcherNoticeReadFailed } from "./launcherAssistantPageNotices";
import { useLauncherTasks } from "./assistantTasks/LauncherTaskContext";
import { resolveLauncherApprovalTarget, useLauncherApprovalTarget } from "./launcherAssistantApprovalTarget";

const COPY = {
  zh: {
    title: "个人助理", expand: "展开个人助理聊天", chat: "聊一聊", hide: "隐藏个人助理",
    collapse: "收起聊天", loading: "正在打开对话…", unavailable: "个人助理暂不可用", conversationUnavailable: "暂时无法加载对话",
    retry: "重试", refresh: "刷新", placeholder: "和个人助理聊一聊…", send: "发送", sending: "正在发送…",
    unknownSend: "尚未确认消息是否收到。输入已保留，重试会核对同一条消息。",
    sendRejected: "本次发送已被拒绝，未进入对话；请修改后重新发送。",
    sendBusy: "助理正忙（如迁移、停止中或会话已切换），请稍后重试",
    tooLong: "消息超出 64,000 字上限，请精简后再发送。",
    imageUnsupported: "当前模型不支持图片输入，请移除图片附件后再发送。",
    receipts: "任务状态暂不可用", checking: "正在连接 Launcher…",
    waitingBackend: "正在等待工作台后端启动…",
    lifecycleClosing: "助理已随上一次退出停止，正在恢复；若长时间停留请重启应用。",
    statusStale: "个人助理状态轮询暂不可用，会话内容可能未更新",
    statusDelayed: "状态刷新延迟，会话内容可能未更新",
    editAsNew: "编辑为新消息",
    safeGuidance: "引导", safeGuidancePending: "正在引导",
    interruptGuidance: "打断并引导", interruptGuidancePending: "正在打断引导",
  },
  en: {
    title: "Personal assistant", expand: "Open assistant chat", chat: "Chat", hide: "Hide assistant",
    collapse: "Collapse chat", loading: "Opening conversation…", unavailable: "Assistant unavailable", conversationUnavailable: "Conversation could not be loaded",
    retry: "Retry", refresh: "Refresh", placeholder: "Chat with your assistant…", send: "Send", sending: "Sending…",
    unknownSend: "Delivery is unconfirmed. Your input is retained; retry checks the same message.",
    sendRejected: "This send was rejected and never entered the conversation; edit and send again.",
    sendBusy: "Assistant is busy (migrating, stopping, or the session changed); try again shortly",
    tooLong: "Message exceeds the 64,000-character limit; shorten it before sending.",
    imageUnsupported: "The current model does not support image input; remove image attachments before sending.",
    receipts: "Task status unavailable", checking: "Connecting to Launcher…",
    waitingBackend: "Waiting for the workbench backend…",
    lifecycleClosing: "The assistant stopped with the previous exit and is recovering; restart the app if this persists.",
    statusStale: "Assistant status polling is unavailable; conversation content may be stale",
    statusDelayed: "Status refresh is delayed; conversation content may be stale",
    editAsNew: "Edit as new message",
    safeGuidance: "Steer", safeGuidancePending: "Steering",
    interruptGuidance: "Interrupt & steer", interruptGuidancePending: "Interrupting steer",
  },
} as const;

/** Aligns with PERSONAL_ASSISTANT_DISPATCH_LIMIT: bound the receipt history the
 * route keeps and scans for pending approvals. */
const LAUNCHER_ASSISTANT_DISPATCH_LIMIT = 50;

function approvalAcceptDisabled(request: SessionToolApprovalRequest): boolean {
  const summary = request.argumentSummary;
  return request.toolName === "personal_assistant_manage_tool" && (!(managementApprovalActionIsKnown(summary?.assistantAction) || launcherTeamActionIsKnown(summary?.assistantAction) || summary?.assistantAction === "agent_purge_batch") || Boolean(summary.assistantArgumentsInvalid)
    || (autonomyActionIsKnown(summary?.assistantAction) || Object.hasOwn(summary || {}, "assistantAutonomyPreviewVersion")) && !autonomyApprovalPreviewIsValid(summary)
    || platformManagementActionIsKnown(summary?.assistantAction) && !platformManagementPreviewIsValid(summary)
    || (summary?.assistantAction === "provider_model_resolve" || Object.hasOwn(summary || {}, "assistantProviderPreviewVersion")) && !providerModelApprovalPreviewIsValid(summary)
    || agentConfigurationApprovalActionIsKnown(summary?.assistantAction) && !agentConfigurationApprovalPreviewIsValid(summary)
    || launcherTeamActionIsKnown(summary?.assistantAction) && !launcherTeamPreviewIsValid(summary)
    || summary?.assistantAction === "agent_create" && !launcherAgentCreatePreviewIsValid(summary)
    || summary?.assistantAction === "agent_purge" && !agentPurgePreviewIsValid(summary)
    || summary?.assistantAction === "agent_purge_batch" && !agentPurgeBatchPreviewIsValid(summary)
    || summary?.assistantAction === "agent_archive" && !agentArchivePreviewIsValid(summary)
    || summary?.assistantAction === "authorization_upgrade" && !authorizationUpgradePreviewIsValid(summary)
    || summary?.assistantAction === "dispatch_write" && !dispatchWritePreviewIsValid(summary)
    || summary?.assistantAction === "project_lifecycle" && !projectLifecyclePreviewIsValid(summary)
    || summary?.assistantAction === "operator_image_upload" && !operatorImageUploadPreviewIsValid(summary)
    || summary?.assistantAction === "browser_interact" && !browserInteractPreviewIsValid(summary)
    || ["preference_proposal_accept", "preference_proposal_reject"].includes(String(summary?.assistantAction)) && !preferenceProposalPreviewIsValid(summary)
    || summary?.assistantAction === "reminder_handoff_recover" && !recoveryPreviewIsValid(summary));
}

// Decode only JSON string tokens: parsing and reserializing the whole object
// would round large integers. Escape invisible direction controls for review.
function readableApprovalJson(source: string): string {
  return source.replace(/"(?:\\.|[^"\\])*"/g, token => JSON.stringify(JSON.parse(token))
    .replace(/[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`));
}

type ComposerSnapshot = { draft: string; outstanding: LauncherAssistantSubmission | null; acceptedTurnId: string; queuedAcceptance: LauncherAssistantQueuedAcceptance | null; continuation?: PersistedLauncherContinuation; attachments?: ComposerImageAttachment[]; references?: SessionReferenceAttachment[]; questionDraft?: LauncherAssistantQuestionDraft | null };

/** One assistant tool receipt asking the operator to attach a private
 * credential (a `secret_request` action result). */
export type AssistantSecretRequest = { purpose: string; label?: string; key: string };

/** The latest assistant turn's newest tool receipt decides whether the composer
 * should surface a private-attachment request. Receipt JSON rides the canonical
 * `tool_call` item's `output` string; anything else — no assistant turn yet, a
 * newer user reply, a different action, or an unparseable/truncated output —
 * means no request, never a partial banner. `key` is the turn+item identity, so
 * ignoring one exact receipt stays quiet while a newer request re-arms. */
export function resolveAssistantSecretRequest(detail: SessionDetail | undefined): AssistantSecretRequest | null {
  const messages = detail?.messages || [];
  let latestAssistantIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") { latestAssistantIndex = index; break; }
  }
  if (latestAssistantIndex < 0) return null;
  const latestAssistant = messages[latestAssistantIndex]!;
  if (latestAssistant.role !== "assistant") return null;
  // A user message after the request means the conversation moved on: the
  // composer tray (or a plain reply) already answered it, so never resurrect.
  if (messages.slice(latestAssistantIndex + 1).some(message => message.role === "user")) return null;
  const items = latestAssistant.turnItems || [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]!;
    if (item.type !== "tool_call") continue;
    let receipt: unknown;
    try { receipt = JSON.parse(String(item.output ?? "")); } catch { return null; }
    if (!receipt || typeof receipt !== "object") return null;
    const record = receipt as Record<string, unknown>;
    if (record.action !== "secret_request" || record.status !== "awaiting_user_attachment") return null;
    const purpose = typeof record.purpose === "string" ? record.purpose.trim() : "";
    if (!purpose) return null;
    const label = typeof record.label === "string" && record.label.trim() ? record.label.trim() : undefined;
    return { purpose, label, key: `${latestAssistant.turnId}:${item.itemId || item.id}` };
  }
  return null;
}

export function LauncherAssistantRoute({ embedded = false, navigationOwned = false, computerRequested = false, entryIntent }: {
  embedded?: boolean; navigationOwned?: boolean; computerRequested?: boolean;
  entryIntent?: { key: string; title: string; label: string; message: string };
}) {
  useLauncherThemeControl();
  const client = useQueryClient();
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const taskNoticeOwner = useLauncherTasks();
  const approvalNavigation = useLauncherApprovalTarget();
  // The Launcher control surface embeds the assistant page fully expanded; the
  // native floating window keeps its collapsed pet stage until the operator
  // explicitly expands it.
  const [expanded, setExpanded] = useState(embedded);
  const [themeSyncState, setThemeSyncState] = useState<"applied" | "local" | "conflict" | "unknown" | "unavailable">("applied");
  const [themePending, setThemePending] = useState(false);
  const themeGate = useRef(false);
  useEffect(() => subscribeWorkbenchThemeSync(setThemeSyncState), []);
  const [computerOpen, setComputerOpen] = useState(computerRequested);
  const [dismissedEntry, setDismissedEntry] = useState("");
  useEffect(() => { if (computerRequested) setComputerOpen(true); }, [computerRequested]);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [epoch, setEpoch] = useState(0);
  const epochRef = useRef(0);
  const mounted = useRef(true);
  // Restore the lifetime guard before query observers subscribe again during
  // StrictMode effect replay; otherwise the first guarded read aborts locally.
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const sending = useRef<{ submission: LauncherAssistantSubmission } | null>(null);
  const requestReadbackGate = useRef(false);
  const resizing = useRef(false);
  const outstanding = useRef<LauncherAssistantSubmission | null>(null);
  const [draft, setDraft] = useState("");
  const [questionDraft, setQuestionDraft] = useState<(LauncherAssistantQuestionDraft & { sessionId: string }) | null>(null);
  const questionDraftRef = useRef(questionDraft);
  const [answeredQuestion, setAnsweredQuestion] = useState<{ sessionId: string; id: string; turnId: string } | null>(null);
  const [attachments, setAttachments] = useState<ComposerImageAttachment[]>([]);
  const [visibleMessageIds, setVisibleMessageIds] = useState<string[]>([]);
  const attachmentsRef = useRef<ComposerImageAttachment[]>([]);
  const [composerReferences, setComposerReferences] = useState<SessionReferenceAttachment[]>([]);
  const composerReferencesRef = useRef<SessionReferenceAttachment[]>([]);
  const uploadGate = useRef(false);
  const draftRef = useRef("");
  const dragStateRef = useRef<DesktopPetDragState | null>(null);
  const dragBridgeRef = useRef<DesktopPetWindowDragBridge | null>(desktopPetWindowDragBridge());
  const pendingDragPointRef = useRef<DesktopPetDragPoint | null>(null);
  const dragFrameRef = useRef<number | null>(null);
  const nativeDragActiveRef = useRef(false);
  const suppressClickRef = useRef(false);
  const [sendPending, setSendPending] = useState(false);
  const [resizePending, setResizePending] = useState(false);
  const [sendUnconfirmed, setSendUnconfirmed] = useState(false);
  const [continuationUnconfirmed, setContinuationUnconfirmed] = useState(false);
  const [recoverySaveFailed, setRecoverySaveFailed] = useState(false);
  // The unknown-outcome state keeps the backend's own message (bounded) next to
  // the conservative banner instead of silently discarding it.
  const [sendUnknownDetail, setSendUnknownDetail] = useState("");
  const [feedback, setFeedback] = useState("");
  const launcherGate = useRef(false);
  const [launcherPending, setLauncherPending] = useState(false);
  const [acceptedTurnId, setAcceptedTurnId] = useState("");
  const [queuedAcceptance, setQueuedAcceptance] = useState<LauncherAssistantQueuedAcceptance | null>(null);
  const approvalGate = useRef(false);
  const [approvalPending, setApprovalPending] = useState(false);
  const [approvalError, setApprovalError] = useState("");
  const [boundPreview, setBoundPreview] = useState<{ key: string; value: LauncherDispatchApprovalPreview } | null>(null);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [previewError, setPreviewError] = useState<{ key: string; message: string } | null>(null);
  const [decidedDispatchKey, setDecidedDispatchKey] = useState("");
  const controlGate = useRef(false);
  const refreshedTerminal = useRef<{ sessionId: string; turnId: string } | null>(null);
  const [controlPendingMode, setControlPendingMode] = useState<"" | "stop" | "continue">("");
  const controlPending = Boolean(controlPendingMode);
  // First-failure timestamp of the never-succeeded status read. query.state only
  // exposes the LAST error time, and the backoff must grow across failures, so
  // the wait start is held here and reset once any status read succeeds.
  const backendWaitStartedAt = useRef<number | null>(null);
  const status = useQuery({
    queryKey: ["launcher-assistant", "status"], queryFn: () => readLauncherManagementStatus(() =>
      client.getQueryData(["launcher-assistant", "status"])),
    retry: false, staleTime: 0,
    refetchInterval: query => {
      // Cold boot: before the first successful status read, keep probing for the
      // workbench backend with a backoff cadence so a late backend start is
      // joined without any manual refresh.
      if (!query.state.data) return launcherAssistantWaitInterval(backendWaitStartedAt.current, Date.now());
      return expanded && visible ? 10_000 : false;
    },
  });
  const managementPermission = useLauncherManagementPermission(status.data, lang);
  useEffect(() => {
    backendWaitStartedAt.current = status.isError && !status.data
      ? backendWaitStartedAt.current ?? Date.now()
      : null;
  }, [status.isError, status.data]);
  // Consecutive failed status polls. react-query resets its own failure counter
  // on every new fetch attempt, so the debounce count lives here: each new
  // error timestamp bumps it, any success resets it, and the state update
  // re-renders the banner region so the degrade tone tracks the current count.
  const [statusFailures, setStatusFailures] = useState(0);
  const statusOutcome = useRef("");
  useEffect(() => {
    const outcome = status.isError ? `e${status.errorUpdatedAt}` : `s${status.dataUpdatedAt}`;
    if (outcome === statusOutcome.current) return;
    statusOutcome.current = outcome;
    setStatusFailures(current => status.isError ? current + 1 : 0);
  }, [status.isError, status.errorUpdatedAt, status.dataUpdatedAt]);
  const sessionId = status.data?.assistant.directSessionId || "";
  const budget = useLauncherAssistantBudget(sessionId, status.data?.assistant.agentId || "", lang);
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const reading = expanded && visible && Boolean(sessionId);
  const observingOwnSession = visible && Boolean(sessionId);
  const readingAssets = reading && status.data?.operatorAssetsVersion === 1;
  const assetQueryPrefix = ["launcher-assistant", "operator-asset"];
  const assetRevisions = status.data?.operatorAssetRevisions;
  const previousAssetRevisions = useRef<{ sessionId: string; avatar: string | null; background: string | null } | null>(null);
  useEffect(() => {
    if (!sessionId) { previousAssetRevisions.current = null; return; }
    if (!assetRevisions) {
      if (previousAssetRevisions.current?.sessionId !== sessionId) previousAssetRevisions.current = null;
      return;
    }
    const previous = previousAssetRevisions.current;
    previousAssetRevisions.current = { sessionId, ...assetRevisions };
    if (!previous || previous.sessionId !== sessionId) return;
    for (const kind of ["avatar", "background"] as const) {
      if (previous[kind] !== assetRevisions[kind]) {
        void client.invalidateQueries({ queryKey: ["launcher-assistant", "operator-asset", kind, sessionId], exact: true });
      }
    }
  }, [client, sessionId, assetRevisions?.avatar, assetRevisions?.background]);
  const avatar = useQuery({
    queryKey: [...assetQueryPrefix, "avatar", sessionId],
    queryFn: ({ signal }) => getLauncherOperatorAsset("avatar", { signal }),
    enabled: readingAssets, retry: false, staleTime: Infinity,
  });
  const background = useQuery({
    queryKey: [...assetQueryPrefix, "background", sessionId],
    queryFn: ({ signal }) => getLauncherOperatorAsset("background", { signal }),
    enabled: readingAssets, retry: false, staleTime: Infinity,
  });
  const assistantAvatarPrefix = ["launcher-assistant", "assistant-avatar"];
  const assistantAgentId = status.data?.assistant.agentId || "";
  const readingAssistantAvatar = reading && status.data?.assistantAvatarVersion === 1 && Boolean(assistantAgentId);
  const assistantAvatar = useQuery({
    queryKey: [...assistantAvatarPrefix, sessionId, assistantAgentId, status.data?.assistantAvatarRevision],
    queryFn: ({ signal }) => getLauncherAssistantAvatar(assistantAgentId, { signal }),
    enabled: readingAssistantAvatar, retry: false, staleTime: 0,
  });
  useEffect(() => {
    if (readingAssistantAvatar) return;
    void client.cancelQueries({ queryKey: ["launcher-assistant", "assistant-avatar"] });
    void client.invalidateQueries({ queryKey: ["launcher-assistant", "assistant-avatar"], refetchType: "none" });
  }, [client, readingAssistantAvatar]);
  useEffect(() => () => {
    void client.cancelQueries({ queryKey: ["launcher-assistant", "assistant-avatar"] });
    void client.invalidateQueries({ queryKey: ["launcher-assistant", "assistant-avatar"], refetchType: "none" });
  }, [client]);
  const composerKey = ["launcher-assistant", "composer", sessionId];
  const detailKey = ["launcher-assistant", "detail", sessionId];
  const submitReadbackRuntime = {
    detailQueryKey: (id: string) => ["launcher-assistant", "detail", id],
    readDetail: async (id: string, signal: AbortSignal) => {
      signal.throwIfAborted();
      const result = await getLauncherAssistantDetail(id);
      signal.throwIfAborted();
      return result;
    },
    mergeDetail: mergeSessionSubmitDetail,
  };
  function submissionPaint(submission: LauncherAssistantSubmission): OptimisticUserMessageInput {
    return { sessionId, clientSubmissionId: submission.requestId, content: submission.message,
      attachmentIds: submission.attachmentIds, references: submission.references,
      attachments: attachmentsRef.current.filter(item => submission.attachmentSnapshotIds?.includes(item.id) && item.artifactId).map(item => ({
        artifactId: item.artifactId!, filename: item.file.name, contentType: item.file.type,
        sizeBytes: item.file.size, kind: item.kind === "secret" ? "user_secret" : item.kind === "image" ? "user_image" : "user_document", status: "ready",
        url: "", imageUrl: "", downloadUrl: "",
      })) };
  }
  function saveComposer(patch: Partial<ComposerSnapshot>) {
    client.setQueryDefaults(composerKey, { gcTime: Infinity });
    const previous = client.getQueryData<ComposerSnapshot>(composerKey);
    const next = { draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null, ...previous, ...patch };
    const persisted = saveLauncherComposer(sessionId, embedded ? "embedded" : "floating", next);
    client.setQueryData<ComposerSnapshot>(composerKey, next);
    setRecoverySaveFailed(!persisted);
    return persisted;
  }
  function acceptQuestionAnswer(submission: LauncherAssistantSubmission): Partial<ComposerSnapshot> {
    const question = submission.answerQuestion;
    if (!question || sessionIdRef.current !== sessionId) return {};
    setAnsweredQuestion({ sessionId, id: question.id, turnId: question.turnId });
    const current = questionDraftRef.current;
    if (current?.sessionId !== sessionId || current.question.id !== question.id
      || current.question.turnId !== question.turnId || current.value.trim() !== submission.message) return {};
    questionDraftRef.current = null;
    setQuestionDraft(null);
    return { questionDraft: null };
  }
  useEffect(() => {
    if (!sessionId) return;
    const key = ["launcher-assistant", "composer", sessionId];
    const cached = client.getQueryData<ComposerSnapshot>(key);
    const stored = cached ? null : loadLauncherComposer(sessionId, embedded ? "embedded" : "floating");
    const saved: ComposerSnapshot | null = cached ?? (stored
      ? { ...stored, attachments: restoreLauncherComposerAttachments(stored.attachments) }
      : null);
    if (!cached && saved) {
      client.setQueryDefaults(key, { gcTime: Infinity });
      client.setQueryData<ComposerSnapshot>(key, saved);
    }
    draftRef.current = saved?.draft || "";
    setDraft(draftRef.current);
    attachmentsRef.current = (saved?.attachments || []).map(item => item.uploadStatus === "uploading" ? { ...item, uploadStatus: "pending" } : item);
    setAttachments(attachmentsRef.current);
    composerReferencesRef.current = saved?.references || [];
    setComposerReferences(composerReferencesRef.current);
    outstanding.current = saved?.outstanding || null;
    // A transport callback from the previous Session may still arrive. Its
    // durable outstanding request remains with that Session, but it must not
    // keep this Session's answer locked or retire a newer flight.
    sending.current = null;
    setSendPending(false);
    setSendUnknownDetail("");
    setFeedback("");
    const recoveredQuestionDraft = saved?.questionDraft ?? (saved?.outstanding?.answerQuestion
      ? { question: saved.outstanding.answerQuestion, value: saved.outstanding.message } : null);
    questionDraftRef.current = recoveredQuestionDraft ? { ...recoveredQuestionDraft, sessionId } : null;
    setQuestionDraft(questionDraftRef.current);
    setAnsweredQuestion(null);
    setSendUnconfirmed(Boolean(saved?.outstanding));
    setContinuationUnconfirmed(Boolean(saved?.continuation && !saved.continuation.accepted));
    setRecoverySaveFailed(false);
    setAcceptedTurnId(saved?.acceptedTurnId || "");
    setQueuedAcceptance(saved?.queuedAcceptance || null);
  }, [client, sessionId, embedded]);
  // Restored chips start with an empty preview (the blob: URL is unrecoverable);
  // refill each from its already-uploaded artifact through the read IPC, so a
  // reload keeps the tray usable without re-uploading anything. Secret chips
  // are skipped: their `sec_` reference has no readable bytes here, and the
  // read verb must never become a value-fetch channel.
  useEffect(() => {
    if (!sessionId || status.data?.attachmentVersion !== 1) return;
    const targets = attachmentsRef.current.flatMap(item =>
      item.uploadStatus === "uploaded" && item.kind !== "secret" && item.artifactId && !item.previewUrl ? [{ id: item.id, artifactId: item.artifactId }] : []);
    if (!targets.length) return;
    let active = true;
    void (async () => {
      for (const target of targets) {
        try {
          const previewUrl = await readLauncherAttachment(target.artifactId);
          if (!active || sessionIdRef.current !== sessionId) return;
          if (!attachmentsRef.current.some(item => item.id === target.id && !item.previewUrl)) continue;
          updateAttachments(attachmentsRef.current.map(item => item.id === target.id ? { ...item, previewUrl } : item));
        } catch { /* a chip keeps its filename without a thumbnail; sending still works */ }
      }
    })();
    return () => { active = false; };
  }, [sessionId, status.data?.attachmentVersion]);
  // Last host-pushed session event (any type, heartbeats included). A ref, not
  // state: react-query reads it on each interval computation and an event must
  // never re-render the page by itself. Null when no push channel ever spoke,
  // which keeps the 2s active cadence bit-for-bit identical to a shell without it.
  const sseAliveAt = useRef<number | null>(null);
  // The key deliberately excludes the visibility/epoch counter: swapping the key
  // drops the cached conversation for a frame, `{detail.data ? ...}` flips to
  // the loading shell and unmounts the chat view (resetting its expansion
  // state). A visibility restore refreshes this query in place instead.
  const detail = useQuery({
    queryKey: ["launcher-assistant", "detail", sessionId],
    queryFn: async ({ signal }) => {
      const result = await getLauncherAssistantDetail(sessionId);
      signal.throwIfAborted();
      return mergeSessionSubmitDetail(client.getQueryData<SessionDetail>(["launcher-assistant", "detail", sessionId]), result);
    },
    // A hidden window must keep the self-healing readback alive for an
    // outstanding send, so these are states (not the outstanding ref): an
    // in-flight send or an epoch-preempted ACK can land while already hidden.
    enabled: observingOwnSession || sendPending || sendUnconfirmed, retry: false,
    refetchInterval: query => {
      const continuation = client.getQueryData<ComposerSnapshot>(composerKey)?.continuation;
      const requests = [outstanding.current?.requestId, continuation && !continuation.accepted ? continuation.requestId : ""]
        .filter((id): id is string => Boolean(id));
      // The enabled query supplies one recovery read. Missing data alone is
      // not a reason for an idle/error loop without known outstanding work.
      if (!query.state.data && !acceptedTurnId && !queuedAcceptance && !requests.length) return false;
      return launcherAssistantPollInterval(observingOwnSession, query.state.data, acceptedTurnId, queuedAcceptance, requests,
        { sseHealthy: launcherAssistantSseHealthy(sseAliveAt.current, Date.now()) });
    },
    // Interval refetches pause in the background by default; an outstanding
    // send opts in so the hidden-window fallback poll (the 10s readback) runs.
    refetchIntervalInBackground: sendPending || sendUnconfirmed,
  });
  const sessionStream = useMemo(() => createLauncherAssistantStream(sessionId), [sessionId]);
  const [activeLayer, setActiveLayer] = useState<ActiveTurnLayerState>();
  const latestDetail = useRef(detail.data);
  latestDetail.current = detail.data;
  const historyGate = useRef(false);
  const [earlierMessagesLoading, setEarlierMessagesLoading] = useState(false);
  async function loadEarlierMessages() {
    const cursor = latestDetail.current?.messageWindow?.nextBeforeMessageIndex;
    if (historyGate.current || !sessionId || !cursor) return;
    historyGate.current = true;
    setEarlierMessagesLoading(true);
    try {
      const page = await getLauncherAssistantDetail(sessionId, cursor);
      if (mounted.current && sessionIdRef.current === sessionId) {
        client.setQueryData<SessionDetail>(["launcher-assistant", "detail", sessionId], previous => mergeSessionDetailMessageWindow(previous, page));
      }
    } catch (error) { if (mounted.current && sessionIdRef.current === sessionId) setFeedback(errorMessage(error)); }
    finally { historyGate.current = false; if (mounted.current) setEarlierMessagesLoading(false); }
  }
  useEffect(() => {
    if (!observingOwnSession) return;
    let active = true;
    let refreshEpoch = 0;
    // Capability-detected: an older shell yields null and nothing changes. Any
    // frame proves the channel alive; only this session's authoritative snapshot
    // (or a delta that explicitly finished) invalidates detail, after which the
    // existing full-detail readback effects below re-run unchanged. Bursts are
    // left to react-query's own dedupe; the host already throttles snapshots.
    const unsubscribe = subscribeLauncherAssistantSessionEvent(event => {
      if (!active) return;
      sseAliveAt.current = Date.now();
      if (event.sessionId !== sessionId) return;
      const incomingEpoch = event.connectionEpoch ?? 0;
      const changedEpoch = incomingEpoch > refreshEpoch;
      refreshEpoch = Math.max(refreshEpoch, incomingEpoch);
      const result = sessionStream.apply(event, latestDetail.current);
      setActiveLayer(result.layer);
      // The stream owns stale/retired-epoch rejection as well as refresh needs.
      if (!result.needsRefresh) return;
      const filter = { queryKey: ["launcher-assistant", "detail", sessionId], exact: true };
      const refresh = () => client.invalidateQueries(filter, { cancelRefetch: false });
      if (changedEpoch) {
        // Even the initial no-cache read predates this connection. Discard its
        // result before starting a new read; same-epoch bursts reuse that read.
        void client.cancelQueries(filter).then(() => {
          if (active && refreshEpoch === incomingEpoch) return refresh();
        });
      } else {
        void refresh();
      }
    });
    if (!unsubscribe) return;
    return () => { active = false; unsubscribe(); };
  }, [client, observingOwnSession, sessionId, sessionStream]);
  useEffect(() => {
    setActiveLayer(detail.data ? sessionStream.reconcile(detail.data) : undefined);
  }, [detail.data, detail.dataUpdatedAt, sessionStream]);
  useEffect(() => {
    const submission = outstanding.current;
    const recovered = submission && launcherAssistantRequestReadback(detail.data, submission.requestId);
    if (!submission || !recovered) return;
    appendStoredPromptHistoryEntry(submission.message);
    client.setQueryData<SessionDetail>(detailKey, previous => acceptSessionSubmit(previous, submissionPaint(submission), {
      turnId: recovered.turnId, queuedTurnId: recovered.queuedAcceptance?.id,
    }));
    setActiveLayer(sessionStream.acceptSubmission(submission.requestId, recovered.turnId, Boolean(recovered.queuedAcceptance)));
    // A collapse may invalidate the transport ACK epoch. Only exact native
    // submission evidence may retire that original request, preserving new B.
    outstanding.current = null;
    if (sending.current?.submission === submission) {
      sending.current = null;
      setSendPending(false);
    }
    clearAcceptedAttachments(submission);
    clearAcceptedReferences(submission);
    const remainingDraft = !submission.preserveDraft && draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
    draftRef.current = remainingDraft;
    saveComposer({ draft: remainingDraft, outstanding: null, acceptedTurnId: recovered.turnId,
      queuedAcceptance: recovered.queuedAcceptance, ...acceptQuestionAnswer(submission) });
    setDraft(remainingDraft);
    setAcceptedTurnId(recovered.turnId);
    setQueuedAcceptance(recovered.queuedAcceptance);
    setSendUnconfirmed(false);
  }, [client, detail.data, sessionId]);
  const terminalTurnId = detail.data?.lastTurnTerminalTurnId?.trim() || "";
  const terminalOutcome = detail.data ? resolveSessionActivity(detail.data).outcome : "";
  useEffect(() => {
    if (!observingOwnSession || !terminalTurnId || !terminalOutcome) return;
    if (refreshedTerminal.current?.sessionId === sessionId && refreshedTerminal.current.turnId === terminalTurnId) return;
    refreshedTerminal.current = { sessionId, turnId: terminalTurnId };
    // Native tools can update identity/preferences during a Turn. Refresh their
    // owning query once that exact Turn settles, without introducing idle polls.
    void client.invalidateQueries({ queryKey: ["launcher-assistant", "status"], exact: true });
    void client.invalidateQueries({ queryKey: queryKeys.configPublic(), exact: true });
    void client.invalidateQueries({ queryKey: [launcherConversationApi.cacheKey, "config"], exact: true });
    void client.invalidateQueries({ queryKey: ["launcher-assistant", "operator-asset"] });
    void client.invalidateQueries({ queryKey: launcherAssistantBudgetQueryKey(status.data?.assistant.agentId || "", sessionId), exact: true });
  }, [client, observingOwnSession, sessionId, terminalOutcome, terminalTurnId]);
  const approvals = useQuery({
    queryKey: ["launcher-assistant", "approvals", sessionId, epoch],
    queryFn: async ({ signal }) => {
      const result = await getLauncherAssistantApprovals(sessionId);
      signal.throwIfAborted();
      return result;
    },
    enabled: reading, retry: false,
    refetchInterval: query => query.state.data?.some(request => request.status === "pending") && reading
      ? 2_000 : launcherAssistantPollInterval(reading, detail.data, acceptedTurnId, queuedAcceptance),
    refetchIntervalInBackground: false,
  });
  const approval = approvals.data?.find(request => request.status === "pending"
    && request.sessionId === sessionId && request.agentId === status.data?.assistant.agentId);
  const queueReadback = launcherAssistantQueueReadback(detail.data, queuedAcceptance);
  useEffect(() => {
    if (queueReadback.receipt === queuedAcceptance && !queueReadback.admittedTurnId) return;
    setQueuedAcceptance(queueReadback.receipt);
    if (queueReadback.admittedTurnId) setAcceptedTurnId(queueReadback.admittedTurnId);
    client.setQueryData<ComposerSnapshot>(["launcher-assistant", "composer", sessionId], previous => previous ? {
      ...previous, queuedAcceptance: queueReadback.receipt,
      acceptedTurnId: queueReadback.admittedTurnId || previous.acceptedTurnId,
    } : previous);
  }, [client, queueReadback.receipt, queueReadback.admittedTurnId, queuedAcceptance, sessionId]);

  useEffect(() => {
    if (!acceptedTurnId || (detail.data?.activeTurnId !== acceptedTurnId && detail.data?.lastTurnTerminalTurnId !== acceptedTurnId)) return;
    setAcceptedTurnId("");
    client.setQueryData<ComposerSnapshot>(["launcher-assistant", "composer", sessionId], previous => previous
      ? { ...previous, acceptedTurnId: "" } : previous);
  }, [acceptedTurnId, client, detail.data?.activeTurnId, detail.data?.lastTurnTerminalTurnId, sessionId]);
  useEffect(() => {
    const saved = client.getQueryData<ComposerSnapshot>(["launcher-assistant", "composer", sessionId]);
    const attempt = saved?.continuation;
    if (!detail.data || !attempt || attempt.accepted) return;
    const evidence = findSubmitAcceptanceEvidence(detail.data, attempt.requestId);
    const turnId = evidence ? exactAcceptedSubmitTurnId(detail.data, attempt.requestId, evidence) : "";
    if (!turnId) return;
    if (attempt.expected.agentId !== assistantAgentId) return;
    saveComposer({ continuation: { ...attempt, accepted: true }, acceptedTurnId: turnId });
    setContinuationUnconfirmed(false);
    setAcceptedTurnId(turnId);
    setFeedback("");
  }, [client, detail.data, sessionId]);
  const dispatchReadIdentity = JSON.stringify([assistantAgentId, sessionId, epoch]);
  const readableDispatch = useRef("");
  readableDispatch.current = reading ? dispatchReadIdentity : "";
  const dispatches = useQuery({
    queryKey: ["launcher-assistant", "dispatches", assistantAgentId, sessionId, epoch],
    queryFn: async ({ signal }) => {
      const result = await readLauncherAssistantTaskSource(JSON.stringify([assistantAgentId, sessionId]), signal,
        getLauncherAssistantDispatches, () => mounted.current && document.visibilityState !== "hidden"
          && readableDispatch.current === dispatchReadIdentity);
      signal.throwIfAborted();
      // Same 50-row ceiling as the personal-assistant dispatch feed; the host
      // request shape owns no limit field, so the route bounds what it retains.
      return result.slice(0, LAUNCHER_ASSISTANT_DISPATCH_LIMIT);
    },
    enabled: reading, retry: false,
    refetchInterval: query => reading && query.state.data?.some(row => row.receipt?.shouldPoll)
      ? 2_000 : launcherAssistantPollInterval(reading, detail.data),
    refetchIntervalInBackground: false,
  });
  // The native approval dialog owns global shortcuts, so show exactly one
  // request at a time and give the assistant's own session priority.
  const selectedApprovalTarget = embedded ? approvalNavigation?.target : null;
  const dispatchApproval = approval ? undefined : selectedApprovalTarget
    ? resolveLauncherApprovalTarget(selectedApprovalTarget, dispatches.isError ? [] : dispatches.data ?? [], assistantAgentId, sessionId)
    : dispatches.data?.flatMap(row => (row.receipt?.pendingApprovals ?? []).map(request => ({ row, request })))[0];
  const dispatchPreviewKey = dispatchApproval && reading ? JSON.stringify([epoch, dispatchApproval.row.dispatchId,
    dispatchApproval.row.nativeTaskId, dispatchApproval.row.agentId, dispatchApproval.request.approvalId, dispatchApproval.request.toolName,
    selectedApprovalTarget?.nonce]) : "";
  useEffect(() => {
    let active = true;
    setBoundPreview(null);
    setPreviewError(null);
    if (dispatchApproval && dispatchPreviewKey) {
      void previewLauncherDispatchApproval(dispatchApproval.row, dispatchApproval.request).then(value => {
        if (active) setBoundPreview({ key: dispatchPreviewKey, value });
      }).catch(() => { if (active) setPreviewError({ key: dispatchPreviewKey, message: lang === "zh" ? "完整操作暂不可核对，请刷新回执。" : "Complete action preview unavailable; refresh the receipt." }); });
    }
    return () => { active = false; };
    // The scalar key captures identity without restarting on receipt polling.
  }, [dispatchPreviewKey, previewAttempt, lang]);
  const activeDispatchPreview = boundPreview?.key === dispatchPreviewKey && reading ? boundPreview.value : null;
  const activePreviewError = previewError?.key === dispatchPreviewKey && reading ? previewError.message : "";
  const canDeclineSummary = Boolean(dispatchApproval && activePreviewError && !approvalError
    && decidedDispatchKey !== dispatchPreviewKey && dispatchApproval.request.availableDecisions.includes("decline")
    && launcherDispatchDeclineRevisionIsValid(dispatchApproval.request.revision));

  useEffect(() => {
    // The transparent pet root belongs to the floating window only; the
    // Launcher control surface owns its own document chrome.
    if (!embedded) {
      document.documentElement.dataset.vibelutionDesktopPet = "true";
      document.body.dataset.vibelutionDesktopPet = "true";
    }
    function visibilityChanged() {
      const next = document.visibilityState !== "hidden";
      setVisible(next);
      if (next) {
        void status.refetch();
        // Refresh content in place: the detail key stays stable, because a key
        // swap drops the cached conversation for a frame and unmounts the chat
        // view (expansion state reset with it). The counter below only retires
        // in-flight transport ACKs and refreshes the small auxiliary queries.
        void client.invalidateQueries({ queryKey: ["launcher-assistant", "detail"] });
      }
      if (outstanding.current) setSendUnconfirmed(true);
      epochRef.current += 1;
      setEpoch(epochRef.current);
    }
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      epochRef.current += 1;
      document.removeEventListener("visibilitychange", visibilityChanged);
      if (!embedded) {
        delete document.documentElement.dataset.vibelutionDesktopPet;
        delete document.body.dataset.vibelutionDesktopPet;
      }
      finishWindowDrag();
      // Window lifecycle never owns a native turn or a dispatched task.
    };
    // embedded is a mount-time host constant (floating window vs Launcher page).
  }, [embedded]);

  function flushWindowDrag() {
    dragFrameRef.current = null;
    const point = pendingDragPointRef.current;
    pendingDragPointRef.current = null;
    if (point !== null && nativeDragActiveRef.current) {
      dragBridgeRef.current?.moveDesktopPetWindowDrag(point);
    }
  }

  function queueWindowDrag(point: DesktopPetDragPoint) {
    pendingDragPointRef.current = point;
    if (dragFrameRef.current === null) {
      dragFrameRef.current = window.requestAnimationFrame(flushWindowDrag);
    }
  }

  function finishWindowDrag(finalPoint?: DesktopPetDragPoint) {
    if (finalPoint) {
      pendingDragPointRef.current = finalPoint;
    }
    if (dragFrameRef.current !== null) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = null;
    }
    flushWindowDrag();
    if (nativeDragActiveRef.current) {
      dragBridgeRef.current?.endDesktopPetWindowDrag();
      nativeDragActiveRef.current = false;
    }
  }

  function beginCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    suppressClickRef.current = false;
    dragStateRef.current = beginDesktopPetDrag(event.pointerId, {
      screenX: event.screenX,
      screenY: event.screenY,
    });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const current = dragStateRef.current;
    if (current === null) {
      return;
    }
    const update = updateDesktopPetDrag(current, event.pointerId, {
      screenX: event.screenX,
      screenY: event.screenY,
    });
    if (update === null) {
      return;
    }
    dragStateRef.current = update.state;
    if (!current.moved && update.state.moved) {
      suppressClickRef.current = true;
    }
    if (update.delta !== null) {
      event.preventDefault();
      const bridge = dragBridgeRef.current;
      if (!nativeDragActiveRef.current && bridge !== null) {
        bridge.beginDesktopPetWindowDrag(current.start);
        nativeDragActiveRef.current = true;
      }
      if (nativeDragActiveRef.current) {
        queueWindowDrag({ screenX: event.screenX, screenY: event.screenY });
      }
    }
  }

  function endCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const current = dragStateRef.current;
    if (current === null || current.pointerId !== event.pointerId) {
      return;
    }
    dragStateRef.current = null;
    finishWindowDrag({ screenX: event.screenX, screenY: event.screenY });
  }

  function cancelCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    endCharacterDrag(event);
    suppressClickRef.current = false;
  }

  function characterClicked() {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    void openLauncher();
  }

  async function toggle() {
    // The embedded Launcher page never resizes a host window and never collapses.
    if (embedded || resizing.current || !status.data) return;
    resizing.current = true;
    setResizePending(true);
    setFeedback("");
    const requestEpoch = epochRef.current;
    try {
      await setLauncherAssistantExpanded(!expanded);
      if (!mounted.current || requestEpoch !== epochRef.current) return;
      epochRef.current += 1;
      setEpoch(epochRef.current);
      setExpanded(!expanded);
      if (expanded) {
        // Collapse cancels in-flight image reads and marks them stale without
        // starting an IPC request. Reopening reads the current native choice.
        void client.cancelQueries({ queryKey: assetQueryPrefix });
        void client.invalidateQueries({ queryKey: assetQueryPrefix, refetchType: "none" });
      }
      if (!expanded) void status.refetch();
      if (sending.current) setSendUnconfirmed(true);
    } catch (error) {
      if (mounted.current && requestEpoch === epochRef.current) setFeedback(errorMessage(error));
    } finally {
      resizing.current = false;
      if (mounted.current) setResizePending(false);
    }
  }

  async function hide() {
    // The embedded Launcher page has no window to hide.
    if (embedded) return;
    try { await hideLauncherAssistant(); }
    catch (error) { if (mounted.current) setFeedback(errorMessage(error)); }
  }

  async function openLauncher() {
    if (launcherGate.current) return;
    launcherGate.current = true;
    setLauncherPending(true);
    setFeedback("");
    try { await openLauncherFromAssistant(); }
    catch (error) { if (mounted.current) setFeedback(errorMessage(error)); }
    finally { launcherGate.current = false; if (mounted.current) setLauncherPending(false); }
  }

  const modelConfigGate = useRef(false);
  const [modelConfigPending, setModelConfigPending] = useState(false);
  async function openModelConnection() {
    if (modelConfigGate.current) return;
    modelConfigGate.current = true;
    setModelConfigPending(true);
    setFeedback("");
    try { await openLauncherModelConnection(); }
    catch (error) { if (mounted.current) setFeedback(errorMessage(error)); }
    finally { modelConfigGate.current = false; if (mounted.current) setModelConfigPending(false); }
  }
  async function changeModel(modelId: string) {
    if (modelConfigGate.current || !modelId || hasExecutionOwnership(resolveSessionActivity(latestDetail.current || {}).execution)) return;
    modelConfigGate.current = true;
    setModelConfigPending(true);
    setFeedback("");
    try {
      await setLauncherAssistantModel(modelId);
      await status.refetch();
      void client.invalidateQueries({ queryKey: [launcherConversationApi.cacheKey, "config"], exact: true });
    } catch (error) { if (mounted.current) setFeedback(errorMessage(error)); }
    finally { modelConfigGate.current = false; if (mounted.current) setModelConfigPending(false); }
  }

  const historyAttachments = useLauncherAttachmentHistory(detail.data?.messages || [], sessionId, reading && status.data?.attachmentVersion === 1, visibleMessageIds);

  function updateAttachments(next: ComposerImageAttachment[]) {
    attachmentsRef.current = next;
    setAttachments(next);
    saveComposer({ attachments: next });
  }
  function clearAcceptedAttachments(submission: LauncherAssistantSubmission) {
    const accepted = new Set(submission.attachmentSnapshotIds || []);
    if (!accepted.size) return;
    const remaining = attachmentsRef.current.filter(item => {
      if (!accepted.has(item.id)) return true;
      URL.revokeObjectURL(item.previewUrl);
      return false;
    });
    updateAttachments(remaining);
  }
  function addAttachments(files: FileList | File[]) {
    if (status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || uploadGate.current) return;
    const incoming = classifyComposerFiles(files);
    const merged = mergeComposerAttachmentsWithRejections(attachmentsRef.current, incoming.accepted);
    merged.rejected.forEach(item => URL.revokeObjectURL(item.previewUrl));
    updateAttachments(merged.attachments);
    if (incoming.rejected.length || merged.rejected.length) setFeedback(lang === "zh" ? "部分附件类型不支持、过大或超过数量限制。" : "Some attachments are unsupported, too large, or exceed the limit.");
    else setFeedback("");
  }
  // Privacy attachments: the dialog plaintext goes straight to the closed IPC
  // verb and only the `sec_` reference returns. The chip below carries the
  // masked display name and that reference — never the value — and is already
  // "uploaded", so submit includes sec_x in attachmentIds without any re-upload.
  const MAX_SECRET_ATTACHMENTS = 4;
  // Assistant `secret_request` receipts surface as a one-click banner near the
  // composer. Suppressed three ways: the operator dismissed that exact receipt,
  // a secret chip is already staged, or the receipt aged out of the newest
  // conversational position (resolveAssistantSecretRequest). A successful
  // attach retires the current request even if the chip is removed later.
  const resolvedSecretRequest = useMemo(() => resolveAssistantSecretRequest(detail.data), [detail.data]);
  const [dismissedSecretRequestKeys, setDismissedSecretRequestKeys] = useState<string[]>([]);
  useEffect(() => { setDismissedSecretRequestKeys([]); }, [sessionId]);
  const secretRequest = resolvedSecretRequest
    && !dismissedSecretRequestKeys.includes(resolvedSecretRequest.key)
    && !attachments.some(item => item.kind === "secret")
    ? resolvedSecretRequest : null;
  function dismissSecretRequest() {
    if (!resolvedSecretRequest) return;
    setDismissedSecretRequestKeys(current => current.includes(resolvedSecretRequest.key)
      ? current : [...current, resolvedSecretRequest.key]);
  }
  async function addSecretAttachment(input: ChatComposerSecretAttachmentInput): Promise<void> {
    if (status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || uploadGate.current) {
      throw new Error(lang === "zh" ? "当前不能添加隐私附件，请稍后再试。" : "A private attachment cannot be added right now.");
    }
    if (attachmentsRef.current.filter(item => item.kind === "secret").length >= MAX_SECRET_ATTACHMENTS) {
      throw new Error(lang === "zh" ? `隐私附件最多 ${MAX_SECRET_ATTACHMENTS} 个，请先移除一个再添加。` : `Up to ${MAX_SECRET_ATTACHMENTS} private attachments; remove one first.`);
    }
    const { attachmentId } = await uploadLauncherUserSecret(input.value, input.label);
    // Staged: retire the request banner too, durably (the chip alone would
    // resurrect the banner if the operator removed it before sending).
    dismissSecretRequest();
    // No display name falls back to the same generic mask label the history
    // bubble side uses for a label-less user_secret attachment.
    const displayName = (input.label || "").trim() || (lang === "zh" ? "隐私附件" : "Private attachment");
    const chipLabel = lang === "zh" ? `隐私 · ${displayName}` : `Private · ${displayName}`;
    updateAttachments([...attachmentsRef.current, {
      id: crypto.randomUUID(),
      file: new File([], chipLabel, { type: "application/octet-stream" }),
      filename: chipLabel,
      previewUrl: "",
      sizeBytes: 0,
      contentType: "application/octet-stream",
      kind: "secret",
      uploadStatus: "uploaded",
      artifactId: attachmentId,
    }]);
  }
  function removeAttachment(id: string) {
    if (sendPending || sendUnconfirmed || uploadGate.current) return;
    const item = attachmentsRef.current.find(row => row.id === id);
    if (item) URL.revokeObjectURL(item.previewUrl);
    updateAttachments(attachmentsRef.current.filter(row => row.id !== id));
  }
  // Reference chips (selection-quote message quotes today; session/knowledge
  // candidates await a session-list IPC verb). Same dedupe and cap as the chat
  // composer: six per turn, keyed by the reference's own id.
  function composerReferenceId(reference: SessionReferenceAttachment): string {
    return sessionReferenceId(reference);
  }
  function updateComposerReferences(next: SessionReferenceAttachment[]) {
    composerReferencesRef.current = next;
    setComposerReferences(next);
    saveComposer({ references: next });
  }
  function addComposerReference(reference: SessionReferenceAttachment) {
    if (sendPending || sendUnconfirmed || controlPending) return;
    const referenceId = composerReferenceId(reference);
    if (!referenceId) return;
    if (composerReferencesRef.current.some(item => composerReferenceId(item) === referenceId)) return;
    updateComposerReferences([...composerReferencesRef.current, reference].slice(-6));
  }
  function removeComposerReference(referenceId: string) {
    if (sendPending || sendUnconfirmed || controlPending) return;
    updateComposerReferences(composerReferencesRef.current.filter(item => composerReferenceId(item) !== referenceId));
  }
  function clearAcceptedReferences(submission: LauncherAssistantSubmission) {
    const sent = submission.references;
    if (!sent?.length) return;
    updateComposerReferences(composerReferencesRef.current.filter(item => !sent.some(reference => sameSubmittedReferenceSnapshot(item, reference))));
  }
  async function uploadAttachments(onlyId?: string): Promise<boolean> {
    if (uploadGate.current || status.data?.attachmentVersion !== 1 || !sessionId) return false;
    const uploadSessionId = sessionId;
    const targets = attachmentsRef.current.filter(item => (!onlyId || item.id === onlyId) && !(item.uploadStatus === "uploaded" && item.artifactId));
    if (!targets.length) return true;
    uploadGate.current = true;
    setSendPending(true);
    const ids = new Set(targets.map(item => item.id));
    updateAttachments(attachmentsRef.current.map(item => ids.has(item.id) ? { ...item, uploadStatus: "uploading" } : item));
    const results = await Promise.allSettled(targets.map(item => uploadLauncherAttachment(item.file)));
    const outcomes: ComposerAttachmentUploadOutcome[] = results.map((result, index) => result.status === "fulfilled"
      ? { id: targets[index].id, status: "uploaded", artifactId: result.value }
      : { id: targets[index].id, status: "failed", error: result.reason });
    const updateOutcomes = (items: ComposerImageAttachment[]) => applyComposerAttachmentUploadOutcomes(items, outcomes);
    if (sessionIdRef.current !== uploadSessionId || !mounted.current) {
      client.setQueryData<ComposerSnapshot>(["launcher-assistant", "composer", uploadSessionId], previous => previous
        ? { ...previous, attachments: updateOutcomes(previous.attachments || []) } : previous);
      uploadGate.current = false;
      if (mounted.current) setSendPending(false);
      return false;
    }
    updateAttachments(updateOutcomes(attachmentsRef.current));
    uploadGate.current = false;
    setSendPending(false);
    const failed = results.some(result => result.status === "rejected");
    if (failed) setFeedback(lang === "zh" ? "附件上传失败，请重试。" : "Attachment upload failed; retry.");
    else setFeedback("");
    return !failed;
  }

  async function submit(prepared?: LauncherAssistantSubmission): Promise<boolean> {
    if (sending.current || requestReadbackGate.current || uploadGate.current || controlGate.current || continuationUnconfirmed || !sessionId
      || (prepared && outstanding.current)
      || (!prepared && attachmentsRef.current.length > 0 && status.data?.attachmentVersion !== 1)) return false;
    // Pre-flight checks only gate a NEW submission: an unconfirmed retry resends
    // its original, already-validated request verbatim. They run before any
    // upload so a doomed send never consumes attachment uploads.
    if (!outstanding.current) {
      if (launcherAssistantMessageOverLimit(prepared ? prepared.message : draftRef.current.trim())) {
        setFeedback(copy.tooLong);
        return false;
      }
      if (!prepared && attachmentsRef.current.some(item => item.kind === "image") && status.data?.settings?.supportsImageInput === false) {
        setFeedback(copy.imageUnsupported);
        return false;
      }
    }
    if (!prepared && !outstanding.current && attachmentsRef.current.length && !(await uploadAttachments())) return false;
    const priorSubmission = outstanding.current;
    if (priorSubmission) {
      requestReadbackGate.current = true;
      try {
        const readback = await readbackSubmitAcceptance(client, sessionId, priorSubmission.requestId, submitReadbackRuntime);
        if (!mounted.current || sessionIdRef.current !== sessionId || outstanding.current !== priorSubmission) return true;
        if (readback.status === "readback_failed" || launcherAssistantRequestReadback(client.getQueryData<SessionDetail>(detailKey), priorSubmission.requestId)) return false;
      } finally { requestReadbackGate.current = false; }
    }
    const snapshot = attachmentsRef.current;
    const submission = prepared ?? launcherAssistantSubmission(outstanding.current, draftRef.current, undefined,
      snapshot.map(item => item.artifactId || "").filter(Boolean), snapshot.map(item => item.id),
      composerReferencesRef.current);
    if (!submission) return false;
    outstanding.current = submission;
    if (!saveComposer({ draft: draftRef.current, outstanding: submission })) {
      outstanding.current = priorSubmission;
      saveComposer({ outstanding: priorSubmission });
      // Restoring the smaller prior snapshot does not recover the rejected send.
      setRecoverySaveFailed(true);
      return false;
    }
    const paint = submissionPaint(submission);
    const beforeSubmitDetail = client.getQueryData<SessionDetail>(detailKey);
    client.setQueryData<SessionDetail>(detailKey, previous => beginSessionSubmit(previous, paint, busy));
    const paintedDetail = client.getQueryData<SessionDetail>(detailKey);
    if (!busy) setActiveLayer(sessionStream.beginSubmission(submission.requestId));
    const flight = { submission };
    sending.current = flight;
    setSendPending(true);
    setSendUnconfirmed(false);
    setSendUnknownDetail("");
    setFeedback("");
    const requestEpoch = epochRef.current;
    try {
      const acceptance = await sendLauncherAssistantMessage(submission.message, submission.requestId,
        submission.attachmentIds, submission.references);
      if (!mounted.current || requestEpoch !== epochRef.current || sending.current !== flight || outstanding.current !== submission) return true;
      client.setQueryData<SessionDetail>(detailKey, previous => acceptSessionSubmit(previous, paint, acceptance));
      setActiveLayer(sessionStream.acceptSubmission(submission.requestId, acceptance.turnId, Boolean(acceptance.queuedTurnId)));
      appendStoredPromptHistoryEntry(submission.message);
      outstanding.current = null;
      clearAcceptedAttachments(submission);
      clearAcceptedReferences(submission);
      const queueReceipt = acceptance.queuedTurnId ? { id: acceptance.queuedTurnId, clientSubmissionId: acceptance.clientSubmissionId, observed: false } : null;
      const remainingDraft = !submission.preserveDraft && draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
      draftRef.current = remainingDraft;
      saveComposer({ draft: remainingDraft, outstanding: null, acceptedTurnId: acceptance.turnId,
        queuedAcceptance: queueReceipt, ...acceptQuestionAnswer(submission) });
      setAcceptedTurnId(acceptance.turnId);
      setQueuedAcceptance(queueReceipt);
      setDraft(remainingDraft);
      setSendUnconfirmed(false);
      void detail.refetch();
      void dispatches.refetch();
      void approvals.refetch();
    } catch (error) {
      if (mounted.current && requestEpoch === epochRef.current && sending.current === flight && outstanding.current === submission) {
        if (launcherAssistantSendDefinitelyRejected(error)) {
          removeSessionSubmitPaint(client, detailKey, paint, { previous: beforeSubmitDetail, optimistic: paintedDetail });
          setActiveLayer(sessionStream.rejectSubmission(submission.requestId));
          // A provable pre-admission refusal left nothing queued, so the
          // conservative unconfirmed lock would only dead-end the composer.
          // Draft and tray stay editable for an immediate corrected resend.
          outstanding.current = null;
          saveComposer({ outstanding: null });
          setSendUnconfirmed(false);
          setFeedback(copy.sendRejected);
        } else if (launcherAssistantSendRetryableBusy(error)) {
          removeSessionSubmitPaint(client, detailKey, paint, { previous: beforeSubmitDetail, optimistic: paintedDetail });
          setActiveLayer(sessionStream.rejectSubmission(submission.requestId));
          // These host codes are pre-admission quiescence gates (the native
          // layer asks callers to retain and retry) or the idempotent 409
          // session-changed conflict: nothing is executing, so a verbatim
          // retry with the same requestId is safe and the unconfirmed lock
          // would only dead-end the composer. The draft stays for that retry.
          outstanding.current = null;
          saveComposer({ outstanding: null });
          setSendUnconfirmed(false);
          setSendUnknownDetail("");
          const code = launcherAssistantSendBusyCode(error);
          setFeedback(code ? `${copy.sendBusy} (${code})` : copy.sendBusy);
        } else {
          setSendUnconfirmed(true);
          setSendUnknownDetail(boundedErrorDetail(error));
          // Confirm the original request through this surface's IPC reader;
          // shared evidence rules never mistake local paint for admission.
          await readbackSubmitAcceptance(client, sessionId, submission.requestId, submitReadbackRuntime);
        }
      }
    } finally {
      // Native readback can retire this flight before its RPC returns. A late
      // callback owns neither that acceptance nor a newer request's busy flag.
      if (sending.current === flight) {
        sending.current = null;
        if (mounted.current) setSendPending(false);
      }
    }
    return true;
  }

  const computerAccess = useLauncherComputerAccess({
    detail: detail.data, agentId: status.data?.assistant.agentId || "", reading,
    manualOpen: computerOpen, onCloseManual: () => setComputerOpen(false),
    lang,
  });

  async function decide(request: SessionToolApprovalRequest, decision: "accept" | "decline") {
    if (approvalGate.current || request.requestId !== approval?.requestId || !request.availableDecisions.includes(decision)
      || decision === "accept" && (approvalAcceptDisabled(request) || approvalAcceptDisabled(approval))) return;
    approvalGate.current = true;
    setApprovalPending(true);
    setApprovalError("");
    try {
      const resolved = await resolveLauncherAssistantApproval(request, decision);
      if (mounted.current) client.setQueryData<SessionToolApprovalRequest[]>(["launcher-assistant", "approvals", sessionId, epoch], previous => previous?.map(row => row.requestId === resolved.requestId ? resolved : row));
    } catch (error) {
      if (mounted.current) setApprovalError(errorMessage(error));
    } finally {
      approvalGate.current = false;
      if (mounted.current) {
        setApprovalPending(false);
        void approvals.refetch();
        void detail.refetch();
      }
    }
  }

  async function decideDispatch(decision: "accept" | "decline") {
    const selected = dispatchApproval;
    const preview = activeDispatchPreview;
    if (!selected || approvalGate.current || !selected.request.availableDecisions.includes(decision)
      || (!preview && (decision !== "decline" || !canDeclineSummary)) || decidedDispatchKey === dispatchPreviewKey) return;
    approvalGate.current = true;
    setApprovalPending(true);
    setApprovalError("");
    setDecidedDispatchKey(dispatchPreviewKey);
    setBoundPreview(null);
    try {
      if (preview) await decideLauncherDispatchApproval(selected.row, selected.request, preview, decision);
      else await declineLauncherDispatchSummary(selected.row, selected.request);
      if (selectedApprovalTarget) approvalNavigation?.dismiss(selectedApprovalTarget.nonce);
    } catch {
      // A failed decision releases the dialog lock immediately: both buttons
      // recover for a direct retry while the error card keeps explaining the
      // failure, and the preview is re-read for a possibly renewed revision.
      if (mounted.current) {
        setApprovalError(lang === "zh" ? "审批结果未确认，请刷新回执核对。" : "Approval outcome is unconfirmed; refresh the receipt.");
        setDecidedDispatchKey("");
        setPreviewAttempt(value => value + 1);
      }
    } finally {
      approvalGate.current = false;
      if (mounted.current) {
        setApprovalPending(false);
        void dispatches.refetch();
      }
    }
  }

  async function stopTurn() {
    if (controlGate.current || !detail.data || !hasExecutionOwnership(resolveSessionActivity(detail.data).execution)) return;
    const turnId = resolveSessionStopTurnId(detail.data, acceptedTurnId);
    if (!turnId) return;
    controlGate.current = true;
    setControlPendingMode("stop");
    setFeedback("");
    const previous = client.getQueryData<SessionDetail>(detailKey);
    const requestedAt = new Date().toISOString();
    client.setQueryData<SessionDetail>(detailKey, current => markSessionDetailStopping(current, { requestedAt }));
    try {
      const next = await stopLauncherAssistantTurn(sessionId, turnId);
      if (mounted.current && sessionIdRef.current === sessionId) {
        client.setQueryData<SessionDetail>(detailKey, current => mergeSessionSubmitDetail(current, next));
      }
    } catch (error) {
      if (mounted.current && sessionIdRef.current === sessionId) {
        client.setQueryData<SessionDetail>(detailKey, current => current ? clearSessionDetailStopping(current, { requestedAt, previous }) : current);
        setFeedback(errorMessage(error));
      }
    } finally {
      controlGate.current = false;
      if (mounted.current) { setControlPendingMode(""); void detail.refetch(); }
    }
  }

  async function continueTurn() {
    if (controlGate.current || requestReadbackGate.current || sending.current || draft.trim() || outstanding.current) return;
    const previous = client.getQueryData<ComposerSnapshot>(composerKey)?.continuation;
    if (previous && !previous.accepted) {
      if (previous.expected.agentId !== assistantAgentId) return;
      requestReadbackGate.current = true;
      try {
        const readback = await readbackSubmitAcceptance(client, sessionId, previous.requestId, submitReadbackRuntime);
        if (!mounted.current || sessionIdRef.current !== sessionId || readback.status === "readback_failed") return;
        if (readback.evidence && exactAcceptedSubmitTurnId(client.getQueryData<SessionDetail>(detailKey), previous.requestId, readback.evidence)) return;
      } finally { requestReadbackGate.current = false; }
    }
    const expected = resolveConversationContinuation(detail.data, sessionId);
    if (!expected && (!previous || previous.accepted)) return;
    // A lost ACK is reconciled before considering any newer eligible head.
    // Native admission replays this original request before validating today's
    // snapshot, so replacing its UUID would create a distinct continuation.
    const attempt = previous && (!previous.accepted || (expected && continuationSnapshotKey(previous.expected) === continuationSnapshotKey(expected)))
      ? previous : { requestId: crypto.randomUUID(), expected: expected!, accepted: false };
    if (attempt.accepted) return;
    if (!saveComposer({ continuation: attempt })) return;
    controlGate.current = true;
    setControlPendingMode("continue");
    setFeedback("");
    try {
      const accepted = await continueLauncherAssistantTurn(attempt.expected, attempt.requestId);
      if (!mounted.current || sessionIdRef.current !== sessionId) return;
      saveComposer({ continuation: { ...attempt, accepted: true }, acceptedTurnId: accepted.turnId });
      setActiveLayer(sessionStream.acceptSubmission(attempt.requestId, accepted.turnId));
      setContinuationUnconfirmed(false);
      if (mounted.current) setAcceptedTurnId(accepted.turnId);
    } catch (error) {
      if (mounted.current && sessionIdRef.current === sessionId) {
        setContinuationUnconfirmed(true); setFeedback(errorMessage(error));
        await readbackSubmitAcceptance(client, sessionId, attempt.requestId, submitReadbackRuntime);
      }
    } finally {
      controlGate.current = false;
      if (mounted.current) { setControlPendingMode(""); void detail.refetch(); }
    }
  }

  const [switchHeadPending, setSwitchHeadPending] = useState(false);
  async function switchMessageVersion(message: ConversationMessage, targetNodeId: string) {
    if (controlGate.current || !detail.data || !sessionId) return;
    const nodeId = String(targetNodeId || "").trim();
    if (!nodeId || nodeId === String(message.nodeId || "").trim()) return;
    // Same busy gate as the chat baseline: a running or stopping turn owns the
    // head, and the native service would refuse the switch with a conflict.
    if (busy || stopping) return;
    controlGate.current = true;
    setSwitchHeadPending(true);
    setFeedback("");
    try {
      await client.cancelQueries({ queryKey: detailKey, exact: true });
      const next = await switchLauncherAssistantHead(sessionId, nodeId);
      if (!mounted.current || sessionIdRef.current !== sessionId) return;
      // A head switch republishes the whole active path; replace the cached
      // window wholesale instead of merging earlier pages from the old branch.
      client.setQueryData<SessionDetail>(["launcher-assistant", "detail", sessionId], next);
    } catch (error) {
      if (mounted.current) setFeedback(errorMessage(error));
    } finally {
      controlGate.current = false;
      if (mounted.current) { setSwitchHeadPending(false); void detail.refetch(); }
    }
  }

  // The latest assistant answer a regenerate action may rerun: the last
  // assistant message that has a user message before it (chat-page baseline).
  const regenerableAssistantMessageId = (() => {
    const messages = detail.data?.messages || [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role !== "assistant") continue;
      const hasUserBefore = messages.slice(0, index).some(entry => entry.role === "user");
      return hasUserBefore ? messages[index].id : "";
    }
    return "";
  })();
  const [regeneratePending, setRegeneratePending] = useState(false);
  // A lost regenerate ACK keeps its original request id: native admission
  // replays by clientSubmissionId, so a new id would create a distinct turn.
  const regenerateAttempt = useRef<{ messageId: string; requestId: string } | null>(null);
  async function regenerateMessage(message: ConversationMessage) {
    if (controlGate.current || sending.current || !detail.data || !sessionId) return;
    if (message.role !== "assistant" || busy || stopping) return;
    const messages = detail.data.messages;
    const assistantIndex = messages.findIndex(entry => String(entry.id || "").trim() === String(message.id || "").trim());
    if (assistantIndex <= 0) return;
    let userMessage: ConversationMessage | undefined;
    for (let index = assistantIndex - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user") { userMessage = messages[index]; break; }
    }
    if (!userMessage) return;
    const messageId = String(userMessage.id || "").trim();
    if (!messageId) return;
    const attempt = regenerateAttempt.current?.messageId === messageId
      ? regenerateAttempt.current : { messageId, requestId: crypto.randomUUID() };
    regenerateAttempt.current = attempt;
    controlGate.current = true;
    setRegeneratePending(true);
    setFeedback("");
    await client.cancelQueries({ queryKey: detailKey, exact: true });
    const previousDetail = client.getQueryData<SessionDetail>(detailKey);
    client.setQueryData<SessionDetail>(detailKey, current => applyOptimisticRegenerate(current, { messageId }));
    const optimisticDetail = client.getQueryData<SessionDetail>(detailKey);
    setActiveLayer(sessionStream.beginSubmission(attempt.requestId));
    try {
      const next = await regenerateLauncherAssistantMessage(sessionId, attempt.messageId, attempt.requestId);
      regenerateAttempt.current = null;
      if (!mounted.current || sessionIdRef.current !== sessionId) return;
      client.setQueryData<SessionDetail>(["launcher-assistant", "detail", sessionId], previous =>
        mergeSessionDetailMessageWindow(previous, next));
      const evidence = findSubmitAcceptanceEvidence(next, attempt.requestId);
      const turnId = evidence ? exactAcceptedSubmitTurnId(next, attempt.requestId, evidence) : String(next.activeTurnId || "");
      setActiveLayer(sessionStream.acceptSubmission(attempt.requestId, turnId));
      if (mounted.current) setAcceptedTurnId(turnId);
    } catch (error) {
      // The attempt is retained so an immediate retry replays the same id.
      const readback = await readbackSubmitAcceptance(client, sessionId, attempt.requestId, submitReadbackRuntime);
      if (mounted.current && sessionIdRef.current === sessionId) {
        const turnId = readback.evidence ? exactAcceptedSubmitTurnId(client.getQueryData<SessionDetail>(detailKey), attempt.requestId, readback.evidence) : "";
        if (turnId) {
          regenerateAttempt.current = null;
          setAcceptedTurnId(turnId);
          setActiveLayer(sessionStream.acceptSubmission(attempt.requestId, turnId));
        } else {
          client.setQueryData<SessionDetail>(detailKey, current => current === optimisticDetail ? previousDetail : current);
          setActiveLayer(sessionStream.rejectSubmission(attempt.requestId));
          setFeedback(errorMessage(error));
        }
      }
    } finally {
      controlGate.current = false;
      if (mounted.current) { setRegeneratePending(false); void detail.refetch(); }
    }
  }

  const [guidancePendingMode, setGuidancePendingMode] = useState<"" | "safe" | "interrupt">("");
  async function submitGuidance(mode: "safe" | "interrupt") {
    // Same gates as the chat baseline: guidance only steers a running turn and
    // carries the draft text; attachments ride the queue instead.
    if (!detail.data || !sessionId || guidancePendingMode) return;
    if (!busy || stopping || sendPending || sendUnconfirmed) return;
    const content = draftRef.current.trim();
    if (!content) return;
    setGuidancePendingMode(mode);
    setFeedback("");
    try {
      const next = await guideLauncherAssistantTurn(sessionId, content, mode);
      if (!mounted.current || sessionIdRef.current !== sessionId) return;
      client.setQueryData<SessionDetail>(detailKey, current => mergeSessionSubmitDetail(current, next));
      const remaining = draftRef.current.trim() === content ? "" : draftRef.current;
      draftRef.current = remaining;
      saveComposer({ draft: remaining });
      setDraft(remaining);
    } catch (error) {
      if (mounted.current) setFeedback(errorMessage(error));
    } finally {
      if (mounted.current) { setGuidancePendingMode(""); void detail.refetch(); }
    }
  }

  const identity = status.data?.assistant;
  const avatarImage = readingAssets && !avatar.isError ? avatar.data?.image : null;
  const assistantAvatarImage = readingAssistantAvatar && !assistantAvatar.isError && !assistantAvatar.isFetching ? assistantAvatar.data?.image : null;
  const backgroundImage = readingAssets && !background.isError ? background.data?.image : null;
  const backgroundStyle = backgroundImage
    ? { "--workbench-theme-background-image": `url(${JSON.stringify(backgroundImage.url)})` } as CSSProperties
    : undefined;
  const preferences = status.data?.settings?.preferences || DEFAULT_PET_PREFERENCES;
  const displayName = status.data?.settings?.displayName || identity?.displayName || copy.title;
  const { tone, animationState } = launcherAssistantActivity(detail.data);
  const activity = resolveSessionActivity(detail.data || {});
  const busy = hasExecutionOwnership(activity.execution);
  const stopping = Boolean(detail.data?.stopRequested);
  const canContinue = !draft.trim() && !attachments.length && !sendUnconfirmed && (continuationUnconfirmed || Boolean(resolveConversationContinuation(detail.data, sessionId)));
  const actionMode = busy || stopping ? "stop" : canContinue ? "continue" : "send";
  const queueEnabled = status.data?.followupQueueVersion === 1;
  const followupQueue = useLauncherAssistantFollowupQueue({
    sessionId, activeTurnId: acceptedTurnId || undefined, detail: detail.data, enabled: queueEnabled, lang,
    blocked: sendPending || sendUnconfirmed || controlPending || stopping || modelConfigPending || Boolean(guidancePendingMode),
  });
  // "待你回答" banner above the composer. Same gates as the chat page: a
  // running turn (execution ownership) or an unfinished send hides the banner,
  // and only the question written by the last terminal turn stays fresh.
  const pendingQuestion = (() => {
    // Keep the exact question and answer visible while its original request is
    // pending/unconfirmed, even if native admission has already consumed the slot.
    if ((sendPending || sendUnconfirmed) && outstanding.current?.answerQuestion) return outstanding.current.answerQuestion;
    const question = detail.data?.pendingQuestion ?? null;
    if (!question || detail.data?.id !== sessionId) return null;
    if (answeredQuestion?.sessionId === sessionId && answeredQuestion.id === question.id
      && answeredQuestion.turnId === question.turnId) return null;
    if (question.turnId !== "" && question.turnId !== (detail.data?.lastTurnTerminalTurnId ?? "")) return null;
    if (busy || sendPending || sendUnconfirmed) return null;
    return question;
  })();
  const answerValue = pendingQuestion && questionDraft?.sessionId === sessionId
    && questionDraft.question.id === pendingQuestion.id && questionDraft.question.turnId === pendingQuestion.turnId
    ? questionDraft.value : outstanding.current?.answerQuestion?.id === pendingQuestion?.id ? outstanding.current?.message || "" : "";
  function changeQuestionAnswer(value: string) {
    if (!pendingQuestion || sendPending || sendUnconfirmed || controlPending) return;
    const next = { question: pendingQuestion, value };
    questionDraftRef.current = { ...next, sessionId };
    setQuestionDraft(questionDraftRef.current);
    saveComposer({ questionDraft: next });
    setFeedback("");
  }
  function submitQuestionAnswer() {
    if (!pendingQuestion || sessionIdRef.current !== sessionId || sending.current || controlPending || stopping) return;
    if (outstanding.current?.answerQuestion) {
      // An unknown outcome must replay the original identity, never create a
      // second answer just because the backend slot has moved on.
      if (sendUnconfirmed) void submit();
      return;
    }
    const current = latestDetail.current;
    const question = current?.pendingQuestion;
    if (busy || !question || current?.id !== sessionId || question.id !== pendingQuestion.id
      || question.turnId !== pendingQuestion.turnId
      || (question.turnId && question.turnId !== current.lastTurnTerminalTurnId) || !answerValue.trim()) return;
    void submit({ message: answerValue.trim(), requestId: crypto.randomUUID(), preserveDraft: true, answerQuestion: { ...question } });
  }
  const nativeQueueRows = detail.data?.queuedTurns?.filter(row => !isLocalQueuedSubmit(row));
  const queueRow = nativeQueueRows?.find(row => row.id === queuedAcceptance?.id) || nativeQueueRows?.[0];
  const waitingQueueText = lang === "zh" ? "已排队，正在读取原生队列…" : "Queued; reading the native queue…";
  const removedQueueText = lang === "zh" ? "排队消息已移除" : "Queued message removed";
  const queueStatusText = queueReadback.removed ? removedQueueText : queueRow ? launcherAssistantQueueLabel(queueRow.status, lang)
    : queuedAcceptance && !queuedAcceptance.observed ? waitingQueueText : "";
  // The very first status read has never succeeded: at a cold boot this is the
  // workbench backend still starting, not a broken assistant. The page shows a
  // waiting state (kept probing by the backoff interval above) instead of a
  // dead-end unavailable error. A CLOSING refusal is different: the resident
  // assistant was stopped by a shell exit (possibly one Main is still
  // recovering), so the honest copy names that instead of the backend wait.
  const waitingForBackend = status.isError && !status.data;
  const lifecycleClosing = waitingForBackend && launcherAssistantLifecycleClosing(status.error);
  // Debounced degradation of the status poll over the mounted conversation: a
  // single failed poll is a weak hint; red requires persistence (two failures
  // or a 30s silence gap) AND a dead push channel, because live push events
  // keep the conversation updating no matter how the poll is doing.
  const statusDegradeTone = launcherAssistantStatusDegradeTone({
    isError: status.isError, isFetching: status.isFetching, hasData: Boolean(status.data),
    consecutiveFailures: statusFailures, lastSuccessAt: status.dataUpdatedAt,
    now: Date.now(), sseHealthy: launcherAssistantSseHealthy(sseAliveAt.current, Date.now()),
  });
  const statusHardDown = statusDegradeTone === "error";
  const notificationsHosted = usePublishLauncherNotices(expanded ? launcherAssistantPageNotices({
    lang,
    reads: [
      { label: lang === "zh" ? "状态刷新" : "Status refresh", feature: "assistant", failed: (!taskNoticeOwner && launcherNoticeReadFailed(status)) || (!launcherNoticeReadFailed(status) && statusDegradeTone !== "quiet"), pending: status.isFetching, error: status.error, retry: status.refetch },
      { label: lang === "zh" ? "会话刷新" : "Conversation refresh", feature: "conversation", failed: reading && launcherNoticeReadFailed(detail), pending: detail.isFetching, error: detail.error, retry: detail.refetch },
      { label: lang === "zh" ? "待授权查询" : "Pending approvals", feature: "approvals", failed: reading && launcherNoticeReadFailed(approvals), pending: approvals.isFetching, error: approvals.error, retry: approvals.refetch },
      { label: lang === "zh" ? "任务状态" : "Task status", feature: "tasks", failed: reading && launcherNoticeReadFailed(dispatches), pending: dispatches.isFetching, error: dispatches.error, retry: dispatches.refetch },
    ],
    appearance: [
      { label: lang === "zh" ? "用户头像" : "User avatar", failed: readingAssets && launcherNoticeReadFailed(avatar), pending: avatar.isFetching, error: avatar.error, retry: avatar.refetch },
      { label: lang === "zh" ? "背景图片" : "Background image", failed: readingAssets && launcherNoticeReadFailed(background), pending: background.isFetching, error: background.error, retry: background.refetch },
      { label: lang === "zh" ? "助理头像" : "Assistant avatar", failed: readingAssistantAvatar && launcherNoticeReadFailed(assistantAvatar), pending: assistantAvatar.isFetching, error: assistantAvatar.error, retry: assistantAvatar.refetch },
    ],
    history: { missing: historyAttachments.missingGenerated, failed: historyAttachments.failed, pending: historyAttachments.pending, retry: historyAttachments.retry, refresh: detail.refetch },
    deliveryUnreported: status.data?.patrol?.state === "unavailable" || ["unknown", "failed", "interrupted"].some(key => (status.data?.patrol?.deliveryStates[key] || 0) > 0),
  }) : []);
  // Read-only context-usage ring from the native detail's usage projections.
  // Null before the first usage frame; diagnostics handoff and the auto-compaction
  // countdown are absent because this surface mounts neither dialog nor setting.
  const composerContextRing = useMemo(() => launcherAssistantContextRing(detail.data, lang), [detail.data, lang]);
  const composerCacheUsage = useComposerCacheUsage({ sessionId, agentId: status.data?.assistant.agentId ?? "", source: "assistant",
    refreshMarker: `${detail.data?.llmUsage?.recordedAt ?? ""}:${detail.data?.status ?? ""}`,
    running: detail.data?.status === "running" });
  const modelDisplay = launcherAssistantModelDisplay(status.data?.settings?.modelId, lang);
  // The header keeps the normal session status line for a weakly degraded poll;
  // "unavailable" is reserved for the hard-down case (persistent failure AND a
  // dead push channel), and the cold-boot wait keeps its own wording.
  const statusText = feedback || queueStatusText || (waitingForBackend ? lifecycleClosing ? copy.lifecycleClosing : copy.waitingBackend : statusHardDown ? copy.unavailable
    : status.isPending ? copy.checking
    : detail.data ? !detail.isError && !approval && !stopping && !acceptedTurnId && !sendPending && !sendUnconfirmed && preferences.idleMessage
        && (activity.execution === "idle" || (activity.execution === "settled" && activity.outcome === "completed"))
      ? preferences.idleMessage : sessionActivityStatusLabel(activity, lang)
      : copy.title);
  const displayedStatusText = notificationsHosted && detail.data && !feedback && !queueStatusText && (statusHardDown || detail.isError)
    ? `${sessionActivityStatusLabel(activity, lang)} · ${lang === "zh" ? "上次已知状态" : "Last known status"}` : statusText;

  // A status refresh failure no longer discards the mounted conversation.
  // While any session content exists (detail data), the page stays mounted
  // behind one compact recovery banner. A first-load failure with no content is
  // the cold-boot backend wait (loading skeleton with pulse lines) unless a
  // prior success proves the identity itself broke; collapsed keeps its status
  // line visible through the wait.
  if (status.isError && expanded && !detail.data) return waitingForBackend ? lifecycleClosing ?
    <VStateSurface fill tone="unavailable" data-launcher-assistant-waiting="lifecycle-closing"
      title={copy.lifecycleClosing}
      actions={notificationsHosted ? undefined : <VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>
      {notificationsHosted ? null : status.error.message}</VStateSurface>
    : <VStateSurface fill tone="loading"
    data-launcher-assistant-waiting="backend" title={copy.waitingBackend}>{notificationsHosted ? null : status.error.message}</VStateSurface>
    : <VStateSurface fill tone={notificationsHosted ? "unavailable" : "error"} title={notificationsHosted ? copy.conversationUnavailable : copy.unavailable}
    actions={notificationsHosted ? undefined : <VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>{notificationsHosted ? null : status.error.message}</VStateSurface>;

  const refreshAll = () => {
    void status.refetch(); void detail.refetch(); void dispatches.refetch(); void approvals.refetch();
    void client.invalidateQueries({ queryKey: assetQueryPrefix });
    void client.invalidateQueries({ queryKey: assistantAvatarPrefix });
    void client.invalidateQueries({ queryKey: launcherAssistantBudgetQueryKey(status.data?.assistant.agentId || "", sessionId), exact: true });
    void client.invalidateQueries({ queryKey: composerCacheUsageQueryKey("assistant", status.data?.assistant.agentId || "", sessionId), exact: true });
  };

  if (!expanded) return <main className={petStyles.root} data-vui-domain-recipe="launcher-assistant"
    data-expanded="false" data-tone={tone} aria-label={displayName}
    data-waiting={waitingForBackend ? lifecycleClosing ? "lifecycle-closing" : "backend" : undefined}>
    <div className={petStyles.stage}>
      <div className={petStyles.toolbar}>
        <span className={petStyles.status} role="status" aria-live="polite" hidden={!preferences.showStatus && !feedback && !(waitingForBackend || statusHardDown)}>
          <span className={petStyles.statusDot} aria-hidden="true" />{statusText}
        </span>
        <VNativeButton className={petStyles.close} aria-label={copy.hide} onClick={() => void hide()}><X size={14} /></VNativeButton>
      </div>
      <VNativeButton className={petStyles.characterButton} aria-label={lang === "zh" ? "打开 Launcher" : "Open Launcher"}
        disabled={launcherPending} onClick={characterClicked}
        onPointerDown={beginCharacterDrag}
        onPointerMove={moveCharacterDrag}
        onPointerUp={endCharacterDrag}
        onPointerCancel={cancelCharacterDrag}>
        <DesktopPetCharacter characterId={preferences.characterId} name={displayName} tone={tone} animationState={animationState} />
      </VNativeButton>
      <VNativeButton className={petStyles.chatCue} disabled={launcherPending} onClick={() => void openLauncher()}>
        <MessageCircle size={13} aria-hidden="true" />{copy.chat}
      </VNativeButton>
    </div>
  </main>;

  const approvalPrompt = approval || dispatchApproval ? <div className={petStyles.approvalDock} data-launcher-assistant-approval-dock>
    {approval ? <ChatToolApprovalDialog lang={lang} variant="composer"
      pending={approvalPending || !approval.availableDecisions.includes("accept") || !approval.availableDecisions.includes("decline")}
      argumentSummary={approval.argumentSummary} rawTitle={approval.toolName === "personal_assistant_manage_tool" && launcherTeamActionIsKnown(approval.argumentSummary?.assistantAction)
        ? launcherTeamActionTitle(approval.argumentSummary.assistantAction, lang) : approval.toolName} riskLabel={approval.argumentSummary?.assistantAction === "browser_interact" ? (lang === "zh" ? "网页操作" : "Webpage action") : toolApprovalRiskLabel(approval.risk, lang)}
      scopeLabel={lang === "zh" ? "仅本次调用" : "This call only"}
      toolLabels={[{ id: approval.toolName, label: toolApprovalDisplayName(approval.toolName, lang) }]}
      toolName={approval.toolName} actionPreview={approval.toolName === "personal_assistant_manage_tool" && launcherTeamActionIsKnown(approval.argumentSummary?.assistantAction)
        ? launcherTeamActionPreview(approval.argumentSummary, lang) : approval.toolName === "personal_assistant_manage_tool" && approval.argumentSummary?.assistantAction === "agent_purge_batch"
          ? launcherAgentPurgeBatchActionPreview(approval.argumentSummary, lang) : toolApprovalActionPreview(approval.argumentSummary, approval.toolName, lang)}
      fullActionPreview={approval.toolName === "personal_assistant_manage_tool" && (autonomyActionIsKnown(approval.argumentSummary?.assistantAction) || launcherTeamActionIsKnown(approval.argumentSummary?.assistantAction) || platformManagementActionIsKnown(approval.argumentSummary?.assistantAction) || ["agent_create", "agent_archive", "agent_purge", "agent_purge_batch", "authorization_upgrade", "dispatch_write", "project_lifecycle", "operator_image_upload", "reminder_handoff_recover", "browser_interact"].includes(String(approval.argumentSummary?.assistantAction)))}
      approveDisabled={approvalAcceptDisabled(approval)}
      onApprove={() => void decide(approval, "accept")} onReject={() => void decide(approval, "decline")} /> : null}
    {dispatchApproval ? <ChatToolApprovalDialog lang={lang} variant="composer"
      pending={approvalPending}
      approveDisabled={!activeDispatchPreview || decidedDispatchKey === dispatchPreviewKey || !dispatchApproval.request.availableDecisions.includes("accept")}
      rejectDisabled={(!activeDispatchPreview && !canDeclineSummary) || decidedDispatchKey === dispatchPreviewKey || !dispatchApproval.request.availableDecisions.includes("decline")} rawTitle={dispatchApproval.request.toolName}
      riskLabel={toolApprovalRiskLabel(activeDispatchPreview?.risk || dispatchApproval.request.risk, lang)}
      scopeLabel={lang === "zh" ? "目标任务 · 仅本次" : "Target task · this call"}
      toolLabels={[{ id: dispatchApproval.request.toolName, label: toolApprovalDisplayName(dispatchApproval.request.toolName, lang) }]}
      toolName={dispatchApproval.request.toolName} fullActionPreview
      actionPreview={[
        `${lang === "zh" ? "项目" : "Project"}: ${dispatchApproval.row.projectId || "—"}`,
        `Agent: ${dispatchApproval.row.agentId || "—"}`,
        `${lang === "zh" ? "派遣 ID" : "Dispatch ID"}: ${dispatchApproval.row.dispatchId}`,
        `${lang === "zh" ? "任务 ID" : "Task ID"}: ${dispatchApproval.row.nativeTaskId}`,
        `${lang === "zh" ? "审批 ID" : "Approval ID"}: ${dispatchApproval.request.approvalId}`,
        ...(activeDispatchPreview ? [
          `${lang === "zh" ? "轮次" : "Turn"}: ${activeDispatchPreview.turnId}`,
          `${lang === "zh" ? "调用" : "Call"}: ${activeDispatchPreview.callId}`,
          `${lang === "zh" ? "权限模式" : "Permission preset"}: ${activeDispatchPreview.permissionPreset}`,
          `${lang === "zh" ? "审批要求" : "Approval requirement"}: ${activeDispatchPreview.approval}`,
          lang === "zh" ? "完整原始参数:" : "Complete original arguments:", readableApprovalJson(activeDispatchPreview.argumentsJson),
          lang === "zh" ? "完整执行参数（含默认值）:" : "Complete execution arguments (including defaults):", readableApprovalJson(activeDispatchPreview.executionArgumentsJson),
        ] : [lang === "zh" ? "目标动作摘要（不完整）:" : "Target action summary (incomplete):",
          JSON.stringify(dispatchApproval.request.targetSummary, null, 2),
          activePreviewError || (lang === "zh" ? "正在读取完整操作，暂不能决定。" : "Reading complete action; decisions are unavailable."),
          ...(canDeclineSummary ? [lang === "zh" ? "完整操作不可用，不能批准；你仍可拒绝本次请求。" : "Complete action unavailable. Approval is disabled; you may decline this request."] : [])]),
      ].join("\n")}
      onApprove={() => void decideDispatch("accept")} onReject={() => void decideDispatch("decline")} /> : null}
  </div> : null;

  const showWelcome = navigationOwned && Boolean(detail.data && !detail.isError && !detail.data.messages.length
    && !detail.data.activeTurnId && !detail.data.queuedTurns?.length && !approval && !dispatchApproval && !sendUnconfirmed);
  function changeDraft(value: string) { draftRef.current = value; setDraft(value); saveComposer({ draft: value }); }
  // Assistant edit affordance: backfill the composer with a previous user
  // message's text for a NEW send. The native facade owns no edit-resubmit
  // verb, so history is never replaced and the button copy says "edit as new".
  function editMessageToComposer(message: ConversationMessage) {
    if (sendPending || sendUnconfirmed || controlPending || busy || stopping) return;
    const backfill = launcherAssistantEditBackfillDraft(message);
    if (backfill === null) return;
    changeDraft(backfill);
  }
  return <VDenseOpsPage hideHeader ariaLabel={displayName}
    className={embedded ? petStyles.launcherChatEmbedded : petStyles.launcherChatWindow} bodyClassName={`${petStyles.chatBody} ${navigationOwned ? petStyles.unifiedChatBody : ""}`} style={backgroundStyle}
    data-vui-domain-recipe="launcher-assistant" data-assistant-chat={embedded ? "embedded" : "compact"} data-expanded="true" data-tone={tone}
    data-assistant-embedded={embedded ? "true" : undefined}
    data-assistant-navigation-owned={navigationOwned ? "true" : undefined}
    data-assistant-empty={showWelcome ? "true" : undefined}
    data-operator-avatar={avatarImage ? "custom" : "default"}
    data-theme-background={backgroundImage ? "custom" : "default"}
    data-theme-background-readability={backgroundImage ? background.data?.readability : undefined}
    toolbarSlot={embedded ? <header className={navigationOwned ? petStyles.chatHeaderUnified : petStyles.chatHeaderStatic}>
      <div className={petStyles.chatIdentity}>
        <h1 className={petStyles.chatTitle}>{navigationOwned ? (lang === "zh" ? "对话" : "Chat") : (lang === "zh" ? "个人助理" : "Personal assistant")}</h1>
        <span className={petStyles.chatStatus} role={feedback ? "alert" : "status"}>{displayedStatusText}</span>
      </div>
      {!navigationOwned ? <VButton density="compact" variant="ghost" aria-pressed={computerOpen}
        onClick={() => setComputerOpen(value => !value)}>{lang === "zh" ? "电脑操作" : "Computer"}</VButton> : null}
      {!navigationOwned ? <VButton density="compact" variant="ghost" icon={<RefreshCw size={14} aria-hidden="true" />}
        onClick={refreshAll}>{copy.refresh}</VButton> : null}
    </header> : <header className={petStyles.chatHeader}>
      <div className={petStyles.chatIdentity}>
        <h1 className={petStyles.chatTitle} hidden={!preferences.showTitles}>{displayName}</h1>
        <span className={petStyles.chatStatus} hidden={!preferences.showStatus && !feedback} role={feedback ? "alert" : "status"}>{displayedStatusText}</span>
      </div>
      <VButton density="compact" variant="ghost" aria-pressed={computerOpen}
        onClick={() => setComputerOpen(value => !value)}>{lang === "zh" ? "电脑操作" : "Computer"}</VButton>
      <VButton density="compact" variant="ghost" isPending={launcherPending} isDisabled={launcherPending}
        onClick={() => void openLauncher()}>{lang === "zh" ? "打开 Launcher" : "Open Launcher"}</VButton>
      <VNativeButton className={petStyles.close} aria-label={copy.refresh} onClick={refreshAll}><RefreshCw size={14} /></VNativeButton>
      <VNativeButton className={petStyles.close} aria-label={copy.collapse} disabled={resizePending} onClick={() => void toggle()}><X size={14} /></VNativeButton>
    </header>}>
    {themeSyncState !== "applied" ? <VStateSurface tone="error" title={themeSyncState === "unknown" ? (lang === "zh" ? "主题变更结果未确认" : "Theme change is unconfirmed") : themeSyncState === "conflict" ? (lang === "zh" ? "助理主题与全局主题不同" : "Assistant and global themes differ") : (lang === "zh" ? "主题尚未同步" : "Theme is not synchronized")}
      actions={<><VButton isDisabled={themePending} onClick={() => { if (themeGate.current) return; themeGate.current = true; setThemePending(true); void requestWorkbenchTheme(readStoredWorkbenchTheme()).then(result => { if (result !== "superseded") setThemeSyncState(result); }).finally(() => { themeGate.current = false; setThemePending(false); }); }}>{lang === "zh" ? "使用助理主题" : "Use assistant theme"}</VButton>
        <VButton isDisabled={themePending} onClick={() => { if (themeGate.current) return; themeGate.current = true; setThemePending(true); void useAuthorityTheme().then(result => { if (result !== "superseded") setThemeSyncState(result); }).finally(() => { themeGate.current = false; setThemePending(false); }); }}>{lang === "zh" ? "使用全局主题" : "Use global theme"}</VButton></>} /> : null}
    {!notificationsHosted && status.isError && statusDegradeTone === "error" ? <VStateSurface density="compact" tone="error" title={copy.statusStale}
      actions={<VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>{status.error.message}</VStateSurface>
      : !notificationsHosted && statusDegradeTone === "soft" ? <VStateSurface density="compact" tone="unavailable" title={copy.statusDelayed} /> : null}
    {showWelcome ? <LauncherAssistantWelcome lang={lang} onPrompt={changeDraft}/> : null}
    {detail.data ? <FollowupQueueTogglePauseContext.Provider value={queueEnabled ? followupQueue.handleFollowupQueueTogglePause : null}>
    <LazyConversationView
      runtimeApi={launcherConversationApi}
      sessionId={detail.data.id} title={detail.data.title || identity?.displayName || copy.title}
      phase={resolveSessionActivity(detail.data).execution} messages={historyAttachments.messages}
      activeTurnMessage={activeLayer?.sessionId === sessionId ? activeTurnLayerToConversationMessage(activeLayer) : undefined}
      hasEarlierMessages={Boolean(detail.data.messageWindow?.hasEarlier)} earlierMessagesLoading={earlierMessagesLoading}
      onLoadEarlierMessages={() => void loadEarlierMessages()}
      onVisibleTimelineMessageIds={setVisibleMessageIds}
      turnError={detail.data.lastTurnError}
      defaultFileContext={detail.data.defaultFileContext} assistantDisplayName={displayName}
      assistantAvatarImageUrl={assistantAvatarImage?.url}
      userDisplayName={resolveChatUserDisplayName(status.data?.operatorProfile?.displayName)} userAvatarPreset={status.data?.operatorProfile?.avatarPreset}
      userAvatarImageUrl={avatarImage?.url}
      showHeader={false} showSessionOverview={false} showMentalSnapshots={false}
      // The embedded page reads at standard density; the compact surface
      // paddings stay exclusive to the 400px floating window.
      density={embedded ? "default" : "compact"} composerVariant="codex"
      composerValue={draft} composerPlaceholder={copy.placeholder} composerDisabled={sendPending || sendUnconfirmed || controlPending || Boolean(pendingQuestion)}
      composerHidden={Boolean(pendingQuestion)}
      composerPending={sendPending || controlPending || stopping} composerActionMode={actionMode}
      // While busy, a control RPC is the stop request; the queue/send submit is
      // its own pending source so queueing never borrows the stopping copy.
      composerStopPending={controlPendingMode === "stop" || stopping} composerSubmitPending={sendPending}
      followupQueue={followupQueue.followupQueue}
      onFollowupQueueUpdate={queueEnabled ? followupQueue.handleFollowupQueueUpdate : undefined}
      onFollowupQueueRemove={queueEnabled ? followupQueue.handleFollowupQueueRemove : undefined}
      onFollowupQueueMove={queueEnabled ? followupQueue.handleFollowupQueueMove : undefined}
      onFollowupQueueSteer={queueEnabled ? followupQueue.handleFollowupQueueSteer : undefined}
      onFollowupQueueSendNow={queueEnabled ? followupQueue.handleFollowupQueueSendNow : undefined}
      followupQueueSteerLabel={copy.safeGuidance}
      composerAttachmentInputDisabled={status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || controlPending}
      composerAttachments={attachments}
      composerReferences={composerReferences}
      composerReferenceOptions={[]}
      onAddComposerReference={addComposerReference}
      onRemoveComposerReference={removeComposerReference}
      onAddComposerAttachments={addAttachments} onRemoveComposerAttachment={removeAttachment}
      onRetryComposerAttachment={id => void uploadAttachments(id)} onRetryComposerAttachmentUploads={() => void uploadAttachments()}
      composerError={sendUnconfirmed ? copy.unknownSend
        : attachments.some(item => item.kind === "image") && status.data?.settings?.supportsImageInput === false ? copy.imageUnsupported
        : attachments.some(item => item.uploadStatus === "failed") ? (lang === "zh" ? "附件上传失败，请重试。" : "Attachment upload failed; retry.") : followupQueue.error}
      submitLabel={sendUnconfirmed ? copy.retry : copy.send} submitPendingLabel={copy.sending}
      composerActionDisabled={sendPending || controlPending || (attachments.length > 0 && status.data?.attachmentVersion !== 1) || (actionMode === "stop" ? stopping || !resolveSessionStopTurnId(detail.data, acceptedTurnId) : actionMode === "send" && !sendUnconfirmed && !draft.trim() && !attachments.length)}
      onComposerChange={value => { followupQueue.clearError(); changeDraft(value); }} onSubmit={() => void submit()}
      onStop={() => void stopTurn()} onContinueTurn={() => void continueTurn()}
      composerContextRing={composerContextRing}
      composerCacheUsage={composerCacheUsage}
      onEditUserMessage={editMessageToComposer}
      editUserMessageLabel={copy.editAsNew}
      editUserMessageDisabled={sendPending || sendUnconfirmed || controlPending || busy || stopping}
      onSwitchMessageVersion={switchMessageVersion}
      branchVersionSwitchDisabled={busy || stopping || switchHeadPending}
      onRegenerateAssistantMessage={regenerateMessage}
      regenerableAssistantMessageId={regenerableAssistantMessageId}
      regenerateDisabled={busy || stopping || sendPending || sendUnconfirmed || controlPending || regeneratePending}
      regeneratePending={regeneratePending}
      onSafeGuidance={() => void submitGuidance("safe")}
      onInterruptGuidance={() => void submitGuidance("interrupt")}
      safeGuidanceLabel={copy.safeGuidance} safeGuidancePendingLabel={copy.safeGuidancePending}
      interruptGuidanceLabel={copy.interruptGuidance} interruptGuidancePendingLabel={copy.interruptGuidancePending}
      composerSafeGuidancePending={guidancePendingMode === "safe" || followupQueue.guidancePending}
      composerInterruptGuidancePending={guidancePendingMode === "interrupt"}
      composerLeadingControl={<><ChatComposerPlusMenu lang={lang} showCapabilities={false} showReferences={false}
        budget={budget}
        sessionReferences={[]} onAddAttachments={addAttachments}
        onAttachSecret={input => addSecretAttachment(input)}
        secretRequest={secretRequest} onSecretRequestDismiss={dismissSecretRequest}
        attachmentDisabled={status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || controlPending} />
        <LauncherManagementPermissionControl state={managementPermission} lang={lang} /></>}
      composerModelControl={status.data ? <LauncherAssistantModelControl key={sessionId} lang={lang}
        modelId={status.data.settings?.modelId || ""} modelDisplay={modelDisplay}
        choices={status.data.settings?.modelChoices} pending={modelConfigPending}
        selectionDisabled={busy || stopping || sendPending || sendUnconfirmed || controlPending}
        onModelChange={modelId => void changeModel(modelId)}
        onOpenSettings={embedded ? () => void openModelConnection() : undefined} /> : undefined}
      composerPrecedingContent={<>
      {pendingQuestion ? <LauncherAssistantQuestionCard key={sessionId + ":" + pendingQuestion.id}
        questionId={pendingQuestion.id} questionText={pendingQuestion.questionText} value={answerValue}
        onChange={changeQuestionAnswer} onSubmit={submitQuestionAnswer} lang={lang}
        pending={sendPending} disabled={controlPending || stopping || (!sendUnconfirmed && busy)}
        unconfirmed={sendUnconfirmed}
        error={sendUnconfirmed ? [copy.unknownSend, sendUnknownDetail].filter(Boolean).join(" ") : feedback} /> : null}
      {entryIntent && dismissedEntry !== entryIntent.key ? <VStateSurface density="compact" tone="empty" title={entryIntent.title}
        actions={<><VButton isDisabled={sendPending || controlPending || sendUnconfirmed} onClick={() => {
          void submit({ message: entryIntent.message, requestId: crypto.randomUUID(), preserveDraft: true }).then(attempted => {
            if (attempted) setDismissedEntry(entryIntent.key);
          });
        }}>{entryIntent.label}</VButton><VButton variant="ghost" onClick={() => setDismissedEntry(entryIntent.key)}>{lang === "zh" ? "暂不处理" : "Dismiss"}</VButton></>} /> : null}
      {computerAccess.show ? <PersonalAssistantComputerPanel key={computerAccess.request?.id || "computer-grant"} active={reading} transport={launcherAssistantComputer}
        authorizationRequestId={computerAccess.request?.id} presentation="conversation" onGranted={computerAccess.onGranted} onCollapse={computerAccess.onDismiss} /> : null}
      {computerAccess.notice ? <p className={petStyles.computerNotice} role="status">{computerAccess.notice}</p> : null}
      {approvalPrompt}</>}
      fallback={<VStateSurface fill tone="loading" title={copy.loading} />}
    />
    </FollowupQueueTogglePauseContext.Provider> : <VStateSurface fill tone={detail.isError ? notificationsHosted ? "unavailable" : "error" : "loading"} title={detail.isError ? notificationsHosted ? copy.conversationUnavailable : copy.unavailable : copy.loading}
      actions={detail.isError && !notificationsHosted ? <VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton> : undefined}>{notificationsHosted ? null : detail.error?.message}</VStateSurface>}
    {!detail.data ? approvalPrompt : null}
    {!notificationsHosted && historyAttachments.missingGenerated ? <VStateSurface tone="error" title={lang === "zh" ? "历史图片缺少附件标识，暂不可查看" : "Historical image has no artifact ID"}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>} /> : null}
    {!notificationsHosted && historyAttachments.failed ? <VStateSurface tone="error" title={lang === "zh" ? "历史附件暂不可用（单个文件上限 8 MiB）" : "Historical attachment unavailable (8 MiB per file limit)"}
      actions={<VButton onClick={historyAttachments.retry}>{copy.retry}</VButton>} /> : null}
    {!notificationsHosted && (readingAssets && (avatar.isError || background.isError) || readingAssistantAvatar && assistantAvatar.isError) ? <VStateSurface tone="error"
      title={lang === "zh" ? "部分外观图片暂不可用，聊天仍可使用" : "Some appearance images are unavailable; chat is ready"}
      actions={<VButton onClick={() => { if (readingAssets && avatar.isError) void avatar.refetch(); if (readingAssets && background.isError) void background.refetch(); if (readingAssistantAvatar && assistantAvatar.isError) void assistantAvatar.refetch(); }}>{copy.retry}</VButton>} /> : null}
    {!notificationsHosted && (status.data?.patrol?.state === "unavailable" || ["unknown", "failed", "interrupted"].some(key => (status.data?.patrol?.deliveryStates[key] || 0) > 0))
      ? <VStateSurface tone="error" title={lang === "zh" ? "部分任务结果暂未汇报，可在对话中让助理查询" : "Some task results have not been reported. Ask the assistant to check in chat."} /> : null}
    {dispatchApproval && activePreviewError ? <VStateSurface tone="error" title={activePreviewError}
      actions={<VButton onClick={() => { setPreviewAttempt(value => value + 1); void dispatches.refetch(); }}>{copy.retry}</VButton>} /> : null}
    {selectedApprovalTarget && !approval ? <VStateSurface tone={dispatchApproval ? "info" : "unavailable"}
      title={dispatchApproval ? (lang === "zh" ? "正在处理所选任务审批" : "Reviewing the selected task approval")
        : (lang === "zh" ? "所选任务审批已失效或暂不可用，请刷新回执核对。" : "The selected task approval is unavailable; refresh its receipt.")}
      actions={<><VButton onClick={() => void dispatches.refetch()}>{copy.refresh}</VButton><VButton onClick={() => approvalNavigation?.dismiss(selectedApprovalTarget.nonce)}>{lang === "zh" ? "关闭定位" : "Close selection"}</VButton></>} /> : null}
    {approvalError || !notificationsHosted && approvals.isError ? <VStateSurface tone="error" title={approvalError || (lang === "zh" ? "待授权查询暂不可用" : "Pending approvals unavailable")}
      actions={<VButton onClick={() => { setApprovalError(""); setDecidedDispatchKey(""); setPreviewAttempt(value => value + 1); void approvals.refetch(); void dispatches.refetch(); }}>{copy.retry}</VButton>}>{notificationsHosted ? null : approvals.error?.message}</VStateSurface> : null}
    {(!queueEnabled && detail.data?.queuedTurns?.length) || detail.data?.queueHold
      || (queuedAcceptance && !queuedAcceptance.observed) || queueReadback.removed ? <section data-launcher-assistant-queue
      className={petStyles.receiptPanel}
      aria-label={lang === "zh" ? "原生消息队列" : "Native message queue"}>
      {/* An explicit stop freezes the queue until a new message unfreezes it;
          without this note a frozen queue reads as silently lost work. */}
      {detail.data?.queueHold ? <p role="status" data-launcher-assistant-queue-hold>
        {lang === "zh" ? "队列已暂停：停止后排队消息保持冻结，发送新消息即可恢复。" : "Queue paused: queued messages stay frozen after a stop; send a new message to resume."}
      </p> : null}
      {queuedAcceptance && !queuedAcceptance.observed ? <p role="status">{waitingQueueText}</p> : null}
      {!queueEnabled ? detail.data?.queuedTurns?.map(row => <p key={row.id} role="status">{launcherAssistantQueueLabel(row.status, lang)}{row.lastError ? ` · ${row.lastError}` : ""}</p>) : null}
      {queueReadback.removed ? <p role="status">{removedQueueText}</p> : null}
    </section> : null}
    {sendUnconfirmed && !outstanding.current?.answerQuestion ? <VStateSurface tone="error" title={copy.unknownSend}
      actions={<VButton onClick={() => void submit()} isDisabled={sendPending || controlPending || stopping}>{copy.retry}</VButton>}>{sendUnknownDetail}</VStateSurface> : null}
    {continuationUnconfirmed ? <VStateSurface tone="unavailable" title={lang === "zh" ? "尚未确认继续请求是否收到，将先核对原请求。" : "Continuation is unconfirmed; the original request will be checked first."}
      actions={<VButton onClick={() => void continueTurn()} isDisabled={controlPending || sendPending || stopping}>{copy.retry}</VButton>} /> : null}
    {recoverySaveFailed ? <VStateSurface tone="error" title={lang === "zh" ? "恢复记录未能保存，请保留当前页面并重试。" : "Recovery could not be saved; keep this page open and retry."} /> : null}
    {!notificationsHosted && detail.isError && detail.data && statusDegradeTone !== "error" ? <VStateSurface tone="error" title={copy.unavailable}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>}>{detail.error.message}</VStateSurface> : null}
    {!notificationsHosted && dispatches.isError ? <VStateSurface tone="error" title={copy.receipts}
      actions={<VButton onClick={() => void dispatches.refetch()}>{copy.retry}</VButton>}>{dispatches.error.message}</VStateSurface> : null}
  </VDenseOpsPage>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** A bounded, single-line extract of the backend's own failure text for the
 * unknown-send banner. Transport wrappers can be long and multiline; the
 * conversation only needs the diagnosis, so collapse whitespace and cap it. */
function boundedErrorDetail(error: unknown): string {
  const flat = (error instanceof Error ? error.message : "").replace(/\s+/g, " ").trim();
  return flat.length > 200 ? `${flat.slice(0, 200)}…` : flat;
}

/** Launcher control-surface session page: the same assistant conversation
 * embedded full-size in the launcher main pane, without the floating window's
 * pet stage, drag, hide, or expand/collapse resize IPC. */
export function LauncherAssistantEmbeddedRoute() {
  return <LauncherAssistantRoute embedded />;
}
