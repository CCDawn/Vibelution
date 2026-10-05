import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Building2, Circle, ExternalLink, Loader2, Newspaper, Play, RefreshCw, ShieldAlert, StopCircle, TrendingUp } from "lucide-react";
import { fetchSessionDetail, stopSessionTurn } from "../../api/chat";
import {
  createFinancialTeamRun,
  fetchFinancialTeam,
  fetchFinancialTeamRun,
  fetchFinancialTeamRuns,
  financialTeamKeys,
  isFetchJsonHttpError,
  provisionFinancialTeam,
  recordFinancialTeamTurn,
  submitFinancialTeamPrimaryRole,
  submitFinancialTeamDebate,
  submitFinancialTeamSynthesis,
  type FinancialTeamRole,
  type FinancialTeamRun,
  type FinancialTeamRunList,
} from "../../api/financialTeam";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/financialMarket";
import type { AssistantConversationTurn, SessionDetail } from "../../api/types";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { projectTimelineProcessMessages } from "../../components/conversation/timelineMessageProcessProjection";
import { VButton, VChip, VInput, VSelect, VStateSurface, VSurface } from "../../components/vui";
import styles from "./FinanceAnalystTeam.styles";
import { FinanceReportExport } from "./FinanceReportExport";
import { FinanceResearchApprovals } from "./FinanceResearchApprovals";
import { isNativeResearchStopNotice, localResearchDate } from "./stockResearchModel";

type FinancialTeamPrimaryRole = Extract<FinancialTeamRole, "market" | "fundamental" | "news">;
const PRIMARY_ROLES: FinancialTeamPrimaryRole[] = ["market", "fundamental", "news"];
const ALL_ROLES: FinancialTeamRole[] = [...PRIMARY_ROLES, "bull", "bear"];
const ROLE_LABELS: Record<FinancialTeamRole, [string, string]> = {
  market: ["行情", "Market"],
  fundamental: ["基本面", "Fundamentals"],
  news: ["新闻", "News"],
  bull: ["乐观研究", "Bull case"],
  bear: ["审慎研究", "Bear case"],
};
const ROLE_ICONS: Record<FinancialTeamRole, typeof Activity> = {
  market: TrendingUp,
  fundamental: Building2,
  news: Newspaper,
  bull: Activity,
  bear: ShieldAlert,
};
const DEPTH_OPTIONS = [
  { id: "brief", label: "1 · 快速" },
  { id: "basic", label: "2 · 基础" },
  { id: "standard", label: "3 · 标准" },
  { id: "detailed", label: "4 · 深入" },
  { id: "exhaustive", label: "5 · 全面" },
] as const;
const TEAM_POLL_MS = 1800;
const MAX_LIVE_POLL_MS = 20 * 60 * 1000;

type RoleState = "missing" | "loading" | "unavailable" | "waiting" | "running" | "completed" | "failed" | "stopped" | "incomplete";
type NativeTurnProjection = {
  turn: AssistantConversationTurn | null;
  answer: string;
  activity: string;
  state: RoleState;
  submissionSeen: boolean;
};

