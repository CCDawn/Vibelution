import type {
  SupervisedJudgeRubricCriterion,
  SupervisedWorktreeRun,
} from "../api/types";

export type SupervisedApprovalAction =
  | "approve_review"
  | "run_agent_approval"
  | "reject_review"
  | "request_rerun"
  | "rollback";

export type SupervisedApprovalPhase =
  | "empty"
  | "running"
  | "pending_review"
  | "ready_merge"
  | "blocked"
  | "committed"
  | "activating"
  | "applied"
  | "activation_failed"
  | "rollback_activating"
  | "merged"
  | "rolled_back"
  | "closed";

export type SupervisedApprovalTone = "neutral" | "info" | "warning" | "success" | "danger";

export type SupervisedApprovalRuntimeEffect =
  | "not_applied"
  | "commit_created"
  | "activating"
  | "applied"
  | "activation_failed"
  | "rollback_activating"
  | "rolled_back";

export type SupervisedRuntimeActivationModel = {
  status: string;
  attempt: number | null;
  targetCommit: string;
  intentStatus: string;
  reason: string;
  verified: boolean;
  runtimeSourceCommit: string;
  frontendBuiltFromCommit: string;
  runtimeSourceTrackedClean: boolean;
  phase: string;
  backendHealthy: boolean;
  activeWorkCount: number | null;
};

export type SupervisedApprovalMetricModel = {
  baselineScore: number | null;
  candidateScore: number | null;
  scoreDelta: number | null;
  baselineTaskScore: number | null;
  baselineSystemScore: number | null;
  candidateTaskScore: number | null;
  candidateSystemScore: number | null;
  changedFileCount: number;
  highRiskFileCount: number;
  overlapFileCount: number;
  blockerCount: number;
};

export type SupervisedApprovalRubricCriterionModel = {
  id: string;
  label: string;
  description: string;
  weight: number;
  baselineScore: number | null;
  candidateScore: number | null;
};

export type SupervisedApprovalRubricModel = {
  hash: string;
  taskSummary: string;
  taskWeight: number | null;
  systemWeight: number | null;
  taskCriteria: SupervisedApprovalRubricCriterionModel[];
  systemCriteria: SupervisedApprovalRubricCriterionModel[];
};

export type SupervisedApprovalJudgeRecommendationModel = {
  code: string;
  label: string;
};

export type SupervisedEvaluationStateModel = {
  code: "VALID" | "INVALID" | "ERROR" | "INCONCLUSIVE";
  label: string;
  description: string;
  mergeEligible: boolean;
};

export type SupervisedApprovalModeModel = {
  code: "human" | "agent";
  label: string;
};

export type SupervisedApprovalEvidenceModel = {
  tone: "positive" | "warning" | "neutral";
  text: string;
};

export type SupervisedApprovalStepModel = {
  id: "review" | "merge" | "rollback";
  title: string;
  status: "active" | "done" | "pending" | "blocked" | "undone";
  statusLabel: string;
  description: string;
  consequence: string;
};

export type SupervisedApprovalDecisionModel = {
  phase: SupervisedApprovalPhase;
  tone: SupervisedApprovalTone;
  statusLabel: string;
  headline: string;
  reason: string;
  primaryAction: SupervisedApprovalAction | null;
  primaryActionLabel: string;
  primaryActionReason: string;
  secondaryActions: Array<{
    action: SupervisedApprovalAction;
    label: string;
    reason: string;
  }>;
  runtimeEffect: SupervisedApprovalRuntimeEffect;
  runtimeEffectLabel: string;
  runtimeActivation: SupervisedRuntimeActivationModel;
  judgeRecommendation: SupervisedApprovalJudgeRecommendationModel;
  evaluationState: SupervisedEvaluationStateModel;
  approvalMode: SupervisedApprovalModeModel;
  rubric: SupervisedApprovalRubricModel;
  metrics: SupervisedApprovalMetricModel;
  evidence: SupervisedApprovalEvidenceModel[];
  steps: SupervisedApprovalStepModel[];
  changedFiles: NonNullable<SupervisedWorktreeRun["mergeAnalysis"]["changedFiles"]>;
  blockers: string[];
};

type ApprovalLanguage = "zh" | "en";

type RawRubricCriterion = Omit<
  SupervisedJudgeRubricCriterion,
  "evidenceRequirements"
>;

const ACTIVE_RUN_STATUSES = new Set(["queued", "starting", "running", "stopping", "paused"]);

