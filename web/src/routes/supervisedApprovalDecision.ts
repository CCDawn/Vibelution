import type { SupervisedWorktreeRun } from "../api/types";

export type SupervisedApprovalAction = "approve_review" | "merge" | "rollback";

export type SupervisedApprovalPhase =
  | "empty"
  | "running"
  | "pending_review"
  | "ready_merge"
  | "blocked"
  | "merged"
  | "rolled_back"
  | "closed";

export type SupervisedApprovalTone = "neutral" | "info" | "warning" | "success" | "danger";

export type SupervisedApprovalRuntimeEffect = "not_applied" | "refresh_required";

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
  runtimeEffect: SupervisedApprovalRuntimeEffect;
  runtimeEffectLabel: string;
  judgeRecommendation: SupervisedApprovalJudgeRecommendationModel;
  rubric: SupervisedApprovalRubricModel;
  metrics: SupervisedApprovalMetricModel;
  evidence: SupervisedApprovalEvidenceModel[];
  steps: SupervisedApprovalStepModel[];
  changedFiles: NonNullable<SupervisedWorktreeRun["mergeAnalysis"]["changedFiles"]>;
  blockers: string[];
};

type ApprovalLanguage = "zh" | "en";

type ExtendedJudgment = {
  recommendation?: string;
  decision?: string;
  taskScore?: number;
  systemScore?: number;
  rubricHash?: string;
};

type ExtendedSupervisedWorktreeRun = SupervisedWorktreeRun & {
  judgeRubric?: {
    rubricHash?: string;
    taskSummary?: string;
    compositionWeights?: {
      taskSpecific?: number;
      systemFixed?: number;
    };
    taskCriteria?: SupervisedApprovalRubricCriterionModel[];
    systemCriteria?: SupervisedApprovalRubricCriterionModel[];
  };
  baselineJudgment?: SupervisedWorktreeRun["baselineJudgment"] & ExtendedJudgment;
  candidateJudgment?: SupervisedWorktreeRun["candidateJudgment"] & ExtendedJudgment;
  decision: SupervisedWorktreeRun["decision"] & {
    judgeRecommendation?: string;
  };
};

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

