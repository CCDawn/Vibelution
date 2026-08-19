import type { LauncherBranchInstance } from "../api/launcher";

export const BRANCH_INSTANCE_PAGE_SIZE = 8;

export const CLEANUP_RISK_LABELS_ZH: Record<string, string> = {
  discard_dirty: "将丢弃未提交改动",
  stop_then_remove: "将先停止再拆除运行中的实例",
  delete_unmerged: "将删除尚未合入 main 的本地提交",
};

export const CLEANUP_RISK_LABELS_EN: Record<string, string> = {
  discard_dirty: "Uncommitted changes will be discarded",
  stop_then_remove: "The running instance will be stopped, then removed",
  delete_unmerged: "Local commits not merged into main will be deleted",
};

export function isCleanupEligible(item: LauncherBranchInstance): boolean {
  if (item.cleanupEligible === false) {
    return false;
  }
  if (item.cleanupEligible === true) {
    return true;
  }
  return item.kind !== "main" && !item.current && item.branch !== "main" && item.id !== "main";
}

export function inferCleanupRisks(item: LauncherBranchInstance): string[] {
  if (item.cleanupRisks && item.cleanupRisks.length > 0) {
    return item.cleanupRisks;
  }
  const risks: string[] = [];
  if (item.dirty) {
    risks.push("discard_dirty");
  }
  if (item.alive) {
    risks.push("stop_then_remove");
  }
  if (item.mergedToMain === false) {
    risks.push("delete_unmerged");
  }
  return risks;
}

export function cleanupRiskLabels(item: LauncherBranchInstance, isZh: boolean): string[] {
  const labels = isZh ? CLEANUP_RISK_LABELS_ZH : CLEANUP_RISK_LABELS_EN;
  return inferCleanupRisks(item).map((code) => labels[code] || code);
}

export type InstanceRuntimeState = "starting" | "running" | "partial" | "stopping" | "restarting" | "failed" | "stopped";

export type InstancePendingOperation = {
  instanceId: string;
  instanceIds?: string[];
  operation: "start" | "stop" | "restart";
  baselineLifecycleState?: LauncherBranchInstance["runtime"]["lifecycleState"];
};

export type PendingLifecycleIntent = {
  instanceId: string;
  operation: "start" | "stop" | "restart";
  localRevision: number;
  requestId: string;
  baselineLifecycleState?: LauncherBranchInstance["runtime"]["lifecycleState"];
};

export type LifecycleIntentTable = Record<string, PendingLifecycleIntent>;

export type LifecyclePendingInput = InstancePendingOperation | LifecycleIntentTable;

export function toPendingBranchOperation(input: {
  instanceId: string;
  instanceIds?: string[];
  operation: "start" | "stop" | "restart" | "force-stop";
  baselineLifecycleState?: LauncherBranchInstance["runtime"]["lifecycleState"];
}): InstancePendingOperation {
  return {
    instanceId: input.instanceId,
    instanceIds: input.instanceIds && input.instanceIds.length > 0 ? input.instanceIds : undefined,
    operation: input.operation === "force-stop" ? "stop" : input.operation,
    baselineLifecycleState: input.baselineLifecycleState,
  };
}

export function isLifecycleIntentTable(
  pending?: LifecyclePendingInput,
): pending is LifecycleIntentTable {
  return Boolean(pending) && !("operation" in (pending as InstancePendingOperation));
}

export function pendingIntentToOperation(intent: PendingLifecycleIntent): InstancePendingOperation {
  return {
    instanceId: intent.instanceId,
    operation: intent.operation,
    baselineLifecycleState: intent.baselineLifecycleState,
  };
}

export function resolveItemPending(
  item: LauncherBranchInstance,
  pending?: LifecyclePendingInput,
): InstancePendingOperation | undefined {
  if (!pending) {
    return undefined;
  }
  if (isLifecycleIntentTable(pending)) {
    const intent = pending[item.id];
    return intent ? pendingIntentToOperation(intent) : undefined;
  }
  return pendingAppliesTo(item, pending) ? pending : undefined;
}

