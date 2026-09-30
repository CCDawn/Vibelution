import type { BackendHealth, CodeFreshnessVerdict, RuntimeSummary, WorkRunSnapshot } from "../api/types";
import { shellDictionary, type ShellTranslationKey } from "../i18n/shellDictionary";

export type SystemStatusTone = "idle" | "running" | "failed" | "caution";

export type FrontendSystemState = "connected" | "background" | "offline";
export type BackendSystemState = "checking" | "healthy" | "offline" | "unhealthy";
export type RuntimeControllerState = "managed" | "closing" | "unmanaged" | "failed";
export type ActiveWorkKind =
  | "supervised"
  | "self"
  | "self_evolution_autonomous_loop"
  | "formal_review"
  | "source_collection"
  | "chat"
  | "chat_room";

export type ActiveWorkIndicatorItem = {
  kind: ActiveWorkKind;
  label: string;
  summary: string;
  fullSummary: string;
  status: string;
  runId: string;
  href: string;
  detail: string;
  tone: SystemStatusTone;
  /** Terminal failed run left in the active slot — never counted as active work. */
  staleFailure?: boolean;
};

export type ActiveWorkIndicator = ActiveWorkIndicatorItem & {
  count: number;
  overflowCount: number;
  items: ActiveWorkIndicatorItem[];
  /** Terminal failed runs still parked in the active slot; rendered in their own caution section. */
  staleFailures: ActiveWorkIndicatorItem[];
};

export type SystemStatusCard = {
  id: "frontend" | "backend" | "runtime";
  label: string;
  value: string;
  tone: SystemStatusTone;
};

export type StartupProgressState = {
  active: boolean;
  title: string;
  detail: string;
  stage: string;
  tone: SystemStatusTone;
};

export function shouldRenderStartupOverlay(
  progress: StartupProgressState,
  _desktopShell: boolean,
): boolean {
  if (!progress.active) {
    return false;
  }
  // Once this shell is mounted, every terminal or advisory state must leave
  // recovery controls reachable. The header keeps the failure visible while
  // the overlay is reserved for the only genuinely blocking state: startup.
  return progress.tone === "running";
}

type RuntimeSnapshot = Pick<RuntimeSummary, "runtimeManager" | "workbench">;
type StartupRuntimeSnapshot = RuntimeSnapshot & Pick<RuntimeSummary, "lifecycleProof">;
type StartupLoadingSnapshot = {
  configPending: boolean;
  runtimePending: boolean;
  backendPending: boolean;
  configError: boolean;
  runtimeError: boolean;
  backendError: boolean;
};
type StartupDisconnectedSnapshot = {
  startupActive: boolean;
  runtimeUnavailable: boolean;
  backendUnavailable: boolean;
};
type ActiveWorkRunSnapshot = Partial<WorkRunSnapshot> & Record<string, unknown>;
type RuntimeWorkSnapshot = {
  workRuns?: {
    active?: {
      chat_turn?: ActiveWorkRunSnapshot | null;
      chat_room_round?: ActiveWorkRunSnapshot | null;
      self_evolution_run?: ActiveWorkRunSnapshot | null;
      self_evolution_autonomous_loop?: ActiveWorkRunSnapshot | null;
      supervised_evolution_run?: ActiveWorkRunSnapshot | null;
      supervised_worktree_evolution_run?: ActiveWorkRunSnapshot | null;
      source_collection_run?: ActiveWorkRunSnapshot | null;
      formal_review?: ActiveWorkRunSnapshot | null;
    } | null;
    activeItems?: {
      chat_turn?: ActiveWorkRunSnapshot[] | null;
      chat_room_round?: ActiveWorkRunSnapshot[] | null;
      self_evolution_run?: ActiveWorkRunSnapshot[] | null;
      self_evolution_autonomous_loop?: ActiveWorkRunSnapshot[] | null;
      supervised_evolution_run?: ActiveWorkRunSnapshot[] | null;
      supervised_worktree_evolution_run?: ActiveWorkRunSnapshot[] | null;
      source_collection_run?: ActiveWorkRunSnapshot[] | null;
      formal_review?: ActiveWorkRunSnapshot[] | null;
    } | null;
  } | null;
  taskSummary?: string | null;
  sessionTitle?: string | null;
  currentPhase?: string | null;
};

export function deriveFrontendSystemState({
  online,
  visible,
}: {
  online: boolean;
  visible: boolean;
}): FrontendSystemState {
  if (!online) {
    return "offline";
  }
  if (!visible) {
    return "background";
  }
  return "connected";
}

