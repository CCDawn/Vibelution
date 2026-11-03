import "../../design/route-css/desktop-pet.tailwind.css";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, MessageCircle, RefreshCw, SlidersHorizontal, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus, setLauncherAssistantModel,
  hideLauncherAssistant, sendLauncherAssistantMessage, setLauncherAssistantExpanded,
  launcherConversationApi,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  previewLauncherDispatchApproval, decideLauncherDispatchApproval, declineLauncherDispatchSummary, launcherDispatchDeclineRevisionIsValid, type LauncherDispatchApprovalPreview,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn,
  getLauncherOperatorAsset, getLauncherAssistantAvatar, openLauncherFromAssistant, uploadLauncherAttachment,
  readLauncherAttachment, subscribeLauncherAssistantSessionEvent,
} from "../../api/launcherAssistant";
import { openLauncherModelConnection } from "../../api/launcher";
import type { ConversationMessage, SessionDetail } from "../../api/types";
import type { SessionContinuationExpectation } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionToolApprovalRequest } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import { LauncherAssistantWelcome } from "./LauncherAssistantWelcome";
import { VButton, VDenseOpsPage, VNativeButton, VNativeSelect, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { hasExecutionOwnership, resolveSessionActivity, sessionActivityStatusLabel } from "../sessionActivityState";
import { continuationSnapshotKey, resolveConversationContinuation } from "../chat/conversationContinuationModel";
import { resolveSessionStopTurnId } from "../chat/chatStopTurnModel";
import { resolveChatUserDisplayName } from "../chatCompactPanel";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence } from "../chat/chatSubmitAcceptanceReadback";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import {
  beginDesktopPetDrag, desktopPetWindowDragBridge, updateDesktopPetDrag,
  type DesktopPetDragPoint, type DesktopPetDragState, type DesktopPetWindowDragBridge
} from "./desktopPetWindowDrag";
import { DEFAULT_PET_PREFERENCES } from "./desktopPetPreferences";
import { ChatToolApprovalDialog } from "../chat/ChatToolApprovalDialog";
import { toolApprovalRiskLabel } from "../chat/toolApprovalLabels";
import { agentArchivePreviewIsValid, agentPurgePreviewIsValid, autonomyActionIsKnown, autonomyApprovalPreviewIsValid, authorizationUpgradePreviewIsValid, browserInteractPreviewIsValid, dispatchWritePreviewIsValid, launcherAgentCreatePreviewIsValid, operatorImageUploadPreviewIsValid, preferenceProposalPreviewIsValid, projectLifecyclePreviewIsValid, recoveryPreviewIsValid, managementApprovalActionIsKnown, platformManagementActionIsKnown, platformManagementPreviewIsValid, toolApprovalActionPreview, toolApprovalDisplayName } from "../chat/toolApprovalPreview";
import { launcherTeamActionIsKnown, launcherTeamPreviewIsValid, launcherTeamActionPreview, launcherTeamActionTitle } from "./teamManagementApprovalPreview";
import { useLauncherThemeControl } from "./useLauncherThemeControl";
import { readStoredWorkbenchTheme, requestWorkbenchTheme, subscribeWorkbenchThemeSync, useAuthorityTheme } from "../../app/themePreference";
import { PersonalAssistantComputerPanel } from "../personalAssistant/PersonalAssistantComputerPanel";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import { useLauncherComputerAccess } from "./useLauncherComputerAccess";
import petStyles from "./DesktopAssistantRoute.styles";
import { useLauncherAttachmentHistory } from "./useLauncherAttachmentHistory";
import { classifyComposerFiles, mergeComposerAttachmentsWithRejections, type ComposerImageAttachment } from "../chat/chatComposerSubmitModel";
import {
  launcherAssistantActivity, launcherAssistantMessageOverLimit, launcherAssistantPollInterval, launcherAssistantSubmission,
  launcherAssistantQueueReadback, launcherAssistantQueueLabel, launcherAssistantRequestReadback,
  launcherAssistantSendDefinitelyRejected, launcherAssistantSessionEventRefreshesDetail, launcherAssistantSseHealthy,
  launcherAssistantStatusDegradeTone, launcherAssistantWaitInterval, launcherAssistantContextRing, launcherAssistantModelDisplay,
  launcherAssistantEditBackfillDraft,
  type LauncherAssistantSubmission, type LauncherAssistantQueuedAcceptance,
} from "./launcherAssistantModel";
import { activeTurnLayerToConversationMessage, createLauncherAssistantStream } from "./launcherAssistantStream";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { loadLauncherComposer, restoreLauncherComposerAttachments, saveLauncherComposer } from "./launcherAssistantComposerStorage";
import { readLauncherAssistantTaskSource } from "./launcherAssistantTaskReads";