export function acceptLifecycleIntent(
  table: LifecycleIntentTable,
  input: {
    instanceId: string;
    operation: PendingLifecycleIntent["operation"];
    requestId: string;
    baselineLifecycleState?: PendingLifecycleIntent["baselineLifecycleState"];
  },
): {
  accepted: boolean;
  table: LifecycleIntentTable;
  intent?: PendingLifecycleIntent;
  reason?: "duplicate" | "blocked";
} {
  const current = table[input.instanceId];
  if (current && current.operation === input.operation) {
    return { accepted: false, table, reason: "duplicate" };
  }
  if (current && input.operation !== "stop") {
    return { accepted: false, table, reason: "blocked" };
  }
  const intent: PendingLifecycleIntent = {
    instanceId: input.instanceId,
    operation: input.operation,
    requestId: input.requestId,
    localRevision: (current?.localRevision ?? 0) + 1,
    baselineLifecycleState: input.baselineLifecycleState,
  };
  return {
    accepted: true,
    table: { ...table, [input.instanceId]: intent },
    intent,
  };
}

export function shouldApplyLifecycleMutationFeedback(
  table: LifecycleIntentTable,
  input: {
    instanceId?: string;
    instanceIds?: string[];
    requestId?: string;
    localRevision?: number;
  },
): boolean {
  if (!input.requestId || input.localRevision == null) {
    return false;
  }
  const ids = input.instanceIds && input.instanceIds.length > 0
    ? input.instanceIds
    : input.instanceId
      ? [input.instanceId]
      : [];
  if (ids.length === 0) {
    return false;
  }
  return ids.every((id) => {
    const current = table[id];
    return Boolean(
      current
      && current.requestId === input.requestId
      && current.localRevision === input.localRevision,
    );
  });
}

export function settleLifecycleIntentTable(
  table: LifecycleIntentTable,
  items: readonly LauncherBranchInstance[],
): LifecycleIntentTable {
  const next: LifecycleIntentTable = {};
  for (const [id, intent] of Object.entries(table)) {
    const pending = pendingIntentToOperation(intent);
    if (resolveActivePendingOperation(pending, items)) {
      next[id] = intent;
    }
  }
  const currentKeys = Object.keys(table);
  const nextKeys = Object.keys(next);
  if (
    currentKeys.length === nextKeys.length
    && currentKeys.every((key) => next[key] === table[key])
  ) {
    return table;
  }
  return next;
}

export type BranchInstanceGroups = {
  running: LauncherBranchInstance[];
  attention: LauncherBranchInstance[];
  startable: LauncherBranchInstance[];
  maintenance: LauncherBranchInstance[];
};

export type InstanceListFilters = {
  dirty?: boolean;
  unmerged?: boolean;
};

export function overlayCleanupMetadata(
  items: readonly LauncherBranchInstance[],
  annotated?: readonly LauncherBranchInstance[] | null,
): LauncherBranchInstance[] {
  if (!annotated?.length) {
    return [...items];
  }
  const byId = new Map(annotated.map((item) => [item.id, item]));
  return items.map((item) => {
    const extra = byId.get(item.id);
    if (!extra) {
      return item;
    }
    return {
      ...item,
      mergedToMain: extra.mergedToMain,
      cleanupEligible: extra.cleanupEligible,
      cleanupRisks: extra.cleanupRisks,
    };
  });
}

export function instanceWindowOpen(item: LauncherBranchInstance): boolean {
  return Boolean(item.runtime.window.open);
}

export function instanceHasLiveRuntime(item: LauncherBranchInstance): boolean {
  const backend = item.runtime.backend;
  return Boolean(backend.alive || backend.listening || instanceWindowOpen(item));
}

function pendingAppliesTo(item: LauncherBranchInstance, pending?: InstancePendingOperation): boolean {
  if (!pending) {
    return false;
  }
  if (pending.instanceIds && pending.instanceIds.length > 0) {
    return pending.instanceIds.includes(item.id);
  }
  return pending.instanceId === item.id;
}