export function deriveBackendSystemState({
  isPending,
  hasData,
  isError,
  health,
}: {
  isPending: boolean;
  hasData: boolean;
  isError: boolean;
  health?: BackendHealth | null;
}): BackendSystemState {
  if (isPending && !hasData) {
    return "checking";
  }
  if (isError) {
    return "offline";
  }
  if (health?.status === "ok") {
    return "healthy";
  }
  return "unhealthy";
}

function workbenchWindowOwned(workbench: RuntimeSnapshot["workbench"] | null | undefined): boolean {
  // browserManaged is the Edge-app alias; Electron projects windowManaged and forces browserManaged false.
  return Boolean(workbench?.windowManaged) || Boolean(workbench?.browserManaged);
}

export function deriveRuntimeControllerState(runtime: RuntimeSnapshot | null | undefined): RuntimeControllerState {
  const managerRunning = Boolean(runtime?.runtimeManager?.running);
  const desiredState = String(runtime?.workbench?.desiredState ?? "closed").trim().toLowerCase();
  const observedState = String(runtime?.workbench?.observedState ?? "closed").trim().toLowerCase();
  const phase = String(runtime?.workbench?.phase ?? "").trim().toLowerCase();
  const failureMessage = String(runtime?.workbench?.failureMessage ?? "").trim();
  const windowOwned = workbenchWindowOwned(runtime?.workbench);
  const browserWindowAlive = Boolean(runtime?.workbench?.browserWindowAlive);
  const lifecycleConsistency = String(runtime?.workbench?.lifecycleConsistency ?? "").trim().toLowerCase();
  const frontendOrphaned = Boolean(runtime?.workbench?.frontendOrphaned) || lifecycleConsistency === "orphaned_browser";
  const browserMissing = lifecycleConsistency === "browser_missing"
    || (windowOwned && observedState === "partial" && !browserWindowAlive);

  if (frontendOrphaned || browserMissing || phase === "failed" || failureMessage) {
    return "failed";
  }
  if (desiredState === "closed" && observedState === "closed") {
    return "unmanaged";
  }
  if (desiredState === "closed" && observedState !== "closed") {
    return "closing";
  }
  if (managerRunning && windowOwned && observedState === "open") {
    return "managed";
  }
  return "unmanaged";
}

export function deriveStartupProgressState(
  runtime: StartupRuntimeSnapshot | null | undefined,
  lang: "zh" | "en" = "zh",
): StartupProgressState {
  const workbench = runtime?.workbench;
  const lifecycleProof = runtime?.lifecycleProof;
  const desiredState = String(workbench?.desiredState ?? "").trim().toLowerCase();
  const observedState = String(workbench?.observedState ?? "").trim().toLowerCase();
  const phase = String(workbench?.phase ?? "").trim().toLowerCase();
  const lifecycleState = String(lifecycleProof?.overallState ?? "").trim().toLowerCase();
  const lifecycleConsistency = String(workbench?.lifecycleConsistency ?? "").trim().toLowerCase();
  const rawFailureMessage = String(workbench?.failureMessage ?? "").trim();
  // Runtime may keep lifecycle failure only on lastError after older reconciles;
  // prefer failureMessage, fall back to lastError.message when phase is failed.
  const rawLastErrorMessage = String(
    (runtime as { lastError?: { message?: string } } | null | undefined)?.lastError?.message
      ?? (workbench as { lastErrorMessage?: string } | null | undefined)?.lastErrorMessage
      ?? "",
  ).trim();
  const failureMessage = textValue(rawFailureMessage) || (phase === "failed" ? textValue(rawLastErrorMessage) : "");
  const statusLine = textValue(workbench?.statusLine);
  const summary = textValue(lifecycleProof?.summary);
  const backendReady = Boolean(workbench?.backendHealthy || workbench?.backendAlive || workbench?.backendObserved);
  const workbenchReady = desiredState === "open"
    && observedState === "open"
    && phase === "steady"
    && backendReady;

  if (failureMessage || phase === "failed" || (lifecycleState === "failed" && !workbenchReady)) {
    const failureSummary = summarizeStartupFailure(
      rawFailureMessage || rawLastErrorMessage || failureMessage || statusLine || summary,
      lang,
    );
    return {
      active: true,
      title: failureSummary.title,
      detail: failureSummary.detail,
      stage: failureSummary.stage,
      tone: "failed",
    };
  }

  const browserMissing = lifecycleConsistency === "browser_missing"
    || observedState === "partial";
  if (desiredState === "open" && browserMissing && !workbenchReady) {
    return {
      active: true,
      title: lang === "en" ? "Workbench window is not open" : "工作台窗口未打开",
      detail: statusLine || summary || (lang === "en" ? "The backend is still running, but the workbench window is missing." : "后端仍在运行，但工作台窗口缺失。"),
      stage: lang === "en" ? "Partial" : "部分运行",
      tone: "caution",
    };
  }

  const isStarting = lifecycleState === "starting"
    || phase === "opening"
    || (desiredState === "open" && observedState !== "open");
  if (isStarting) {
    return {
      active: true,
      title: lang === "en" ? "Starting Vibelution" : "正在启动 Vibelution",
      detail: statusLine || summary || (lang === "en" ? "The runtime manager is opening the workbench." : "运行器正在打开工作台。"),
      stage: startupStageLabel({ phase, lifecycleState, observedState, lang }),
      tone: "running",
    };
  }

  return {
    active: false,
    title: "",
    detail: "",
    stage: "",
    tone: "idle",
  };
}