const COPY = {
  zh: {
    title: "个人助理", expand: "展开个人助理聊天", chat: "聊一聊", hide: "隐藏个人助理",
    collapse: "收起聊天", loading: "正在打开对话…", unavailable: "个人助理暂不可用",
    retry: "重试", refresh: "刷新", placeholder: "和个人助理聊一聊…", send: "发送", sending: "正在发送…",
    unknownSend: "尚未确认消息是否收到。输入已保留，重试会核对同一条消息。",
    sendRejected: "本次发送已被拒绝，未进入对话；请修改后重新发送。",
    tooLong: "消息超出 64,000 字上限，请精简后再发送。",
    imageUnsupported: "当前模型不支持图片输入，请移除图片附件后再发送。",
    receipts: "任务状态暂不可用", checking: "正在连接 Launcher…",
    waitingBackend: "正在等待工作台后端启动…",
    statusStale: "个人助理状态轮询暂不可用，会话内容可能未更新",
    statusDelayed: "状态刷新延迟，会话内容可能未更新",
    pendingQuestion: "待你回答",
    answerBelow: "去回答", answerHint: "请在下方输入回答，再点击发送。",
    modelSettings: "模型设置", currentModel: "当前模型",
    editAsNew: "编辑为新消息",
  },
  en: {
    title: "Personal assistant", expand: "Open assistant chat", chat: "Chat", hide: "Hide assistant",
    collapse: "Collapse chat", loading: "Opening conversation…", unavailable: "Assistant unavailable",
    retry: "Retry", refresh: "Refresh", placeholder: "Chat with your assistant…", send: "Send", sending: "Sending…",
    unknownSend: "Delivery is unconfirmed. Your input is retained; retry checks the same message.",
    sendRejected: "This send was rejected and never entered the conversation; edit and send again.",
    tooLong: "Message exceeds the 64,000-character limit; shorten it before sending.",
    imageUnsupported: "The current model does not support image input; remove image attachments before sending.",
    receipts: "Task status unavailable", checking: "Connecting to Launcher…",
    waitingBackend: "Waiting for the workbench backend…",
    statusStale: "Assistant status polling is unavailable; conversation content may be stale",
    statusDelayed: "Status refresh is delayed; conversation content may be stale",
    pendingQuestion: "Waiting for your answer",
    answerBelow: "Answer below", answerHint: "Type your answer below, then send it.",
    modelSettings: "Model settings", currentModel: "Current model",
    editAsNew: "Edit as new message",
  },
} as const;

/** Aligns with PERSONAL_ASSISTANT_DISPATCH_LIMIT: bound the receipt history the
 * route keeps and scans for pending approvals. */
const LAUNCHER_ASSISTANT_DISPATCH_LIMIT = 50;

