import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, LoaderCircle, Play, RefreshCw, Square } from "lucide-react";
import { useMemo, useState } from "react";

import {
  getLauncherStatus,
  reattachLauncherSupervisor,
  restartLauncherBundle,
  startLauncherBundle,
  stopLauncherBundle,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { LauncherComponentState, LauncherOperation } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./LauncherRoute.module.css";

type LauncherNotice = {
  tone: "neutral" | "success" | "warning" | "error";
  text: string;
};

type LauncherGuardianResponsibility = {
  id: string;
  owner: string;
  adapter: string;
  status: string;
  detail: string;
};

type LauncherControlPlaneCommand = {
  commandId: string;
  type: string;
  requestedBy: string;
  requestedAt: string;
  reason: string;
  source: string;
  noBrowser: boolean;
  stopManager: boolean;
  deferredUntilActiveWorkClear?: boolean;
  queuedBecauseActiveWork?: boolean;
  deferUntil?: string;
  activeWorkDeferCount?: number;
  lastActiveWorkCount?: number;
};

type LauncherControlPlaneResult = {
  commandId: string;
  ok: boolean;
  completed: boolean;
  message: string;
  errorType: string;
  stateVersion: number;
};

type LauncherControlPlaneEvent = {
  type: string;
  at: string;
  commandId: string;
  commandType: string;
  ok: boolean | null;
  message: string;
};

type LauncherStatusWithGuardian = Awaited<ReturnType<typeof getLauncherStatus>> & {
  controlPlaneEvidence?: {
    schemaVersion: number;
    state: {
      stateVersion: number;
      runtimeState: string;
      managerPid: number;
      updatedAt: string;
      activeCommand: LauncherControlPlaneCommand;
    };
    queue: {
      pendingCount: number;
      processingCount: number;
      pending: LauncherControlPlaneCommand[];
      processing: LauncherControlPlaneCommand[];
    };
    results: {
      recent: LauncherControlPlaneResult[];
    };
    events: {
      recent: LauncherControlPlaneEvent[];
    };
    recovery: {
      active: boolean;
      commandId: string;
      commandType: string;
      recoveredAt: string;
      resultMessage: string;
      resultOk: boolean | null;
      statusLine: string;
    };
    restartQueue?: {
      pending: boolean;
      pendingCount: number;
      active: boolean;
      commandId: string;
      deferUntil: string;
      activeWorkDeferCount: number;
      lastActiveWorkCount: number;
      statusLine: string;
    };
  };
  guardianAdapter?: {
    schemaVersion: number;
    mode: string;
    targetMode: string;
    statusLine: string;
    ownedCount: number;
    adapterCount: number;
    supervisor?: {
      pid: number;
      alive: boolean;
      status: string;
      stdoutPath: string;
      stderrPath: string;
      runtimeSceneId: string;
      runtimeSceneDir: string;
      detail: string;
    };
    responsibilities: LauncherGuardianResponsibility[];
  };
};

type StatusRow = {
  id: string;
  label: string;
  status: string;
  role: string;
  detail: string;
  technical: string;
  ok: boolean;
};

type LauncherCopy = {
  controlLimited: string;
  controlLimitedDetail: string;
  controlReady: string;
  controlReadyDetail: string;
  lifecycleClosed: string;
  lifecycleClosedDetail: string;
  lifecycleFailed: string;
  lifecycleFailedDetail: string;
  lifecycleReadingLimited: string;
  lifecycleReadingLimitedDetail: string;
  lifecycleRestarting: string;
  lifecycleRestartingDetail: string;
  lifecycleRunning: string;
  lifecycleRunningDetail: string;
  lifecycleStarting: string;
  lifecycleStartingDetail: string;
  lifecycleStatus: string;
  lifecycleStopping: string;
  lifecycleStoppingDetail: string;
  lifecycleUnknown: string;
  lifecycleUnknownDetail: string;
  openWorkbenchSummary: string;
  safeToUse: string;
  startProjectSummary: string;
  useCheckAction: string;
  useStartAction: string;
  useWaitAction: string;
};

type LifecycleDisplay = {
  state: "running" | "closed" | "starting" | "stopping" | "restarting" | "failed" | "limited" | "unknown";
  label: string;
  detail: string;
  tone: "neutral" | "success" | "warning" | "error";
};

const COMPONENT_ORDER = new Map([
  ["backend", 0],
  ["frontend", 1],
  ["browser", 2],
]);

function sortComponents(components: LauncherComponentState[]) {
  return [...components].sort((left, right) => {
    const leftOrder = COMPONENT_ORDER.get(left.id) ?? 99;
    const rightOrder = COMPONENT_ORDER.get(right.id) ?? 99;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return left.id.localeCompare(right.id);
  });
}

function compactDate(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function stateTone(state: string, ok = true) {
  const normalized = state.trim().toLowerCase();
  if (!ok || normalized.includes("fail") || normalized.includes("error") || normalized.includes("conflict")) {
    return "error";
  }
  if (normalized.includes("run") || normalized.includes("ready") || normalized.includes("ok") || normalized.includes("healthy")) {
    return "success";
  }
  if (normalized.includes("start") || normalized.includes("stop") || normalized.includes("queue") || normalized.includes("restart")) {
    return "warning";
  }
  return "neutral";
}

function boolText(value: boolean | undefined, yes: string, no: string) {
  return value ? yes : no;
}

function humanState(value: string | undefined, lang: "zh" | "en") {
  const raw = String(value || "").trim();
  const normalized = raw.toLowerCase();
  const zh: Record<string, string> = {
    alive: "运行中",
    active: "已接管",
    closed: "已关闭",
    failed: "异常",
    healthy: "健康",
    idle: "空闲",
    managed: "已托管",
    open: "已打开",
    processing: "执行中",
    queued: "排队中",
    ready: "就绪",
    running: "运行中",
    steady: "稳定",
    stopped: "已停止",
  };
  const en: Record<string, string> = {
    alive: "Running",
    active: "Owned",
    closed: "Closed",
    failed: "Failed",
    healthy: "Healthy",
    idle: "Idle",
    managed: "Managed",
    open: "Open",
    processing: "Processing",
    queued: "Queued",
    ready: "Ready",
    running: "Running",
    steady: "Stable",
    stopped: "Stopped",
  };
  return (lang === "zh" ? zh : en)[normalized] || raw || "-";
}

function humanCommandType(value: string | undefined, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    close_workbench: "关闭项目",
    open_workbench: "打开项目",
    restart_workbench: "重启项目",
    start_supervised_run: "启动监督运行",
  };
  const en: Record<string, string> = {
    close_workbench: "Close project",
    open_workbench: "Open project",
    restart_workbench: "Restart project",
    start_supervised_run: "Start supervised run",
  };
  return (lang === "zh" ? zh : en)[normalized] || normalized || "-";
}

function isLauncherStatusNetworkDisconnect(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /failed to fetch|network request failed|networkerror|load failed/i.test(message);
}

function isControlTokenError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /missing or invalid web control token|control token request failed|control token response was empty/i.test(message);
}