export function deriveStartupLoadingState(
  snapshot: StartupLoadingSnapshot | null | undefined,
  lang: "zh" | "en" = "zh",
): StartupProgressState {
  const configPending = Boolean(snapshot?.configPending);
  const runtimePending = Boolean(snapshot?.runtimePending);
  const backendPending = Boolean(snapshot?.backendPending);
  const configError = Boolean(snapshot?.configError);
  const runtimeError = Boolean(snapshot?.runtimeError);
  const backendError = Boolean(snapshot?.backendError);

  if (configError || runtimeError || backendError) {
    const detailParts = [
      configError ? (lang === "en" ? "workspace config" : "工作区配置") : "",
      runtimeError ? (lang === "en" ? "runtime state" : "运行状态") : "",
      backendError ? (lang === "en" ? "backend health" : "后端健康") : "",
    ].filter(Boolean);
    return {
      active: true,
      title: lang === "en" ? "Startup needs attention" : "启动需要处理",
      detail: detailParts.length > 0
        ? (lang === "en"
          ? `Failed to load ${detailParts.join(", ")}.`
          : `加载${detailParts.join("、")}时出现问题。`)
        : (lang === "en" ? "Startup data is not available yet." : "启动数据暂时不可用。"),
      stage: lang === "en" ? "Failed" : "异常",
      tone: "failed",
    };
  }

  if (configPending) {
    return {
      active: true,
      title: lang === "en" ? "Starting Vibelution" : "正在启动 Vibelution",
      detail: lang === "en"
        ? "Loading workspace configuration and workbench settings."
        : "正在加载工作区配置和工作台设置。",
      stage: lang === "en" ? "Loading config" : "加载配置",
      tone: "running",
    };
  }

  if (runtimePending) {
    return {
      active: true,
      title: lang === "en" ? "Starting Vibelution" : "正在启动 Vibelution",
      detail: lang === "en"
        ? "Reading runtime state and lifecycle proof."
        : "正在读取运行状态和生命周期证明。",
      stage: lang === "en" ? "Loading runtime" : "读取运行状态",
      tone: "running",
    };
  }

  if (backendPending) {
    return {
      active: true,
      title: lang === "en" ? "Starting Vibelution" : "正在启动 Vibelution",
      detail: lang === "en"
        ? "Checking backend health and API reachability."
        : "正在检查后端健康状态和接口可达性。",
      stage: lang === "en" ? "Checking backend" : "检查后端",
      tone: "running",
    };
  }

  return {
    active: false,
    title: "",
    detail: "",
    stage: "",
    tone: "idle",
  };
}

export function deriveStartupDisconnectedState(
  snapshot: StartupDisconnectedSnapshot | null | undefined,
  lang: "zh" | "en" = "zh",
): StartupProgressState {
  const startupActive = Boolean(snapshot?.startupActive);
  const runtimeUnavailable = Boolean(snapshot?.runtimeUnavailable);
  const backendUnavailable = Boolean(snapshot?.backendUnavailable);

  if (!startupActive || (!runtimeUnavailable && !backendUnavailable)) {
    return {
      active: false,
      title: "",
      detail: "",
      stage: "",
      tone: "idle",
    };
  }

  return {
    active: true,
    title: lang === "en" ? "Workbench is stopped" : "工作台已停止",
    detail: lang === "en"
      ? "This window is no longer connected to the Launcher-managed backend. Start the project from Launcher, or close this stale window."
      : "这个窗口已经断开与 Launcher 托管后端的连接。请回到 Launcher 启动项目，或关闭这个旧窗口。",
    stage: lang === "en" ? "Disconnected" : "连接已断开",
    tone: "failed",
  };
}

