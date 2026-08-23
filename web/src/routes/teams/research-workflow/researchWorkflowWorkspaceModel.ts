import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";
import type {
  ResearchWorkflowCurrentTask,
  ResearchWorkflowProgress,
  ResearchWorkflowSnapshot,
  ResearchWorkflowTaskState,
} from "../../../api/types/research-workflow/core";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";

export type ResearchWorkflowWorkspaceScope = {
  teamId: string;
  workflowId: string;
  questionId: string | null;
  runId: string | null;
  runVersion: number | null;
};

export type ResearchWorkflowWorkspaceLoadState =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error"
  | "scope_mismatch"
  | "resync_required";

export type ResearchWorkflowCatalogAuthorization = {
  required?: boolean;
  authorized?: boolean;
  status?: string | null;
  label?: string | null;
  detail?: string | null;
  authorizationId?: string | null;
};

export type ResearchWorkflowFormalPrimaryAction = {
  source: "formal_runtime";
  kind: "command_offer";
  offer: CommandOffer;
};

export type ResearchWorkflowWorkspaceTaskStatus =
  | "not_started"
  | "running"
  | "waiting_system"
  | "waiting_user"
  | "recoverable_error"
  | "blocked"
  | "never_started"
  | "failed_to_dispatch"
  | "completed";

export type ResearchWorkflowFormalWorkspaceTask = {
  source: "formal_runtime";
  authority: "formal_runtime";
  key: string;
  nodeId: string | null;
  stageId: string | null;
  nodeRunId: string | null;
  attempt: number | null;
  actorKind: string | null;
  taskId: string | null;
  state: ResearchWorkflowTaskState;
  status: ResearchWorkflowWorkspaceTaskStatus;
  kind: ResearchWorkflowCurrentTask["kind"];
  label: string;
  detail: string;
  responsibility: ResearchWorkflowCurrentTask["responsibility"];
  automaticNextStep: ResearchWorkflowCurrentTask["automaticNextStep"];
  blockedReason: ResearchWorkflowCurrentTask["blockedReason"];
  recovery: ResearchWorkflowCurrentTask["recovery"];
  primaryAction: ResearchWorkflowFormalPrimaryAction | null;
};

export type ResearchWorkflowCatalogAuthorizationTask = {
  source: "catalog_authorization";
  authority: "catalog_authorization";
  key: string;
  status: "waiting_user" | "blocked" | "completed";
  permission: "required" | "waiting" | "denied" | "authorized";
  title: string;
  detail: string;
  primaryAction: null;
};

export type ResearchWorkflowHypothesisWorkspaceTask = {
  source: "hypothesis_first";
  authority: "hypothesis_first";
  key: string;
  status: ResearchWorkflowWorkspaceTaskStatus;
  title: string;
  detail: string;
  targetNodeId: string | null;
  primaryAction: null;
  nextAction: HypothesisFirstNextAction;
};

export type ResearchWorkflowRouteWorkspaceTask = {
  source: "route";
  authority: "route";
  key: string;
  status: "not_started";
  title: string;
  detail: string;
  targetNodeId: null;
  primaryAction: null;
};

export type ResearchWorkflowWorkspaceTask =
  | ResearchWorkflowFormalWorkspaceTask
  | ResearchWorkflowCatalogAuthorizationTask
  | ResearchWorkflowHypothesisWorkspaceTask
  | ResearchWorkflowRouteWorkspaceTask;

export type ResearchWorkflowWorkspaceModelInput = {
  scope: ResearchWorkflowWorkspaceScope;
  snapshot: ResearchWorkflowSnapshot | null;
  commandOffers?: readonly CommandOffer[] | null;
  legacyNextAction?: HypothesisFirstNextAction | null;
  catalogAuthorization?: ResearchWorkflowCatalogAuthorization | null;
  selectedNodeId?: string | null;
  panel: ResearchProcessPanel;
  loading?: boolean;
  refreshing?: boolean;
  error?: string | null;
  resyncRequired?: boolean;
  previous?: ResearchWorkflowWorkspaceModel | null;
};

