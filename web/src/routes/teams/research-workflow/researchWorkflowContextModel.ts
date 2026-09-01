import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import type {
  ActionCommand,
  CommandAction,
} from "../../../api/types/hypothesisFirst";
import {
  type HypothesisFirstCommand,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { getNodeAdapter } from "./nodeAdapterModel";
import { RESEARCH_STAGE_TERMS } from "./researchTerminology";
import type {
  ResearchWorkflowWorkspaceModel,
  ResearchWorkflowWorkspaceTask,
} from "./researchWorkflowWorkspaceModel";

export type ResearchWorkflowLoadState =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error"
  | "resync_required"
  | "scope_mismatch";

export type ResearchWorkflowStageId =
  | "hypothesis_first"
  | "knowledge_collection"
  | "experiment_design"
  | "execution_iteration";

export type ResearchWorkflowTaskStep =
  | "launch"
  | "generation"
  | "selection"
  | "review"
  | "evidence_gap"
  | "convergence"
  | "formal_runtime";

export type ResearchWorkflowTaskStatus =
  | "not_started"
  | "running"
  | "waiting_system"
  | "waiting_user"
  | "recoverable_error"
  | "blocked"
  | "never_started"
  | "failed_to_dispatch"
  | "completed";

export type ResearchWorkflowDispatchStatus = "never_started" | "failed_to_dispatch";

type ResearchWorkflowNodeAttemptProjection = {
  nodeRunId?: string | null;
  attempt?: number | null;
  status?: string | null;
};

export type ResearchWorkflowCommandAction = {
  /** Legacy-channel command; undefined when the action is canonical-only. */
  command?: HypothesisFirstCommand;
  /** V2-only command with no legacy endpoint backing this CTA. */
  canonicalCommand?: ActionCommand;
  /** Signed canonical action to dispatch for a canonical-only CTA. */
  canonicalAction?: CommandAction;
  label: string;
  detail?: string;
  disabledReason?: string;
};

export type ResearchWorkflowNavigationAction = {
  targetNodeId: string;
  label: string;
};

export type ResearchWorkflowCurrentTask = {
  key: string;
  stage: ResearchWorkflowStageId;
  step: ResearchWorkflowTaskStep;
  status: ResearchWorkflowTaskStatus;
  title: string;
  detail: string;
  targetNodeId: string | null;
  meetingRoundId?: string;
  collectionRequestId?: string;
  progress?: { current: number; total: number; label: string };
  navigationAction: ResearchWorkflowNavigationAction | null;
  commandAction: ResearchWorkflowCommandAction | null;
  retryAction?: { label: string; detail?: string };
  blocker?: { code: string; message: string; retryable: boolean };
  authority: "hypothesis_first" | "formal_runtime" | "route";
};

export type ResearchWorkflowStageSummary = {
  id: ResearchWorkflowStageId;
  label: string;
  detail: string;
  state: "completed" | "current" | "upcoming" | "blocked";
};

export type ResearchWorkflowContext = {
  scope: {
    key: string;
    teamId: string;
    workflowId: string;
    questionId: string | null;
    runId: string | null;
    runVersion: number | null;
  };
  loadState: ResearchWorkflowLoadState;
  currentTask: ResearchWorkflowCurrentTask | null;
  stages: ResearchWorkflowStageSummary[];
  view: {
    panel: ResearchProcessPanel;
    selectedNodeId: string | null;
    selectedIsCurrentTask: boolean;
    archiveMode: boolean;
  };
};

export type BuildResearchWorkflowContextInput = {
  teamId: string;
  workflowId: string;
  questionId?: string | null;
  runId?: string | null;
  runVersion?: number | null;
  dataQuestionId?: string | null;
  dataRunId?: string | null;
  dataTeamId?: string | null;
  dataWorkflowId?: string | null;
  dataRunVersion?: number | null;
  /** Once true, every requested identity must be present and equal. */
  dataScopeReady?: boolean;
  /** Server-owned run state used to distinguish a dispatch failure from a normal task. */
  runStatus?: string | null;
  runTerminalReason?: string | null;
  /** Canvas projection of node attempts; pending binding placeholders are not attempts. */
  nodeRuns?: Readonly<Record<string, ResearchWorkflowNodeAttemptProjection>> | null;
  scopeMismatch?: boolean;
  loading?: boolean;
  refreshing?: boolean;
  error?: string | null;
  nextAction?: HypothesisFirstNextAction | null;
  selectedNodeId?: string | null;
  panel: ResearchProcessPanel;
  questionTitle?: string | null;
  roundProgress?: { current: number; total: number } | null;
  /** Normalized formal/catalog/hypothesis authority from the workspace model. */
  workspaceModel?: ResearchWorkflowWorkspaceModel | null;
};

const STAGES: Array<Pick<ResearchWorkflowStageSummary, "id" | "label" | "detail">> = [
  { id: "hypothesis_first", label: "假说先行", detail: "形成、选择并评审假说" },
  { id: "knowledge_collection", label: RESEARCH_STAGE_TERMS.knowledge_collection.zh, detail: "围绕收敛假说补充证据" },
  { id: "experiment_design", label: "实验设计", detail: "形成并冻结可执行协议" },
  { id: "execution_iteration", label: "执行迭代", detail: "运行、评价并归档成果" },
];

function normalized(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

function normalizedQuestion(value: string | null | undefined): string {
  return normalized(value).toUpperCase();
}

function hasNodeAttempt(nodeRun: ResearchWorkflowNodeAttemptProjection): boolean {
  if (normalized(nodeRun.nodeRunId)) return true;
  if (Number(nodeRun.attempt ?? 0) > 0) return true;
  const status = normalized(nodeRun.status).toLowerCase();
  return Boolean(status && status !== "pending");
}

/**
 * Dispatch state is derived only from server run facts. Binding placeholders
 * in the canvas projection have status=pending and no nodeRunId, so they do
 * not make a created run look started.
 */
export function researchWorkflowDispatchStatus(input: {
  runStatus?: string | null;
  runTerminalReason?: string | null;
  nodeRuns?: Readonly<Record<string, ResearchWorkflowNodeAttemptProjection>> | null;
}): ResearchWorkflowDispatchStatus | null {
  const status = normalized(input.runStatus).toLowerCase();
  const terminalReason = normalized(input.runTerminalReason).toLowerCase();
  if (status === "failed" && terminalReason === "dispatch_never_started") {
    return "failed_to_dispatch";
  }
  if (status === "created" && !Object.values(input.nodeRuns ?? {}).some(hasNodeAttempt)) {
    return "never_started";
  }
  return null;
}

export function buildResearchWorkflowScopeKey(input: {
  teamId: string;
  workflowId: string;
  questionId?: string | null;
  runId?: string | null;
  runVersion?: number | null;
}): string {
  return [
    normalized(input.teamId),
    normalized(input.workflowId),
    normalizedQuestion(input.questionId) || "no-question",
    normalized(input.runId) || "no-run",
    input.runVersion == null ? "no-version" : String(input.runVersion),
  ].join("::");
}

export function researchWorkflowScopeMismatch(input: {
  questionId?: string | null;
  runId?: string | null;
  runVersion?: number | null;
  teamId?: string | null;
  workflowId?: string | null;
  dataTeamId?: string | null;
  dataWorkflowId?: string | null;
  dataQuestionId?: string | null;
  dataRunId?: string | null;
  dataRunVersion?: number | null;
  dataScopeReady?: boolean;
}): boolean {
  const pairs: Array<[string, string]> = [
    [normalized(input.teamId), normalized(input.dataTeamId)],
    [normalized(input.workflowId), normalized(input.dataWorkflowId)],
    [normalizedQuestion(input.questionId), normalizedQuestion(input.dataQuestionId)],
    [normalized(input.runId), normalized(input.dataRunId)],
  ];
  for (const [requested, resolved] of pairs) {
    if (requested && resolved && requested !== resolved) return true;
    if (input.dataScopeReady && requested && !resolved) return true;
  }
  if (
    input.runVersion != null
    && input.dataRunVersion != null
    && input.runVersion !== input.dataRunVersion
  ) return true;
  if (input.dataScopeReady && input.runVersion != null && input.dataRunVersion == null) return true;
  return false;
}

type TaskPresentation = Pick<
  ResearchWorkflowCurrentTask,
  "stage" | "step" | "status" | "title" | "detail" | "authority"
>;

function dispatchPresentation(status: ResearchWorkflowDispatchStatus): TaskPresentation {
  if (status === "failed_to_dispatch") {
    return {
      stage: "hypothesis_first",
      step: "launch",
      status,
      title: "运行启动失败",
      detail: "运行在派发节点尝试前失败（dispatch_never_started），可以重试启动。",
      authority: "route",
    };
  }
  return {
    stage: "hypothesis_first",
    step: "launch",
    status,
    title: "运行从未启动",
    detail: "运行已创建，但还没有任何节点尝试，可能在派发前中断。可以重试启动。",
    authority: "route",
  };
}

function reviewTitle(action: HypothesisFirstNextAction, suffix: string): string {
  const round = action.meetingRoundId ? "本轮" : "评审";
  return `${round}${suffix}`;
}

/**
 * Build the workspace CTA from a next action. Legacy commands keep the old
 * shape; V2 canonical-only commands (stop_collection / cancel_run /
 * archive_run) have no legacy endpoint — `command` is undefined while the
 * signed action and server label are complete — so the CTA falls back to the
 * canonical channel instead of disappearing.
 */
function commandActionFor(
  action: HypothesisFirstNextAction,
  command = action.command,
  label = action.commandLabel,
): ResearchWorkflowCommandAction | null {
  if (command && label) {
    return {
      command,
      label,
      detail: action.commandDetail,
      disabledReason: action.disabledReason,
    };
  }
  if (!command && action.canonicalCommand && action.canonicalAction && action.commandLabel) {
    return {
      canonicalCommand: action.canonicalCommand,
      canonicalAction: action.canonicalAction,
      label: action.commandLabel,
      detail: action.commandDetail,
      disabledReason: action.disabledReason,
    };
  }
  return null;
}

function presentationFor(action: HypothesisFirstNextAction): TaskPresentation {
  switch (action.stage) {
    case "no_run":
      return {
        stage: "hypothesis_first",
        step: "launch",
        status: "not_started",
        title: "选择题目开始研究",
        detail: "选择研究题目后，系统会先组织候选假说讨论。",
        authority: "route",
      };
    case "generation_missing":
      return {
        stage: "hypothesis_first",
        step: "generation",
        status: "waiting_user",
        title: "生成候选假说",
        detail: "启动团队讨论，形成可供筛选的候选假说。",
        authority: "hypothesis_first",
      };
    case "generation_running":
      return {
        stage: "hypothesis_first",
        step: "generation",
        status: "running",
        title: "候选假说讨论中",
        detail: "团队正在围绕研究问题提出机制解释，暂时无需操作。",
        authority: "hypothesis_first",
      };
    case "generation_ready_to_summarize":
    case "generation_summarizing":
      return {
        stage: "hypothesis_first",
        step: "generation",
        status: action.recovery ? "recoverable_error" : "waiting_system",
        title: action.recovery ? "候选清单整理失败" : "候选清单正在整理",
        detail: action.recovery
          ? "自动整理没有完成，可以在当前任务中重试。"
          : "系统正在把团队发言整理为候选假说；完成后需要你确认。",
        authority: "hypothesis_first",
      };
    case "generation_awaiting_approval":
      return {
        stage: "hypothesis_first",
        step: "generation",
        status: "waiting_user",
        title: "确认候选假说清单",
        detail: "确认后候选会进入假说选择，由你决定哪些进入评审。",
        authority: "hypothesis_first",
      };
    case "selection_required":
      return {
        stage: "hypothesis_first",
        step: "selection",
        status: "waiting_user",
        title: "选择进入评审的假说",
        detail: "从候选中选择本轮要评审的假说，提交后系统自动开启团队评审。",
        authority: "hypothesis_first",
      };
    case "review_running":
    case "next_review":
      return {
        stage: "hypothesis_first",
        step: "review",
        status: "running",
        title: action.stage === "next_review" ? "下一轮评审已开启" : "团队评审进行中",
        detail: "团队正在核对机制、反对意见和证据缺口，暂时无需操作。",
        authority: "hypothesis_first",
      };
    case "review_ready_to_summarize":
    case "review_summarizing":
      return {
        stage: "hypothesis_first",
        step: "review",
        status: action.recovery ? "recoverable_error" : "waiting_system",
        title: action.recovery ? reviewTitle(action, "结论整理失败") : reviewTitle(action, "评审正在整理"),
        detail: action.recovery
          ? "自动整理没有完成，可以在当前任务中重试。"
          : "系统正在把讨论整理成保留结论、反对意见和证据缺口；完成后需要你确认。",
        authority: "hypothesis_first",
      };
    case "review_awaiting_approval":
      return {
        stage: "hypothesis_first",
        step: "review",
        status: action.disabledReason ? "blocked" : "waiting_user",
        title: "确认本轮评审结论",
        detail: "确认后会归档本轮结论，并自动进入证据补充或假说收敛。",
        authority: "hypothesis_first",
      };
    case "collecting":
      return {
        stage: "hypothesis_first",
        step: "evidence_gap",
        status: "waiting_system",
        title: "正在补充证据",
        detail: "系统正围绕本轮证据缺口搜集资料；完成后会自动交接下一步。",
        authority: "hypothesis_first",
      };
    case "collection_recovery":
      return {
        stage: "hypothesis_first",
        step: "evidence_gap",
        status: "recoverable_error",
        title: "资料补充需要处理",
        detail: action.recovery?.reason || "资料搜集未完成，可以在当前任务中继续。",
        authority: "hypothesis_first",
      };
    case "handoff_pending":
      return {
        stage: "hypothesis_first",
        step: "evidence_gap",
        status: "recoverable_error",
        title: "资料等待自动交接",
        detail: "资料已搜集完成，但还没有交给下一轮评审，可以重试交接。",
        authority: "hypothesis_first",
      };
    case "budget_exhausted":
      return {
        stage: "hypothesis_first",
        step: "convergence",
        status: "waiting_user",
        title: "需要人工裁决",
        detail: "评审轮次预算已用完，需要人工决定保留哪些假说。",
        authority: "hypothesis_first",
      };
    case "converged": {
      const adapter = getNodeAdapter(action.targetNodeId);
      return adapter
        ? {
            stage: adapter.stageId,
            step: "formal_runtime",
            status: "running",
            title: adapter.label,
            detail: action.commandDetail || "假说阶段已完成，继续处理当前正式研究任务。",
            authority: "formal_runtime",
          }
        : {
            stage: "hypothesis_first",
            step: "convergence",
            status: "completed",
            title: "假说阶段完成",
            detail: "假说已经收敛，可以查看下一步研究任务。",
            authority: "hypothesis_first",
          };
    }
    case "program_delivery":
      return {
        stage: "hypothesis_first",
        step: "formal_runtime",
        status: action.disabledReason ? "blocked" : "waiting_user",
        title: action.disabledReason ? "正式结果交付需要处理" : "审核正式研究结果",
        detail: action.disabledReason || action.statusMessage || "正式研究结果已登记，等待完成 H1–H4 审核。",
        authority: "hypothesis_first",
      };
    case "completed":
      return {
        stage: "hypothesis_first",
        step: "formal_runtime",
        status: "completed",
        title: "挑战杯研究流程已闭环",
        detail: action.statusMessage || "正式研究结果和 H1–H4 审核均已完成。",
        authority: "hypothesis_first",
      };
    case "blocked":
      return {
        stage: "hypothesis_first",
        step: "convergence",
        status: "blocked",
        title: "当前流程需要处理",
        detail: action.disabledReason || "当前状态无法自动判断下一步。",
        authority: "hypothesis_first",
      };
  }
}

function stageSummaries(currentTask: ResearchWorkflowCurrentTask | null): ResearchWorkflowStageSummary[] {
  const currentIndex = currentTask ? STAGES.findIndex((stage) => stage.id === currentTask.stage) : -1;
  return STAGES.map((stage, index) => ({
    ...stage,
    state: !currentTask
      ? "upcoming"
      : index < currentIndex
        ? "completed"
        : index > currentIndex
          ? "upcoming"
          : currentTask.status === "blocked"
            ? "blocked"
            : "current",
  }));
}

function stageIdForContext(stageId: string | null | undefined): ResearchWorkflowStageId {
  if (stageId === "knowledge_collection" || stageId === "experiment_design" || stageId === "execution_iteration") {
    return stageId;
  }
  return "hypothesis_first";
}

function contextTaskFromWorkspaceTask(
  task: ResearchWorkflowWorkspaceTask | null,
): ResearchWorkflowCurrentTask | null {
  if (!task) return null;
  if (task.source === "formal_runtime") {
    return {
      key: task.key,
      stage: stageIdForContext(task.stageId),
      step: "formal_runtime",
      status: task.status,
      title: task.label,
      detail: task.detail,
      targetNodeId: task.nodeId,
      navigationAction: task.nodeId
        ? { targetNodeId: task.nodeId, label: task.label }
        : null,
      commandAction: null,
      blocker: task.blockedReason
        ? {
            code: task.blockedReason.code || "formal_runtime_blocked",
            message: task.blockedReason.message || task.blockedReason.detail || "当前正式任务被阻塞",
            retryable: task.recovery.retryable,
          }
        : undefined,
      authority: "formal_runtime",
    };
  }
  if (task.source === "catalog_authorization") {
    return {
      key: task.key,
      stage: "hypothesis_first",
      step: "launch",
      status: task.status,
      title: task.title,
      detail: task.detail,
      targetNodeId: null,
      navigationAction: null,
      commandAction: null,
      blocker: task.permission === "denied"
        ? { code: "catalog_authorization_denied", message: task.detail, retryable: false }
        : undefined,
      authority: "route",
    };
  }
  if (task.source === "hypothesis_first") {
    const presentation = presentationFor(task.nextAction);
    return {
      key: task.key,
      ...presentation,
      targetNodeId: task.targetNodeId,
      navigationAction: task.targetNodeId
        ? { targetNodeId: task.targetNodeId, label: task.nextAction.navigationLabel }
        : null,
      commandAction: commandActionFor(task.nextAction),
      blocker: task.nextAction.disabledReason
        ? {
            code: task.nextAction.stage === "blocked" ? "workflow_blocked" : "command_blocked",
            message: task.nextAction.disabledReason,
            retryable: Boolean(task.nextAction.recovery),
          }
        : undefined,
      meetingRoundId: task.nextAction.meetingRoundId,
      collectionRequestId: task.nextAction.collectionRequestId,
    };
  }
  return {
    key: task.key,
    stage: "hypothesis_first",
    step: "launch",
    status: task.status,
    title: task.title,
    detail: task.detail,
    targetNodeId: null,
    navigationAction: null,
    commandAction: null,
    authority: "route",
  };
}

function stageSummariesFromWorkspaceModel(
  model: ResearchWorkflowWorkspaceModel,
  currentTask: ResearchWorkflowCurrentTask | null,
): ResearchWorkflowStageSummary[] {
  const progressById = new Map(
    (model.progress?.stages ?? []).map((stage) => [stage.id, stage.state]),
  );
  const currentStage = currentTask?.stage;
  return STAGES.map((stage) => ({
    ...stage,
    state: progressById.get(stage.id)
      ?? (currentStage === stage.id
        ? (currentTask?.status === "blocked" ? "blocked" : "current")
        : "upcoming"),
  }));
}

export function buildResearchWorkflowContext(
  input: BuildResearchWorkflowContextInput,
): ResearchWorkflowContext {
  if (input.workspaceModel) {
    const model = input.workspaceModel;
    const currentTask = model.scopeMismatch ? null : contextTaskFromWorkspaceTask(model.currentTask);
    const loadState: ResearchWorkflowLoadState = model.scopeMismatch
      ? "scope_mismatch"
      : model.loadState === "resync_required"
        ? "resync_required"
        : model.loadState;
    return {
      scope: {
        key: model.scopeKey,
        teamId: model.scope.teamId,
        workflowId: model.scope.workflowId,
        questionId: model.scope.questionId,
        runId: model.scope.runId,
        runVersion: model.scope.runVersion,
      },
      loadState,
      currentTask,
      stages: stageSummariesFromWorkspaceModel(model, currentTask),
      view: {
        panel: model.view.panel,
        selectedNodeId: model.view.selectedNodeId,
        selectedIsCurrentTask: model.view.selectedIsCurrentTask,
        archiveMode: model.view.archiveMode,
      },
    };
  }
  const teamId = normalized(input.teamId);
  const workflowId = normalized(input.workflowId);
  const questionId = normalizedQuestion(input.questionId) || null;
  const runId = normalized(input.runId) || null;
  const scope = {
    key: buildResearchWorkflowScopeKey({
      teamId,
      workflowId,
      questionId,
      runId,
      runVersion: input.runVersion,
    }),
    teamId,
    workflowId,
    questionId,
    runId,
    runVersion: input.runVersion ?? null,
  };
  const mismatch = Boolean(input.scopeMismatch || researchWorkflowScopeMismatch(input));
  const loadState: ResearchWorkflowLoadState = mismatch
    ? "scope_mismatch"
    : input.error
      ? "error"
      : input.loading
        ? "loading"
        : input.refreshing
          ? "refreshing"
          : questionId || input.nextAction
            ? "ready"
            : "idle";

  const dispatchStatus = researchWorkflowDispatchStatus({
    runStatus: input.runStatus,
    runTerminalReason: input.runTerminalReason,
    nodeRuns: input.nodeRuns,
  });
  let currentTask: ResearchWorkflowCurrentTask | null = null;
  if (!mismatch && !input.loading && (input.nextAction || dispatchStatus)) {
    const action = input.nextAction;
    const presentation = dispatchStatus ? dispatchPresentation(dispatchStatus) : presentationFor(action!);
    currentTask = {
      key: [
        scope.key,
        dispatchStatus ? "dispatch" : action!.stage,
        dispatchStatus
          || action?.meetingRoundId
          || action?.collectionRequestId
          || action?.targetNodeId
          || "task",
      ].join("::"),
      ...presentation,
      targetNodeId: action?.targetNodeId ?? null,
      meetingRoundId: action?.meetingRoundId,
      collectionRequestId: action?.collectionRequestId,
      progress: input.roundProgress
        ? {
            ...input.roundProgress,
            label: `第 ${input.roundProgress.current} 轮 / 硬上限 ${input.roundProgress.total}`,
          }
        : undefined,
      navigationAction: action?.targetNodeId
        ? { targetNodeId: action.targetNodeId, label: action.navigationLabel }
        : null,
      commandAction: !dispatchStatus && action
        ? commandActionFor(
            action,
            action.command || action.recovery?.command,
            action.commandLabel || action.recovery?.label,
          )
        : null,
      retryAction: dispatchStatus
        ? { label: "重试启动", detail: presentation.detail }
        : undefined,
      blocker: dispatchStatus
        ? {
            code: dispatchStatus,
            message: presentation.detail,
            retryable: true,
          }
        : action?.disabledReason
          ? {
              code: action.stage === "blocked" ? "workflow_blocked" : "command_blocked",
              message: action.disabledReason,
              retryable: Boolean(action.recovery),
            }
          : undefined,
    };
  }

  return {
    scope,
    loadState,
    currentTask,
    stages: stageSummaries(currentTask),
    view: {
      panel: input.panel,
      selectedNodeId: input.selectedNodeId ?? null,
      selectedIsCurrentTask: Boolean(
        currentTask?.targetNodeId
        && input.panel === "node"
        && input.selectedNodeId === currentTask.targetNodeId,
      ),
      archiveMode: input.panel === "question",
    },
  };
}