function startupStageLabel({
  phase,
  lifecycleState,
  observedState,
  lang,
}: {
  phase: string;
  lifecycleState: string;
  observedState: string;
  lang: "zh" | "en";
}): string {
  if (phase === "opening") {
    return lang === "en" ? "Opening runtime" : "打开运行器";
  }
  if (lifecycleState === "starting") {
    return lang === "en" ? "Checking backend and window" : "检查后端和窗口";
  }
  if (observedState !== "open") {
    return lang === "en" ? "Waiting for workbench" : "等待工作台";
  }
  return lang === "en" ? "Connecting" : "连接中";
}

function summarizeStartupFailure(message: string, lang: "zh" | "en"): Pick<StartupProgressState, "title" | "detail" | "stage"> {
  const fallbackDetail = lang === "en" ? "The runtime reported a startup failure." : "运行器报告启动异常。";
  const text = textValue(message);
  const frontendBuildFailed = /frontend\.build\.failed|npm\s+run\s+build\s+failed|frontend build failed/i.test(text);
  if (frontendBuildFailed) {
    return {
      title: lang === "en" ? "Frontend build failed" : "前端构建失败",
      detail: firstBuildErrorLine(text) || text || fallbackDetail,
      stage: lang === "en" ? "Frontend build" : "前端构建",
    };
  }
  return {
    title: lang === "en" ? "Startup needs attention" : "启动需要处理",
    detail: text || fallbackDetail,
    stage: lang === "en" ? "Failed" : "异常",
  };
}

function firstBuildErrorLine(message: string): string {
  const raw = String(message || "");
  const sourceErrorMatch = raw.match(/(?:^|\s)((?:web[/\\])?(?:src[/\\])?[^\s"'`]+[/\\][^\s"'`]+\.(?:ts|tsx|js|jsx)\(\d+,\d+\):\s+error\s+TS\d+:[\s\S]*?)(?=\s+(?:At\s+|(?:web[/\\])?(?:src[/\\])?[^\s"'`]+[/\\][^\s"'`]+\.(?:ts|tsx|js|jsx)\(\d+,\d+\):\s+error\s+TS\d+:|$))/i);
  if (sourceErrorMatch?.[1]) {
    return sourceErrorMatch[1].trim().replace(/^web[/\\]/i, "");
  }
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const sourceErrorLine = lines.find((line) => /(?:^|\b)(?:src|web\/src|web\\src)[/\\].+\(\d+,\d+\):\s+error\s+TS\d+/i.test(line));
  if (sourceErrorLine) {
    return sourceErrorLine.replace(/^web[/\\]/i, "");
  }
  const tsErrorLine = lines.find((line) => /error\s+TS\d+/i.test(line));
  if (tsErrorLine) {
    return tsErrorLine.replace(/^web[/\\]/i, "");
  }
  const eventLine = lines.find((line) => /frontend\.build\.failed|npm\s+run\s+build\s+failed|frontend build failed/i.test(line));
  return eventLine || "";
}

