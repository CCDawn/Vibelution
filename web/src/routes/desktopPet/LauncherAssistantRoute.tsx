import "../../design/route-css/desktop-pet.tailwind.css";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus,
  hideLauncherAssistant, sendLauncherAssistantMessage, setLauncherAssistantExpanded,
  launcherConversationApi,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  declineLauncherDispatchApproval, launcherDispatchRevisionIsValid,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn,
  getLauncherOperatorAsset, openLauncherFromAssistant, uploadLauncherAttachment,
} from "../../api/launcherAssistant";
import type { SessionContinuationExpectation } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionToolApprovalRequest } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import { VButton, VDenseOpsPage, VNativeButton, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { hasExecutionOwnership, resolveSessionActivity, sessionActivityStatusLabel } from "../sessionActivityState";
import { continuationSnapshotKey, resolveConversationContinuation } from "../chat/conversationContinuationModel";
import { resolveSessionStopTurnId } from "../chat/chatStopTurnModel";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence } from "../chat/chatSubmitAcceptanceReadback";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import { DEFAULT_PET_PREFERENCES } from "./desktopPetPreferences";
import { ChatToolApprovalDialog } from "../chat/ChatToolApprovalDialog";
import { toolApprovalRiskLabel } from "../chat/toolApprovalLabels";
import { authorizationUpgradePreviewIsValid, dispatchWritePreviewIsValid, launcherAgentCreatePreviewIsValid, projectLifecyclePreviewIsValid, managementApprovalActionIsKnown, toolApprovalActionPreview, toolApprovalDisplayName } from "../chat/toolApprovalPreview";
import { useLauncherThemeControl } from "./useLauncherThemeControl";
import { PersonalAssistantComputerPanel } from "../personalAssistant/PersonalAssistantComputerPanel";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import petStyles from "./DesktopAssistantRoute.styles";
import { useLauncherAttachmentHistory } from "./useLauncherAttachmentHistory";
import { classifyComposerFiles, mergeComposerAttachmentsWithRejections, type ComposerImageAttachment } from "../chat/chatComposerSubmitModel";
import {
  launcherAssistantActivity, launcherAssistantPollInterval, launcherAssistantSubmission,
  launcherAssistantQueueReadback, launcherAssistantQueueLabel, launcherAssistantRequestReadback,
  launcherDispatchLabel, type LauncherAssistantSubmission, type LauncherAssistantQueuedAcceptance,
} from "./launcherAssistantModel";

const COPY = {
  zh: {
    title: "个人助理", expand: "展开个人助理聊天", chat: "聊一聊", hide: "隐藏个人助理",
    collapse: "收起聊天", loading: "正在打开原生会话…", unavailable: "个人助理暂不可用",
    retry: "重试", refresh: "刷新", placeholder: "和个人助理聊一聊…", send: "发送", sending: "正在发送…",
    unknownSend: "尚未确认消息是否收到。输入已保留，重试会核对同一条消息。",
    receipts: "派发回执", receiptBoundary: "任务状态来自原生回执，结果仍需验收。", checking: "正在连接 Launcher…",
  },
  en: {
    title: "Personal assistant", expand: "Open assistant chat", chat: "Chat", hide: "Hide assistant",
    collapse: "Collapse chat", loading: "Opening native conversation…", unavailable: "Assistant unavailable",
    retry: "Retry", refresh: "Refresh", placeholder: "Chat with your assistant…", send: "Send", sending: "Sending…",
    unknownSend: "Delivery is unconfirmed. Your input is retained; retry checks the same message.",
    receipts: "Dispatch receipts", receiptBoundary: "Native task status; results still need acceptance.", checking: "Connecting to Launcher…",
  },
} as const;

function approvalAcceptDisabled(request: SessionToolApprovalRequest): boolean {
  const summary = request.argumentSummary;
  return request.toolName === "personal_assistant_manage_tool" && (!managementApprovalActionIsKnown(summary?.assistantAction) || Boolean(summary.assistantArgumentsInvalid)
    || summary?.assistantAction === "agent_create" && !launcherAgentCreatePreviewIsValid(summary)
    || summary?.assistantAction === "authorization_upgrade" && !authorizationUpgradePreviewIsValid(summary)
    || summary?.assistantAction === "dispatch_write" && !dispatchWritePreviewIsValid(summary)
    || summary?.assistantAction === "project_lifecycle" && !projectLifecyclePreviewIsValid(summary));
}