export function pendingLifecycleReflected(
  item: LauncherBranchInstance,
  pending: InstancePendingOperation,
): boolean {
  const state = item.runtime.lifecycleState;
  if (pending.baselineLifecycleState) {
    return state !== pending.baselineLifecycleState;
  }
  if (pending.operation === "start") {
    return state !== "closed";
  }
  if (pending.operation === "stop") {
    return state === "closed" || state === "stopping" || state === "error";
  }
  return state === "restarting" || state === "starting" || state === "error";
}

export function resolveActivePendingOperation(
  pending: InstancePendingOperation | undefined,
  items: readonly LauncherBranchInstance[],
): InstancePendingOperation | undefined {
  if (!pending) {
    return undefined;
  }
  const ids = pending.instanceIds && pending.instanceIds.length > 0
    ? pending.instanceIds
    : [pending.instanceId];
  const remaining = ids.filter((id) => {
    const item = items.find((candidate) => candidate.id === id);
    return !item || !pendingLifecycleReflected(item, pending);
  });
  if (remaining.length === 0) {
    return undefined;
  }
  return {
    instanceId: remaining[0],
    instanceIds: remaining.length > 1 ? remaining : undefined,
    operation: pending.operation,
    baselineLifecycleState: pending.baselineLifecycleState,
  };
}

export function instanceRuntimeState(
  item: LauncherBranchInstance,
  pending?: LifecyclePendingInput,
): InstanceRuntimeState {
  const active = resolveItemPending(item, pending);
  if (active) {
    if (active.operation === "stop") {
      return "stopping";
    }
    return active.operation === "restart" ? "restarting" : "starting";
  }
  const states: Record<LauncherBranchInstance["runtime"]["lifecycleState"], InstanceRuntimeState> = {
    closed: "stopped",
    starting: "starting",
    running: "running",
    stopping: "stopping",
    restarting: "restarting",
    partial: "partial",
    error: "failed",
  };
  return states[item.runtime.lifecycleState];
}

export function instanceRuntimeStateLabel(state: InstanceRuntimeState, isZh: boolean): string {
  if (isZh) {
    return {
      starting: "正在启动",
      running: "正常运行",
      partial: "部分运行",
      stopping: "停止中",
      restarting: "重启中",
      failed: "需要处理",
      stopped: "已停止",
    }[state];
  }
  return {
    starting: "Starting",
    running: "Running",
    partial: "Partially running",
    stopping: "Stopping",
    restarting: "Restarting",
    failed: "Needs attention",
    stopped: "Stopped",
  }[state];
}

export function isOperableInstance(item: LauncherBranchInstance): boolean {
  return Boolean(item.checkedOut && (item.kind === "main" || item.kind === "worktree"));
}

export function isStartableInstance(item: LauncherBranchInstance, pending?: LifecyclePendingInput): boolean {
  return Boolean(item.startable && isOperableInstance(item) && instanceRuntimeState(item, pending) === "stopped");
}

export function isAttentionInstance(item: LauncherBranchInstance, pending?: LifecyclePendingInput): boolean {
  const state = instanceRuntimeState(item, pending);
  if (["starting", "stopping", "restarting"].includes(state)) {
    return false;
  }
  if (state === "failed") {
    return true;
  }
  return state === "partial" && !instanceHasLiveRuntime(item);
}

export function instanceStopLabel(item: LauncherBranchInstance, isZh: boolean, pending?: LifecyclePendingInput): string {
  if (isAttentionInstance(item, pending) && !instanceHasLiveRuntime(item)) {
    return isZh ? "关闭" : "Close";
  }
  return isZh ? "停止" : "Stop";
}

export function instanceErrorMessage(item: LauncherBranchInstance): string {
  return String(item.runtime.error?.message || "").trim();
}