export function deriveActiveWorkIndicator(
  runtime: RuntimeWorkSnapshot | null | undefined,
  lang: "zh" | "en" = "zh",
): ActiveWorkIndicator | null {
  const active = runtime?.workRuns?.active;
  if (!active) {
    return null;
  }
  const activeItems = runtime?.workRuns?.activeItems;
  const supervisedRuns = [
    ...activeWorkRunSnapshots(
      activeItems?.supervised_worktree_evolution_run,
      active.supervised_worktree_evolution_run,
    ),
    ...activeWorkRunSnapshots(
      activeItems?.supervised_evolution_run,
      active.supervised_evolution_run,
    ),
  ];
  const supervisedSessionIds = supervisedChildSessionIds(supervisedRuns);
  const visibleChatItems = Array.isArray(activeItems?.chat_turn)
    ? activeItems.chat_turn.filter((run) =>
      !supervisedSessionIds.has(
        firstTextValue(run, ["sessionId", "sourceSessionId", "conversationId", "directSessionId"]),
      ))
    : activeItems?.chat_turn;
  const visibleChatFallback = supervisedSessionIds.has(
    firstTextValue(active.chat_turn ?? {}, ["sessionId", "sourceSessionId", "conversationId", "directSessionId"]),
  )
    ? null
    : active.chat_turn;

  const built = [
    ...activeWorkCandidatesFromItems(
      "supervised",
      activeItems?.supervised_worktree_evolution_run,
      runtime,
      lang,
      active.supervised_worktree_evolution_run,
    ),
    ...activeWorkCandidatesFromItems(
      "supervised",
      activeItems?.supervised_evolution_run,
      runtime,
      lang,
      active.supervised_evolution_run,
    ),
    buildActiveWorkCandidate("self", active.self_evolution_run, runtime, lang),
    // The autonomous loop keeps a single active snapshot (no activeItems list
    // on the backend); formal review fans out per provider invocation.
    buildActiveWorkCandidate(
      "self_evolution_autonomous_loop",
      active.self_evolution_autonomous_loop,
      runtime,
      lang,
    ),
    ...activeWorkCandidatesFromItems("formal_review", activeItems?.formal_review, runtime, lang, active.formal_review),
    ...activeWorkCandidatesFromItems("source_collection", activeItems?.source_collection_run, runtime, lang, active.source_collection_run),
    ...activeWorkCandidatesFromItems("chat_room", activeItems?.chat_room_round, runtime, lang, active.chat_room_round),
    ...activeWorkCandidatesFromItems("chat", visibleChatItems, runtime, lang, visibleChatFallback),
  ].filter((item): item is ActiveWorkIndicatorItem => Boolean(item));

  // Terminal failed runs parked in the active slot are stale leftovers, not
  // active work: they never count toward "N running" but stay visible so a
  // dead round cannot disappear without a trace.
  const staleFailures = built.filter((item) => item.staleFailure);
  const candidates = built.filter((item) => !item.staleFailure);
  if (!candidates.length && !staleFailures.length) {
    return null;
  }

  if (!candidates.length) {
    return {
      ...staleFailures[0],
      count: 0,
      overflowCount: 0,
      items: [],
      staleFailures,
    };
  }

  return {
    ...candidates[0],
    count: candidates.length,
    overflowCount: Math.max(0, candidates.length - 1),
    items: candidates,
    staleFailures,
  };
}

const systemStatusTonePriority: Record<SystemStatusTone, number> = {
  failed: 0,
  caution: 1,
  running: 2,
  idle: 3,
};

/** Worst-tone card wins; ties keep the earlier card (frontend first). */
export function pickPrimarySystemStatusCard(cards: SystemStatusCard[]): SystemStatusCard {
  return cards.reduce((selected, item) =>
    systemStatusTonePriority[item.tone] < systemStatusTonePriority[selected.tone] ? item : selected,
  cards[0]);
}

/**
 * The runtime-summary feed is down (health is fine, /api/runtime/summary keeps
 * failing): the runtime card must stop reading as a neutral "unmanaged" idle
 * and speak the truth at caution grade, so the primary status can never stay
 * a pure green "connected" while the backend is half dead.
 */
export function applyRuntimeSummaryOutage(
  card: SystemStatusCard,
  unavailable: boolean,
  unavailableValue: string,
): SystemStatusCard {
  if (!unavailable) {
    return card;
  }
  return {
    ...card,
    value: unavailableValue,
    tone: card.tone === "failed" ? card.tone : "caution",
  };
}

function activeWorkRunSnapshots(
  items: ActiveWorkRunSnapshot[] | null | undefined,
  fallback?: ActiveWorkRunSnapshot | null,
): ActiveWorkRunSnapshot[] {
  if (Array.isArray(items) && items.length) {
    return items;
  }
  return fallback ? [fallback] : [];
}

function supervisedChildSessionIds(runs: ActiveWorkRunSnapshot[]): Set<string> {
  const sessionIds = new Set<string>();
  const add = (value: unknown) => {
    const sessionId = textValue(value);
    if (sessionId) {
      sessionIds.add(sessionId);
    }
  };
  for (const run of runs) {
    add(run.conversationSessionId);
    add(run.candidateConversationSessionId);
    const currentCaseIo = run.currentCaseIo && typeof run.currentCaseIo === "object"
      ? run.currentCaseIo as Record<string, unknown>
      : null;
    add(currentCaseIo?.conversationSessionId);
    for (const rawStep of Array.isArray(run.workflowSteps) ? run.workflowSteps : []) {
      if (rawStep && typeof rawStep === "object") {
        add((rawStep as Record<string, unknown>).conversationSessionId);
      }
    }
    const roleSessions = run.roleConversationSessions && typeof run.roleConversationSessions === "object"
      ? run.roleConversationSessions as Record<string, unknown>
      : {};
    for (const rawSession of Object.values(roleSessions)) {
      if (rawSession && typeof rawSession === "object") {
        add((rawSession as Record<string, unknown>).conversationSessionId);
      }
    }
  }
  return sessionIds;
}