export type ResearchWorkflowWorkspaceModel = {
  scope: ResearchWorkflowWorkspaceScope;
  scopeKey: string;
  loadState: ResearchWorkflowWorkspaceLoadState;
  source: "formal_runtime" | "catalog_authorization" | "hypothesis_first" | "route";
  scopeMismatch: boolean;
  snapshot: ResearchWorkflowSnapshot | null;
  sequence: number;
  progress: ResearchWorkflowProgress | null;
  currentTask: ResearchWorkflowWorkspaceTask | null;
  primaryAction: ResearchWorkflowFormalPrimaryAction | null;
  legacyNextAction: HypothesisFirstNextAction | null;
  view: {
    panel: ResearchProcessPanel;
    selectedNodeId: string | null;
    selectedIsCurrentTask: boolean;
    archiveMode: boolean;
  };
  resyncRequired: boolean;
  error: string | null;
};

const HYPOTHESIS_STAGE_LABELS: Record<string, string> = {
  no_run: "选择题目开始研究",
  generation_missing: "生成候选假说",
  generation_running: "候选假说讨论中",
  generation_ready_to_summarize: "整理候选清单",
  generation_summarizing: "候选清单正在整理",
  generation_awaiting_approval: "确认候选假说清单",
  selection_required: "选择进入评审的假说",
  review_running: "团队评审进行中",
  next_review: "下一轮评审已开启",
  review_ready_to_summarize: "整理本轮评审结论",
  review_summarizing: "评审正在整理",
  review_awaiting_approval: "确认本轮评审结论",
  collecting: "正在补充证据",
  collection_recovery: "资料补充需要处理",
  handoff_pending: "等待自动交接",
  budget_exhausted: "需要人工裁决",
  converged: "假说阶段完成",
  blocked: "当前流程需要处理",
};

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function normalizedQuestion(value: unknown): string {
  return text(value).toUpperCase();
}

function scopeKey(scope: ResearchWorkflowWorkspaceScope): string {
  return [
    text(scope.teamId),
    text(scope.workflowId),
    normalizedQuestion(scope.questionId) || "no-question",
    text(scope.runId) || "no-run",
    scope.runVersion == null ? "no-version" : String(scope.runVersion),
  ].join("::");
}

function comparable(value: unknown, question = false): string {
  return question ? normalizedQuestion(value) : text(value);
}

function scopeConflict(
  requested: ResearchWorkflowWorkspaceScope,
  snapshot: ResearchWorkflowSnapshot | null,
): boolean {
  if (!snapshot) return false;
  const run = snapshot.run;
  const pairs: Array<[unknown, unknown, boolean]> = [
    [requested.teamId, run.teamId, false],
    [requested.workflowId, run.workflowId, false],
    [requested.questionId, run.questionId, true],
    [requested.runId, run.runId, false],
  ];
  if (pairs.some(([left, right, question]) => {
    const a = comparable(left, question);
    const b = comparable(right, question);
    return Boolean(a && b && a !== b);
  })) return true;
  return requested.runVersion != null
    && run.runVersion != null
    && requested.runVersion !== run.runVersion;
}

function statusForFormalTask(state: ResearchWorkflowTaskState): ResearchWorkflowWorkspaceTaskStatus {
  switch (state) {
    case "auto_running":
      return "running";
    case "waiting_user":
      return "waiting_user";
    case "blocked_retryable":
      return "recoverable_error";
    case "blocked_terminal":
      return "blocked";
    case "completed":
      return "completed";
  }
}

function canExposeFormalAction(state: ResearchWorkflowTaskState): boolean {
  return state === "waiting_user" || state === "blocked_retryable";
}

function matchingFormalOffer(
  task: ResearchWorkflowCurrentTask,
  snapshot: ResearchWorkflowSnapshot,
  offers: readonly CommandOffer[],
): ResearchWorkflowFormalPrimaryAction | null {
  if (!canExposeFormalAction(task.state)) return null;
  const taskNodeId = text(task.nodeId);
  const runVersion = snapshot.run.runVersion;
  const matching = offers.filter((offer) => (
    offer.available
    && text(offer.nodeId) === taskNodeId
    && Number(offer.expectedRunVersion) === Number(runVersion)
  ));
  if (matching.length !== 1) return null;
  return {
    source: "formal_runtime",
    kind: "command_offer",
    offer: matching[0],
  };
}