function approvalAcceptDisabled(request: SessionToolApprovalRequest): boolean {
  const summary = request.argumentSummary;
  return request.toolName === "personal_assistant_manage_tool" && (!(managementApprovalActionIsKnown(summary?.assistantAction) || launcherTeamActionIsKnown(summary?.assistantAction)) || Boolean(summary.assistantArgumentsInvalid)
    || (autonomyActionIsKnown(summary?.assistantAction) || Object.hasOwn(summary || {}, "assistantAutonomyPreviewVersion")) && !autonomyApprovalPreviewIsValid(summary)
    || platformManagementActionIsKnown(summary?.assistantAction) && !platformManagementPreviewIsValid(summary)
    || launcherTeamActionIsKnown(summary?.assistantAction) && !launcherTeamPreviewIsValid(summary)
    || summary?.assistantAction === "agent_create" && !launcherAgentCreatePreviewIsValid(summary)
    || summary?.assistantAction === "agent_purge" && !agentPurgePreviewIsValid(summary)
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

type ContinueAttempt = { requestId: string; expected: SessionContinuationExpectation; accepted: boolean };
type ComposerSnapshot = { draft: string; outstanding: LauncherAssistantSubmission | null; acceptedTurnId: string; queuedAcceptance: LauncherAssistantQueuedAcceptance | null; continuation?: ContinueAttempt; attachments?: ComposerImageAttachment[] };

export function LauncherAssistantRoute({ embedded = false, navigationOwned = false, computerRequested = false, entryIntent }: {
  embedded?: boolean; navigationOwned?: boolean; computerRequested?: boolean;
  entryIntent?: { key: string; title: string; label: string; message: string };
}) {
  useLauncherThemeControl();
  const client = useQueryClient();
  const { lang } = useShellI18n();
  const copy = COPY[lang];
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
  const sending = useRef<{ submission: LauncherAssistantSubmission } | null>(null);
  const resizing = useRef(false);
  const outstanding = useRef<LauncherAssistantSubmission | null>(null);
  const [draft, setDraft] = useState("");
  const [answerFocus, setAnswerFocus] = useState<{ sessionId: string; questionId: string; signal: string } | null>(null);
  const settleAnswerFocus = useCallback((signal: string) => {
    setAnswerFocus(current => current?.signal === signal ? null : current);
  }, []);
  const [attachments, setAttachments] = useState<ComposerImageAttachment[]>([]);
  const [visibleMessageIds, setVisibleMessageIds] = useState<string[]>([]);
  const attachmentsRef = useRef<ComposerImageAttachment[]>([]);
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
  const [controlPending, setControlPending] = useState(false);
  // First-failure timestamp of the never-succeeded status read. query.state only
  // exposes the LAST error time, and the backoff must grow across failures, so
  // the wait start is held here and reset once any status read succeeds.
  const backendWaitStartedAt = useRef<number | null>(null);
  const status = useQuery({
    queryKey: ["launcher-assistant", "status"], queryFn: getLauncherAssistantStatus,
    retry: false, staleTime: 0,
    refetchInterval: query => {
      // Cold boot: before the first successful status read, keep probing for the
      // workbench backend with a backoff cadence so a late backend start is
      // joined without any manual refresh.
      if (!query.state.data) return launcherAssistantWaitInterval(backendWaitStartedAt.current, Date.now());
      return expanded && visible ? 10_000 : false;
    },
  });
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
  function saveComposer(patch: Partial<ComposerSnapshot>) {
    client.setQueryDefaults(composerKey, { gcTime: Infinity });
    client.setQueryData<ComposerSnapshot>(composerKey, previous => {
      const next = { draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null, ...previous, ...patch };
      saveLauncherComposer(sessionId, embedded ? "embedded" : "floating", next);
      return next;
    });
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
    outstanding.current = saved?.outstanding || null;
    setSendUnconfirmed(Boolean(saved?.outstanding));
    setAcceptedTurnId(saved?.acceptedTurnId || "");
    setQueuedAcceptance(saved?.queuedAcceptance || null);
  }, [client, sessionId, embedded]);
  // Restored chips start with an empty preview (the blob: URL is unrecoverable);
  // refill each from its already-uploaded artifact through the read IPC, so a
  // reload keeps the tray usable without re-uploading anything.
  useEffect(() => {
    if (!sessionId || status.data?.attachmentVersion !== 1) return;
    const targets = attachmentsRef.current.flatMap(item =>
      item.uploadStatus === "uploaded" && item.artifactId && !item.previewUrl ? [{ id: item.id, artifactId: item.artifactId }] : []);
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
      return mergeSessionDetailMessageWindow(client.getQueryData<SessionDetail>(["launcher-assistant", "detail", sessionId]), result);
    },
    enabled: observingOwnSession, retry: false,
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
    refetchIntervalInBackground: false,
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
    // Capability-detected: an older shell yields null and nothing changes. Any
    // frame proves the channel alive; only this session's authoritative snapshot
    // (or a delta that explicitly finished) invalidates detail, after which the
    // existing full-detail readback effects below re-run unchanged. Bursts are
    // left to react-query's own dedupe; the host already throttles snapshots.
    const unsubscribe = subscribeLauncherAssistantSessionEvent(event => {
      if (!active) return;
      sseAliveAt.current = Date.now();
      const result = sessionStream.apply(event, latestDetail.current);
      setActiveLayer(result.layer);
      if (!result.needsRefresh && !launcherAssistantSessionEventRefreshesDetail(event, sessionId)) return;
      void client.invalidateQueries({ queryKey: ["launcher-assistant", "detail", sessionId] });
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
    // A collapse may invalidate the transport ACK epoch. Only exact native
    // submission evidence may retire that original request, preserving new B.
    outstanding.current = null;
    if (sending.current?.submission === submission) {
      sending.current = null;
      setSendPending(false);
    }
    clearAcceptedAttachments(submission);
    const remainingDraft = !submission.preserveDraft && draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
    draftRef.current = remainingDraft;
    saveComposer({ draft: remainingDraft, outstanding: null, acceptedTurnId: recovered.turnId, queuedAcceptance: recovered.queuedAcceptance });
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
    client.setQueryData<ComposerSnapshot>(["launcher-assistant", "composer", sessionId], previous => previous
      && previous.continuation?.requestId === attempt.requestId
      ? { ...previous, continuation: { ...attempt, accepted: true }, acceptedTurnId: turnId } : previous);
    setAcceptedTurnId(turnId);
    setFeedback("");
  }, [client, detail.data, sessionId]);
  const dispatchReadIdentity = JSON.stringify([assistantAgentId, sessionId, epoch]);
  const readableDispatch = useRef("");
  readableDispatch.current = reading ? dispatchReadIdentity : "";
  const dispatches = useQuery({
    queryKey: ["launcher-assistant", "dispatches", epoch],
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
  const dispatchApproval = approval ? undefined : dispatches.data?.flatMap(row =>
    (row.receipt?.pendingApprovals ?? []).map(request => ({ row, request })))[0];
  const dispatchPreviewKey = dispatchApproval && reading ? JSON.stringify([epoch, dispatchApproval.row.dispatchId,
    dispatchApproval.row.nativeTaskId, dispatchApproval.row.agentId, dispatchApproval.request.approvalId, dispatchApproval.request.toolName]) : "";
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
    mounted.current = true;
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
      mounted.current = false;
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
  function removeAttachment(id: string) {
    if (sendPending || sendUnconfirmed || uploadGate.current) return;
    const item = attachmentsRef.current.find(row => row.id === id);
    if (item) URL.revokeObjectURL(item.previewUrl);
    updateAttachments(attachmentsRef.current.filter(row => row.id !== id));
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
    const byId = new Map(targets.map((item, index) => [item.id, results[index]]));
    const updateOutcomes = (items: ComposerImageAttachment[]): ComposerImageAttachment[] => items.map(item => {
      const result = byId.get(item.id);
      return !result ? item : result.status === "fulfilled" ? { ...item, uploadStatus: "uploaded", artifactId: result.value }
        : { ...item, uploadStatus: "failed" };
    });
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
    if (sending.current || uploadGate.current || controlGate.current || !sessionId
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
    const snapshot = attachmentsRef.current;
    const submission = prepared ?? launcherAssistantSubmission(outstanding.current, draftRef.current, undefined,
      snapshot.map(item => item.artifactId || "").filter(Boolean), snapshot.map(item => item.id));
    if (!submission) return false;
    outstanding.current = submission;
    saveComposer({ draft: draftRef.current, outstanding: submission });
    const flight = { submission };
    sending.current = flight;
    setSendPending(true);
    setSendUnconfirmed(false);
    setFeedback("");
    const requestEpoch = epochRef.current;
    try {
      const acceptance = await sendLauncherAssistantMessage(submission.message, submission.requestId, submission.attachmentIds);
      if (!mounted.current || requestEpoch !== epochRef.current || sending.current !== flight || outstanding.current !== submission) return true;
      outstanding.current = null;
      clearAcceptedAttachments(submission);
      const queueReceipt = acceptance.queuedTurnId ? { id: acceptance.queuedTurnId, clientSubmissionId: acceptance.clientSubmissionId, observed: false } : null;
      const remainingDraft = !submission.preserveDraft && draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
      draftRef.current = remainingDraft;
      saveComposer({ draft: remainingDraft, outstanding: null, acceptedTurnId: acceptance.turnId, queuedAcceptance: queueReceipt });
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
          // A provable pre-admission refusal left nothing queued, so the
          // conservative unconfirmed lock would only dead-end the composer.
          // Draft and tray stay editable for an immediate corrected resend.
          outstanding.current = null;
          saveComposer({ outstanding: null });
          setSendUnconfirmed(false);
          setFeedback(copy.sendRejected);
        } else {
          setSendUnconfirmed(true);
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
    setControlPending(true);
    setFeedback("");
    try {
      await stopLauncherAssistantTurn(sessionId, turnId);
    } catch (error) {
      if (mounted.current) setFeedback(errorMessage(error));
    } finally {
      controlGate.current = false;
      if (mounted.current) { setControlPending(false); void detail.refetch(); }
    }
  }

  async function continueTurn() {
    if (controlGate.current || sending.current || draft.trim() || outstanding.current) return;
    const previous = client.getQueryData<ComposerSnapshot>(composerKey)?.continuation;
    const expected = resolveConversationContinuation(detail.data, sessionId);
    if (!expected && (!previous || previous.accepted)) return;
    // A lost ACK is reconciled before considering any newer eligible head.
    // Native admission replays this original request before validating today's
    // snapshot, so replacing its UUID would create a distinct continuation.
    const attempt = previous && (!previous.accepted || (expected && continuationSnapshotKey(previous.expected) === continuationSnapshotKey(expected)))
      ? previous : { requestId: crypto.randomUUID(), expected: expected!, accepted: false };
    if (attempt.accepted) return;
    saveComposer({ continuation: attempt });
    controlGate.current = true;
    setControlPending(true);
    setFeedback("");
    try {
      const accepted = await continueLauncherAssistantTurn(attempt.expected, attempt.requestId);
      saveComposer({ continuation: { ...attempt, accepted: true }, acceptedTurnId: accepted.turnId });
      if (mounted.current) setAcceptedTurnId(accepted.turnId);
    } catch (error) {
      if (mounted.current) setFeedback(errorMessage(error));
    } finally {
      controlGate.current = false;
      if (mounted.current) { setControlPending(false); void detail.refetch(); }
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
  const canContinue = !draft.trim() && !attachments.length && !sendUnconfirmed && Boolean(resolveConversationContinuation(detail.data, sessionId));
  const actionMode = busy || stopping ? "stop" : canContinue ? "continue" : "send";
  // "待你回答" banner above the composer. Same gates as the chat page: a
  // running turn (execution ownership) or an unfinished send hides the banner,
  // and only the question written by the last terminal turn stays fresh.
  const pendingQuestion = (() => {
    const question = detail.data?.pendingQuestion ?? null;
    if (!question) return null;
    if (question.turnId !== "" && question.turnId !== (detail.data?.lastTurnTerminalTurnId ?? "")) return null;
    if (busy || sendPending || sendUnconfirmed) return null;
    return question;
  })();
  const queueRow = detail.data?.queuedTurns?.find(row => row.id === queuedAcceptance?.id) || detail.data?.queuedTurns?.[0];
  const waitingQueueText = lang === "zh" ? "已排队，正在读取原生队列…" : "Queued; reading the native queue…";
  const removedQueueText = lang === "zh" ? "排队消息已移除" : "Queued message removed";
  const queueStatusText = queueReadback.removed ? removedQueueText : queueRow ? launcherAssistantQueueLabel(queueRow.status, lang)
    : queuedAcceptance && !queuedAcceptance.observed ? waitingQueueText : "";
  // The very first status read has never succeeded: at a cold boot this is the
  // workbench backend still starting, not a broken assistant. The page shows a
  // waiting state (kept probing by the backoff interval above) instead of a
  // dead-end unavailable error.
  const waitingForBackend = status.isError && !status.data;
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
  // Read-only context-usage ring from the native detail's usage projections.
  // Null before the first usage frame; diagnostics handoff and the auto-compaction
  // countdown are absent because this surface mounts neither dialog nor setting.
  const composerContextRing = useMemo(() => launcherAssistantContextRing(detail.data, lang), [detail.data, lang]);
  const modelDisplay = launcherAssistantModelDisplay(status.data?.settings?.modelId, lang);
  // The header keeps the normal session status line for a weakly degraded poll;
  // "unavailable" is reserved for the hard-down case (persistent failure AND a
  // dead push channel), and the cold-boot wait keeps its own wording.
  const statusText = feedback || queueStatusText || (waitingForBackend ? copy.waitingBackend : statusHardDown ? copy.unavailable
    : status.isPending ? copy.checking
    : detail.data ? !detail.isError && !approval && !stopping && !acceptedTurnId && !sendPending && !sendUnconfirmed && preferences.idleMessage
        && (activity.execution === "idle" || (activity.execution === "settled" && activity.outcome === "completed"))
      ? preferences.idleMessage : sessionActivityStatusLabel(activity, lang)
      : copy.title);

  // A status refresh failure no longer discards the mounted conversation.
  // While any session content exists (detail data), the page stays mounted
  // behind one compact recovery banner. A first-load failure with no content is
  // the cold-boot backend wait (loading skeleton with pulse lines) unless a
  // prior success proves the identity itself broke; collapsed keeps its status
  // line visible through the wait.
  if (status.isError && expanded && !detail.data) return waitingForBackend ? <VStateSurface fill tone="loading"
    data-launcher-assistant-waiting="backend" title={copy.waitingBackend}>{status.error.message}</VStateSurface>
    : <VStateSurface fill tone="error" title={copy.unavailable}
    actions={<VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>{status.error.message}</VStateSurface>;

  const refreshAll = () => {
    void status.refetch(); void detail.refetch(); void dispatches.refetch(); void approvals.refetch();
    void client.invalidateQueries({ queryKey: assetQueryPrefix });
    void client.invalidateQueries({ queryKey: assistantAvatarPrefix });
  };

  if (!expanded) return <main className={petStyles.root} data-vui-domain-recipe="launcher-assistant"
    data-expanded="false" data-tone={tone} aria-label={displayName}
    data-waiting={waitingForBackend ? "backend" : undefined}>
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
        ? launcherTeamActionPreview(approval.argumentSummary, lang) : toolApprovalActionPreview(approval.argumentSummary, approval.toolName, lang)}
      fullActionPreview={approval.toolName === "personal_assistant_manage_tool" && (autonomyActionIsKnown(approval.argumentSummary?.assistantAction) || launcherTeamActionIsKnown(approval.argumentSummary?.assistantAction) || platformManagementActionIsKnown(approval.argumentSummary?.assistantAction) || ["agent_create", "agent_archive", "agent_purge", "authorization_upgrade", "dispatch_write", "project_lifecycle", "operator_image_upload", "reminder_handoff_recover", "browser_interact"].includes(String(approval.argumentSummary?.assistantAction)))}
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
        <span className={petStyles.chatStatus} role={feedback ? "alert" : "status"}>{statusText}</span>
      </div>
      {!navigationOwned ? <VButton density="compact" variant="ghost" aria-pressed={computerOpen}
        onClick={() => setComputerOpen(value => !value)}>{lang === "zh" ? "电脑操作" : "Computer"}</VButton> : null}
      {!navigationOwned ? <VButton density="compact" variant="ghost" icon={<RefreshCw size={14} aria-hidden="true" />}
        onClick={refreshAll}>{copy.refresh}</VButton> : null}
    </header> : <header className={petStyles.chatHeader}>
      <div className={petStyles.chatIdentity}>
        <h1 className={petStyles.chatTitle} hidden={!preferences.showTitles}>{displayName}</h1>
        <span className={petStyles.chatStatus} hidden={!preferences.showStatus && !feedback} role={feedback ? "alert" : "status"}>{statusText}</span>
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
    {status.isError && statusDegradeTone === "error" ? <VStateSurface density="compact" tone="error" title={copy.statusStale}
      actions={<VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>{status.error.message}</VStateSurface>
      : statusDegradeTone === "soft" ? <VStateSurface density="compact" tone="unavailable" title={copy.statusDelayed} /> : null}
    {showWelcome ? <LauncherAssistantWelcome lang={lang} onPrompt={changeDraft}/> : null}
    {detail.data ? <LazyConversationView
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
      composerValue={draft} composerPlaceholder={copy.placeholder} composerDisabled={sendPending || sendUnconfirmed || controlPending}
      composerFocusSignal={answerFocus?.sessionId === sessionId && answerFocus.questionId === pendingQuestion?.id ? answerFocus.signal : ""}
      onComposerFocusRequestSettled={settleAnswerFocus}
      composerPending={sendPending || controlPending || stopping} composerActionMode={actionMode}
      composerAttachmentInputDisabled={status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || controlPending}
      composerAttachments={attachments}
      onAddComposerAttachments={addAttachments} onRemoveComposerAttachment={removeAttachment}
      onRetryComposerAttachment={id => void uploadAttachments(id)} onRetryComposerAttachmentUploads={() => void uploadAttachments()}
      composerError={sendUnconfirmed ? copy.unknownSend
        : attachments.some(item => item.kind === "image") && status.data?.settings?.supportsImageInput === false ? copy.imageUnsupported
        : attachments.some(item => item.uploadStatus === "failed") ? (lang === "zh" ? "附件上传失败，请重试。" : "Attachment upload failed; retry.") : ""}
      submitLabel={sendUnconfirmed ? copy.retry : copy.send} submitPendingLabel={copy.sending}
      composerActionDisabled={sendPending || controlPending || (attachments.length > 0 && status.data?.attachmentVersion !== 1) || (actionMode === "stop" ? stopping || !resolveSessionStopTurnId(detail.data, acceptedTurnId) : actionMode === "send" && !sendUnconfirmed && !draft.trim() && !attachments.length)}
      onComposerChange={changeDraft} onSubmit={() => void submit()}
      onStop={() => void stopTurn()} onContinueTurn={() => void continueTurn()}
      composerContextRing={composerContextRing}
      onEditUserMessage={editMessageToComposer}
      editUserMessageLabel={copy.editAsNew}
      editUserMessageDisabled={sendPending || sendUnconfirmed || controlPending || busy || stopping}
      composerPrecedingContent={<>{status.data ? <div className={petStyles.modelRow}
        data-launcher-assistant-model-row aria-label={copy.currentModel}>
        <Bot size={12} aria-hidden="true" />
        {status.data.settings?.modelChoices?.length ? <VNativeSelect aria-label={lang === "zh" ? "助理模型" : "Assistant model"}
          value={status.data.settings.modelId} disabled={modelConfigPending || busy || stopping || sendPending || sendUnconfirmed || controlPending}
          onChange={event => void changeModel(event.currentTarget.value)} className={petStyles.modelSelect}>
          {!status.data.settings.modelChoices.some(choice => choice.modelId === status.data?.settings?.modelId)
            ? <option value={status.data.settings.modelId}>{modelDisplay}</option> : null}
          {status.data.settings.modelChoices.map(choice => <option key={choice.modelId} value={choice.modelId}
            disabled={choice.providerHealthy === false || choice.missingApiKey === true}>{choice.label || choice.modelId}</option>)}
        </VNativeSelect> : <span className={petStyles.modelName}>{modelDisplay}</span>}
        {embedded ? <VButton density="compact" variant="ghost" className={petStyles.modelSettingsButton} isPending={modelConfigPending} isDisabled={modelConfigPending}
          icon={<SlidersHorizontal size={12} aria-hidden="true" />}
          onClick={() => void openModelConnection()}>{copy.modelSettings}</VButton> : null}
      </div> : null}
      {pendingQuestion ? <VStateSurface density="compact" tone="info" title={copy.pendingQuestion}
        data-launcher-assistant-pending-question={pendingQuestion.id}
        actions={<VButton isDisabled={sendPending || sendUnconfirmed || controlPending} onClick={event => {
          // This explicit handoff releases button focus so the shared scheduler
          // can focus the composer without overriding another active control.
          event.currentTarget.blur();
          setAnswerFocus({ sessionId, questionId: pendingQuestion.id, signal: crypto.randomUUID() });
        }}>{copy.answerBelow}</VButton>}>
        {pendingQuestion.questionText}<br />{copy.answerHint}
      </VStateSurface> : null}
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
    /> : <VStateSurface fill tone={detail.isError ? "error" : "loading"} title={detail.isError ? copy.unavailable : copy.loading}
      actions={detail.isError ? <VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton> : undefined}>{detail.error?.message}</VStateSurface>}
    {!detail.data ? approvalPrompt : null}
    {historyAttachments.missingGenerated ? <VStateSurface tone="error" title={lang === "zh" ? "历史图片缺少附件标识，暂不可查看" : "Historical image has no artifact ID"}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>} /> : null}
    {historyAttachments.failed ? <VStateSurface tone="error" title={lang === "zh" ? "历史附件暂不可用（单个文件上限 8 MiB）" : "Historical attachment unavailable (8 MiB per file limit)"}
      actions={<VButton onClick={historyAttachments.retry}>{copy.retry}</VButton>} /> : null}
    {(readingAssets && (avatar.isError || background.isError) || readingAssistantAvatar && assistantAvatar.isError) ? <VStateSurface tone="error"
      title={lang === "zh" ? "部分外观图片暂不可用，聊天仍可使用" : "Some appearance images are unavailable; chat is ready"}
      actions={<VButton onClick={() => { if (readingAssets && avatar.isError) void avatar.refetch(); if (readingAssets && background.isError) void background.refetch(); if (readingAssistantAvatar && assistantAvatar.isError) void assistantAvatar.refetch(); }}>{copy.retry}</VButton>} /> : null}
    {status.data?.patrol?.state === "unavailable" || ["unknown", "failed", "interrupted"].some(key => (status.data?.patrol?.deliveryStates[key] || 0) > 0)
      ? <VStateSurface tone="error" title={lang === "zh" ? "部分任务结果暂未汇报，可在对话中让助理查询" : "Some task results have not been reported. Ask the assistant to check in chat."} /> : null}
    {dispatchApproval && activePreviewError ? <VStateSurface tone="error" title={activePreviewError}
      actions={<VButton onClick={() => { setPreviewAttempt(value => value + 1); void dispatches.refetch(); }}>{copy.retry}</VButton>} /> : null}
    {approvalError || approvals.isError ? <VStateSurface tone="error" title={approvalError || (lang === "zh" ? "待授权查询暂不可用" : "Pending approvals unavailable")}
      actions={<VButton onClick={() => { setApprovalError(""); setDecidedDispatchKey(""); setPreviewAttempt(value => value + 1); void approvals.refetch(); void dispatches.refetch(); }}>{copy.retry}</VButton>}>{approvals.error?.message}</VStateSurface> : null}
    {detail.data?.queuedTurns?.length || queuedAcceptance ? <section data-launcher-assistant-queue
      className={petStyles.receiptPanel}
      aria-label={lang === "zh" ? "原生消息队列" : "Native message queue"}>
      {queuedAcceptance && !queuedAcceptance.observed ? <p role="status">{waitingQueueText}</p> : null}
      {detail.data?.queuedTurns?.map(row => <p key={row.id} role="status">{launcherAssistantQueueLabel(row.status, lang)}{row.lastError ? ` · ${row.lastError}` : ""}</p>)}
      {queueReadback.removed ? <p role="status">{removedQueueText}</p> : null}
    </section> : null}
    {sendUnconfirmed ? <VStateSurface tone="error" title={copy.unknownSend}
      actions={<VButton onClick={() => void submit()} isDisabled={sendPending || controlPending || stopping}>{copy.retry}</VButton>} /> : null}
    {detail.isError && detail.data && statusDegradeTone !== "error" ? <VStateSurface tone="error" title={copy.unavailable}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>}>{detail.error.message}</VStateSurface> : null}
    {dispatches.isError ? <VStateSurface tone="error" title={copy.receipts}
      actions={<VButton onClick={() => void dispatches.refetch()}>{copy.retry}</VButton>}>{dispatches.error.message}</VStateSurface> : null}
  </VDenseOpsPage>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Launcher control-surface session page: the same assistant conversation
 * embedded full-size in the launcher main pane, without the floating window's
 * pet stage, drag, hide, or expand/collapse resize IPC. */
export function LauncherAssistantEmbeddedRoute() {
  return <LauncherAssistantRoute embedded />;
}