function activeWorkCandidatesFromItems(
  kind: ActiveWorkKind,
  items: ActiveWorkRunSnapshot[] | null | undefined,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
  fallback?: ActiveWorkRunSnapshot | null,
): ActiveWorkIndicatorItem[] {
  if (Array.isArray(items) && items.length) {
    const allowSharedRuntimeFallback = items.length <= 1;
    return items
      .map((item) => buildActiveWorkCandidate(kind, item, runtime, lang, { allowSharedRuntimeFallback }))
      .filter((item): item is ActiveWorkIndicatorItem => Boolean(item));
  }
  const candidate = buildActiveWorkCandidate(kind, fallback, runtime, lang, { allowSharedRuntimeFallback: true });
  return candidate ? [candidate] : [];
}

export function frontendSystemTone(state: FrontendSystemState): SystemStatusTone {
  switch (state) {
    case "offline":
      return "failed";
    case "background":
      return "idle";
    default:
      return "running";
  }
}

export function backendSystemTone(state: BackendSystemState): SystemStatusTone {
  switch (state) {
    case "healthy":
      return "running";
    case "checking":
      return "idle";
    default:
      return "failed";
  }
}

export function runtimeControllerTone(state: RuntimeControllerState): SystemStatusTone {
  switch (state) {
    case "managed":
    case "closing":
      return "running";
    case "unmanaged":
      return "idle";
    default:
      return "failed";
  }
}

function buildActiveWorkCandidate(
  kind: ActiveWorkKind,
  run: ActiveWorkRunSnapshot | null | undefined,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
  options: { allowSharedRuntimeFallback?: boolean } = {},
): ActiveWorkIndicatorItem | null {
  if (!run || typeof run !== "object") {
    return null;
  }

  const status = normalizeWorkRunStatus(run);
  const terminal = isTerminalWorkRunStatus(status);
  if (terminal && !isFailedWorkRunStatus(status)) {
    return null;
  }
  // A failed round left in the active slot becomes a stale-failure item: it
  // renders in its own caution section instead of counting as running work.
  const staleFailure = terminal;
  const label = staleFailure
    ? staleWorkKindLabel(kind, lang)
    : activeWorkKindLabel(kind, lang);
  const fullSummary = staleFailure
    ? staleWorkSummary(kind, run)
    : activeWorkSummary(kind, run, runtime, lang, options);
  // Chat turns and room rounds surface raw diagnostic text; compact them so the
  // chip and the popover read like sentences instead of log dumps. The full
  // text stays on the item for tooltips and the linked surface.
  const summary = !staleFailure && kind === "chat_room"
    ? compactActiveWorkSummary(fullSummary)
    : !staleFailure && kind === "chat"
      ? compactActiveWorkSummary(fullSummary, 96)
      : fullSummary;
  const runId = textValue(run.runId);
  const href = activeWorkHref(kind, run);
  // Keep raw ids out of user-facing copy.
  const detailParts = [label, summary].filter(Boolean);

  return {
    kind,
    label,
    summary,
    fullSummary,
    status: status || "running",
    runId,
    href,
    detail: detailParts.join(" · "),
    tone: staleFailure ? "caution" : activeWorkTone(status),
    staleFailure: staleFailure || undefined,
  };
}