function includesAny(value: string, needles: string[]) {
  return needles.some((needle) => value.includes(needle));
}

function resolveLifecycleDisplay(
  status: LauncherStatusWithGuardian | undefined,
  copy: LauncherCopy,
  options: { disconnected: boolean; controlLimited: boolean },
): LifecycleDisplay {
  if (options.disconnected) {
    return {
      state: "closed",
      label: copy.lifecycleClosed,
      detail: copy.lifecycleClosedDetail,
      tone: "neutral",
    };
  }
  if (!status) {
    return {
      state: options.controlLimited ? "limited" : "unknown",
      label: options.controlLimited ? copy.lifecycleReadingLimited : copy.lifecycleUnknown,
      detail: options.controlLimited ? copy.lifecycleReadingLimitedDetail : copy.lifecycleUnknownDetail,
      tone: options.controlLimited ? "warning" : "neutral",
    };
  }

  const bundle = status.projectBundle;
  const evidence = status.controlPlaneEvidence;
  const restartQueue = evidence?.restartQueue;
  const desired = String(bundle?.desiredState || "").toLowerCase();
  const observed = String(bundle?.observedState || "").toLowerCase();
  const phase = String(bundle?.phase || status.launcher.phase || "").toLowerCase();
  const overall = String(status.lifecycleProof?.overallState || bundle?.overallState || "").toLowerCase();
  const commandType = String(evidence?.state.activeCommand?.type || "").toLowerCase();
  const recoveryType = String(evidence?.recovery?.commandType || "").toLowerCase();
  const activeLifecycleCommand = commandType || (evidence?.recovery?.active ? recoveryType : "");

  if (restartQueue?.active) {
    return {
      state: "restarting",
      label: copy.lifecycleRestarting,
      detail: restartQueue.statusLine || copy.lifecycleRestartingDetail,
      tone: "warning",
    };
  }
  if (includesAny(overall, ["fail", "error", "conflict"]) || includesAny(phase, ["fail", "error", "conflict"])) {
    return {
      state: "failed",
      label: copy.lifecycleFailed,
      detail: bundle?.failureMessage || bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleFailedDetail,
      tone: "error",
    };
  }
  if (activeLifecycleCommand.includes("restart") || includesAny(phase, ["restart"])) {
    return {
      state: "restarting",
      label: copy.lifecycleRestarting,
      detail: evidence?.recovery?.statusLine || bundle?.statusLine || copy.lifecycleRestartingDetail,
      tone: "warning",
    };
  }
  if (activeLifecycleCommand.includes("open") || includesAny(phase, ["start", "open", "queue", "processing"])) {
    return {
      state: "starting",
      label: copy.lifecycleStarting,
      detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleStartingDetail,
      tone: "warning",
    };
  }
  if (activeLifecycleCommand.includes("close") || includesAny(phase, ["stop", "close", "shutdown"])) {
    return {
      state: "stopping",
      label: copy.lifecycleStopping,
      detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleStoppingDetail,
      tone: "warning",
    };
  }
  if (desired === "open" && observed === "open") {
    return {
      state: "running",
      label: copy.lifecycleRunning,
      detail: status.lifecycleProof?.summary || bundle?.statusLine || copy.lifecycleRunningDetail,
      tone: "success",
    };
  }
  if (desired === "closed" && observed === "closed") {
    return {
      state: "closed",
      label: copy.lifecycleClosed,
      detail: bundle?.statusLine || copy.lifecycleClosedDetail,
      tone: "neutral",
    };
  }

  return {
    state: "unknown",
    label: copy.lifecycleUnknown,
    detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleUnknownDetail,
    tone: "warning",
  };
}

function componentLabel(id: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    backend: "后端服务",
    browser: "工作台窗口",
    frontend: "前端资源",
    project: "项目整体",
    runtime_manager: "生命周期管理",
    supervisor: "后台守护检查",
  };
  const en: Record<string, string> = {
    backend: "Backend service",
    browser: "Workbench window",
    frontend: "Frontend assets",
    project: "Project bundle",
    runtime_manager: "Lifecycle manager",
    supervisor: "Background monitor",
  };
  return (lang === "zh" ? zh : en)[id] || id;
}

function responsibilityLabel(id: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    backend_process: "后端服务",
    browser_window: "工作台窗口",
    desktop_supervisor: "后台守护检查",
    project_bundle_lifecycle: "项目生命周期",
    runtime_manager_daemon: "生命周期管理器",
    runtime_scene_logging: "运行证据",
  };
  const en: Record<string, string> = {
    backend_process: "Backend service",
    browser_window: "Workbench window",
    desktop_supervisor: "Background monitor",
    project_bundle_lifecycle: "Project lifecycle",
    runtime_manager_daemon: "Lifecycle manager",
    runtime_scene_logging: "Runtime evidence",
  };
  return (lang === "zh" ? zh : en)[id] || id;
}