function newFinancialRunRequestKey(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (!cryptoApi?.getRandomValues) throw new Error("Secure request IDs are unavailable");
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function exactSubmission(detail: SessionDetail | undefined, submissionId: string, turnId: string): { turn: AssistantConversationTurn | null; submissionSeen: boolean } {
  const messages = projectTimelineProcessMessages(detail?.messages ?? []);
  const userTurnIds = new Set(messages.flatMap((message) => {
    if (message.role !== "user" || String(message.metadata?.clientSubmissionId ?? "") !== submissionId) return [];
    const nativeTurnId = String(message.metadata?.turnId ?? "").trim();
    return nativeTurnId ? [nativeTurnId] : [];
  }));
  const associatedAssistants = messages.filter((message): message is AssistantConversationTurn => {
    if (message.role !== "assistant") return false;
    const metadataSubmissionId = String(message.metadata?.clientSubmissionId ?? "");
    const nativeSubmissionTurn = userTurnIds.has(message.turnId);
    return metadataSubmissionId === submissionId || nativeSubmissionTurn;
  });
  const associatedTurnIds = new Set(associatedAssistants.map((message) => message.turnId));
  const seen = userTurnIds.size > 0
    || messages.some((message) => message.role === "user" && String(message.metadata?.clientSubmissionId ?? "") === submissionId)
    || associatedAssistants.length > 0;
  if (associatedTurnIds.size > 1) return { turn: null, submissionSeen: true };
  const associatedTurnId = associatedTurnIds.values().next().value as string | undefined;
  if (turnId) {
    const exact = associatedAssistants.find((message) => message.turnId === turnId);
    if (exact && (userTurnIds.has(turnId) || String(exact.metadata?.clientSubmissionId ?? "") === submissionId)) {
      return { turn: exact, submissionSeen: true };
    }
    return { turn: null, submissionSeen: seen };
  }
  if (!associatedTurnId) return { turn: null, submissionSeen: seen };
  return {
    turn: associatedAssistants.find((message) => message.turnId === associatedTurnId) ?? null,
    submissionSeen: true,
  };
}

function finalAnswer(turn: AssistantConversationTurn | null): string {
  if (!turn || turn.status !== "completed") return "";
  const answer = turn.turnItems
    .filter((item) => item.type === "agent_message" && item.phase === "final_answer" && item.status === "completed" && Boolean(item.text.trim()))
    .map((item) => item.type === "agent_message" ? item.text.trim() : "")
    .filter(Boolean)
    .join("\n\n");
  return isNativeResearchStopNotice(answer) ? "" : answer;
}

function projectNativeTurn(detail: SessionDetail | undefined, ref: { clientSubmissionId: string; turnId: string }): NativeTurnProjection {
  const { turn, submissionSeen } = exactSubmission(detail, ref.clientSubmissionId, ref.turnId);
  const answer = finalAnswer(turn);
  const activities = (turn?.turnItems ?? []).filter((item) => item.status === "running" || item.status === "pending");
  const latestActivity = [...activities].reverse().find((item) => item.type === "status" || item.type === "tool_call" || item.type === "agent_message");
  const activity = latestActivity?.type === "tool_call"
    ? "调用 " + (latestActivity.title || latestActivity.toolName)
    : latestActivity?.type === "agent_message"
      ? latestActivity.text.trim().slice(-180)
      : latestActivity?.type === "status"
        ? latestActivity.text
        : "正在分析";
  const exactTerminal = turn && detail?.lastTurnTerminalTurnId === turn.turnId ? String(detail.terminalReason ?? "").toLowerCase() : "";
  const stopped = /stop|cancel|abort/.test(exactTerminal);
  const failed = turn?.status === "failed" || /failed|error/.test(exactTerminal);
  const state: RoleState = !turn
    ? !detail && ref.turnId ? "loading" : submissionSeen || ref.turnId ? "waiting" : "missing"
    : turn.status === "pending" || turn.status === "running" ? "running"
      : stopped ? "stopped"
        : failed ? "failed"
          : answer ? "completed" : turn.status === "completed" ? "incomplete" : "waiting";
  return { turn, answer, activity, state, submissionSeen };
}

function statusText(state: RoleState, zh: boolean): string {
  const text: Record<RoleState, [string, string]> = {
    missing: ["未提交", "Not submitted"],
    loading: ["读取对话", "Loading conversation"],
    unavailable: ["读取失败", "Read unavailable"],
    waiting: ["等待响应", "Waiting for response"],
    running: ["分析中", "Running"],
    completed: ["已完成", "Completed"],
    failed: ["失败", "Failed"],
    stopped: ["已停止", "Stopped"],
    incomplete: ["缺少最终回答", "No final answer"],
  };
  return text[state][zh ? 0 : 1];
}

function statusTone(state: RoleState): "neutral" | "success" | "warning" | "accent" {
  if (state === "completed") return "success";
  if (state === "failed" || state === "stopped" || state === "incomplete") return "warning";
  if (state === "running" || state === "waiting") return "accent";
  return "neutral";
}

function isTerminal(state: RoleState): boolean {
  return state === "completed" || state === "failed" || state === "stopped" || state === "incomplete";
}

function compactError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

export function FinanceAnalystTeam({ assistant, stock, zh, onOpenSession, onSelectedRunChange, requestedRunId = "", onBackToBatch }: {
  assistant: FinancialAssistant;
  stock: StockIdentity;
  zh: boolean;
  onOpenSession: (sessionId: string) => void;
  onSelectedRunChange?: (run: FinancialTeamRun | null) => void;
  requestedRunId?: string;
  onBackToBatch?: () => void;
}) {
  const queryClient = useQueryClient();
  const [periodDays, setPeriodDays] = useState<7 | 30 | 90>(30);
  const [researchDate, setResearchDate] = useState(() => localResearchDate());
  const [depth, setDepth] = useState<(typeof DEPTH_OPTIONS)[number]["id"]>("standard");
  const [selectedRunId, setSelectedRunId] = useState(requestedRunId);
  const [setupPending, setSetupPending] = useState(false);
  const [startPending, setStartPending] = useState(false);
  const [stoppingRole, setStoppingRole] = useState<FinancialTeamRole | "synthesis" | "">("");
  const [pendingRoles, setPendingRoles] = useState<Set<FinancialTeamRole>>(() => new Set());
  const [operationError, setOperationError] = useState("");
  const [debatingRunId, setDebatingRunId] = useState("");
  const [synthesisRunId, setSynthesisRunId] = useState("");
  const submitGates = useRef(new Set<string>());
  const debateGates = useRef(new Set<string>());
  const synthesisGates = useRef(new Set<string>());
  const recoveryGates = useRef(new Set<string>());
  const stopGate = useRef(false);
  const createRequest = useRef<{ fingerprint: string; key: string; sourceRunId?: string } | null>(null);
  const mounted = useRef(false);
  const teamKey = financialTeamKeys.detail(assistant.agentId);
  const runsKey = financialTeamKeys.runs(assistant.agentId);
  const teamQuery = useQuery({
    queryKey: teamKey,
    queryFn: ({ signal }) => fetchFinancialTeam(assistant.agentId, { signal }),
    staleTime: 15_000,
    retry: false,
  });
  const runsQuery = useQuery({
    queryKey: runsKey,
    queryFn: async ({ signal }) => {
      const result = await fetchFinancialTeamRuns(assistant.agentId, { signal, limit: 20 });
      if (result.assistantAgentId !== assistant.agentId || result.runs.some((run) => run.assistantAgentId !== assistant.agentId)) throw new Error(zh ? "研究记录归属不匹配" : "Research owner mismatch");
      return result;
    },
    staleTime: 5_000,
    retry: false,
    refetchInterval: (query) => query.state.data?.runs.some((run) => run.coordinationStatus === "waiting" || run.coordinationStatus === "running") ? TEAM_POLL_MS : false,
  });
  const runs = runsQuery.data?.runs ?? [];
  const listedRun = runs.find((run) => run.runId === selectedRunId);
  const exactRunQuery = useQuery({
    queryKey: financialTeamKeys.run(assistant.agentId, selectedRunId),
    queryFn: async ({ signal }) => {
      const result = await fetchFinancialTeamRun(assistant.agentId, selectedRunId, { signal });
      if (result.assistantAgentId !== assistant.agentId || result.runId !== selectedRunId) throw new Error(zh ? "研究记录归属不匹配" : "Research owner mismatch");
      return result;
    },
    enabled: Boolean(selectedRunId && !listedRun),
    staleTime: 3_000,
    retry: false,
    refetchInterval: (query) => query.state.data?.coordinationStatus === "waiting" || query.state.data?.coordinationStatus === "running" ? TEAM_POLL_MS : false,
  });
  const selectedRun = selectedRunId ? listedRun ?? exactRunQuery.data ?? null : runs[0] ?? null;
  useEffect(() => { onSelectedRunChange?.(selectedRun); }, [onSelectedRunChange, selectedRun]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!selectedRunId && runs[0]) setSelectedRunId(runs[0].runId);
  }, [runs, selectedRunId]);

  const detailSpecs = useMemo(() => selectedRun ? [
    ...ALL_ROLES.filter((role) => selectedRun.analysts[role]).map((role) => ({
      key: role,
      ref: selectedRun.analysts[role]!,
      run: selectedRun,
    })),
    { key: "synthesis" as const, ref: selectedRun.synthesis, run: selectedRun },
  ] : [], [selectedRun]);
  const detailQueries = useQueries({
    queries: detailSpecs.map((spec) => ({
      queryKey: ["financial-team-session", assistant.agentId, spec.run.runId, spec.key, spec.ref.sessionId, spec.ref.clientSubmissionId, spec.ref.turnId, spec.run.coordinationStatus ?? "legacy"],
      queryFn: ({ signal }) => fetchSessionDetail(spec.ref.sessionId, { transcriptScope: "all", includeSecondary: false, signal }),
      enabled: Boolean(spec.ref.sessionId),
      staleTime: 0,
      retry: false,
      refetchInterval: (query: { state: { data: unknown } }) => {
        const createdAt = Date.parse(spec.run.createdAt);
        const backendRunning = spec.run.coordinationStatus === "waiting" || spec.run.coordinationStatus === "running";
        if (!backendRunning && (!Number.isFinite(createdAt) || Date.now() - createdAt > MAX_LIVE_POLL_MS)) return false;
        const projection = projectNativeTurn(query.state.data as SessionDetail | undefined, spec.ref);
        return isTerminal(projection.state) ? false : TEAM_POLL_MS;
      },
    })),
  });
  const details = useMemo(() => new Map(detailSpecs.map((spec, index) => [spec.key, detailQueries[index]?.data as SessionDetail | undefined])), [detailQueries, detailSpecs]);
  const projections = useMemo(() => {
    const result = new Map<FinancialTeamRole | "synthesis", NativeTurnProjection>();
    detailSpecs.forEach((spec, index) => {
      const projection = projectNativeTurn(details.get(spec.key), spec.ref);
      if (detailQueries[index]?.isError && !details.get(spec.key)) projection.state = "unavailable";
      result.set(spec.key, projection);
    });
    return result;
  }, [detailQueries, detailSpecs, details]);

  const updateRun = useCallback((next: FinancialTeamRun) => {
    queryClient.setQueryData<FinancialTeamRunList>(runsKey, (current) => ({
      assistantAgentId: assistant.agentId,
      runs: [next, ...(current?.runs ?? []).filter((run) => run.runId !== next.runId)],
    }));
    queryClient.setQueryData(financialTeamKeys.run(assistant.agentId, next.runId), next);
  }, [assistant.agentId, queryClient, runsKey]);

  const bindTurn = useCallback(async (run: FinancialTeamRun, role: FinancialTeamRole | "synthesis", turnId: string) => {
    const ref = role === "synthesis" ? run.synthesis : run.analysts[role];
    if (!ref) throw new Error(zh ? "此旧版研究记录没有该分析角色" : "This saved run does not include that role");
    const updated = await recordFinancialTeamTurn(assistant.agentId, run.runId, role, {
      sessionId: ref.sessionId,
      clientSubmissionId: ref.clientSubmissionId,
      turnId,
    });
    updateRun(updated);
    return updated;
  }, [assistant.agentId, updateRun, zh]);

  const submitRole = useCallback(async (run: FinancialTeamRun, role: FinancialTeamPrimaryRole) => {
    const ref = run.analysts[role];
    if (!ref || ref.turnId) return;
    const gateKey = run.runId + ":" + role;
    if (submitGates.current.has(gateKey)) return;
    submitGates.current.add(gateKey);
    if (mounted.current) setPendingRoles((current) => new Set(current).add(role));
    try {
      const updated = await submitFinancialTeamPrimaryRole(assistant.agentId, run.runId, role);
      updateRun(updated);
    } finally {
      submitGates.current.delete(gateKey);
      if (mounted.current) setPendingRoles((current) => {
        const next = new Set(current);
        next.delete(role);
        return next;
      });
    }
  }, [assistant.agentId, updateRun]);

  const startDebate = useCallback(async (run: FinancialTeamRun, retry = false) => {
    if (run.schemaVersion < 2) return;
    if (retry) debateGates.current.delete(run.runId);
    if (debateGates.current.has(run.runId)) return;
    debateGates.current.add(run.runId);
    setDebatingRunId(run.runId);
    setOperationError("");
    try {
      const updated = await submitFinancialTeamDebate(assistant.agentId, run.runId);
      updateRun(updated);
      void queryClient.invalidateQueries({ queryKey: runsKey });
    } catch (error) {
      setOperationError(compactError(error, zh ? "多空分析未提交" : "Debate could not start"));
    } finally {
      if (mounted.current) setDebatingRunId("");
    }
  }, [assistant.agentId, queryClient, runsKey, updateRun, zh]);

  const startSynthesis = useCallback(async (run: FinancialTeamRun, retry = false) => {
    if (retry) synthesisGates.current.delete(run.runId);
    if (synthesisGates.current.has(run.runId)) return;
    synthesisGates.current.add(run.runId);
    setSynthesisRunId(run.runId);
    setOperationError("");
    try {
      const updated = await submitFinancialTeamSynthesis(assistant.agentId, run.runId);
      updateRun(updated);
      void queryClient.invalidateQueries({ queryKey: runsKey });
    } catch (error) {
      setOperationError(compactError(error, zh ? "主助手汇总未提交" : "Synthesis could not start"));
    } finally {
      if (mounted.current) setSynthesisRunId("");
    }
  }, [assistant.agentId, queryClient, runsKey, updateRun, zh]);

  const allPrimaryComplete = Boolean(selectedRun && PRIMARY_ROLES.every((role) => projections.get(role)?.state === "completed"));
  const synthesisRoles = selectedRun?.schemaVersion === 1 ? PRIMARY_ROLES : ALL_ROLES;
  const allAnalystsComplete = Boolean(selectedRun && synthesisRoles.every((role) => projections.get(role)?.state === "completed"));
  useEffect(() => {
    if (!selectedRun || selectedRun.coordinationStatus || !allPrimaryComplete || selectedRun.schemaVersion < 2) return;
    if (selectedRun.analysts.bull?.turnId && selectedRun.analysts.bear?.turnId) return;
    void startDebate(selectedRun);
  }, [allPrimaryComplete, selectedRun, startDebate]);
  useEffect(() => {
    if (!selectedRun || selectedRun.coordinationStatus || !allAnalystsComplete || selectedRun.synthesis.turnId) return;
    void startSynthesis(selectedRun);
  }, [allAnalystsComplete, selectedRun, startSynthesis]);

  useEffect(() => {
    if (!selectedRun) return;
    detailSpecs.forEach((spec) => {
      if (spec.key === "synthesis" || spec.ref.turnId) return;
      const projection = projections.get(spec.key);
      const turnId = projection?.turn?.turnId;
      if (!turnId) return;
      const recoveryKey = selectedRun.runId + ":" + spec.key + ":" + turnId;
      if (recoveryGates.current.has(recoveryKey)) return;
      recoveryGates.current.add(recoveryKey);
      void bindTurn(selectedRun, spec.key, turnId).catch((error) => {
        if (mounted.current) setOperationError(compactError(error, zh ? "会话进度恢复失败" : "Could not recover conversation progress"));
      });
    });
  }, [bindTurn, detailSpecs, projections, selectedRun, zh]);

  async function setupTeam() {
    if (setupPending) return;
    setSetupPending(true);
    setOperationError("");
    try {
      const team = await provisionFinancialTeam(assistant.agentId);
      queryClient.setQueryData(teamKey, team);
      void queryClient.invalidateQueries({ queryKey: runsKey });
    } catch (error) {
      setOperationError(compactError(error, zh ? "团队初始化失败" : "Team setup failed"));
    } finally {
      if (mounted.current) setSetupPending(false);
    }
  }

  async function startResearch(restartRun?: FinancialTeamRun) {
    if (startPending || teamQuery.data?.status !== "ready") return;
    setStartPending(true);
    setOperationError("");
    const payload = restartRun
      ? {
          symbol: restartRun.symbol,
          periodDays: restartRun.periodDays,
          researchDate: restartRun.researchDate || researchDate,
          depth: restartRun.depth || "standard",
        }
      : { symbol: stock.symbol, periodDays, researchDate, depth };
    const fingerprint = JSON.stringify(payload);
    if (restartRun) {
      if (
        !createRequest.current
        || createRequest.current.fingerprint !== fingerprint
        || createRequest.current.sourceRunId !== restartRun.runId
      ) {
        createRequest.current = { fingerprint, key: newFinancialRunRequestKey(), sourceRunId: restartRun.runId };
      }
    } else if (
      !createRequest.current
      || createRequest.current.fingerprint !== fingerprint
      || Boolean(createRequest.current.sourceRunId)
    ) {
      createRequest.current = { fingerprint, key: newFinancialRunRequestKey() };
    }
    try {
      const run = await createFinancialTeamRun(assistant.agentId, payload, createRequest.current.key);
      createRequest.current = null;
      updateRun(run);
      setSelectedRunId(run.runId);
      const results = await Promise.allSettled(PRIMARY_ROLES.map((role) => submitRole(run, role)));
      const failed = results.flatMap((result, index) => result.status === "rejected" ? [ROLE_LABELS[PRIMARY_ROLES[index]][zh ? 0 : 1] + "：" + compactError(result.reason, zh ? "未提交" : "Not submitted")] : []);
      if (failed.length) setOperationError(failed.join("；"));
      void queryClient.invalidateQueries({ queryKey: runsKey });
    } catch (error) {
      if (isFetchJsonHttpError(error) && error.status < 500) createRequest.current = null;
      setOperationError(compactError(error, zh ? "研究轮次创建失败" : "Could not create research run"));
    } finally {
      if (mounted.current) setStartPending(false);
    }
  }

  async function resumeRun() {
    if (!selectedRun) return;
    setOperationError("");
    const missingPrimary = PRIMARY_ROLES.filter((role) => !selectedRun.analysts[role]?.turnId);
    const results = await Promise.allSettled(missingPrimary.map((role) => submitRole(selectedRun, role)));
    const failed = results.flatMap((result, index) => result.status === "rejected" ? [ROLE_LABELS[missingPrimary[index]][zh ? 0 : 1] + "：" + compactError(result.reason, zh ? "恢复失败" : "Could not resume")] : []);
    if (failed.length) setOperationError(failed.join("；"));
    void queryClient.invalidateQueries({ queryKey: runsKey });
  }

  async function stopExactTurn(role: FinancialTeamRole | "synthesis", ref: { sessionId: string; turnId: string }) {
    if (stopGate.current || !ref.turnId) return;
    stopGate.current = true;
    setStoppingRole(role);
    setOperationError("");
    try {
      await stopSessionTurn(ref.sessionId, ref.turnId);
      const spec = detailSpecs.find((item) => item.key === role);
      if (spec) await queryClient.invalidateQueries({ queryKey: ["financial-team-session", assistant.agentId, spec.run.runId, role] });
    } catch (error) {
      setOperationError(compactError(error, zh ? "停止请求失败" : "Stop request failed"));
    } finally {
      stopGate.current = false;
      if (mounted.current) setStoppingRole("");
    }
  }

  const teamReady = teamQuery.data?.status === "ready";
  const readyCount = teamQuery.data?.roles.filter((role) => role.status === "ready").length ?? 0;
  const hasMissingPrimary = Boolean(selectedRun && PRIMARY_ROLES.some((role) => !selectedRun.analysts[role]?.turnId));
  const serverCoordinated = Boolean(selectedRun?.coordinationStatus);
  const synthesisProjection = projections.get("synthesis");
  const detailsLoading = [...projections.values()].some((projection) => projection.state === "loading");
  const detailsUnavailable = [...projections.values()].some((projection) => projection.state === "unavailable");
  const hasRestartableTurn = Boolean(selectedRun && (
    ALL_ROLES.some((role) => {
      const turnId = selectedRun.analysts[role]?.turnId;
      const state = projections.get(role)?.state;
      return Boolean(turnId && (state === "failed" || state === "stopped" || state === "incomplete"));
    })
    || selectedRun.synthesis.turnId && (synthesisProjection?.state === "failed" || synthesisProjection?.state === "stopped" || synthesisProjection?.state === "incomplete")
  ));

  function renderTurnCard(role: FinancialTeamRole) {
    if (!selectedRun) return null;
    const ref = selectedRun.analysts[role];
    if (!ref) return null;
    const projection = projections.get(role) ?? { turn: null, answer: "", activity: "", state: "missing" as const, submissionSeen: false };
    const Icon = ROLE_ICONS[role];
    const isPending = pendingRoles.has(role);
    const canStop = Boolean(ref.turnId && projection.state === "running");
    return <VSurface key={role} as="article" tone="card" padding="normal" className={styles.analystCard} data-role={role}>
      <div className={styles.cardHeading}>
        <div className={styles.roleTitle}><Icon size={16} /><h3>{ROLE_LABELS[role][zh ? 0 : 1]}</h3></div>
        <VChip tone={statusTone(isPending ? "waiting" : projection.state)}>{statusText(isPending ? "waiting" : projection.state, zh)}</VChip>
      </div>
      {projection.activity && projection.state === "running" ? <p className={styles.activity} role="status">{projection.activity}</p> : null}
      {projection.answer ? <div className={styles.answer} data-turn-id={projection.turn?.turnId}><LazyConversationMarkdownRenderer content={projection.answer} language={zh ? "zh" : "en"} /></div> : <p className={styles.placeholder}>{projection.state === "loading" ? (zh ? "正在读取本轮对话" : "Loading this run's conversation") : projection.state === "unavailable" ? (zh ? "会话暂无法读取，请刷新重试" : "Conversation unavailable; refresh to retry") : projection.state === "missing" ? (zh ? "等待提交" : "Ready to submit") : projection.state === "waiting" ? (zh ? "已提交，等待状态同步" : "Submitted; waiting for status") : projection.state === "running" || isPending ? (zh ? "正在生成分析结果" : "Generating analysis") : projection.state === "incomplete" ? (zh ? "本轮没有最终回答，可查看对话核对" : "No final answer; review the conversation") : projection.state === "failed" ? (zh ? "本轮失败，查看对话了解详情" : "Analysis failed; review the conversation") : projection.state === "stopped" ? (zh ? "本轮已停止" : "Analysis stopped") : (zh ? "尚无分析结果" : "No result yet")}</p>}
      <div className={styles.cardActions}>
        <VButton variant="ghost" icon={<ExternalLink size={14} />} onPress={() => onOpenSession(ref.sessionId)}>{zh ? "查看对话" : "View conversation"}</VButton>
        {canStop ? <VButton variant="secondary" icon={<StopCircle size={14} />} isPending={stoppingRole === role} isDisabled={Boolean(stoppingRole)} onPress={() => void stopExactTurn(role, ref)}>{zh ? "停止本轮" : "Stop turn"}</VButton> : null}
      </div>
    </VSurface>;
  }

  return <div className={styles.page} data-finance-analyst-team>
    <div className={styles.header}>
      <div className={styles.headingGroup}>
        <h1>{zh ? "分析团队" : "Analyst team"}</h1>
        <p>{zh ? "行情、基本面、新闻与多空研判" : "Market, fundamentals, news and opposing reviews"}</p>
      </div>
      <div className={styles.headerActions}>
        {onBackToBatch ? <VButton variant="ghost" onPress={onBackToBatch}>{zh ? "返回批次" : "Back to batch"}</VButton> : null}
        <VChip tone={teamQuery.isPending ? "neutral" : teamReady ? "success" : teamQuery.data?.status === "needs_attention" ? "warning" : "neutral"}>{teamQuery.isPending ? (zh ? "检查中" : "Checking") : teamReady ? readyCount + "/5 " + (zh ? "就绪" : "ready") : teamQuery.data?.status === "needs_attention" ? (zh ? "需检查配置" : "Needs attention") : (zh ? "未初始化" : "Not set up")}</VChip>
        <VButton variant="ghost" icon={<RefreshCw size={14} />} isPending={teamQuery.isFetching || runsQuery.isFetching || exactRunQuery.isFetching} onPress={() => { void teamQuery.refetch(); void runsQuery.refetch(); if (selectedRunId && !listedRun) void exactRunQuery.refetch(); detailQueries.forEach((query) => { void query.refetch(); }); }}>{zh ? "刷新" : "Refresh"}</VButton>
      </div>
    </div>

    {operationError ? <VStateSurface tone="error" title={zh ? "操作未完成" : "Action incomplete"}><span className={styles.errorText}>{operationError}</span></VStateSurface> : null}
    {selectedRunId && !listedRun && exactRunQuery.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取所选研究" : "Loading selected research"} /> : null}
    {selectedRunId && !listedRun && exactRunQuery.isError ? <VStateSurface tone="error" title={zh ? "所选研究无法读取" : "Selected research unavailable"} actions={<VButton onPress={() => void exactRunQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
    {selectedRun?.coordinationStatus === "blocked" ? <VStateSurface tone="error" title={zh ? "研究暂停" : "Research paused"}><span className={styles.errorText}>{selectedRun.coordinationError || (zh ? "查看分析对话核对本轮状态。" : "Review the analysis conversation for this run.")}</span></VStateSurface> : null}
    {teamQuery.isError ? <VStateSurface tone="error" title={zh ? "团队状态不可用" : "Team unavailable"} actions={<VButton onPress={() => void teamQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{compactError(teamQuery.error, zh ? "无法读取团队配置" : "Could not load team")}</VStateSurface> : null}
    {teamQuery.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取分析团队" : "Loading analyst team"} /> : null}
    {teamQuery.data && !teamReady ? <VSurface tone="panel" padding="normal" className={styles.setupPanel}>
      <div className={styles.setupCopy}><strong>{zh ? "需要初始化 5 位分析员" : "Set up the five analysts"}</strong><span>{zh ? "只继承主助手模型与已授权工具；乐观和审慎分析员只读取本轮证据。" : "They inherit the assistant model and granted tools; debate roles read this run's evidence only."}</span></div>
      <VButton variant="primary" icon={<Play size={14} />} isPending={setupPending} isDisabled={setupPending || teamQuery.data.status === "needs_attention"} onPress={() => void setupTeam()}>{zh ? "初始化团队" : "Set up team"}</VButton>
      {teamQuery.data.status === "needs_attention" ? <p className={styles.warning}>{zh ? "检测到人工改过的成员配置；请先在 Agent 管理中核对。" : "A member was edited; review it in Agent management first."}</p> : null}
      <div className={styles.roster}>{teamQuery.data.roles.map((member) => <span key={member.role} className={styles.rosterItem}><Circle size={11} className={member.status === "ready" ? styles.readyIcon : styles.pendingIcon} />{member.label}</span>)}</div>
    </VSurface> : null}

    {teamReady ? <>
      <VSurface tone="toolbar" padding="normal" className={styles.controls}>
        <div className={styles.stockIdentity}><strong>{stock.name}</strong><span>{stock.ticker}</span></div>
        <label className={styles.field}>{zh ? "研究日期" : "Research date"}<VInput type="date" value={researchDate} max={localResearchDate()} onChange={(event) => setResearchDate(event.target.value)} /></label>
        <label className={styles.field}>{zh ? "观察周期" : "Lookback"}<VSelect selectedKey={String(periodDays)} aria-label={zh ? "分析团队观察周期" : "Analyst team lookback"} onSelectionChange={(key) => setPeriodDays(Number(key) as 7 | 30 | 90)} options={[{ id: "7", label: zh ? "近 7 天" : "7 days" }, { id: "30", label: zh ? "近 30 天" : "30 days" }, { id: "90", label: zh ? "近 90 天" : "90 days" }]} /></label>
        <label className={styles.field}>{zh ? "研究深度" : "Research depth"}<VSelect selectedKey={depth} aria-label={zh ? "分析团队研究深度" : "Analyst team research depth"} onSelectionChange={(key) => setDepth(key as typeof depth)} options={DEPTH_OPTIONS.map((option) => ({ id: option.id, label: option.label }))} /></label>
        <VButton variant="primary" icon={<Play size={14} />} isPending={startPending} isDisabled={startPending || !researchDate || new Date(researchDate + "T00:00:00").getTime() > Date.now()} onPress={() => void startResearch()}>{zh ? "开始五方研究" : "Start five-agent run"}</VButton>
      </VSurface>

      {runsQuery.isError ? <VStateSurface tone="error" title={zh ? "研究记录不可用" : "Run history unavailable"} actions={<VButton onPress={() => void runsQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
      {runsQuery.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取研究记录" : "Loading runs"} /> : null}
      {runs.length ? <div className={styles.history} aria-label={zh ? "最近分析轮次" : "Recent analyst runs"}>
        {runs.slice(0, 8).map((run) => <VButton key={run.runId} variant="secondary" className={[styles.historyButton, run.runId === selectedRun?.runId ? styles.historySelected : ""].join(" ")} aria-pressed={run.runId === selectedRun?.runId} onPress={() => setSelectedRunId(run.runId)}>
          <span className={styles.historyItem}><strong>{run.symbol}</strong><span>{run.researchDate || new Date(run.createdAt).toLocaleDateString()} · {run.periodDays}{zh ? "天" : "d"}</span></span>
          <VChip tone="neutral">{run.stage === "synthesis" ? (zh ? "汇总阶段" : "Synthesis stage") : run.stage === "debate" ? (zh ? "多空分析" : "Debate") : (zh ? "基础分析" : "Research")}</VChip>
        </VButton>)}
      </div> : !selectedRunId && !runsQuery.isPending && !runsQuery.isError ? <VStateSurface tone="empty" title={zh ? "还没有研究轮次" : "No analyst runs yet"} /> : null}

      {selectedRun ? <>
        <FinanceResearchApprovals assistantAgentId={assistant.agentId} zh={zh} turns={detailSpecs.flatMap((spec) =>
          projections.get(spec.key)?.state === "running" && spec.ref.turnId
            ? [{ role: spec.key, ...spec.ref, symbol: selectedRun.symbol }] : [])} />
        <div className={styles.runHeader}>
          <div><span className={styles.eyebrow}>{zh ? "本轮任务" : "Selected run"}</span><h2>{selectedRun.symbol} · {selectedRun.researchDate || "—"}</h2></div>
          <div className={styles.runMeta}><VChip tone="neutral">{selectedRun.periodDays}{zh ? "天" : " days"}</VChip><VChip tone="neutral">{DEPTH_OPTIONS.find((item) => item.id === selectedRun.depth)?.label || (zh ? "旧版深度" : "Legacy depth")}</VChip></div>
          <div className={styles.runActions}>
            {hasMissingPrimary ? <VButton variant="secondary" icon={<RefreshCw size={14} />} isDisabled={startPending} onPress={() => void resumeRun()}>{zh ? "恢复本轮" : "Resume run"}</VButton> : null}
            {hasRestartableTurn ? <VButton variant="secondary" icon={<RefreshCw size={14} />} isPending={startPending} isDisabled={startPending} onPress={() => void startResearch(selectedRun)}>{zh ? "重新开始研究" : "Start new research"}</VButton> : null}
            {!serverCoordinated && selectedRun.schemaVersion >= 2 && allPrimaryComplete && (!selectedRun.analysts.bull?.turnId || !selectedRun.analysts.bear?.turnId) ? <VButton variant="secondary" isPending={debatingRunId === selectedRun.runId} onPress={() => void startDebate(selectedRun, true)}>{zh ? "重试多空分析" : "Retry debate"}</VButton> : null}
            {!serverCoordinated && allAnalystsComplete && !selectedRun.synthesis.turnId ? <VButton variant="secondary" isPending={synthesisRunId === selectedRun.runId} onPress={() => void startSynthesis(selectedRun, true)}>{zh ? "重试汇总" : "Retry synthesis"}</VButton> : null}
          </div>
        </div>
        {selectedRun.schemaVersion < 2 ? <p className={styles.warning}>{zh ? "旧版三方研究；五方研究需新建一轮。" : "Legacy three-analyst research. Start a new run for five analysts."}</p> : null}
        <div className={styles.progress} role="status">
          <span>{zh ? "研究进度" : "Progress"}</span>
          <strong>{detailsLoading || detailsUnavailable ? "—" : ALL_ROLES.filter((role) => projections.get(role)?.state === "completed").length}/5</strong>
          <span>{detailsLoading ? (zh ? "读取本轮对话" : "Loading run conversations") : detailsUnavailable ? (zh ? "部分对话暂无法读取" : "Some conversations are unavailable") : selectedRun.synthesis.turnId ? (synthesisProjection?.state === "completed" ? (zh ? "主助手已汇总" : "Synthesis complete") : synthesisProjection?.state === "running" ? (zh ? "主助手汇总中" : "Synthesis running") : `${zh ? "主助手汇总" : "Synthesis"} · ${statusText(synthesisProjection?.state ?? "missing", zh)}`) : selectedRun.schemaVersion < 2 ? (zh ? "旧版轮次" : "Legacy run") : selectedRun.stage === "debate" ? (zh ? "多空分析阶段" : "Debate stage") : (zh ? "基础研究阶段" : "Research stage")}</span>
        </div>
        <div className={styles.analystGrid}>{ALL_ROLES.map((role) => renderTurnCard(role))}</div>
        <VSurface as="section" tone="panel" padding="normal" className={styles.synthesis} data-financial-team-synthesis>
          <div className={styles.cardHeading}><div className={styles.roleTitle}><Activity size={16} /><h3>{zh ? "主助手综合结论" : "Assistant synthesis"}</h3></div><VChip tone={statusTone(synthesisProjection?.state ?? "missing")}>{statusText(synthesisProjection?.state ?? "missing", zh)}</VChip></div>
          {synthesisProjection?.answer ? <div className={styles.answer}><LazyConversationMarkdownRenderer content={synthesisProjection.answer} language={zh ? "zh" : "en"} /></div> : <p className={styles.placeholder}>{synthesisProjection && ["failed", "stopped", "incomplete"].includes(synthesisProjection.state) ? (zh ? `汇总${statusText(synthesisProjection.state, zh)}，可重新开始研究。` : `Synthesis: ${statusText(synthesisProjection.state, zh)}. Start a new research run.`) : allAnalystsComplete ? (zh ? "分析员已完成，等待主助手汇总" : "Analysts completed; waiting for synthesis") : (zh ? "分析员完成后自动汇总" : "Synthesis starts when all analysts finish")}</p>}
          <div className={styles.cardActions}>{synthesisProjection?.state === "completed" && selectedRun.synthesis.turnId ? <FinanceReportExport assistantAgentId={assistant.agentId} sessionId={selectedRun.synthesis.sessionId} turnId={selectedRun.synthesis.turnId} zh={zh} /> : null}<VButton variant="ghost" icon={<ExternalLink size={14} />} onPress={() => onOpenSession(selectedRun.synthesis.sessionId)}>{zh ? "打开主助手会话" : "Assistant Session"}</VButton>{synthesisProjection?.state === "running" && selectedRun.synthesis.turnId ? <VButton variant="secondary" icon={<StopCircle size={14} />} isPending={stoppingRole === "synthesis"} isDisabled={Boolean(stoppingRole)} onPress={() => void stopExactTurn("synthesis", selectedRun.synthesis)}>{zh ? "停止汇总" : "Stop synthesis"}</VButton> : null}</div>
        </VSurface>
      </> : null}
    </> : null}
  </div>;
}

export function FinanceAnalystTeamInspector({ run, zh, onOpenSession }: {
  run: FinancialTeamRun | null;
  zh: boolean;
  onOpenSession: (sessionId: string) => void;
}) {
  if (!run) return <VStateSurface tone="empty" title={zh ? "选择或开始一轮研究" : "Select or start a research run"} />;
  const completed = run.coordinationStatus === "completed" && Boolean(run.synthesis.turnId) && ALL_ROLES.every((role) => run.analysts[role]?.turnId);
  const blocked = run.coordinationStatus === "blocked";
  return <section className={styles.inspector} aria-label={zh ? "本轮协作进度" : "Selected run progress"}>
    <div className={styles.inspectorMeta}><strong>{run.symbol}</strong><span>{run.researchDate || "—"} · {run.periodDays}{zh ? "天" : " days"}</span></div>
    <VChip tone={completed ? "success" : blocked ? "warning" : "neutral"}>{completed ? (zh ? "已完成汇总" : "Synthesis completed") : blocked ? (zh ? "研究暂停" : "Research paused") : run.coordinationStatus === "waiting" || run.coordinationStatus === "running" ? (zh ? "研究进行中" : "Research running") : (zh ? "研究进度待核对" : "Review run progress")}</VChip>
    {ALL_ROLES.filter((role) => run.analysts[role]).map((role) => <div key={role} className={styles.inspectorRow}><span>{ROLE_LABELS[role][zh ? 0 : 1]}</span><VChip tone={completed ? "success" : "neutral"}>{completed ? (zh ? "已完成" : "Completed") : run.analysts[role]?.turnId ? (zh ? "已提交" : "Submitted") : (zh ? "待提交" : "Not submitted")}</VChip></div>)}
    {blocked && run.coordinationError ? <VStateSurface tone="error" title={zh ? "协作未完成" : "Coordination incomplete"}>{run.coordinationError}</VStateSurface> : null}
    <VButton variant="secondary" icon={<ExternalLink size={14} />} isDisabled={!run.synthesis.turnId} onPress={() => onOpenSession(run.synthesis.sessionId)}>{zh ? "查看汇总对话" : "Open synthesis conversation"}</VButton>
  </section>;
}