type ContinueAttempt = { requestId: string; expected: SessionContinuationExpectation; accepted: boolean };
type ComposerSnapshot = { draft: string; outstanding: LauncherAssistantSubmission | null; acceptedTurnId: string; queuedAcceptance: LauncherAssistantQueuedAcceptance | null; continuation?: ContinueAttempt; attachments?: ComposerImageAttachment[] };

export function LauncherAssistantRoute() {
  useLauncherThemeControl();
  const client = useQueryClient();
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const [expanded, setExpanded] = useState(false);
  const [computerOpen, setComputerOpen] = useState(false);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [epoch, setEpoch] = useState(0);
  const epochRef = useRef(0);
  const mounted = useRef(true);
  const sending = useRef<{ submission: LauncherAssistantSubmission } | null>(null);
  const resizing = useRef(false);
  const outstanding = useRef<LauncherAssistantSubmission | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ComposerImageAttachment[]>([]);
  const [visibleMessageIds, setVisibleMessageIds] = useState<string[]>([]);
  const attachmentsRef = useRef<ComposerImageAttachment[]>([]);
  const uploadGate = useRef(false);
  const draftRef = useRef("");
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
  const controlGate = useRef(false);
  const refreshedTerminal = useRef<{ sessionId: string; turnId: string } | null>(null);
  const [controlPending, setControlPending] = useState(false);
  const status = useQuery({
    queryKey: ["launcher-assistant", "status"], queryFn: getLauncherAssistantStatus,
    retry: false, staleTime: 0, refetchInterval: expanded && visible ? 10_000 : false,
  });
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
  const composerKey = ["launcher-assistant", "composer", sessionId];
  function saveComposer(patch: Partial<ComposerSnapshot>) {
    client.setQueryDefaults(composerKey, { gcTime: Infinity });
    client.setQueryData<ComposerSnapshot>(composerKey, previous => ({
      draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null, ...previous, ...patch,
    }));
  }
  useEffect(() => {
    if (!sessionId) return;
    const saved = client.getQueryData<ComposerSnapshot>(["launcher-assistant", "composer", sessionId]);
    draftRef.current = saved?.draft || "";
    setDraft(draftRef.current);
    attachmentsRef.current = (saved?.attachments || []).map(item => item.uploadStatus === "uploading" ? { ...item, uploadStatus: "pending" } : item);
    setAttachments(attachmentsRef.current);
    outstanding.current = saved?.outstanding || null;
    setSendUnconfirmed(Boolean(saved?.outstanding));
    setAcceptedTurnId(saved?.acceptedTurnId || "");
    setQueuedAcceptance(saved?.queuedAcceptance || null);
  }, [client, sessionId]);
  const detail = useQuery({
    queryKey: ["launcher-assistant", "detail", sessionId, epoch],
    queryFn: async ({ signal }) => {
      const result = await getLauncherAssistantDetail(sessionId);
      signal.throwIfAborted();
      return result;
    },
    enabled: observingOwnSession, retry: false,
    refetchInterval: query => {
      const continuation = client.getQueryData<ComposerSnapshot>(composerKey)?.continuation;
      const requests = [outstanding.current?.requestId, continuation && !continuation.accepted ? continuation.requestId : ""]
        .filter((id): id is string => Boolean(id));
      // The enabled query supplies one recovery read. Missing data alone is
      // not a reason for an idle/error loop without known outstanding work.
      if (!query.state.data && !acceptedTurnId && !queuedAcceptance && !requests.length) return false;
      return launcherAssistantPollInterval(observingOwnSession, query.state.data, acceptedTurnId, queuedAcceptance, requests);
    },
    refetchIntervalInBackground: false,
  });
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
    const remainingDraft = draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
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
  const dispatches = useQuery({
    queryKey: ["launcher-assistant", "dispatches", epoch],
    queryFn: async ({ signal }) => {
      const result = await getLauncherAssistantDispatches();
      signal.throwIfAborted();
      return result;
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

  useEffect(() => {
    mounted.current = true;
    document.documentElement.dataset.vibelutionDesktopPet = "true";
    document.body.dataset.vibelutionDesktopPet = "true";
    function visibilityChanged() {
      const next = document.visibilityState !== "hidden";
      setVisible(next);
      if (next) void status.refetch();
      if (outstanding.current) setSendUnconfirmed(true);
      epochRef.current += 1;
      setEpoch(epochRef.current);
    }
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      mounted.current = false;
      epochRef.current += 1;
      document.removeEventListener("visibilitychange", visibilityChanged);
      delete document.documentElement.dataset.vibelutionDesktopPet;
      delete document.body.dataset.vibelutionDesktopPet;
      // Window lifecycle never owns a native turn or a dispatched task.
    };
  }, []);

  async function toggle() {
    if (resizing.current || !status.data) return;
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

  async function submit() {
    if (sending.current || uploadGate.current || controlGate.current || !sessionId
      || (attachmentsRef.current.length > 0 && status.data?.attachmentVersion !== 1)) return;
    if (!outstanding.current && attachmentsRef.current.length && !(await uploadAttachments())) return;
    const snapshot = attachmentsRef.current;
    const submission = launcherAssistantSubmission(outstanding.current, draftRef.current, undefined,
      snapshot.map(item => item.artifactId || "").filter(Boolean), snapshot.map(item => item.id));
    if (!submission) return;
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
      if (!mounted.current || requestEpoch !== epochRef.current || sending.current !== flight || outstanding.current !== submission) return;
      outstanding.current = null;
      clearAcceptedAttachments(submission);
      const queueReceipt = acceptance.queuedTurnId ? { id: acceptance.queuedTurnId, clientSubmissionId: acceptance.clientSubmissionId, observed: false } : null;
      const remainingDraft = draftRef.current === (submission.draftSnapshot ?? submission.message) ? "" : draftRef.current;
      draftRef.current = remainingDraft;
      saveComposer({ draft: remainingDraft, outstanding: null, acceptedTurnId: acceptance.turnId, queuedAcceptance: queueReceipt });
      setAcceptedTurnId(acceptance.turnId);
      setQueuedAcceptance(queueReceipt);
      setDraft(remainingDraft);
      setSendUnconfirmed(false);
      void detail.refetch();
      void dispatches.refetch();
      void approvals.refetch();
    } catch {
      if (mounted.current && requestEpoch === epochRef.current && sending.current === flight && outstanding.current === submission) setSendUnconfirmed(true);
    } finally {
      // Native readback can retire this flight before its RPC returns. A late
      // callback owns neither that acceptance nor a newer request's busy flag.
      if (sending.current === flight) {
        sending.current = null;
        if (mounted.current) setSendPending(false);
      }
    }
  }

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

  async function declineDispatch() {
    const selected = dispatchApproval;
    if (!selected || approvalGate.current || !selected.request.availableDecisions.includes("decline")
      || !launcherDispatchRevisionIsValid(selected.request.revision)) return;
    approvalGate.current = true;
    setApprovalPending(true);
    setApprovalError("");
    try {
      await declineLauncherDispatchApproval(selected.row, selected.request);
    } catch (error) {
      if (mounted.current) setApprovalError(errorMessage(error));
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
  const queueRow = detail.data?.queuedTurns?.find(row => row.id === queuedAcceptance?.id) || detail.data?.queuedTurns?.[0];
  const waitingQueueText = lang === "zh" ? "已排队，正在读取原生队列…" : "Queued; reading the native queue…";
  const removedQueueText = lang === "zh" ? "排队消息已移除" : "Queued message removed";
  const queueStatusText = queueReadback.removed ? removedQueueText : queueRow ? launcherAssistantQueueLabel(queueRow.status, lang)
    : queuedAcceptance && !queuedAcceptance.observed ? waitingQueueText : "";
  const statusText = feedback || queueStatusText || (status.isPending ? copy.checking
    : detail.data ? !detail.isError && !approval && !stopping && !acceptedTurnId && !sendPending && !sendUnconfirmed && preferences.idleMessage
        && (activity.execution === "idle" || (activity.execution === "settled" && activity.outcome === "completed"))
      ? preferences.idleMessage : sessionActivityStatusLabel(activity, lang)
      : copy.title);

  if (status.isError) return <VStateSurface fill tone="error" title={copy.unavailable}
    actions={<VButton onClick={() => void status.refetch()}>{copy.retry}</VButton>}>{status.error.message}</VStateSurface>;

  if (!expanded) return <main className={petStyles.root} data-vui-domain-recipe="launcher-assistant"
    data-expanded="false" data-tone={tone} aria-label={displayName}>
    <div className={petStyles.stage}>
      <div className={petStyles.toolbar}>
        <span className={petStyles.status} role="status" aria-live="polite" hidden={!preferences.showStatus && !feedback}>
          <span className={petStyles.statusDot} aria-hidden="true" />{statusText}
        </span>
        <VNativeButton className={petStyles.close} aria-label={copy.hide} onClick={() => void hide()}><X size={14} /></VNativeButton>
      </div>
      <VNativeButton className={petStyles.characterButton} aria-label={copy.expand}
        disabled={!identity || resizePending} onClick={() => void toggle()}>
        <DesktopPetCharacter characterId={preferences.characterId} name={displayName} tone={tone} animationState={animationState} />
      </VNativeButton>
      <VNativeButton className={petStyles.chatCue} disabled={!identity || resizePending} onClick={() => void toggle()}>
        <MessageCircle size={13} aria-hidden="true" />{copy.chat}
      </VNativeButton>
    </div>
  </main>;

  return <VDenseOpsPage hideHeader ariaLabel={displayName}
    className={petStyles.launcherChatWindow} bodyClassName={petStyles.chatBody} style={backgroundStyle}
    data-vui-domain-recipe="launcher-assistant" data-assistant-chat="compact" data-expanded="true" data-tone={tone}
    data-operator-avatar={avatarImage ? "custom" : "default"}
    data-theme-background={backgroundImage ? "custom" : "default"}
    data-theme-background-readability={backgroundImage ? background.data?.readability : undefined}
    toolbarSlot={<header className={petStyles.chatHeader}>
      <div className={petStyles.chatIdentity}>
        <h1 className={petStyles.chatTitle} hidden={!preferences.showTitles}>{displayName}</h1>
        <span className={petStyles.chatStatus} hidden={!preferences.showStatus && !feedback} role={feedback ? "alert" : "status"}>{statusText}</span>
      </div>
      <VButton density="compact" variant="ghost" aria-pressed={computerOpen}
        onClick={() => setComputerOpen(value => !value)}>{lang === "zh" ? "电脑操作" : "Computer"}</VButton>
      <VButton density="compact" variant="ghost" isPending={launcherPending} isDisabled={launcherPending}
        onClick={() => void openLauncher()}>{lang === "zh" ? "打开 Launcher" : "Open Launcher"}</VButton>
      <VNativeButton className={petStyles.close} aria-label={copy.refresh} onClick={() => { void status.refetch(); void detail.refetch(); void dispatches.refetch(); void approvals.refetch(); void client.invalidateQueries({ queryKey: assetQueryPrefix }); }}><RefreshCw size={14} /></VNativeButton>
      <VNativeButton className={petStyles.close} aria-label={copy.collapse} disabled={resizePending} onClick={() => void toggle()}><X size={14} /></VNativeButton>
    </header>}>
    {computerOpen ? <PersonalAssistantComputerPanel active={reading} transport={launcherAssistantComputer}
      onCollapse={() => setComputerOpen(false)} /> : detail.data ? <LazyConversationView
      runtimeApi={launcherConversationApi}
      sessionId={detail.data.id} title={detail.data.title || identity?.displayName || copy.title}
      phase={resolveSessionActivity(detail.data).execution} messages={historyAttachments.messages}
      onVisibleTimelineMessageIds={setVisibleMessageIds}
      turnError={detail.data.lastTurnError}
      defaultFileContext={detail.data.defaultFileContext} assistantDisplayName={displayName}
      userDisplayName={status.data?.operatorProfile?.displayName} userAvatarPreset={status.data?.operatorProfile?.avatarPreset}
      userAvatarImageUrl={avatarImage?.url}
      showHeader={false} showSessionOverview={false} showMentalSnapshots={false} density="compact" composerVariant="codex"
      composerValue={draft} composerPlaceholder={copy.placeholder} composerDisabled={sendPending || sendUnconfirmed || controlPending}
      composerPending={sendPending || controlPending || stopping} composerActionMode={actionMode}
      composerAttachmentInputDisabled={status.data?.attachmentVersion !== 1 || sendPending || sendUnconfirmed || controlPending}
      composerAttachments={attachments}
      onAddComposerAttachments={addAttachments} onRemoveComposerAttachment={removeAttachment}
      onRetryComposerAttachment={id => void uploadAttachments(id)} onRetryComposerAttachmentUploads={() => void uploadAttachments()}
      composerError={sendUnconfirmed ? copy.unknownSend : attachments.some(item => item.uploadStatus === "failed") ? (lang === "zh" ? "附件上传失败，请重试。" : "Attachment upload failed; retry.") : ""}
      submitLabel={sendUnconfirmed ? copy.retry : copy.send} submitPendingLabel={copy.sending}
      composerActionDisabled={sendPending || controlPending || (attachments.length > 0 && status.data?.attachmentVersion !== 1) || (actionMode === "stop" ? stopping || !resolveSessionStopTurnId(detail.data, acceptedTurnId) : actionMode === "send" && !sendUnconfirmed && !draft.trim() && !attachments.length)}
      onComposerChange={value => { draftRef.current = value; setDraft(value); saveComposer({ draft: value }); }} onSubmit={() => void submit()}
      onStop={() => void stopTurn()} onContinueTurn={() => void continueTurn()}
      fallback={<VStateSurface fill tone="loading" title={copy.loading} />}
    /> : <VStateSurface fill tone={detail.isError ? "error" : "loading"} title={detail.isError ? copy.unavailable : copy.loading}
      actions={detail.isError ? <VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton> : undefined}>{detail.error?.message}</VStateSurface>}
    {historyAttachments.missingGenerated ? <VStateSurface tone="error" title={lang === "zh" ? "历史图片缺少附件标识，暂不可查看" : "Historical image has no artifact ID"}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>} /> : null}
    {historyAttachments.failed ? <VStateSurface tone="error" title={lang === "zh" ? "历史附件暂不可用（单个文件上限 8 MiB）" : "Historical attachment unavailable (8 MiB per file limit)"}
      actions={<VButton onClick={historyAttachments.retry}>{copy.retry}</VButton>} /> : null}
    {readingAssets && (avatar.isError || background.isError) ? <VStateSurface tone="error"
      title={lang === "zh" ? "部分外观图片暂不可用，聊天仍可使用" : "Some appearance images are unavailable; chat is ready"}
      actions={<VButton onClick={() => { if (avatar.isError) void avatar.refetch(); if (background.isError) void background.refetch(); }}>{copy.retry}</VButton>} /> : null}
    {status.data?.patrol?.state === "unavailable" || ["unknown", "failed", "interrupted"].some(key => (status.data?.patrol?.deliveryStates[key] || 0) > 0)
      ? <VStateSurface tone="error" title={lang === "zh" ? "部分任务回执无法自动汇报，请查看派发回执" : "Some task receipts could not be reported automatically; check dispatch receipts"} /> : null}
    {approval ? <ChatToolApprovalDialog lang={lang} variant="inline"
      pending={approvalPending || !approval.availableDecisions.includes("accept") || !approval.availableDecisions.includes("decline")}
      rawTitle={approval.toolName} riskLabel={toolApprovalRiskLabel(approval.risk, lang)}
      scopeLabel={lang === "zh" ? "仅本次调用" : "This call only"}
      toolLabels={[{ id: approval.toolName, label: toolApprovalDisplayName(approval.toolName, lang) }]}
      toolName={approval.toolName} actionPreview={toolApprovalActionPreview(approval.argumentSummary, approval.toolName, lang)}
      fullActionPreview={approval.toolName === "personal_assistant_manage_tool" && ["agent_create", "authorization_upgrade", "dispatch_write", "project_lifecycle"].includes(String(approval.argumentSummary?.assistantAction))}
      approveDisabled={approvalAcceptDisabled(approval)}
      onApprove={() => void decide(approval, "accept")} onReject={() => void decide(approval, "decline")} /> : null}
    {dispatchApproval ? <ChatToolApprovalDialog lang={lang} variant="inline"
      pending={approvalPending}
      approveDisabled rejectDisabled={!dispatchApproval.request.availableDecisions.includes("decline") || !launcherDispatchRevisionIsValid(dispatchApproval.request.revision)} rawTitle={dispatchApproval.request.toolName}
      riskLabel={toolApprovalRiskLabel(dispatchApproval.request.risk, lang)}
      scopeLabel={lang === "zh" ? "目标任务 · 仅本次" : "Target task · this call"}
      toolLabels={[{ id: dispatchApproval.request.toolName, label: toolApprovalDisplayName(dispatchApproval.request.toolName, lang) }]}
      toolName={dispatchApproval.request.toolName} fullActionPreview
      actionPreview={[
        `${lang === "zh" ? "项目" : "Project"}: ${dispatchApproval.row.projectId || "—"}`,
        `Agent: ${dispatchApproval.row.agentId || "—"}`,
        `${lang === "zh" ? "派遣 ID" : "Dispatch ID"}: ${dispatchApproval.row.dispatchId}`,
        `${lang === "zh" ? "任务 ID" : "Task ID"}: ${dispatchApproval.row.nativeTaskId}`,
        `${lang === "zh" ? "审批 ID" : "Approval ID"}: ${dispatchApproval.request.approvalId}`,
        lang === "zh" ? "目标项目返回的动作摘要（可能不完整）:" : "Action summary from target project (may be incomplete):",
        JSON.stringify(dispatchApproval.request.targetSummary, null, 2),
        lang === "zh" ? "摘要无法证明完整动作，当前不能安全批准。"
          : "The summary cannot prove the complete action. Approval is unavailable.",
        !launcherDispatchRevisionIsValid(dispatchApproval.request.revision)
          ? (lang === "zh" ? "审批版本不可用，无法安全拒绝；请刷新回执。" : "Approval revision unavailable. Decline is disabled; refresh the receipt.")
          : dispatchApproval.request.availableDecisions.includes("decline")
            ? (lang === "zh" ? "你可以拒绝本次请求。" : "You can decline this request.")
            : (lang === "zh" ? "当前不能拒绝本次请求，请刷新回执。" : "Decline is unavailable; refresh the receipt."),
      ].join("\n")}
      onApprove={() => {}} onReject={() => void declineDispatch()} /> : null}
    {approvalError || approvals.isError ? <VStateSurface tone="error" title={approvalError || (lang === "zh" ? "待授权查询暂不可用" : "Pending approvals unavailable")}
      actions={<VButton onClick={() => { setApprovalError(""); void approvals.refetch(); void dispatches.refetch(); }}>{copy.retry}</VButton>}>{approvals.error?.message}</VStateSurface> : null}
    {detail.data?.queuedTurns?.length || queuedAcceptance ? <section data-launcher-assistant-queue
      className={petStyles.receiptPanel}
      aria-label={lang === "zh" ? "原生消息队列" : "Native message queue"}>
      {queuedAcceptance && !queuedAcceptance.observed ? <p role="status">{waitingQueueText}</p> : null}
      {detail.data?.queuedTurns?.map(row => <p key={row.id} role="status">{launcherAssistantQueueLabel(row.status, lang)}{row.lastError ? ` · ${row.lastError}` : ""}</p>)}
      {queueReadback.removed ? <p role="status">{removedQueueText}</p> : null}
    </section> : null}
    {sendUnconfirmed ? <VStateSurface tone="error" title={copy.unknownSend}
      actions={<VButton onClick={() => void submit()} isDisabled={sendPending || controlPending || stopping}>{copy.retry}</VButton>} /> : null}
    {detail.isError && detail.data ? <VStateSurface tone="error" title={copy.unavailable}
      actions={<VButton onClick={() => void detail.refetch()}>{copy.retry}</VButton>}>{detail.error.message}</VStateSurface> : null}
    {dispatches.isError ? <VStateSurface tone="error" title={copy.receipts}
      actions={<VButton onClick={() => void dispatches.refetch()}>{copy.retry}</VButton>}>{dispatches.error.message}</VStateSurface> : null}
    {dispatches.data?.length ? <section className={petStyles.receiptPanel} aria-label={copy.receipts}>
      <p className={petStyles.receiptBoundary}>{copy.receiptBoundary}</p>
      {dispatches.data.map(row => <p key={row.dispatchId}>{row.projectId || row.dispatchId} · {launcherDispatchLabel(row, lang)}</p>)}
    </section> : null}
  </VDenseOpsPage>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