function responsibilityOwner(owner: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    launcher_api: "Launcher",
    powershell_launcher: "启动脚本",
    runtime_manager: "生命周期管理器",
    runtime_scene_service: "日志系统",
  };
  const en: Record<string, string> = {
    launcher_api: "Launcher",
    powershell_launcher: "Launch script",
    runtime_manager: "Lifecycle manager",
    runtime_scene_service: "Log system",
  };
  return (lang === "zh" ? zh : en)[owner] || owner || "-";
}

function responsibilityDetail(item: LauncherGuardianResponsibility, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    backend_process: "后端进程纳入项目生命周期维护。",
    browser_window: "工作台窗口纳入项目生命周期维护。",
    desktop_supervisor: "后台守护检查未运行时，不影响当前项目使用。",
    project_bundle_lifecycle: "启动、停止、重启统一通过 Launcher 入口处理。",
    runtime_manager_daemon: "负责排队并执行生命周期命令。",
    runtime_scene_logging: "运行过程持续写入 runtime scene 证据。",
  };
  const en: Record<string, string> = {
    backend_process: "Backend process is maintained as part of the project lifecycle.",
    browser_window: "Workbench window is maintained as part of the project lifecycle.",
    desktop_supervisor: "When stopped, the background monitor does not block current project use.",
    project_bundle_lifecycle: "Start, stop, and restart are handled through Launcher.",
    runtime_manager_daemon: "Queues and executes lifecycle commands.",
    runtime_scene_logging: "Runtime scene evidence is written continuously.",
  };
  return (lang === "zh" ? zh : en)[item.id] || item.detail || "-";
}