function formalTask(
  snapshot: ResearchWorkflowSnapshot,
  offers: readonly CommandOffer[],
): ResearchWorkflowFormalWorkspaceTask | null {
  const task = snapshot.currentTask;
  if (!task) return null;
  const primaryAction = matchingFormalOffer(task, snapshot, offers);
  return {
    source: "formal_runtime",
    authority: "formal_runtime",
    key: task.key,
    nodeId: task.nodeId,
    stageId: task.stageId,
    nodeRunId: task.nodeRunId,
    attempt: task.attempt,
    actorKind: task.actorKind,
    taskId: task.taskId,
    state: task.state,
    status: statusForFormalTask(task.state),
    kind: task.kind,
    label: text(task.label) || "当前任务",
    detail: text(task.detail) || "工作流正在处理当前任务",
    responsibility: task.responsibility,
    automaticNextStep: task.automaticNextStep,
    blockedReason: task.blockedReason,
    recovery: task.recovery,
    primaryAction,
  };
}

function authorizationStatus(
  authorization: ResearchWorkflowCatalogAuthorization,
): ResearchWorkflowCatalogAuthorizationTask["permission"] | null {
  if (!authorization.required) return null;
  if (authorization.authorized === true) return "authorized";
  const status = text(authorization.status).toLowerCase();
  if (["authorized", "approved", "granted", "ready", "complete", "completed"].includes(status)) {
    return "authorized";
  }
  if (["denied", "rejected", "blocked"].includes(status)) return "denied";
  if (["required"].includes(status)) return "required";
  return "waiting";
}

function authorizationTask(
  scope: ResearchWorkflowWorkspaceScope,
  authorization: ResearchWorkflowCatalogAuthorization,
): ResearchWorkflowCatalogAuthorizationTask | null {
  const permission = authorizationStatus(authorization);
  if (!permission || permission === "authorized") return null;
  return {
    source: "catalog_authorization",
    authority: "catalog_authorization",
    key: `${scopeKey(scope)}::catalog-authorization`,
    status: permission === "denied" ? "blocked" : "waiting_user",
    permission,
    title: text(authorization.label) || "需要研究授权",
    detail: text(authorization.detail) || "目录研究需要授权后才能启动正式工作流。",
    primaryAction: null,
  };
}

function hypothesisTask(
  scope: ResearchWorkflowWorkspaceScope,
  nextAction: HypothesisFirstNextAction,
): ResearchWorkflowHypothesisWorkspaceTask {
  const status: ResearchWorkflowWorkspaceTaskStatus = nextAction.stage === "blocked"
    ? "blocked"
    : nextAction.recovery
      ? "recoverable_error"
      : ["generation_running", "review_running", "next_review", "collecting", "generation_summarizing", "review_summarizing"].includes(nextAction.stage)
        ? "running"
        : ["generation_awaiting_approval", "selection_required", "budget_exhausted"].includes(nextAction.stage)
          ? "waiting_user"
          : nextAction.stage === "no_run"
            ? "not_started"
            : "waiting_system";
  return {
    source: "hypothesis_first",
    authority: "hypothesis_first",
    key: `${scopeKey(scope)}::hypothesis::${text(nextAction.meetingRoundId || nextAction.collectionRequestId || nextAction.stage)}`,
    status,
    title: HYPOTHESIS_STAGE_LABELS[nextAction.stage] || "当前假说任务",
    detail: text(nextAction.statusMessage || nextAction.disabledReason || nextAction.commandDetail) || "请继续当前假说先行流程。",
    targetNodeId: nextAction.targetNodeId ?? null,
    primaryAction: null,
    nextAction,
  };
}

function routeTask(scope: ResearchWorkflowWorkspaceScope): ResearchWorkflowRouteWorkspaceTask {
  return {
    source: "route",
    authority: "route",
    key: `${scopeKey(scope)}::no-run`,
    status: "not_started",
    title: "选择题目开始研究",
    detail: "选择研究题目后，系统会先组织候选假说讨论。",
    targetNodeId: null,
    primaryAction: null,
  };
}

function acceptedSnapshot(
  input: ResearchWorkflowWorkspaceModelInput,
): ResearchWorkflowSnapshot | null {
  const nextScopeKey = scopeKey(input.scope);
  const current = input.previous?.scopeKey === nextScopeKey
    ? input.previous.snapshot
    : null;
  const next = input.snapshot;
  if (!next) return current;
  if (!current) return next;
  const nextSequence = Number(next.latestEventSequence) || 0;
  const currentSequence = Number(current.latestEventSequence) || 0;
  if (nextSequence < currentSequence) return current;
  if (nextSequence === currentSequence && Number(next.run.runVersion) < Number(current.run.runVersion)) {
    return current;
  }
  return next;
}