function compactActiveWorkSummary(value: string, maxLength = 72): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  // Skip an early label separator (e.g. "工具失败：") so the first sentence
  // boundary after the leading label wins instead of the whole dump.
  const boundary = normalized.slice(6).search(/[：:。；;！？!?]/) + 6;
  if (boundary >= 6 && boundary < maxLength) {
    return normalized.slice(0, boundary).trim();
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function normalizeWorkRunStatus(run: ActiveWorkRunSnapshot): string {
  return firstTextValue(run, ["status", "currentPhase", "phase", "runtimeStatus"]).toLowerCase();
}

function isTerminalWorkRunStatus(status: string): boolean {
  return new Set([
    "done",
    "completed",
    "success",
    "failed",
    "failed_provider",
    "failed_runtime",
    "cancelled",
    "canceled",
    "stopped",
    "stopped_by_user",
    "closed",
    "terminated",
    "needs_continue",
    "paused_limit",
    "superseded",
    "error",
  ]).has(status);
}

/** Only genuine failures become visible stale leftovers; neutral finals stay hidden. */
function isFailedWorkRunStatus(status: string): boolean {
  return ["failed", "failed_provider", "failed_runtime", "error"].includes(status);
}

const staleWorkLabelKeys: Record<ActiveWorkKind, ShellTranslationKey> = {
  supervised: "activeWorkStale_supervised",
  self: "activeWorkStale_self",
  self_evolution_autonomous_loop: "activeWorkStale_self_evolution_autonomous_loop",
  formal_review: "activeWorkStale_formal_review",
  source_collection: "activeWorkStale_source_collection",
  chat_room: "activeWorkStale_chat_room",
  chat: "activeWorkStale_chat",
};

function staleWorkKindLabel(kind: ActiveWorkKind, lang: "zh" | "en"): string {
  return shellDictionary[lang][staleWorkLabelKeys[kind]];
}

function staleWorkSummary(kind: ActiveWorkKind, run: ActiveWorkRunSnapshot): string {
  const lastToolError = recordTextValue(run["lastToolError"], ["summary", "errorPreview", "toolName"]);
  if (kind === "self_evolution_autonomous_loop") {
    return recordTextValue(run["request"], ["goal"]) || lastToolError;
  }
  if (kind === "source_collection") {
    const topic = firstTextValue(run, ["topic", "title"]);
    const summary = firstTextValue(run, ["summary", "currentTask"]) || lastToolError;
    if (topic && summary) {
      return `${topic}: ${summary}`;
    }
    return summary || topic;
  }
  if (kind === "chat") {
    return firstTextValue(run, ["summary", "currentTask"]) || lastToolError || firstTextValue(run, ["userMessage"]);
  }
  return firstTextValue(run, ["topic", "summary", "currentTask", "currentGoal", "goal"])
    || lastToolError;
}

function activeWorkTone(status: string): SystemStatusTone {
  if (["queued", "paused", "pause_requested", "pausing", "stopping"].includes(status)) {
    return "caution";
  }
  return "running";
}

/** Newer kinds resolve their labels through the shared shell dictionary. */
const activeWorkLabelKeys: Partial<Record<ActiveWorkKind, ShellTranslationKey>> = {
  formal_review: "activeWorkLabel_formal_review",
  self_evolution_autonomous_loop: "activeWorkLabel_self_evolution_autonomous_loop",
};

/** Kinds predating the shell-dictionary labels keep their inline copy. */
const legacyActiveWorkLabels: Partial<Record<ActiveWorkKind, string>> = {
  supervised: "监督进化",
  self: "自进化",
  source_collection: "资料搜集",
  chat_room: "Agent 群聊",
  chat: "对话",
};

const legacyActiveWorkLabelsEn: Partial<Record<ActiveWorkKind, string>> = {
  supervised: "Supervised evolution",
  self: "Self evolution",
  source_collection: "Knowledge collection",
  chat_room: "Agent room",
  chat: "Chat",
};

function activeWorkKindLabel(kind: ActiveWorkKind, lang: "zh" | "en"): string {
  const dictionaryKey = activeWorkLabelKeys[kind];
  if (dictionaryKey) {
    return shellDictionary[lang][dictionaryKey];
  }
  return (lang === "en" ? legacyActiveWorkLabelsEn : legacyActiveWorkLabels)[kind] ?? kind;
}

function activeWorkHref(kind: ActiveWorkKind, run: ActiveWorkRunSnapshot): string {
  if (kind === "supervised") {
    return "/supervised-evolution";
  }
  if (kind === "self_evolution_autonomous_loop") {
    return "/self-evolution";
  }
  // Formal review is a team-workflow provider invocation; its bound session is
  // a hidden child session, so the stable entry surface is the teams board.
  if (kind === "formal_review") {
    return "/teams";
  }
  if (kind === "chat") {
    const sessionId = firstTextValue(run, ["sessionId", "sourceSessionId", "conversationId", "directSessionId"]);
    return sessionId ? `/chat?session=${encodeURIComponent(sessionId)}` : "";
  }
  if (kind === "chat_room") {
    const roomId = firstTextValue(run, ["roomId", "sourceRoomId"]);
    return roomId ? `/chat?room=${encodeURIComponent(roomId)}` : "";
  }
  return "";
}

function activeWorkSummary(
  kind: ActiveWorkKind,
  run: ActiveWorkRunSnapshot,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
  options: { allowSharedRuntimeFallback?: boolean } = {},
): string {
  if (kind === "supervised") {
    return firstTextValue(run, [
      "currentTask",
      "latestMessage",
      "summary",
      "reason",
      "currentCaseScenario",
      "bundleName",
      "datasetName",
    ]) || (lang === "en" ? "Supervised run is active" : "监督任务正在运行");
  }

  if (kind === "self") {
    return firstTextValue(run, [
      "currentGoal",
      "goal",
      "latestMessage",
      "summary",
      "currentTask",
    ]) || (lang === "en" ? "Self-evolution pass is active" : "自进化任务正在运行");
  }

  if (kind === "self_evolution_autonomous_loop") {
    // The goal lives under request (see the autonomous-loop service snapshot).
    return recordTextValue(run["request"], ["goal"])
      || (lang === "en" ? "Autonomous self-evolution loop is active" : "自主进化正在运行");
  }

  if (kind === "formal_review") {
    // The snapshot only carries invocation metadata (purpose/lease ids); keep
    // raw ids out of user-facing copy and use a stable sentence instead.
    return lang === "en" ? "Formal review is running" : "正式评审正在进行";
  }

  if (kind === "chat_room") {
    return firstTextValue(run, ["topic", "summary", "currentTask"])
      || (lang === "en" ? "Agent room round is active" : "Agent 群聊正在讨论");
  }

  if (kind === "source_collection") {
    const topic = firstTextValue(run, ["topic", "title"]);
    const summary = firstTextValue(run, ["summary", "currentTask"]);
    if (topic && summary) {
      return lang === "en" ? `${topic}: ${summary}` : `${topic}：${summary}`;
    }
    return summary || topic || (lang === "en" ? "Research team is collecting sources" : "AI 科研团队正在搜集资料");
  }

  const lastToolError = recordTextValue(run["lastToolError"], ["summary", "errorPreview", "toolName"]);
  const perRunSummary = firstTextValue(run, ["summary", "currentTask"])
    || lastToolError
    || firstTextValue(run, ["userMessage"]);
  if (perRunSummary) {
    return perRunSummary;
  }
  if (options.allowSharedRuntimeFallback !== false) {
    return textValue(runtime.taskSummary)
      || textValue(runtime.sessionTitle)
      || (lang === "en" ? "Chat turn is active" : "对话正在运行");
  }
  return lang === "en" ? "Chat turn is active" : "对话正在运行";
}

function recordTextValue(source: unknown, keys: string[]): string {
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    return "";
  }
  return firstTextValue(source as Record<string, unknown>, keys);
}