export function formatAttentionReason(item: LauncherBranchInstance, isZh: boolean): string {
  const error = instanceErrorMessage(item);
  const registryReason = formatRegistryLeaseReason(item, isZh);
  if (error) {
    return registryReason ? `${error} · ${registryReason}` : error;
  }
  const bits: string[] = [];
  const backend = item.runtime.backend;
  if (!backend.alive && !backend.listening) {
    bits.push(isZh ? "后端未运行" : "Backend not running");
  }
  if (backend.portConflict) {
    bits.push(isZh ? "端口冲突" : "Port conflict");
  }
  const frontend = item.runtime.frontend;
  if (!String(frontend.mode).includes("dev") && !frontend.ready) {
    bits.push(isZh ? "前端未构建" : "Frontend not built");
  }
  if (!instanceWindowOpen(item)) {
    bits.push(isZh ? "窗口未打开" : "Window closed");
  }
  if (registryReason) {
    bits.push(registryReason);
  }
  return bits.join(" · ") || (isZh ? "运行状态异常" : "Runtime needs attention");
}

function compareInstances(a: LauncherBranchInstance, b: LauncherBranchInstance): number {
  if (a.current !== b.current) {
    return a.current ? -1 : 1;
  }
  if (a.alive !== b.alive) {
    return a.alive ? -1 : 1;
  }
  return String(a.shortName || a.branch || a.id).localeCompare(String(b.shortName || b.branch || b.id));
}

export function groupBranchInstances(
  items: readonly LauncherBranchInstance[],
  pending?: LifecyclePendingInput,
): BranchInstanceGroups {
  const groups: BranchInstanceGroups = { running: [], attention: [], startable: [], maintenance: [] };
  items.forEach((item) => {
    const state = instanceRuntimeState(item, pending);
    if (state === "stopped") {
      if (isStartableInstance(item, pending)) {
        groups.startable.push(item);
      } else {
        groups.maintenance.push(item);
      }
      return;
    }
    if (isAttentionInstance(item, pending)) {
      groups.attention.push(item);
      return;
    }
    groups.running.push(item);
  });
  groups.running.sort(compareInstances);
  groups.attention.sort(compareInstances);
  groups.startable.sort(compareInstances);
  groups.maintenance.sort(compareInstances);
  return groups;
}

export function instanceMatchesQuery(item: LauncherBranchInstance, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  const haystack = [item.id, item.branch, item.shortName, item.path, item.displayPath]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}

export function instanceMustRemainVisible(
  item: LauncherBranchInstance,
  pending?: LifecyclePendingInput,
): boolean {
  if (item.kind === "main" || item.current || item.id === "main") {
    return true;
  }
  if (instanceHasLiveRuntime(item)) {
    return true;
  }
  return instanceRuntimeState(item, pending) !== "stopped";
}

export function instanceMatchesFilters(
  item: LauncherBranchInstance,
  filters: InstanceListFilters,
  pending?: LifecyclePendingInput,
): boolean {
  if (instanceMustRemainVisible(item, pending)) {
    return true;
  }
  if (filters.dirty && !item.dirty) {
    return false;
  }
  if (filters.unmerged && item.mergedToMain !== false) {
    return false;
  }
  return true;
}

export function filterBranchInstances(
  items: readonly LauncherBranchInstance[],
  query: string,
  filters: InstanceListFilters = {},
  pending?: LifecyclePendingInput,
): LauncherBranchInstance[] {
  return items.filter((item) => instanceMatchesQuery(item, query) && instanceMatchesFilters(item, filters, pending));
}

function withPort(label: string, port: number): string {
  return port > 0 ? `${label} · :${port}` : label;
}

export function formatBackendStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const backend = item.runtime.backend;
  const port = Number(backend.port || 0);
  if (backend.portConflict) {
    return withPort(isZh ? "端口冲突" : "Port conflict", port);
  }
  if (!backend.alive && !backend.listening) {
    return isZh ? "未运行" : "Not running";
  }
  if (backend.alive && backend.healthy && backend.listening) {
    return withPort(isZh ? "健康" : "Healthy", port);
  }
  return withPort(isZh ? "需检查" : "Check required", port);
}