function normalized(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function enabled(run: SupervisedWorktreeRun, actionId: string) {
  return Boolean(run.actionStates?.[actionId]?.enabled);
}

function score(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(
  lang: ApprovalLanguage,
  zh: string,
  en: string,
) {
  return lang === "zh" ? zh : en;
}

function emptyMetrics(): SupervisedApprovalMetricModel {
  return {
    baselineScore: null,
    candidateScore: null,
    scoreDelta: null,
    baselineTaskScore: null,
    baselineSystemScore: null,
    candidateTaskScore: null,
    candidateSystemScore: null,
    changedFileCount: 0,
    highRiskFileCount: 0,
    overlapFileCount: 0,
    blockerCount: 0,
  };
}

function emptyRubric(): SupervisedApprovalRubricModel {
  return {
    hash: "",
    taskSummary: "",
    taskWeight: null,
    systemWeight: null,
    taskCriteria: [],
    systemCriteria: [],
  };
}

function runtimeActivationModel(
  run: SupervisedWorktreeRun | null | undefined,
): SupervisedRuntimeActivationModel {
  const activation = run?.runtimeActivation;
  const proof = activation?.proof;
  const activeWorkCount = score(proof?.activeWorkCount);
  return {
    status: normalized(activation?.status),
    attempt: score(activation?.attempt),
    targetCommit: String(
      activation?.targetCommit
      ?? run?.runtimeActivationTargetCommit
      ?? run?.merge?.commitSha
      ?? "",
    ).trim(),
    intentStatus: normalized(activation?.intentStatus),
    reason: String(activation?.reason ?? "").trim(),
    verified: Boolean(proof?.verified),
    runtimeSourceCommit: String(proof?.runtimeSourceCommit ?? "").trim(),
    frontendBuiltFromCommit: String(proof?.frontendBuiltFromCommit ?? "").trim(),
    runtimeSourceTrackedClean: Boolean(proof?.runtimeSourceTrackedClean),
    phase: String(proof?.phase ?? "").trim(),
    backendHealthy: Boolean(proof?.backendHealthy),
    activeWorkCount,
  };
}

function judgeRecommendation(
  run: SupervisedWorktreeRun | null | undefined,
  lang: ApprovalLanguage,
): SupervisedApprovalJudgeRecommendationModel {
  const raw = String(
    run?.decision?.judgeRecommendation
    ?? run?.candidateJudgment?.recommendation
    ?? run?.candidateJudgment?.decision
    ?? run?.decision?.judgeDecision
    ?? "",
  ).trim().toUpperCase();
  const code = raw === "PROMOTE" ? "APPROVE" : raw === "HOLD" ? "REVISE" : raw;
  const labels: Record<string, [string, string]> = {
    APPROVE: ["建议批准", "Recommend approval"],
    REVISE: ["建议继续改进", "Recommend revision"],
    REJECT: ["建议拒绝", "Recommend rejection"],
    INCONCLUSIVE: ["证据不足", "Insufficient evidence"],
  };
  const label = labels[code];
  return {
    code,
    label: label ? text(lang, label[0], label[1]) : text(lang, "尚无建议", "No recommendation"),
  };
}

function evaluationState(
  run: SupervisedWorktreeRun | null | undefined,
  lang: ApprovalLanguage,
): SupervisedEvaluationStateModel {
  const explicit = String(
    run?.approvalDecision?.evaluationState
    ?? run?.decision?.evaluationState
    ?? run?.candidateJudgment?.evaluationState
    ?? "",
  ).trim().toUpperCase();
  const recommendation = String(
    run?.candidateJudgment?.recommendation
    ?? run?.candidateJudgment?.decision
    ?? "",
  ).trim().toUpperCase();
  let code: SupervisedEvaluationStateModel["code"];
  if (["VALID", "INVALID", "ERROR", "INCONCLUSIVE"].includes(explicit)) {
    code = explicit as SupervisedEvaluationStateModel["code"];
  } else if (normalized(run?.candidateJudgment?.status) && normalized(run?.candidateJudgment?.status) !== "success") {
    code = "ERROR";
  } else if (recommendation === "INCONCLUSIVE") {
    code = "INCONCLUSIVE";
  } else if (
    normalized(run?.candidateJudgment?.status) === "success"
    && normalized(run?.candidateJudgment?.phase) === "rerun"
  ) {
    code = "VALID";
  } else {
    code = "INVALID";
  }
  const copy: Record<SupervisedEvaluationStateModel["code"], [string, string, string, string]> = {
    VALID: ["有效", "Valid", "证据协议完整，可进入最终审批；是否合入仍由审批决定。", "Evidence is structurally valid and may enter final approval."],
    INVALID: ["无效", "Invalid", "证据或协议不满足要求，禁止批准；请修复评估链路。", "Evidence or protocol is invalid; approval is blocked."],
    ERROR: ["错误", "Error", "评估执行发生错误，当前分数不能作为合入依据。", "Evaluation failed; scores cannot authorize merge."],
    INCONCLUSIVE: ["不可判定", "Inconclusive", "现有证据不足以支持批准，应补证据并复跑。", "Evidence is insufficient; collect evidence and rerun."],
  };
  return {
    code,
    label: text(lang, copy[code][0], copy[code][1]),
    description: text(lang, copy[code][2], copy[code][3]),
    mergeEligible: code === "VALID",
  };
}

function approvalMode(
  run: SupervisedWorktreeRun | null | undefined,
  lang: ApprovalLanguage,
): SupervisedApprovalModeModel {
  const code = String(run?.approvalMode ?? run?.approvalDecision?.mode ?? "human").toLowerCase() === "agent"
    ? "agent"
    : "human";
  return {
    code,
    label: code === "agent"
      ? text(lang, "Agent 审批", "Agent approval")
      : text(lang, "人工审批", "Human approval"),
  };
}

function rubricModel(run: SupervisedWorktreeRun): SupervisedApprovalRubricModel {
  const rubric = run.judgeRubric;
  const withScores = (
    criteria: RawRubricCriterion[] | undefined,
    baselineScores: Record<string, number> | undefined,
    candidateScores: Record<string, number> | undefined,
  ) => (Array.isArray(criteria) ? criteria : []).map((criterion) => ({
    ...criterion,
    baselineScore: score(baselineScores?.[criterion.id]),
    candidateScore: score(candidateScores?.[criterion.id]),
  }));
  return {
    hash: String(rubric?.rubricHash ?? ""),
    taskSummary: String(rubric?.taskSummary ?? ""),
    taskWeight: score(rubric?.compositionWeights?.taskSpecific),
    systemWeight: score(rubric?.compositionWeights?.systemFixed),
    taskCriteria: withScores(
      rubric?.taskCriteria,
      run.baselineJudgment?.taskScores,
      run.candidateJudgment?.taskScores,
    ),
    systemCriteria: withScores(
      rubric?.systemCriteria,
      run.baselineJudgment?.systemScores,
      run.candidateJudgment?.systemScores,
    ),
  };
}

function emptyDecision(lang: ApprovalLanguage): SupervisedApprovalDecisionModel {
  return {
    phase: "empty",
    tone: "neutral",
    statusLabel: text(lang, "等待证据", "Waiting for evidence"),
    headline: text(lang, "等待监督运行生成审批证据", "Waiting for supervised evidence"),
    reason: text(
      lang,
      "完成两次 Judge 评分后，这里会按本轮选择显示人工或 Agent 最终审批。",
      "After both Judge evaluations, this surface shows the selected human or Agent final approval.",
    ),
    primaryAction: null,
    primaryActionLabel: "",
    primaryActionReason: "",
    secondaryActions: [],
    runtimeEffect: "not_applied",
    runtimeEffectLabel: text(lang, "运行时尚未应用", "Runtime not applied"),
    runtimeActivation: runtimeActivationModel(null),
    judgeRecommendation: judgeRecommendation(null, lang),
    evaluationState: evaluationState(null, lang),
    approvalMode: approvalMode(null, lang),
    rubric: emptyRubric(),
    metrics: emptyMetrics(),
    evidence: [],
    steps: [],
    changedFiles: [],
    blockers: [],
  };
}

function approvalPhase(run: SupervisedWorktreeRun): SupervisedApprovalPhase {
  const rollbackStatus = normalized(run.rollback?.status);
  const mergeStatus = normalized(run.merge?.status);
  const activationStatus = normalized(run.runtimeActivation?.status);
  const gateStatus = normalized(run.reviewGate?.status ?? run.mergeAnalysis?.reviewGate?.status);
  const gateRequired = Boolean(run.reviewGate?.required ?? run.mergeAnalysis?.reviewGate?.required);
  const blockers = run.mergeAnalysis?.blockers ?? [];
  const approvalStatus = normalized(run.approvalDecision?.status);
  const approvalDecision = String(run.approvalDecision?.decision ?? "").toUpperCase();

  if (rollbackStatus === "rolled_back") {
    return "rolled_back";
  }
  if (["activation_failed", "activation_blocked"].includes(activationStatus)) {
    return "activation_failed";
  }
  if (rollbackStatus === "revert_committed") {
    return "rollback_activating";
  }
  if (activationStatus === "applied" || mergeStatus === "applied") {
    return "applied";
  }
  if (["restart_queued", "activating", "activation_verifying"].includes(activationStatus)) {
    return "activating";
  }
  if (mergeStatus === "committed") {
    return "committed";
  }
  if (mergeStatus === "merged") {
    return "merged";
  }
  if (ACTIVE_RUN_STATUSES.has(normalized(run.status))) {
    return "running";
  }
  if (approvalStatus === "decided" && approvalDecision !== "APPROVE") {
    return "closed";
  }
  if (!evaluationState(run, "zh").mergeEligible) {
    return "blocked";
  }
  if (
    enabled(run, "approveReview")
    || enabled(run, "runAgentApproval")
    || (gateRequired && gateStatus !== "approved")
  ) {
    return "pending_review";
  }
  if (blockers.length > 0 || run.mergeAnalysis?.mergeAllowed === false) {
    return "blocked";
  }
  if (enabled(run, "merge")) {
    return "ready_merge";
  }
  return "closed";
}

function phaseCopy(
  phase: SupervisedApprovalPhase,
  run: SupervisedWorktreeRun,
  lang: ApprovalLanguage,
) {
  const changedFileCount = run.mergeAnalysis?.changedFiles?.length ?? run.merge?.changedFiles?.length ?? 0;
  const blockers = run.mergeAnalysis?.blockers ?? [];
  const activation = runtimeActivationModel(run);
  const rollbackAvailable =
    normalized(run.rollback?.status) === "available" && enabled(run, "rollback");
  const gateReason = String(run.reviewGate?.reason ?? run.mergeAnalysis?.reviewGate?.reason ?? "").trim();
  const decisionReason = [
    run.approvalDecision?.reason,
    run.decision?.reason,
    run.mergeAnalysis?.reason,
    run.latestMessage,
  ].map((value) => String(value ?? "").trim()).find(Boolean) ?? "";

  if (phase === "running") {
    return {
      tone: "info" as const,
      statusLabel: text(lang, "仍在运行", "Still running"),
      headline: text(lang, "监督运行尚未到达审批阶段", "Supervised run has not reached approval"),
      reason: run.latestMessage || text(lang, "请等待评测与候选复跑完成。", "Wait for evaluation and rerun to finish."),
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "pending_review") {
    const mode = approvalMode(run, lang);
    return {
      tone: "warning" as const,
      statusLabel: mode.label,
      headline: mode.code === "agent"
        ? text(lang, "启动独立审批 Agent 作最终决定", "Run the independent Approval Agent")
        : text(lang, "人工决定是否执行受控合入", "Human decides whether to run controlled merge"),
      reason: gateReason || decisionReason,
      primaryAction: mode.code === "agent" ? "run_agent_approval" as const : "approve_review" as const,
      primaryActionLabel: mode.code === "agent"
        ? text(lang, "启动 Agent 审批", "Run Agent approval")
        : text(lang, "批准并受控合入", "Approve controlled merge"),
    };
  }
  if (phase === "ready_merge") {
    return {
      tone: "success" as const,
      statusLabel: text(lang, "审批已通过", "Approval recorded"),
      headline: text(lang, "审批记录已授权后端受控合入", "Approval record authorizes backend controlled merge"),
      reason: decisionReason || text(lang, "不再提供独立人工 merge 旁路。", "No separate manual merge bypass is exposed."),
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "blocked") {
    const state = evaluationState(run, lang);
    return {
      tone: "danger" as const,
      statusLabel: state.label,
      headline: text(lang, "当前评估状态禁止批准合入", "Current evaluation state blocks approval"),
      reason: state.description || blockers.join("；") || run.mergeAnalysis?.reason || decisionReason,
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "committed") {
    return {
      tone: "warning" as const,
      statusLabel: text(lang, "Git 提交已创建", "Git commit created"),
      headline: text(lang, "候选已提交，运行时尚未应用", "Candidate committed; runtime not applied"),
      reason: text(
        lang,
        `${changedFileCount} 个候选文件已形成可审计提交；只有 Launcher 版本证明通过后才算闭环完成。`,
        `${changedFileCount} candidate files are in an auditable commit; closure requires verified Launcher activation.`,
      ),
      primaryAction: rollbackAvailable ? "rollback" as const : null,
      primaryActionLabel: rollbackAvailable ? text(lang, "创建回退提交", "Create revert commit") : "",
    };
  }
  if (phase === "activating") {
    return {
      tone: "info" as const,
      statusLabel: text(lang, "Launcher 激活中", "Launcher activating"),
      headline: text(lang, "正在激活候选提交", "Activating candidate commit"),
      reason: text(
        lang,
        `当前为第 ${activation.attempt ?? 1} 次激活尝试；提交已保留，尚未获得运行版本证明。`,
        `Activation attempt ${activation.attempt ?? 1} is running; the commit is durable but runtime proof is pending.`,
      ),
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "applied") {
    return {
      tone: "success" as const,
      statusLabel: text(lang, "已提交并生效", "Committed and applied"),
      headline: text(lang, "候选提交与运行时已生效", "Candidate commit is active in runtime"),
      reason: activation.verified
        ? text(
          lang,
          "源码提交、前端构建、干净状态、后端健康与零活动任务证据均已匹配。",
          "Source commit, frontend build, clean state, backend health, and zero active work all match.",
        )
        : text(
          lang,
          "后端报告已应用，但当前快照缺少完整运行证明；请复核运行证据。",
          "The backend reports applied, but this snapshot lacks complete runtime proof.",
        ),
      primaryAction: rollbackAvailable ? "rollback" as const : null,
      primaryActionLabel: rollbackAvailable ? text(lang, "创建回退提交", "Create revert commit") : "",
    };
  }
  if (phase === "activation_failed") {
    const reverting = normalized(run.rollback?.status) === "revert_committed";
    return {
      tone: "danger" as const,
      statusLabel: text(lang, "运行时激活失败", "Runtime activation failed"),
      headline: reverting
        ? text(lang, "回退提交已保留，但运行时尚未恢复", "Revert commit preserved; runtime not restored")
        : text(lang, "候选提交已保留，但运行时未应用", "Candidate commit preserved; runtime not applied"),
      reason: activation.reason || text(
        lang,
        "自动激活已达到重试上限；不要把 Git 提交误判为运行成功，可检查状态后创建可审计回退。",
        "Automatic activation exhausted its retry; do not treat the Git commit as runtime success. Inspect evidence and create an auditable revert if needed.",
      ),
      primaryAction: rollbackAvailable && !reverting ? "rollback" as const : null,
      primaryActionLabel: rollbackAvailable && !reverting
        ? text(lang, "创建回退提交", "Create revert commit")
        : "",
    };
  }
  if (phase === "rollback_activating") {
    return {
      tone: "info" as const,
      statusLabel: text(lang, "回退激活中", "Revert activating"),
      headline: text(lang, "Git 回退提交已创建，等待运行时恢复", "Git revert created; runtime restoration pending"),
      reason: run.rollback?.reason || text(
        lang,
        "只有 Launcher 证明运行版本已切换到回退提交后，才能标记为已回滚。",
        "Rollback completes only after Launcher proves the runtime is on the revert commit.",
      ),
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "merged") {
    return {
      tone: rollbackAvailable ? "success" as const : "warning" as const,
      statusLabel: rollbackAvailable
        ? text(lang, "已合入 · 可回滚", "Merged · rollback available")
        : text(lang, "已合入 · 回滚待确认", "Merged · rollback unverified"),
      headline: rollbackAvailable
        ? text(lang, "候选已写入项目，回滚保护可用", "Candidate merged with rollback protection")
        : text(lang, "候选已写入项目，但回滚保护不可用", "Candidate merged without verified rollback protection"),
      reason: rollbackAvailable
        ? text(
          lang,
          `${changedFileCount} 个候选文件已写入项目；这不等于运行时已经刷新生效。`,
          `${changedFileCount} candidate files entered the project; this does not prove runtime activation.`,
        )
        : text(
          lang,
          "项目文件已经写入，但当前快照没有可执行的回滚清单；请先检查治理记录，不要把此状态视为完整成功。",
          "Project files were written, but the snapshot has no executable rollback manifest; inspect governance evidence before treating this as complete success.",
        ),
      primaryAction: rollbackAvailable ? "rollback" as const : null,
      primaryActionLabel: rollbackAvailable ? text(lang, "回滚合入", "Rollback merge") : "",
    };
  }
  if (phase === "rolled_back") {
    return {
      tone: "neutral" as const,
      statusLabel: text(lang, "已恢复", "Restored"),
      headline: text(lang, "已恢复合入前文件状态", "Pre-merge file state restored"),
      reason: run.rollback?.reason || text(
        lang,
        "候选记录与评测证据仍然保留，便于后续复核。",
        "Candidate records and evaluation evidence remain available for review.",
      ),
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  return {
    tone: "neutral" as const,
    statusLabel: text(lang, "本轮已结束", "Run closed"),
    headline: text(lang, "当前没有待执行的治理动作", "No governance action is pending"),
    reason: decisionReason || text(lang, "请查看本轮结论与候选证据。", "Review the run conclusion and candidate evidence."),
    primaryAction: null,
    primaryActionLabel: "",
  };
}

function buildSteps(
  phase: SupervisedApprovalPhase,
  run: SupervisedWorktreeRun,
  lang: ApprovalLanguage,
): SupervisedApprovalStepModel[] {
  const gateStatus = normalized(run.reviewGate?.status ?? run.mergeAnalysis?.reviewGate?.status);
  const approvalStatus = normalized(run.approvalDecision?.status);
  const approvalDecision = String(run.approvalDecision?.decision ?? "").trim().toUpperCase();
  const decisionRecorded = approvalStatus === "decided";
  const mergeUnauthorized = decisionRecorded && approvalDecision !== "APPROVE";
  const committedPhases = new Set<SupervisedApprovalPhase>([
    "committed",
    "activating",
    "applied",
    "activation_failed",
    "rollback_activating",
    "merged",
    "rolled_back",
  ]);
  const reviewDone = decisionRecorded
    || gateStatus === "approved"
    || committedPhases.has(phase);
  const mergeDone = committedPhases.has(phase)
    && phase !== "rollback_activating"
    && phase !== "rolled_back";
  const mergeUndone = phase === "rollback_activating" || phase === "rolled_back";
  const rollbackDone = phase === "rolled_back";
  const rollbackActivating = phase === "rollback_activating";
  const mode = approvalMode(run, lang);
  const reviewDoneLabel = approvalDecision === "RERUN_REQUIRED"
    ? text(lang, "已要求复跑", "Rerun required")
    : approvalDecision === "REJECT"
      ? text(lang, "已拒绝", "Rejected")
      : approvalDecision === "APPROVE"
        ? text(lang, "已批准", "Approved")
        : text(lang, "已完成", "Done");
  const mergeUnauthorizedLabel = approvalDecision === "RERUN_REQUIRED"
    ? text(lang, "未授权 · 待复跑", "Unauthorized · rerun required")
    : text(lang, "未授权", "Unauthorized");

  return [
    {
      id: "review",
      title: text(lang, `1. ${mode.label}`, `1. ${mode.label}`),
      status: reviewDone ? "done" : phase === "pending_review" ? "active" : "pending",
      statusLabel: reviewDone
        ? reviewDoneLabel
        : phase === "pending_review"
          ? text(lang, "当前可执行", "Available now")
          : text(lang, "等待评测", "Waiting"),
      description: text(lang, "同时审阅两次评分、评估状态、证据完整性、风险与候选差异。", "Review both scores, evaluation state, evidence integrity, risk, and candidate diff."),
      consequence: text(
        lang,
        "审批决定写入不可变记录；分数不是硬门，INVALID / ERROR / INCONCLUSIVE 均不能直接批准。",
        "The decision becomes immutable; scores are not a hard gate, and non-VALID states cannot be approved.",
      ),
    },
    {
      id: "merge",
      title: text(lang, "2. 提交并激活", "2. Commit and activate"),
      status: mergeUndone
        ? "undone"
        : mergeDone
          ? "done"
          : mergeUnauthorized
            ? "blocked"
          : phase === "ready_merge"
            ? "active"
            : phase === "blocked"
              ? "blocked"
              : "pending",
      statusLabel: mergeUndone
        ? text(lang, "已撤销", "Undone")
        : mergeDone
          ? phase === "applied"
            ? text(lang, "已生效", "Applied")
            : phase === "activation_failed"
              ? text(lang, "提交已保留", "Commit preserved")
              : text(lang, "提交已创建", "Commit created")
          : mergeUnauthorized
            ? mergeUnauthorizedLabel
          : phase === "ready_merge"
            ? text(lang, "当前可执行", "Available now")
            : phase === "blocked"
              ? text(lang, "被阻塞", "Blocked")
              : text(lang, "等待评审", "Waiting for review"),
      description: text(lang, "后端仅凭 APPROVE 审批记录创建精确 Git 提交，再由 Launcher 激活并核对源码与前端构建版本。", "The backend accepts only an APPROVE record, creates an exact Git commit, then asks Launcher to activate and verify source and frontend revisions."),
      consequence: text(lang, "提交成功不等于运行时生效；只有版本、健康、干净状态和活动任务证据全部匹配才完成。", "A successful commit is not runtime activation; revision, health, clean-state, and active-work proofs must all match."),
    },
    {
      id: "rollback",
      title: text(lang, "3. 回滚合入", "3. Rollback merge"),
      status: rollbackDone
        ? "done"
        : rollbackActivating
          ? "active"
          : committedPhases.has(phase) && enabled(run, "rollback")
            ? "active"
            : "pending",
      statusLabel: rollbackDone
        ? text(lang, "已回滚", "Rolled back")
        : rollbackActivating
          ? text(lang, "等待运行时恢复", "Waiting for runtime")
          : committedPhases.has(phase) && enabled(run, "rollback")
            ? text(lang, "当前可执行", "Available now")
            : text(lang, "提交后可用", "Available after commit"),
      description: text(lang, "创建可审计 Git revert，并由 Launcher 激活回退提交。", "Create an auditable Git revert and activate it through Launcher."),
      consequence: rollbackDone
        ? text(lang, "项目与运行时均已切换到回退提交；评测证据继续保留。", "Project and runtime now use the revert commit; evaluation evidence remains.")
        : text(lang, "不会删除评测证据；回退提交也必须通过运行时版本证明。", "Evaluation evidence remains, and the revert commit must pass runtime revision proof."),
    },
  ];
}

function buildEvidence(
  run: SupervisedWorktreeRun,
  metrics: SupervisedApprovalMetricModel,
  lang: ApprovalLanguage,
): SupervisedApprovalEvidenceModel[] {
  const evidence: SupervisedApprovalEvidenceModel[] = [];
  const recommendation = judgeRecommendation(run, lang);
  const state = evaluationState(run, lang);
  const activation = runtimeActivationModel(run);
  evidence.push({
    tone: state.mergeEligible ? "positive" : "warning",
    text: text(
      lang,
      `评估状态：${state.label}。${state.description}`,
      `Evaluation state: ${state.label}. ${state.description}`,
    ),
  });
  if (recommendation.code) {
    evidence.push({
      tone: "neutral",
      text: text(
        lang,
        `Judge ${recommendation.label}；建议与分数仅供审批主体参考，不能覆盖评估状态。`,
        `Judge: ${recommendation.label}. Scores are advisory and cannot override evaluation state.`,
      ),
    });
  }
  if (metrics.scoreDelta !== null) {
    evidence.push({
      tone: metrics.scoreDelta > 0 ? "positive" : metrics.scoreDelta < 0 ? "warning" : "neutral",
      text: text(
        lang,
        `候选相对基线变化 ${metrics.scoreDelta >= 0 ? "+" : ""}${metrics.scoreDelta}。`,
        `Candidate delta vs baseline: ${metrics.scoreDelta >= 0 ? "+" : ""}${metrics.scoreDelta}.`,
      ),
    });
  }
  if (run.mergeAnalysis?.reason) {
    evidence.push({
      tone: run.mergeAnalysis.mergeAllowed === false ? "warning" : "positive",
      text: run.mergeAnalysis.reason,
    });
  }
  if (metrics.highRiskFileCount > 0) {
    evidence.push({
      tone: "warning",
      text: text(
        lang,
        `${metrics.highRiskFileCount} 个高风险文件需要人工确认。`,
        `${metrics.highRiskFileCount} high-risk file(s) require human confirmation.`,
      ),
    });
  }
  if (metrics.blockerCount > 0) {
    evidence.push({
      tone: "warning",
      text: text(
        lang,
        `${metrics.blockerCount} 个阻塞项必须在合入前解决。`,
        `${metrics.blockerCount} blocker(s) must be resolved before merge.`,
      ),
    });
  }
  if (
    normalized(run.merge?.status) === "merged"
    && normalized(run.rollback?.status) !== "available"
    && normalized(run.rollback?.status) !== "rolled_back"
  ) {
    evidence.push({
      tone: "warning",
      text: text(
        lang,
        "合入记录缺少可用回滚保护，当前治理结果不完整。",
        "The merge record has no available rollback protection, so governance is incomplete.",
      ),
    });
  }
  if (run.merge?.commitSha) {
    evidence.push({
      tone: activation.verified ? "positive" : "neutral",
      text: text(
        lang,
        `候选 Git 提交：${run.merge.commitSha.slice(0, 12)}。`,
        `Candidate Git commit: ${run.merge.commitSha.slice(0, 12)}.`,
      ),
    });
  }
  if (["activation_failed", "activation_blocked"].includes(activation.status)) {
    evidence.push({
      tone: "warning",
      text: text(
        lang,
        `Launcher 激活未完成：${activation.reason || "未提供失败原因"}。Git 提交仍保留。`,
        `Launcher activation did not complete: ${activation.reason || "no failure reason provided"}. The Git commit is preserved.`,
      ),
    });
  } else if (activation.verified) {
    evidence.push({
      tone: "positive",
      text: text(
        lang,
        "运行时源码提交、前端构建提交、后端健康与活动任务证明均已核验。",
        "Runtime source, frontend build, backend health, and active-work proofs are verified.",
      ),
    });
  }
  return evidence;
}

function runtimeEffectForPhase(
  phase: SupervisedApprovalPhase,
): SupervisedApprovalRuntimeEffect {
  if (phase === "committed" || phase === "merged") return "commit_created";
  if (phase === "activating") return "activating";
  if (phase === "applied") return "applied";
  if (phase === "activation_failed") return "activation_failed";
  if (phase === "rollback_activating") return "rollback_activating";
  if (phase === "rolled_back") return "rolled_back";
  return "not_applied";
}

function runtimeEffectLabel(
  effect: SupervisedApprovalRuntimeEffect,
  lang: ApprovalLanguage,
) {
  const copy: Record<SupervisedApprovalRuntimeEffect, [string, string]> = {
    not_applied: ["运行时尚未应用", "Runtime not applied"],
    commit_created: ["Git 提交已创建，运行时尚未应用", "Git commit created; runtime not applied"],
    activating: ["Launcher 正在激活并核验版本", "Launcher is activating and verifying revisions"],
    applied: ["源码与前端构建已在运行时生效", "Source and frontend build are active in runtime"],
    activation_failed: ["提交已保留，运行时激活失败", "Commit preserved; runtime activation failed"],
    rollback_activating: ["回退提交已创建，等待运行时恢复", "Revert commit created; runtime restoration pending"],
    rolled_back: ["项目与运行时均已回退", "Project and runtime rolled back"],
  };
  return text(lang, copy[effect][0], copy[effect][1]);
}

export function buildSupervisedApprovalDecision(
  run: SupervisedWorktreeRun | null | undefined,
  lang: ApprovalLanguage,
): SupervisedApprovalDecisionModel {
  if (!run) {
    return emptyDecision(lang);
  }

  const changedFiles = run.mergeAnalysis?.changedFiles ?? [];
  const blockers = run.mergeAnalysis?.blockers ?? [];
  const highRiskFiles = run.mergeAnalysis?.highRiskFiles ?? [];
  const metrics: SupervisedApprovalMetricModel = {
    baselineScore: score(run.decision?.baselineScore),
    candidateScore: score(run.decision?.candidateScore),
    scoreDelta: score(run.decision?.scoreDelta),
    baselineTaskScore: score(run.baselineJudgment?.taskScore),
    baselineSystemScore: score(run.baselineJudgment?.systemScore),
    candidateTaskScore: score(run.candidateJudgment?.taskScore),
    candidateSystemScore: score(run.candidateJudgment?.systemScore),
    changedFileCount: changedFiles.length || run.merge?.changedFiles?.length || 0,
    highRiskFileCount: Math.max(
      highRiskFiles.length,
      changedFiles.filter((item) => item.highRisk).length,
    ),
    overlapFileCount: run.mergeAnalysis?.overlapFiles?.length ?? 0,
    blockerCount: blockers.length,
  };
  const phase = approvalPhase(run);
  const copy = phaseCopy(phase, run, lang);
  const state = evaluationState(run, lang);
  const mode = approvalMode(run, lang);
  const runtimeEffect = runtimeEffectForPhase(phase);

  return {
    phase,
    tone: copy.tone,
    statusLabel: copy.statusLabel,
    headline: copy.headline,
    reason: copy.reason,
    primaryAction: copy.primaryAction,
    primaryActionLabel: copy.primaryActionLabel,
    primaryActionReason: copy.primaryAction
      ? run.actionStates?.[
        copy.primaryAction === "approve_review"
          ? "approveReview"
          : copy.primaryAction === "run_agent_approval"
            ? "runAgentApproval"
            : copy.primaryAction
      ]?.reason ?? ""
      : "",
    secondaryActions: mode.code === "human"
      && normalized(run.approvalDecision?.status) !== "decided"
      && !ACTIVE_RUN_STATUSES.has(normalized(run.status))
      ? [
          {
            action: "request_rerun",
            label: text(lang, "要求补证据并复跑", "Request evidence and rerun"),
            reason: run.actionStates?.requestRerun?.reason ?? "",
          },
          {
            action: "reject_review",
            label: text(lang, "拒绝合入", "Reject merge"),
            reason: run.actionStates?.rejectReview?.reason ?? "",
          },
        ]
      : [],
    runtimeEffect,
    runtimeEffectLabel: runtimeEffectLabel(runtimeEffect, lang),
    runtimeActivation: runtimeActivationModel(run),
    judgeRecommendation: judgeRecommendation(run, lang),
    evaluationState: state,
    approvalMode: mode,
    rubric: rubricModel(run),
    metrics,
    evidence: buildEvidence(run, metrics, lang),
    steps: buildSteps(phase, run, lang),
    changedFiles,
    blockers,
  };
}