function withLoadState(
  input: ResearchWorkflowWorkspaceModelInput,
  scopeMismatch: boolean,
  currentTask: ResearchWorkflowWorkspaceTask | null,
): ResearchWorkflowWorkspaceLoadState {
  if (scopeMismatch) return "scope_mismatch";
  if (input.resyncRequired) return "resync_required";
  if (input.error) return "error";
  if (input.loading) return "loading";
  if (input.refreshing) return "refreshing";
  return currentTask || input.scope.questionId ? "ready" : "idle";
}

export function buildResearchWorkflowWorkspaceModel(
  input: ResearchWorkflowWorkspaceModelInput,
): ResearchWorkflowWorkspaceModel {
  const currentScopeKey = scopeKey(input.scope);
  const samePreviousScope = input.previous?.scopeKey === currentScopeKey;
  const snapshot = acceptedSnapshot(input);
  const scopeMismatch = scopeConflict(input.scope, snapshot);
  const formalRunRequested = Boolean(text(input.scope.runId));
  const formalRun = Boolean(snapshot && !scopeMismatch && formalRunRequested);
  const offers = input.commandOffers ?? snapshot?.commandOffers ?? [];
  let source: ResearchWorkflowWorkspaceModel["source"] = "route";
  let currentTask: ResearchWorkflowWorkspaceTask | null = null;
  let primaryAction: ResearchWorkflowFormalPrimaryAction | null = null;
  let legacyNextAction: HypothesisFirstNextAction | null = null;

  if (!scopeMismatch && formalRun && snapshot) {
    source = "formal_runtime";
    currentTask = formalTask(snapshot, offers);
    primaryAction = currentTask?.source === "formal_runtime" ? currentTask.primaryAction : null;
  } else if (!scopeMismatch && formalRunRequested) {
    // A route that already names a formal run must wait for its matching
    // snapshot. Hypothesis-first state from the previous/pre-run scope cannot
    // become the formal current task while loading or after a read failure.
    source = "formal_runtime";
  } else if (!scopeMismatch) {
    const authorization = authorizationTask(input.scope, input.catalogAuthorization ?? {});
    if (authorization) {
      source = "catalog_authorization";
      currentTask = authorization;
    } else if (input.legacyNextAction) {
      source = "hypothesis_first";
      legacyNextAction = input.legacyNextAction;
      currentTask = hypothesisTask(input.scope, input.legacyNextAction);
    } else {
      source = "route";
      currentTask = routeTask(input.scope);
    }
  }

  const sequence = Math.max(
    samePreviousScope ? Number(input.previous?.sequence) || 0 : 0,
    Number(snapshot?.latestEventSequence) || 0,
  );
  const selectedNodeId = text(input.selectedNodeId) || null;
  const taskNodeId = currentTask?.source === "formal_runtime"
    ? currentTask.nodeId
    : currentTask?.source === "hypothesis_first"
      ? currentTask.targetNodeId
      : null;
  const actionsPaused = scopeMismatch
    || Boolean(input.resyncRequired)
    || Boolean(input.loading)
    || Boolean(input.error);
  if (actionsPaused && currentTask?.source === "formal_runtime") {
    currentTask = { ...currentTask, primaryAction: null };
  }
  return {
    scope: input.scope,
    scopeKey: currentScopeKey,
    loadState: withLoadState(input, scopeMismatch, currentTask),
    source,
    scopeMismatch,
    snapshot,
    sequence,
    progress: snapshot?.progress ?? null,
    currentTask: scopeMismatch ? null : currentTask,
    primaryAction: actionsPaused ? null : primaryAction,
    legacyNextAction,
    view: {
      panel: input.panel,
      selectedNodeId,
      selectedIsCurrentTask: Boolean(selectedNodeId && input.panel === "node" && taskNodeId && selectedNodeId === taskNodeId),
      archiveMode: input.panel === "question",
    },
    resyncRequired: Boolean(input.resyncRequired),
    error: input.error ?? null,
  };
}

export function mergeResearchWorkflowWorkspaceSnapshot(
  current: ResearchWorkflowWorkspaceModel,
  input: Omit<ResearchWorkflowWorkspaceModelInput, "previous">,
): ResearchWorkflowWorkspaceModel {
  return buildResearchWorkflowWorkspaceModel({ ...input, previous: current });
}

export function formalWorkspaceTaskStatus(
  state: ResearchWorkflowTaskState,
): ResearchWorkflowWorkspaceTaskStatus {
  return statusForFormalTask(state);
}