export function LauncherRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const copy = lang === "zh"
    ? {
        eyebrow: "Launcher",
        title: "项目启动器",
        subtitle: "统一控制前端、后端和浏览器生命周期",
        refresh: "刷新",
        start: "启动",
        stop: "停止",
        restart: "重启",
        open: "打开",
        startDisabled: "项目已在运行",
        projectStatus: "项目状态",
        launcherStatus: "Launcher 维护",
        lifecycleStatus: "生命周期",
        activeWork: "任务保护",
        activeTasks: "进行中任务",
        noActiveWork: "无进行中任务",
        restartProtected: "有任务，禁止重启",
        restartClear: "可安全重启",
        userAction: "下一步",
        projectRunning: "项目正在运行",
        projectClosed: "项目已关闭",
        projectChanging: "项目正在切换",
        projectProblem: "项目需要处理",
        launcherMaintaining: "正在维护",
        launcherOffline: "未连接",
        lifecycleRunning: "运行中",
        lifecycleRunningDetail: "后端、前端和工作台窗口已对齐，项目可以继续使用。",
        lifecycleClosed: "已关闭",
        lifecycleClosedDetail: "项目生命周期已停止；需要时从这里重新启动。",
        lifecycleStarting: "启动中",
        lifecycleStartingDetail: "Launcher 正在启动后端、前端资源和工作台窗口。",
        lifecycleStopping: "停止中",
        lifecycleStoppingDetail: "Launcher 正在关闭项目生命周期，请等待收口完成。",
        lifecycleRestarting: "重启中",
        lifecycleRestartingDetail: "Launcher 正在执行重启，完成后会回到运行中。",
        lifecycleFailed: "异常",
        lifecycleFailedDetail: "生命周期证据显示项目需要处理，请查看诊断。",
        lifecycleUnknown: "状态待确认",
        lifecycleUnknownDetail: "还没有拿到足够证据判断项目生命周期。",
        lifecycleReadingLimited: "状态读取受限",
        lifecycleReadingLimitedDetail: "项目可能仍在运行，但 Launcher 状态接口需要重新取得控制权限。",
        controlReady: "控制可用",
        controlReadyDetail: "控制 token 正常，启动、停止和重启按钮可按权限提交。",
        controlLimited: "控制受限",
        controlLimitedDetail: "当前缺少有效控制 token；请刷新后再执行启动、停止或重启。",
        safeToUse: "可以打开工作台继续使用",
        useOpenAction: "打开工作台",
        useStartAction: "启动项目",
        useWaitAction: "等待当前操作完成",
        useCheckAction: "查看诊断",
        lifecycle: "生命周期",
        keyStatus: "关键状态",
        matrix: "项目组成",
        controlPlane: "维护范围",
        controlEvidence: "证据",
        guardian: "托管明细",
        advancedDiagnostics: "高级诊断",
        queueAndEvents: "命令与事件",
        recovery: "恢复记录",
        recoveryIdle: "无恢复动作",
        maintenanceDetails: "维护细节",
        diagnostics: "诊断详情",
        activeCommand: "当前命令",
        recentResults: "最近结果",
        recentEvents: "最近事件",
        desired: "目标",
        observed: "实际",
        phase: "稳定性",
        overall: "可用性",
        adapter: "适配器",
        independent: "独立",
        nextPhase: "下一阶段",
        stable: "稳定控制面",
        pid: "PID",
        state: "状态",
        detail: "说明",
        unit: "单元",
        mode: "职责",
        port: "端口",
        listening: "监听",
        owner: "占用 PID",
        alive: "存活",
        healthy: "健康",
        yes: "是",
        no: "否",
        unavailable: "不可用",
        loadFailed: "Launcher 状态读取失败",
        stoppedStatusUnavailable: "工作台已关闭，Launcher 后端连接已断开。重新启动后会恢复状态。",
        stoppedProjectDetail: "后端不可达，当前页面只保留旧前端壳；请从 Launcher 重新启动项目。",
        stoppedBackendDetail: "后端连接已断开，接口和状态刷新不可用。",
        stoppedFrontendDetail: "当前看到的是旧前端页面，不代表项目仍在运行。",
        stoppedBrowserDetail: "工作台窗口或后端已停止，旧窗口可关闭。",
        loading: "正在读取 Launcher 状态",
        commandDone: "命令已提交",
        reattachSupervisor: "检查维护",
        targetMode: "内部目标",
        owned: "维护项",
        legacyAdapter: "记录项",
        supervisor: "守护检查",
        stdout: "stdout",
        stderr: "stderr",
        scene: "现场",
        pending: "待执行",
        processing: "执行中",
        queue: "队列",
        reason: "原因",
        source: "来源",
        transition: "转换",
        proof: "证明",
        schema: "schema",
        advancedDetails: "技术细节",
        notBlocking: "不影响项目使用",
        maintenanceScopeSummary: "Launcher 正在维护项目启动、停止、重启、后端、窗口和日志证据。",
        activeWorkSummary: "有任务运行时，Launcher 会拒绝停止或重启，避免打断会话或进化任务。",
        noActiveWorkSummary: "当前没有进行中的项目任务，生命周期操作不会打断运行任务。",
        openWorkbenchSummary: "工作台已就绪，可继续开发或查看页面。",
        startProjectSummary: "项目未运行时，从这里统一启动前后端和窗口。",
        waitOperationSummary: "Launcher 正在处理生命周期命令，请等待状态稳定。",
        checkDiagnosticsSummary: "关键状态无法确认时，展开高级诊断查看原因。",
        internalMigrationDetails: "内部迁移细节",
      }
    : {
        eyebrow: "Launcher",
        title: "Project Launcher",
        subtitle: "Control frontend, backend, and browser as one lifecycle bundle",
        refresh: "Refresh",
        start: "Start",
        stop: "Stop",
        restart: "Restart",
        open: "Open",
        startDisabled: "Project is already running",
        projectStatus: "Project Status",
        launcherStatus: "Launcher Care",
        lifecycleStatus: "Lifecycle",
        activeWork: "Work Guard",
        activeTasks: "Active Tasks",
        noActiveWork: "No active tasks",
        restartProtected: "Blocked by work",
        restartClear: "Safe to restart",
        userAction: "Next Step",
        projectRunning: "Project is running",
        projectClosed: "Project is closed",
        projectChanging: "Project is changing",
        projectProblem: "Project needs attention",
        launcherMaintaining: "Maintaining",
        launcherOffline: "Disconnected",
        lifecycleRunning: "Running",
        lifecycleRunningDetail: "Backend, frontend, and workbench window line up; the project is usable.",
        lifecycleClosed: "Closed",
        lifecycleClosedDetail: "The project lifecycle is stopped; start it here when needed.",
        lifecycleStarting: "Starting",
        lifecycleStartingDetail: "Launcher is starting backend, frontend assets, and workbench window.",
        lifecycleStopping: "Stopping",
        lifecycleStoppingDetail: "Launcher is closing the project lifecycle; wait for cleanup.",
        lifecycleRestarting: "Restarting",
        lifecycleRestartingDetail: "Launcher is restarting the project and will return to running.",
        lifecycleFailed: "Problem",
        lifecycleFailedDetail: "Lifecycle evidence says the project needs attention; check diagnostics.",
        lifecycleUnknown: "Checking",
        lifecycleUnknownDetail: "There is not enough evidence yet to prove the lifecycle state.",
        lifecycleReadingLimited: "Status limited",
        lifecycleReadingLimitedDetail: "The project may still be running, but Launcher needs fresh control permission.",
        controlReady: "Control ready",
        controlReadyDetail: "Control token is available, so lifecycle buttons can submit commands.",
        controlLimited: "Control limited",
        controlLimitedDetail: "A valid control token is missing; refresh before start, stop, or restart.",
        safeToUse: "Open the workbench and keep working",
        useOpenAction: "Open workbench",
        useStartAction: "Start project",
        useWaitAction: "Wait for the current operation",
        useCheckAction: "Check diagnostics",
        lifecycle: "Lifecycle",
        keyStatus: "Key Status",
        matrix: "Project Parts",
        controlPlane: "Maintenance Scope",
        controlEvidence: "Evidence",
        guardian: "Managed Details",
        advancedDiagnostics: "Advanced Diagnostics",
        queueAndEvents: "Commands and Events",
        recovery: "Recovery",
        recoveryIdle: "No recovery action",
        maintenanceDetails: "Maintenance Details",
        diagnostics: "Diagnostics",
        activeCommand: "Active Command",
        recentResults: "Recent Results",
        recentEvents: "Recent Events",
        desired: "Target",
        observed: "Actual",
        phase: "Stability",
        overall: "Availability",
        adapter: "Adapter",
        independent: "Independent",
        nextPhase: "Next Phase",
        stable: "Stable Control Plane",
        pid: "PID",
        state: "State",
        detail: "Notes",
        unit: "Unit",
        mode: "Role",
        port: "Port",
        listening: "Listening",
        owner: "Owner PID",
        alive: "Alive",
        healthy: "Healthy",
        yes: "Yes",
        no: "No",
        unavailable: "Unavailable",
        loadFailed: "Launcher status failed",
        stoppedStatusUnavailable: "Workbench is closed; the Launcher backend connection is no longer available. Start again to restore status.",
        stoppedProjectDetail: "The backend is unreachable; this page is only a stale frontend shell. Start the project again from Launcher.",
        stoppedBackendDetail: "The backend connection is gone, so APIs and status refresh are unavailable.",
        stoppedFrontendDetail: "This is a stale frontend page and does not mean the project is still running.",
        stoppedBrowserDetail: "The workbench window or backend has stopped; this stale window can be closed.",
        loading: "Loading Launcher status",
        commandDone: "Command submitted",
        reattachSupervisor: "Check care",
        targetMode: "Internal Target",
        owned: "Managed",
        legacyAdapter: "Recorded",
        supervisor: "Monitor",
        stdout: "stdout",
        stderr: "stderr",
        scene: "Scene",
        pending: "Pending",
        processing: "Processing",
        queue: "Queue",
        reason: "Reason",
        source: "Source",
        transition: "Transition",
        proof: "Proof",
        schema: "schema",
        advancedDetails: "Technical details",
        notBlocking: "Not blocking project use",
        maintenanceScopeSummary: "Launcher maintains project start, stop, restart, backend, window, and runtime evidence.",
        activeWorkSummary: "When tasks are running, Launcher rejects stop and restart requests so chat or evolution work is not interrupted.",
        noActiveWorkSummary: "There are no active project tasks, so lifecycle actions will not interrupt running work.",
        openWorkbenchSummary: "Workbench is ready for development or inspection.",
        startProjectSummary: "When closed, start frontend, backend, and window from here.",
        waitOperationSummary: "Launcher is processing a lifecycle command; wait for the state to settle.",
        checkDiagnosticsSummary: "If key status is unclear, expand diagnostics for the reason.",
        internalMigrationDetails: "Internal migration details",
      };

  const [notice, setNotice] = useState<LauncherNotice>({ tone: "neutral", text: "" });
  const [lastControlOperation, setLastControlOperation] = useState<LauncherOperation | null>(null);
  const statusQuery = useQuery({
    queryKey: queryKeys.launcherStatus(),
    queryFn: getLauncherStatus,
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
  });
  const controlMutation = useMutation({
    mutationFn: async (operation: LauncherOperation) => {
      if (operation === "start") {
        return startLauncherBundle();
      }
      if (operation === "stop") {
        return stopLauncherBundle();
      }
      return restartLauncherBundle();
    },
    onMutate: (operation) => {
      setLastControlOperation(operation);
    },
    onSuccess: (response, operation) => {
      setLastControlOperation(operation === "stop" && response.accepted ? "stop" : null);
      setNotice({
        tone: response.accepted ? "success" : "warning",
        text: response.message || copy.commandDone,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setLastControlOperation(null);
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const supervisorMutation = useMutation({
    mutationFn: reattachLauncherSupervisor,
    onSuccess: (response) => {
      setNotice({
        tone: response.accepted ? "success" : "warning",
        text: response.message || copy.commandDone,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const status = statusQuery.data as LauncherStatusWithGuardian | undefined;
  const bundle = status?.projectBundle;
  const guardian = status?.guardianAdapter;
  const evidence = status?.controlPlaneEvidence;
  const componentRows = useMemo(() => sortComponents(bundle?.components ?? []), [bundle?.components]);
  const busy = controlMutation.isPending || supervisorMutation.isPending;
  const headerTone = stateTone(bundle?.overallState ?? status?.launcher.phase ?? "", Boolean(bundle));
  const transitionAt = compactDate(bundle?.lastOperation.transitionAt ?? "", locale);
  const canRequestSupervisorReattach = Boolean(status && guardian?.supervisor && !guardian.supervisor.alive);
  const uiLang = lang === "zh" ? "zh" : "en";
  const bundleDesired = String(bundle?.desiredState || "").toLowerCase();
  const bundleObserved = String(bundle?.observedState || "").toLowerCase();
  const launcherStatusDisconnected = statusQuery.isError && isLauncherStatusNetworkDisconnect(statusQuery.error);
  const launcherControlLimited = statusQuery.isError && isControlTokenError(statusQuery.error);
  const lifecycleDisplay = resolveLifecycleDisplay(status, copy, { disconnected: launcherStatusDisconnected, controlLimited: launcherControlLimited });
  const projectIsOpen = lifecycleDisplay.state === "running";
  const projectIsClosed = lifecycleDisplay.state === "closed";
  const projectIsChanging = ["starting", "stopping", "restarting"].includes(lifecycleDisplay.state);
  const startDisabled = busy || projectIsOpen || projectIsChanging;
  const projectSummary = lifecycleDisplay.label;
  const launcherSummary = !status
    ? copy.launcherOffline
    : copy.launcherMaintaining;
  const controlSummary = launcherControlLimited ? copy.controlLimited : copy.controlReady;
  const controlDetail = launcherControlLimited ? copy.controlLimitedDetail : copy.controlReadyDetail;
  const activeWorkCount = status?.lifecycleProof.activeWorkRuns.count ?? 0;
  const activeWorkKinds = status?.lifecycleProof.activeWorkRuns.kinds ?? [];
  const restartQueue = evidence?.restartQueue;
  const restartQueueActive = Boolean(restartQueue?.active);
  const restartQueuePending = Boolean(restartQueue?.pending);
  const activeWorkSummary = restartQueueActive
    ? copy.lifecycleRestarting
    : activeWorkCount > 0
      ? copy.restartProtected
      : copy.restartClear;
  const activeWorkDetail = activeWorkCount > 0
    ? `${copy.activeTasks}: ${activeWorkCount}${activeWorkKinds.length ? ` · ${activeWorkKinds.join(", ")}` : ""}${restartQueue?.statusLine ? ` · ${restartQueue.statusLine}` : ""}`
    : restartQueue?.statusLine
      ? restartQueue.statusLine
    : copy.noActiveWorkSummary;
  const nextAction = restartQueueActive
    ? copy.useWaitAction
    : projectIsOpen
    ? copy.safeToUse
    : projectIsChanging
      ? copy.useWaitAction
      : projectIsClosed
        ? copy.useStartAction
        : copy.useCheckAction;
  const nextActionDetail = restartQueueActive
    ? restartQueue?.statusLine || lifecycleDisplay.detail
    : projectIsOpen
    ? copy.openWorkbenchSummary
    : projectIsChanging
      ? lifecycleDisplay.detail
      : projectIsClosed
        ? copy.startProjectSummary
        : lifecycleDisplay.detail || copy.checkDiagnosticsSummary;
  const guardianProgress = `${guardian?.ownedCount ?? 0}/${guardian?.adapterCount ?? 0}`;
  const statusRows = useMemo<StatusRow[]>(() => {
    const componentById = new Map(componentRows.map((component) => [component.id, component]));
    const backend = componentById.get("backend");
    const frontend = componentById.get("frontend");
    const browser = componentById.get("browser");
    return [
      {
        id: "project",
        label: componentLabel("project", uiLang),
        status: projectSummary,
        role: lang === "zh" ? "整体可用性" : "Overall availability",
        detail: launcherStatusDisconnected ? copy.stoppedProjectDetail : lifecycleDisplay.detail || bundle?.statusLine || status?.launcher.message || "-",
        technical: `${copy.desired}: ${humanState(bundle?.desiredState, uiLang)} · ${copy.observed}: ${humanState(bundle?.observedState, uiLang)} · mode ${bundle?.mode || "-"}`,
        ok: Boolean(launcherStatusDisconnected || (bundle && bundle?.overallState !== "failed")),
      },
      {
        id: "backend",
        label: componentLabel("backend", uiLang),
        status: launcherStatusDisconnected ? humanState("stopped", uiLang) : humanState(backend?.state || (bundle?.backend.healthy ? "healthy" : "-"), uiLang),
        role: lang === "zh" ? "处理 API 与静态资源" : "Serves API and static files",
        detail: launcherStatusDisconnected
          ? copy.stoppedBackendDetail
          : bundle?.backend.healthy
          ? (lang === "zh" ? "后端已监听，工作台可以访问。" : "Backend is listening and reachable.")
          : (lang === "zh" ? "后端未确认可用。" : "Backend is not confirmed ready."),
        technical: `${copy.pid} ${bundle?.backend.pid || backend?.pid || "-"} · ${copy.port} ${bundle?.backend.port || "-"} · ${copy.owner} ${bundle?.backend.portOwnerPid || "-"} · ${copy.listening}: ${boolText(bundle?.backend.portListening, copy.yes, copy.no)}`,
        ok: Boolean(!launcherStatusDisconnected && (backend?.ok ?? bundle?.backend.healthy)),
      },
      {
        id: "frontend",
        label: componentLabel("frontend", uiLang),
        status: humanState(frontend?.state || (bundle?.frontend.distReady ? "ready" : "-"), uiLang),
        role: lang === "zh" ? "提供前端页面" : "Provides web UI",
        detail: launcherStatusDisconnected
          ? copy.stoppedFrontendDetail
          : bundle?.frontend.distReady
          ? (lang === "zh" ? "前端资源已就绪。" : "Frontend assets are ready.")
          : (lang === "zh" ? "前端资源还未构建。" : "Frontend assets are not built yet."),
        technical: `dist ${boolText(bundle?.frontend.distReady, copy.yes, copy.no)} · orphaned ${boolText(bundle?.frontend.orphaned, copy.yes, copy.no)} · mode ${bundle?.frontend.mode || "-"} · ${copy.pid} ${frontend?.pid || "-"}`,
        ok: Boolean(frontend?.ok ?? bundle?.frontend.distReady),
      },
      {
        id: "browser",
        label: componentLabel("browser", uiLang),
        status: humanState(launcherStatusDisconnected ? "stopped" : browser?.state || (bundle?.browser.alive ? "alive" : "stopped"), uiLang),
        role: lang === "zh" ? "承载工作台窗口" : "Hosts the workbench window",
        detail: launcherStatusDisconnected
          ? copy.stoppedBrowserDetail
          : bundle?.browser.alive
          ? (lang === "zh" ? "工作台窗口由 Launcher 管理。" : "Workbench window is managed by Launcher.")
          : (lang === "zh" ? "工作台窗口未打开。" : "Workbench window is not open."),
        technical: `${copy.pid} ${bundle?.browser.windowPid || browser?.pid || "-"} · managed ${boolText(bundle?.browser.managed, copy.yes, copy.no)} · ${browser?.detail || "-"}`,
        ok: Boolean(launcherStatusDisconnected || (browser?.ok ?? !bundle?.browser.alive)),
      },
      {
        id: "runtime_manager",
        label: componentLabel("runtime_manager", uiLang),
        status: humanState(status?.runtimeManager.runtimeState || "-", uiLang),
        role: lang === "zh" ? "执行启动、停止、重启" : "Runs start, stop, restart",
        detail: status?.runtimeManager.running
          ? (lang === "zh" ? "生命周期管理器正在维护项目。" : "Lifecycle manager is maintaining the project.")
          : (lang === "zh" ? "生命周期管理器未运行。" : "Lifecycle manager is not running."),
        technical: `${copy.pid} ${status?.runtimeManager.managerPid || "-"} · state ${status?.runtimeManager.stateVersion ?? "-"} · ${evidence?.state.updatedAt ? compactDate(evidence.state.updatedAt, locale) : "-"}`,
        ok: Boolean(status?.runtimeManager.running),
      },
      {
        id: "supervisor",
        label: componentLabel("supervisor", uiLang),
        status: humanState(guardian?.supervisor?.status || "-", uiLang),
        role: copy.notBlocking,
        detail: guardian?.supervisor?.alive
          ? (lang === "zh" ? "后台守护检查仍在运行。" : "Background monitor is running.")
          : (lang === "zh" ? "后台守护检查未运行，不影响当前项目使用。" : "Background monitor is stopped; project use is not blocked."),
        technical: `${copy.pid} ${guardian?.supervisor?.pid || "-"} · ${guardian?.mode || "-"} · ${guardian?.supervisor?.detail || guardian?.statusLine || "-"}`,
        ok: true,
      },
    ];
  }, [bundle, componentRows, copy, evidence?.state.updatedAt, guardian, lang, launcherStatusDisconnected, locale, projectSummary, status, uiLang]);

  const keyStatusRows = statusRows.filter((row) => ["project", "backend", "frontend", "browser"].includes(row.id));
  const diagnosticStatusRows = statusRows.filter((row) => !["project", "backend", "frontend", "browser"].includes(row.id));
  const activeCommand = evidence?.state.activeCommand;
  const recovery = evidence?.recovery;
  const recentResults = (evidence?.results.recent ?? []).slice(0, 3);
  const recentEvents = (evidence?.events.recent ?? []).slice(0, 3);
  const expectedStopDisconnect = statusQuery.isError && (lastControlOperation === "stop" || launcherStatusDisconnected);

  return (
    <section className={styles.route} aria-label={copy.title}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{lifecycleDisplay.detail || copy.subtitle}</p>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.iconButton} onClick={() => void statusQuery.refetch()} disabled={statusQuery.isFetching} title={copy.refresh}>
            {statusQuery.isFetching ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
            <span>{copy.refresh}</span>
          </button>
          <button type="button" className={styles.primaryButton} onClick={() => controlMutation.mutate("start")} disabled={startDisabled} title={startDisabled ? copy.startDisabled : copy.start}>
            <Play size={15} />
            <span>{copy.start}</span>
          </button>
          <button type="button" className={styles.iconButton} onClick={() => controlMutation.mutate("stop")} disabled={busy} title={copy.stop}>
            <Square size={15} />
            <span>{copy.stop}</span>
          </button>
          <button type="button" className={styles.iconButton} onClick={() => controlMutation.mutate("restart")} disabled={busy} title={copy.restart}>
            <RefreshCw size={15} />
            <span>{copy.restart}</span>
          </button>
          {bundle?.url ? (
            <a className={styles.iconButton} href={bundle.url} target="_blank" rel="noreferrer" title={copy.open}>
              <ExternalLink size={15} />
              <span>{copy.open}</span>
            </a>
          ) : null}
        </div>
      </header>

      <div className={styles.summaryStrip} data-tone={launcherStatusDisconnected ? "neutral" : headerTone}>
        <Metric label={copy.lifecycleStatus} value={projectSummary} helper={lifecycleDisplay.detail} tone={lifecycleDisplay.tone} />
        <Metric label={copy.activeWork} value={activeWorkSummary} helper={activeWorkDetail} tone={restartQueuePending || activeWorkCount > 0 ? "warning" : "success"} />
        <Metric label={copy.launcherStatus} value={controlSummary} helper={controlDetail} tone={launcherControlLimited ? "warning" : status ? "success" : "neutral"} />
        <Metric
          label={copy.userAction}
          value={recovery?.active ? copy.recovery : nextAction}
          helper={recovery?.active ? recovery.statusLine || humanCommandType(recovery.commandType, uiLang) : nextActionDetail}
          tone={recovery?.active ? (recovery.resultOk === false ? "warning" : "success") : projectIsOpen ? "success" : projectIsChanging ? "warning" : "neutral"}
        />
      </div>

      {statusQuery.isError ? (
        <p className={styles.notice} data-tone={expectedStopDisconnect ? "success" : launcherControlLimited ? "warning" : "error"}>
          {expectedStopDisconnect ? copy.stoppedStatusUnavailable : launcherControlLimited ? copy.controlLimitedDetail : copy.loadFailed}
        </p>
      ) : null}
      {notice.text ? <p className={styles.notice} data-tone={notice.tone}>{notice.text}</p> : null}
      {statusQuery.isPending && !status ? <p className={styles.notice} data-tone="neutral">{copy.loading}</p> : null}

      <div className={styles.workspace}>
        <section className={`${styles.panel} ${styles.matrixPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.lifecycle}</p>
            <strong>{copy.keyStatus}</strong>
          </div>
          <div className={styles.guardStrip} data-tone={restartQueuePending || activeWorkCount > 0 ? "warning" : "success"}>
            <span>{copy.activeWork}</span>
            <strong>{activeWorkCount > 0 ? `${copy.activeTasks}: ${activeWorkCount}` : copy.noActiveWork}</strong>
            <small>{restartQueue?.statusLine || (activeWorkCount > 0 ? copy.activeWorkSummary : copy.noActiveWorkSummary)}</small>
          </div>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.matrix}</p>
            <strong>{copy.matrix}</strong>
          </div>
          <div className={styles.statusTable} role="table" aria-label={copy.matrix}>
            <div className={styles.statusHead} role="row">
              <span role="columnheader">{copy.unit}</span>
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.mode}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {keyStatusRows.map((row) => (
              <div key={row.id} className={styles.statusRow} role="row" data-tone={stateTone(row.status, row.ok)} title={row.technical}>
                <span role="cell"><strong>{row.label}</strong></span>
                <span role="cell">{row.status}</span>
                <span role="cell">{row.role}</span>
                <span role="cell">{row.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <details className={`${styles.panel} ${styles.diagnosticsPanel}`}>
          <summary>
            <span>{copy.advancedDiagnostics}</span>
            <strong>{status?.lifecycleProof.overallLabel || "-"}</strong>
          </summary>
          <div className={styles.diagnosticsBody}>
            <section className={styles.diagnosticSection}>
              <div className={styles.panelHeader}>
                <p className={styles.panelEyebrow}>{copy.controlPlane}</p>
                <strong>{humanState(status?.runtimeManager.runtimeState, uiLang)}</strong>
              </div>
              <dl className={styles.specGrid}>
                <Spec label={copy.overall} value={launcherSummary} />
                <Spec label={copy.guardian} value={guardianProgress} />
                <Spec label={copy.reason} value={bundle?.lastOperation.reason || bundle?.lastReason || "-"} />
                <Spec label={copy.transition} value={transitionAt} />
              </dl>
            </section>
            <section className={styles.diagnosticSection}>
              <div className={styles.panelHeader}>
                <p className={styles.panelEyebrow}>{copy.controlEvidence}</p>
                <strong>{evidence?.state.runtimeState || "-"}</strong>
              </div>
              <dl className={styles.specGrid}>
                <Spec label={copy.state} value={humanState(evidence?.state.runtimeState, uiLang)} />
                <Spec label={copy.activeCommand} value={activeCommand?.commandId ? humanCommandType(activeCommand.type, uiLang) : "-"} />
                <Spec label={copy.pending} value={String(evidence?.queue.pendingCount ?? 0)} />
                <Spec label={copy.processing} value={String(evidence?.queue.processingCount ?? 0)} />
                <Spec label={copy.recovery} value={recovery?.active ? humanCommandType(recovery.commandType, uiLang) : copy.recoveryIdle} />
              </dl>
              {recovery?.active ? (
                <div className={styles.recoveryLine} data-tone={recovery.resultOk === false ? "warning" : "success"}>
                  <span>{copy.recovery}</span>
                  <strong>{recovery.statusLine || humanCommandType(recovery.commandType, uiLang)}</strong>
                  <small>{[recovery.commandId, compactDate(recovery.recoveredAt, locale)].filter(Boolean).join(" · ") || "-"}</small>
                </div>
              ) : null}
              <div className={styles.commandLine}>
                <span>{copy.activeCommand}</span>
                <strong>{activeCommand?.commandId ? humanCommandType(activeCommand.type, uiLang) : "-"}</strong>
                <small>{[activeCommand?.requestedBy, activeCommand?.reason].filter(Boolean).join(" · ") || "-"}</small>
              </div>
            </section>
            <section className={styles.diagnosticSection}>
              <div className={styles.panelHeader}>
                <p className={styles.panelEyebrow}>{copy.queueAndEvents}</p>
                <strong>{recentResults.length + recentEvents.length}</strong>
              </div>
              <CompactList
                items={[
                  ...recentResults.map((item) => ({
                    id: item.commandId,
                    primary: item.message || humanCommandType(item.commandId, uiLang),
                    secondary: `${item.ok ? "ok" : "failed"} · ${item.message || item.errorType || "-"}`,
                    tone: item.ok ? "success" as const : "error" as const,
                  })),
                  ...recentEvents.map((item) => ({
                    id: `${item.at}-${item.type}-${item.commandId}`,
                    primary: humanCommandType(item.type, uiLang),
                    secondary: [item.commandId, compactDate(item.at, locale)].filter(Boolean).join(" · ") || "-",
                    tone: item.ok === false ? "error" as const : item.ok === true ? "success" as const : "neutral" as const,
                  })),
                ]}
              />
            </section>
            <section className={styles.diagnosticSection}>
              <div className={styles.panelHeader}>
                <p className={styles.panelEyebrow}>{copy.maintenanceDetails}</p>
                <strong>{guardianProgress}</strong>
              </div>
              <div className={styles.guardianSummary}>
                <span>{copy.maintenanceScopeSummary}</span>
                <strong>{copy.owned}: {guardian?.ownedCount ?? 0}</strong>
                <strong>{copy.legacyAdapter}: {guardian?.adapterCount ?? 0}</strong>
                <button type="button" className={styles.iconButton} onClick={() => supervisorMutation.mutate()} disabled={busy || !canRequestSupervisorReattach} title={copy.reattachSupervisor}>
                  {supervisorMutation.isPending ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
                  <span>{copy.reattachSupervisor}</span>
                </button>
              </div>
              <div className={styles.guardianTable} role="table" aria-label={copy.guardian}>
                <div className={styles.guardianHead} role="row">
                  <span role="columnheader">{copy.unit}</span>
                  <span role="columnheader">owner</span>
                  <span role="columnheader">{copy.state}</span>
                  <span role="columnheader">{copy.detail}</span>
                </div>
                {(guardian?.responsibilities ?? []).map((item) => (
                  <div key={item.id} className={styles.guardianRow} role="row" data-tone={stateTone(item.status)}>
                    <span role="cell"><strong>{responsibilityLabel(item.id, uiLang)}</strong></span>
                    <span role="cell">{responsibilityOwner(item.owner, uiLang)}</span>
                    <span role="cell">{humanState(item.status, uiLang)}</span>
                    <span role="cell">{responsibilityDetail(item, uiLang)}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <dl className={styles.diagnosticsGrid}>
            <Spec label={copy.schema} value={String(bundle?.schemaVersion ?? "-")} />
            <Spec label="bundle mode" value={bundle?.mode || "-"} />
            <Spec label="url" value={bundle?.url || "-"} />
            <Spec label={copy.source} value={bundle?.lastOperation.source || "-"} />
            <Spec label={copy.proof} value={status?.lifecycleProof.summary || "-"} />
            <Spec label={copy.supervisor} value={guardian?.supervisor?.status || "-"} />
            <Spec label={copy.internalMigrationDetails} value={[status?.launcher.mode, guardian?.mode, status?.launcher.controlPlane.nextPhase, guardian?.targetMode].filter(Boolean).join(" | ") || "-"} />
            <Spec label={copy.advancedDetails} value={[...keyStatusRows, ...diagnosticStatusRows].map((row) => `${row.label}: ${row.technical}`).join(" | ") || "-"} />
            <Spec label={copy.scene} value={guardian?.supervisor?.runtimeSceneId || "-"} />
            <Spec label={copy.stdout} value={guardian?.supervisor?.stdoutPath || "-"} />
            <Spec label={copy.stderr} value={guardian?.supervisor?.stderrPath || "-"} />
          </dl>
        </details>
      </div>
    </section>
  );
}

function Metric({ label, value, helper, tone }: { label: string; value: string; helper?: string; tone?: "neutral" | "success" | "warning" | "error" }) {
  return (
    <div className={styles.metric} data-tone={tone || "neutral"}>
      <span>{label}</span>
      <strong>{value}</strong>
      {helper ? <small>{helper}</small> : null}
    </div>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function CompactList({
  items,
}: {
  items: Array<{ id: string; primary: string; secondary: string; tone: "neutral" | "success" | "error" }>;
}) {
  return (
    <div className={styles.compactList}>
      {items.length ? items.map((item) => (
        <div key={item.id || item.primary} className={styles.compactItem} data-tone={item.tone}>
          <strong>{item.primary}</strong>
          <small>{item.secondary}</small>
        </div>
      )) : <small>-</small>}
    </div>
  );
}
