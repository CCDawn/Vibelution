import type { BackendHealth, RuntimeSummary, WorkRunSnapshot } from "../api/types";

export type SystemStatusTone = "idle" | "running" | "failed" | "caution";

export type FrontendSystemState = "connected" | "background" | "offline";
export type BackendSystemState = "checking" | "healthy" | "offline" | "unhealthy";
export type RuntimeControllerState = "managed" | "closing" | "unmanaged" | "failed";
export type ActiveWorkKind = "supervised" | "self" | "chat" | "chat_room";

export type ActiveWorkIndicatorItem = {
  kind: ActiveWorkKind;
  label: string;
  summary: string;
  status: string;
  runId: string;
  detail: string;
  tone: SystemStatusTone;
};

export type ActiveWorkIndicator = ActiveWorkIndicatorItem & {
  count: number;
  overflowCount: number;
  items: ActiveWorkIndicatorItem[];
};

export type StartupProgressState = {
  active: boolean;
  title: string;
  detail: string;
  stage: string;
  tone: SystemStatusTone;
};

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
      supervised_evolution_run?: ActiveWorkRunSnapshot | null;
      supervised_worktree_evolution_run?: ActiveWorkRunSnapshot | null;
    } | null;
    activeItems?: {
      chat_turn?: ActiveWorkRunSnapshot[] | null;
      chat_room_round?: ActiveWorkRunSnapshot[] | null;
      self_evolution_run?: ActiveWorkRunSnapshot[] | null;
      supervised_evolution_run?: ActiveWorkRunSnapshot[] | null;
      supervised_worktree_evolution_run?: ActiveWorkRunSnapshot[] | null;
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

export function deriveRuntimeControllerState(runtime: RuntimeSnapshot | null | undefined): RuntimeControllerState {
  const managerRunning = Boolean(runtime?.runtimeManager?.running);
  const desiredState = String(runtime?.workbench?.desiredState ?? "closed").trim().toLowerCase();
  const observedState = String(runtime?.workbench?.observedState ?? "closed").trim().toLowerCase();
  const phase = String(runtime?.workbench?.phase ?? "").trim().toLowerCase();
  const failureMessage = String(runtime?.workbench?.failureMessage ?? "").trim();
  const browserManaged = Boolean(runtime?.workbench?.browserManaged);
  const lifecycleConsistency = String(runtime?.workbench?.lifecycleConsistency ?? "").trim().toLowerCase();
  const frontendOrphaned = Boolean(runtime?.workbench?.frontendOrphaned) || lifecycleConsistency === "orphaned_browser";

  if (frontendOrphaned || phase === "failed" || failureMessage) {
    return "failed";
  }
  if (desiredState === "closed" && observedState !== "closed") {
    return "closing";
  }
  if (managerRunning && browserManaged) {
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
  const rawFailureMessage = String(workbench?.failureMessage ?? "").trim();
  const failureMessage = textValue(rawFailureMessage);
  const statusLine = textValue(workbench?.statusLine);
  const summary = textValue(lifecycleProof?.summary);
  const backendReady = Boolean(workbench?.backendHealthy || workbench?.backendAlive || workbench?.backendObserved);
  const workbenchReady = desiredState === "open"
    && observedState === "open"
    && phase === "steady"
    && backendReady;

  if (failureMessage || phase === "failed" || (lifecycleState === "failed" && !workbenchReady)) {
    const failureSummary = summarizeStartupFailure(rawFailureMessage || failureMessage || statusLine || summary, lang);
    return {
      active: true,
      title: failureSummary.title,
      detail: failureSummary.detail,
      stage: failureSummary.stage,
      tone: "failed",
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

  const candidates = [
    buildActiveWorkCandidate("supervised", active.supervised_evolution_run, runtime, lang),
    buildActiveWorkCandidate("self", active.self_evolution_run, runtime, lang),
    ...activeWorkCandidatesFromItems("chat_room", activeItems?.chat_room_round, runtime, lang, active.chat_room_round),
    ...activeWorkCandidatesFromItems("chat", activeItems?.chat_turn, runtime, lang, active.chat_turn),
  ].filter((item): item is ActiveWorkIndicatorItem => Boolean(item));

  if (!candidates.length) {
    return null;
  }

  return {
    ...candidates[0],
    count: candidates.length,
    overflowCount: Math.max(0, candidates.length - 1),
    items: candidates,
  };
}

function activeWorkCandidatesFromItems(
  kind: ActiveWorkKind,
  items: ActiveWorkRunSnapshot[] | null | undefined,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
  fallback?: ActiveWorkRunSnapshot | null,
): ActiveWorkIndicatorItem[] {
  if (Array.isArray(items) && items.length) {
    return items
      .map((item) => buildActiveWorkCandidate(kind, item, runtime, lang))
      .filter((item): item is ActiveWorkIndicatorItem => Boolean(item));
  }
  const candidate = buildActiveWorkCandidate(kind, fallback, runtime, lang);
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
): ActiveWorkIndicatorItem | null {
  if (!run || typeof run !== "object") {
    return null;
  }

  const status = normalizeWorkRunStatus(run);
  if (isTerminalWorkRunStatus(status)) {
    return null;
  }

  const label = activeWorkKindLabel(kind, lang);
  const summary = activeWorkSummary(kind, run, runtime, lang);
  const runId = textValue(run.runId);
  const detailParts = [
    label,
    summary,
    status ? status.replaceAll("_", " ") : "",
    runId ? `id=${runId}` : "",
  ].filter(Boolean);

  return {
    kind,
    label,
    summary,
    status: status || "running",
    runId,
    detail: detailParts.join(" · "),
    tone: activeWorkTone(status),
  };
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
    "cancelled",
    "canceled",
    "stopped",
    "closed",
    "terminated",
    "error",
  ]).has(status);
}

function activeWorkTone(status: string): SystemStatusTone {
  if (["queued", "paused", "pause_requested", "pausing", "stopping"].includes(status)) {
    return "caution";
  }
  return "running";
}

function activeWorkKindLabel(kind: ActiveWorkKind, lang: "zh" | "en"): string {
  if (lang === "en") {
    return {
      supervised: "Supervised evolution",
      self: "Self evolution",
      chat_room: "Agent room",
      chat: "Chat",
    }[kind];
  }
  return {
    supervised: "监督进化",
    self: "自进化",
    chat_room: "Agent 群聊",
    chat: "对话",
  }[kind];
}

function activeWorkSummary(
  kind: ActiveWorkKind,
  run: ActiveWorkRunSnapshot,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
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

  if (kind === "chat_room") {
    return firstTextValue(run, ["topic", "summary", "currentTask"])
      || (lang === "en" ? "Agent room round is active" : "Agent 群聊正在讨论");
  }

  return firstTextValue(run, ["userMessage", "summary", "currentTask"])
    || textValue(runtime.taskSummary)
    || textValue(runtime.sessionTitle)
    || (lang === "en" ? "Chat turn is active" : "对话正在运行");
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