function judgeRecommendation(
  run: ExtendedSupervisedWorktreeRun | null | undefined,
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

function rubricModel(run: ExtendedSupervisedWorktreeRun): SupervisedApprovalRubricModel {
  const rubric = run.judgeRubric;
  return {
    hash: String(rubric?.rubricHash ?? ""),
    taskSummary: String(rubric?.taskSummary ?? ""),
    taskWeight: score(rubric?.compositionWeights?.taskSpecific),
    systemWeight: score(rubric?.compositionWeights?.systemFixed),
    taskCriteria: Array.isArray(rubric?.taskCriteria) ? rubric.taskCriteria : [],
    systemCriteria: Array.isArray(rubric?.systemCriteria) ? rubric.systemCriteria : [],
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
      "完成两次 Judge 评分后，这里会给出用户审批与受控合入动作。",
      "The user approval and controlled merge action appears after both Judge evaluations finish.",
    ),
    primaryAction: null,
    primaryActionLabel: "",
    primaryActionReason: "",
    runtimeEffect: "not_applied",
    runtimeEffectLabel: text(lang, "运行时尚未应用", "Runtime not applied"),
    judgeRecommendation: judgeRecommendation(null, lang),
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
  const gateStatus = normalized(run.reviewGate?.status ?? run.mergeAnalysis?.reviewGate?.status);
  const gateRequired = Boolean(run.reviewGate?.required ?? run.mergeAnalysis?.reviewGate?.required);
  const blockers = run.mergeAnalysis?.blockers ?? [];

  if (rollbackStatus === "rolled_back") {
    return "rolled_back";
  }
  if (mergeStatus === "merged") {
    return "merged";
  }
  if (ACTIVE_RUN_STATUSES.has(normalized(run.status))) {
    return "running";
  }
  if (enabled(run, "approveReview") || (gateRequired && gateStatus !== "approved")) {
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
  const gateReason = String(run.reviewGate?.reason ?? run.mergeAnalysis?.reviewGate?.reason ?? "").trim();
  const decisionReason = String(run.decision?.reason ?? run.mergeAnalysis?.reason ?? run.latestMessage ?? "").trim();

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
    return {
      tone: "warning" as const,
      statusLabel: text(lang, "需用户决策", "User decision required"),
      headline: text(lang, "审批后由 Judge 触发受控合入", "Approval lets the Judge trigger controlled merge"),
      reason: gateReason || decisionReason,
      primaryAction: "approve_review" as const,
      primaryActionLabel: text(lang, "审批并受控合入", "Approve controlled merge"),
    };
  }
  if (phase === "ready_merge") {
    return {
      tone: "success" as const,
      statusLabel: text(lang, "可人工合入", "Ready for manual merge"),
      headline: text(lang, "评审已通过，可将候选写入项目", "Review approved; candidate can enter the project"),
      reason: decisionReason || text(lang, "当前合并分析允许人工合入。", "Merge analysis currently permits a manual merge."),
      primaryAction: "merge" as const,
      primaryActionLabel: text(lang, "合入项目", "Merge into project"),
    };
  }
  if (phase === "blocked") {
    return {
      tone: "danger" as const,
      statusLabel: text(lang, "存在阻塞", "Blocked"),
      headline: text(lang, "当前候选不能安全合入", "Candidate cannot be merged safely"),
      reason: blockers.join("；") || run.mergeAnalysis?.reason || decisionReason,
      primaryAction: null,
      primaryActionLabel: "",
    };
  }
  if (phase === "merged") {
    const rollbackAvailable =
      normalized(run.rollback?.status) === "available" && enabled(run, "rollback");
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
  const reviewDone = gateStatus === "approved" || phase === "merged" || phase === "rolled_back";
  const mergeDone = phase === "merged";
  const mergeUndone = phase === "rolled_back";
  const rollbackDone = phase === "rolled_back";

  return [
    {
      id: "review",
      title: text(lang, "1. 用户审批", "1. User approval"),
      status: reviewDone ? "done" : phase === "pending_review" ? "active" : "pending",
      statusLabel: reviewDone
        ? text(lang, "已完成", "Done")
        : phase === "pending_review"
          ? text(lang, "当前可执行", "Available now")
          : text(lang, "等待评测", "Waiting"),
      description: text(lang, "确认已审阅两次 Judge 评分、改动风险和候选差异。", "Confirm both Judge scores, candidate risk, and diff were reviewed."),
      consequence: text(
        lang,
        "用户决定批准后，Judge 在原会话中确认结构化请求并触发受控合入；评分不构成硬门。",
        "After user approval, the Judge confirms the structured request in the original session; scores are not a hard gate.",
      ),
    },
    {
      id: "merge",
      title: text(lang, "2. Judge 受控合入", "2. Judge-controlled merge"),
      status: mergeUndone
        ? "undone"
        : mergeDone
          ? "done"
          : phase === "ready_merge"
            ? "active"
            : phase === "blocked"
              ? "blocked"
              : "pending",
      statusLabel: mergeUndone
        ? text(lang, "已撤销", "Undone")
        : mergeDone
          ? text(lang, "已合入", "Merged")
          : phase === "ready_merge"
            ? text(lang, "当前可执行", "Available now")
            : phase === "blocked"
              ? text(lang, "被阻塞", "Blocked")
              : text(lang, "等待评审", "Waiting for review"),
      description: text(lang, "Judge 通过受约束的候选应用器写入文件并生成回滚清单，不执行原始 git merge。", "The Judge triggers the constrained candidate applier and rollback manifest, not raw git merge."),
      consequence: text(lang, "需要 Launcher/runtime 刷新与复验后才能确认生效。", "Requires Launcher/runtime refresh and validation before activation is confirmed."),
    },
    {
      id: "rollback",
      title: text(lang, "3. 回滚合入", "3. Rollback merge"),
      status: rollbackDone ? "done" : phase === "merged" && enabled(run, "rollback") ? "active" : "pending",
      statusLabel: rollbackDone
        ? text(lang, "已回滚", "Rolled back")
        : phase === "merged" && enabled(run, "rollback")
          ? text(lang, "当前可执行", "Available now")
          : text(lang, "合入后可用", "Available after merge"),
      description: text(lang, "按回滚清单恢复合入前文件状态。", "Restore the pre-merge file state from the rollback manifest."),
      consequence: rollbackDone
        ? text(lang, "项目文件已恢复；运行时仍需按实际刷新状态复验。", "Project files restored; runtime still needs validation based on refresh state.")
        : text(lang, "只恢复项目文件，不会删除评测证据。", "Restores project files without deleting evaluation evidence."),
    },
  ];
}

function buildEvidence(
  run: ExtendedSupervisedWorktreeRun,
  metrics: SupervisedApprovalMetricModel,
  lang: ApprovalLanguage,
): SupervisedApprovalEvidenceModel[] {
  const evidence: SupervisedApprovalEvidenceModel[] = [];
  const recommendation = judgeRecommendation(run, lang);
  if (recommendation.code) {
    evidence.push({
      tone: "neutral",
      text: text(
        lang,
        `Judge ${recommendation.label}，该建议和评分仅供参考，最终由用户决定。`,
        `Judge: ${recommendation.label}. The scores are advisory; the user makes the final decision.`,
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
  return evidence;
}

export function buildSupervisedApprovalDecision(
  run: SupervisedWorktreeRun | null | undefined,
  lang: ApprovalLanguage,
): SupervisedApprovalDecisionModel {
  if (!run) {
    return emptyDecision(lang);
  }

  const extendedRun = run as ExtendedSupervisedWorktreeRun;
  const changedFiles = extendedRun.mergeAnalysis?.changedFiles ?? [];
  const blockers = extendedRun.mergeAnalysis?.blockers ?? [];
  const highRiskFiles = extendedRun.mergeAnalysis?.highRiskFiles ?? [];
  const metrics: SupervisedApprovalMetricModel = {
    baselineScore: score(extendedRun.decision?.baselineScore),
    candidateScore: score(extendedRun.decision?.candidateScore),
    scoreDelta: score(extendedRun.decision?.scoreDelta),
    baselineTaskScore: score(extendedRun.baselineJudgment?.taskScore),
    baselineSystemScore: score(extendedRun.baselineJudgment?.systemScore),
    candidateTaskScore: score(extendedRun.candidateJudgment?.taskScore),
    candidateSystemScore: score(extendedRun.candidateJudgment?.systemScore),
    changedFileCount: changedFiles.length || extendedRun.merge?.changedFiles?.length || 0,
    highRiskFileCount: Math.max(
      highRiskFiles.length,
      changedFiles.filter((item) => item.highRisk).length,
    ),
    overlapFileCount: extendedRun.mergeAnalysis?.overlapFiles?.length ?? 0,
    blockerCount: blockers.length,
  };
  const phase = approvalPhase(extendedRun);
  const copy = phaseCopy(phase, extendedRun, lang);
  const runtimeEffect: SupervisedApprovalRuntimeEffect =
    phase === "merged" || phase === "rolled_back" ? "refresh_required" : "not_applied";

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
        copy.primaryAction === "approve_review" ? "approveReview" : copy.primaryAction
      ]?.reason ?? ""
      : "",
    runtimeEffect,
    runtimeEffectLabel: runtimeEffect === "refresh_required"
      ? text(lang, "项目状态已变更，运行时需刷新复验", "Project state changed; refresh and validate runtime")
      : text(lang, "运行时尚未应用", "Runtime not applied"),
    judgeRecommendation: judgeRecommendation(extendedRun, lang),
    rubric: rubricModel(extendedRun),
    metrics,
    evidence: buildEvidence(extendedRun, metrics, lang),
    steps: buildSteps(phase, extendedRun, lang),
    changedFiles,
    blockers,
  };
}