function firstTextValue(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = textValue(source[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function textValue(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function lifecycleStateTone(state: string | null | undefined): SystemStatusTone {
  switch (String(state || "").trim().toLowerCase()) {
    case "ready":
    case "verified":
    case "running":
      return "running";
    case "closed":
    case "missing":
    case "unknown":
      return "idle";
    case "failed":
      return "failed";
    default:
      return "caution";
  }
}

export function lifecycleStateLabel(state: string, lang: "zh" | "en"): string {
  const normalized = String(state || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    ready: "已开启",
    starting: "开启中",
    closing: "关闭中",
    closed: "已关闭",
    partial: "部分成立",
    failed: "异常",
    verified: "已验证",
    missing: "未观测到",
    unknown: "未知",
    running: "运行中",
  };
  const en: Record<string, string> = {
    ready: "Open",
    starting: "Starting",
    closing: "Closing",
    closed: "Closed",
    partial: "Partial",
    failed: "Failed",
    verified: "Verified",
    missing: "Missing",
    unknown: "Unknown",
    running: "Running",
  };
  return (lang === "en" ? en : zh)[normalized] || state;
}

// Code-freshness: a behind runtime build is a caution-grade system condition.
// Kept as one shared predicate so the primary status card and the status guide
// panel can never disagree about whether a stale instance must be surfaced
// (2026-09-11: a stale backend used to render as a neutral "unknown" chip).
export function codeFreshnessStale(
  verdict: CodeFreshnessVerdict | undefined | null,
): boolean {
  return (
    verdict === "backend_behind"
    || verdict === "frontend_behind"
    || verdict === "backend_and_frontend_behind"
  );
}