export function formatFrontendStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const frontend = item.runtime.frontend;
  const stopped = item.runtime.lifecycleState === "closed";
  if (String(frontend.mode).includes("dev")) {
    if (stopped) {
      return isZh ? "Dev Server 模式" : "Dev server mode";
    }
    return frontend.ready
      ? (isZh ? "Dev Server 就绪" : "Dev server ready")
      : (isZh ? "Dev Server 异常" : "Dev server unavailable");
  }
  if (frontend.ready) {
    return isZh ? "前端已构建" : "Frontend built";
  }
  return stopped
    ? (isZh ? "内置模式 · 启动时构建" : "Bundled · Build on start")
    : (isZh ? "前端未构建 · 启动时构建" : "Frontend unbuilt · builds on start");
}

export function formatWorkbenchStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const title = String(item.runtime.window.title || item.workbenchTitle || `${item.shortName || item.branch || item.id}${isZh ? " 台" : " Workbench"}`);
  return `${title} · ${instanceWindowOpen(item) ? (isZh ? "已打开" : "Open") : (isZh ? "未打开" : "Closed")}`;
}

export function formatGitStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const states: string[] = [];
  if (item.dirty) {
    states.push(isZh ? "有未提交" : "Uncommitted");
  }
  if (item.mergedToMain === false) {
    states.push(isZh ? "未合入 main" : "Not merged to main");
  }
  return states.length > 0 ? states.join(" · ") : (isZh ? "干净" : "Clean");
}

export function canRequestOpenInstance(item: LauncherBranchInstance, pending?: LifecyclePendingInput): boolean {
  if (!isOperableInstance(item) || item.startBlockReason === "launcher_refresh_required") {
    return false;
  }
  return !["starting", "stopping", "restarting"].includes(instanceRuntimeState(item, pending));
}

export function canStartInstance(item: LauncherBranchInstance, pending?: LifecyclePendingInput): boolean {
  return isStartableInstance(item, pending)
    || (canRequestOpenInstance(item, pending) && !instanceWindowOpen(item));
}

export function registryClassificationOf(item: LauncherBranchInstance): string {
  return String(item.runtime.registryClassification || "").trim().toLowerCase();
}

export function isUnknownRegistryInstance(item: LauncherBranchInstance): boolean {
  return registryClassificationOf(item) === "unknown";
}

export function formatRegistryLeaseReason(item: LauncherBranchInstance, isZh: boolean): string {
  const bits: string[] = [];
  if (isUnknownRegistryInstance(item)) {
    bits.push(isZh ? "身份未知，仅可诊断" : "Unknown identity, diagnosis only");
  }
  const lease = String(item.runtime.portLeaseStatus || item.portLeaseStatus || "").trim();
  if (lease) {
    bits.push(isZh ? `端口租约 ${lease}` : `port lease ${lease}`);
  }
  const firstObservedAt = String(item.runtime.firstObservedAt || "").trim();
  if (firstObservedAt) {
    bits.push(isZh ? `首次观察 ${firstObservedAt}` : `first observed ${firstObservedAt}`);
  }
  const nextReconcileAt = String(item.runtime.nextReconcileAt || "").trim();
  if (nextReconcileAt) {
    bits.push(isZh ? `下次核对 ${nextReconcileAt}` : `next check ${nextReconcileAt}`);
  }
  return bits.join(" · ");
}

export function canStopInstance(item: LauncherBranchInstance, pending?: LifecyclePendingInput): boolean {
  const state = instanceRuntimeState(item, pending);
  if (state === "stopping") {
    return false;
  }
  const startingOrRestarting = state === "starting" || state === "restarting";
  if (isUnknownRegistryInstance(item) && !instanceHasLiveRuntime(item) && !startingOrRestarting) {
    return false;
  }
  const failedLeftover = (state === "failed" || state === "partial") && !instanceHasLiveRuntime(item);
  return (isOperableInstance(item) || failedLeftover)
    && item.startBlockReason !== "launcher_refresh_required"
    && (instanceHasLiveRuntime(item) || state === "failed" || state === "partial" || startingOrRestarting);
}

export function paginateItems<T>(items: readonly T[], page: number, pageSize = BRANCH_INSTANCE_PAGE_SIZE) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(1, page), pageCount);
  const start = (safePage - 1) * pageSize;
  const slice = items.slice(start, start + pageSize);
  return {
    page: safePage,
    pageCount,
    start,
    end: start + slice.length,
    items: slice,
  };
}
