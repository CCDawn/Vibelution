import { useEffect, useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import {
  fetchResearchWorkflowLaunchOptions,
  type CreateResearchWorkflowRunInput,
  type ResearchWorkflowExperimentOption,
  type ResearchWorkflowLaunchOption,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VFieldRow,
  VInput,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { researchWorkflowErrorInlineText } from "../researchWorkflowErrorModel";
import {
  clearResearchRunLaunchDraft,
  readResearchRunLaunchDraft,
  writeResearchRunLaunchDraft,
} from "./researchRunLaunchDraft";
import { buildResearchRunInput } from "./researchRunLaunchContract";
import { researchRunStatusLabel } from "./researchRunPresentation";
import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import styles from "./ResearchRunLaunchPanel.styles";

const QUESTION_EMPTY_KEY = "__question_empty__";

function nextActionLabel(experiment: ResearchWorkflowExperimentOption): string {
  switch (experiment.nextAction) {
    case "create_run":
      return "可创建运行";
    case "activate_campaign":
      return "激活正式 Campaign";
    case "await_formal_question_approval":
      return "等待正式题目审核通过";
    case "await_dev_readiness":
      return "等待 DEV 流程完成";
    default:
      return experiment.nextAction;
  }
}

/**
 * Blocked states get exactly one CTA that navigates to where the task is done
 * (Shopify setup-guide pattern); actionable states keep their local buttons.
 */
function nextActionCtaLabel(experiment: ResearchWorkflowExperimentOption): string | null {
  switch (experiment.nextAction) {
    case "await_dev_readiness":
      return "去完成平台准备检查";
    case "await_formal_question_approval":
      return "去审核题目结果";
    default:
      return null;
  }
}

export function isLaunchBlockedByExperiment(
  experiments: ResearchWorkflowExperimentOption[],
  questionId: string,
  selectedExperimentId = "",
): boolean {
  if (selectedExperimentId) {
    const selectedExperiment = experiments.find(
      (item) => item.experimentId === selectedExperimentId,
    );
    return Boolean(
      !selectedExperiment
      || !selectedExperiment.launchable
      || selectedExperiment.questionId !== questionId,
    );
  }
  const experiment = experiments.find((item) => item.questionId === questionId);
  return Boolean(experiment && !experiment.launchable);
}

export function ExperimentLaunchStatus(props: {
  experiment: ResearchWorkflowExperimentOption;
  busy: boolean;
  activationPending: boolean;
  onActivate: () => void;
  onOpenProgress?: () => void;
}) {
  const { experiment, busy, activationPending, onActivate, onOpenProgress } = props;
  const navigationCtaLabel = experiment.activationAllowed ? null : nextActionCtaLabel(experiment);
  return (
    <VSurface tone="inset" padding="compact" className={styles.selectedExperiment}>
      <div className={styles.experimentHeader}>
        <strong className={styles.experimentTitle}>{experiment.name}</strong>
        <VStatusChip tone={experiment.activated ? "success" : "warning"}>
          {experiment.activated ? "已激活" : "未激活"}
        </VStatusChip>
      </div>
      <div className={styles.experimentMeta}>
        <span>{experiment.experimentId}</span>
        <span>主题 {experiment.themeId}</span>
        <span>Campaign {experiment.campaignId}</span>
      </div>
      <div className={styles.experimentStatus}>
        下一动作：{nextActionLabel(experiment)}
      </div>
      {!experiment.activated && !experiment.activationAllowed ? (
        <div className={styles.experimentBlockerText}>
          完成 DEV readiness / dev-1 / dev-5 fixture 后才能激活正式 campaign。
          激活不会启动 Qwen / 网络采集 / GPU 任务。
        </div>
      ) : null}
      {experiment.blockers.length ? (
        <ul className={styles.blockers}>
          {experiment.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      {navigationCtaLabel && onOpenProgress ? (
        <VButton
          type="button"
          variant="primary"
          data-vui="experiment-next-action"
          onClick={onOpenProgress}
        >
          {navigationCtaLabel}
        </VButton>
      ) : null}
      {experiment.activationAllowed ? (
        <VButton
          type="button"
          variant="primary"
          isDisabled={busy || activationPending}
          onClick={() => {
            onActivate();
          }}
        >
          激活正式 Campaign
        </VButton>
      ) : null}
    </VSurface>
  );
}

const DOMAIN_LABELS: Record<string, string> = {
  mathematical_sciences: "数学",
  chemistry: "化学",
  medicine_and_health: "医学与健康",
  biology: "生物学",
  astronomy: "天文学",
  physics: "物理学",
  engineering_and_materials_science: "工程与材料",
  information_science: "信息科学",
  neuroscience: "神经科学",
  ecology: "生态学",
  energy_science: "能源",
  artificial_intelligence: "人工智能",
};

function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] || domain;
}

function questionMatchesQuery(question: ResearchWorkflowLaunchOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [
    question.questionId,
    question.title,
    question.domain || "",
    domainLabel(question.domain || ""),
  ].some((value) => value.toLowerCase().includes(needle));
}

export function ResearchRunLaunchPanel(props: {
  teamId: string;
  busy: boolean;
  initialQuestionId?: string;
  onSubmit: (input: CreateResearchWorkflowRunInput) => Promise<void>;
  onCancel: () => void;
  onContinueRun?: (input: { runId: string; nodeId: string }) => void;
}) {
  const { teamId, busy, initialQuestionId, onSubmit, onCancel, onContinueRun } = props;
  // Per-team session draft restores the form after panel switches; an explicit
  // deep-link questionId always wins over the remembered draft.
  const [draft] = useState(() => readResearchRunLaunchDraft(teamId));
  const [questionId, setQuestionId] = useState(initialQuestionId || draft?.questionId || "");
  const [query, setQuery] = useState(draft?.query ?? "");
  const [safetyBudget, setSafetyBudget] = useState(() => draft?.safetyBudget ?? createResearchRunSafetyBudget());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    writeResearchRunLaunchDraft(teamId, { questionId, query, safetyBudget });
  }, [teamId, questionId, query, safetyBudget]);
  const launchOptionsKey = queryKeys.researchWorkflowLaunchOptions(
    CHALLENGE_CUP_WORKFLOW_ID,
    teamId,
  );
  const launchOptions = useQuery({
    queryKey: launchOptionsKey,
    queryFn: () => fetchResearchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled: Boolean(teamId),
    staleTime: 60_000,
  });
  const questions = launchOptions.data?.questions ?? [];
  const selectedQuestion = questions.find((question) => question.questionId === questionId) ?? null;
  const checkpoint = selectedQuestion?.checkpoint ?? null;
  const filteredQuestions = useMemo(
    () => questions.filter((question) => questionMatchesQuery(question, query)),
    [questions, query],
  );
  const visibleQuestions = selectedQuestion && !filteredQuestions.some((item) => item.questionId === questionId)
    ? [selectedQuestion, ...filteredQuestions]
    : filteredQuestions;

  if (launchOptions.isPending) {
    return <VStateSurface tone="loading" title="加载 125 题目录" fill className={styles.state} />;
  }
  if (launchOptions.isError) {
    const rawMessage = launchOptions.error instanceof Error
      ? launchOptions.error.message
      : String(launchOptions.error ?? "");
    return (
      <VStateSurface
        tone="error"
        title="题目目录加载失败"
        fill
        className={styles.state}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void launchOptions.refetch()}>
            重试
          </VButton>
        )}
      >
        <p className={styles.error}>
          {researchWorkflowErrorInlineText(rawMessage, "暂时无法读取 125 题目录，请稍后重试。")}
        </p>
        {rawMessage ? (
          <details className={styles.techDetails}>
            <summary>技术细节</summary>
            <code>{rawMessage}</code>
          </details>
        ) : null}
      </VStateSurface>
    );
  }
  if (!questions.length) {
    return <VStateSurface tone="empty" title="暂无题目目录" fill className={styles.state} />;
  }

  const primaryLabel = checkpoint
    ? (checkpoint.resumable ? "继续运行" : "查看进展")
    : "开始实验";

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title="选择题目并开始实验" headingLevel={3} />
      <VFieldRow label="搜索题目" description="题号、英文问题或学科">
        <VInput
          aria-label="搜索 125 题"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="SCI-003 或 Riemann"
          isDisabled={busy}
        />
      </VFieldRow>
      <VFieldRow label="研究问题">
        <VSelect
          aria-label="选择 125 题"
          placeholder="选择一道题目"
          selectedKey={questionId || QUESTION_EMPTY_KEY}
          options={[
            { id: QUESTION_EMPTY_KEY, label: "请选择题目" },
            ...visibleQuestions.map((question) => ({
              id: question.questionId,
              label: `${question.questionId} · ${question.title}`,
              description: [
                domainLabel(question.domain || question.scope),
                question.checkpoint
                  ? `${question.checkpoint.currentNodeLabel || "未开始"} · ${question.checkpoint.completedCount}/${question.checkpoint.totalSteps}`
                  : "尚未开始",
              ].filter(Boolean).join(" · "),
            })),
          ]}
          onSelectionChange={(key) => {
            setQuestionId(key == null || key === QUESTION_EMPTY_KEY ? "" : String(key));
            setError(null);
          }}
          isDisabled={busy}
        />
      </VFieldRow>
      {selectedQuestion ? (
        <VSurface tone="inset" padding="compact" className={styles.selectedQuestion}>
          <strong className={styles.questionTitle}>{selectedQuestion.questionId} · {selectedQuestion.title}</strong>
          <span className={styles.questionScope}>{domainLabel(selectedQuestion.domain || selectedQuestion.scope)}</span>
          {checkpoint ? (
            <div className={styles.checkpoint} data-testid="question-checkpoint">
              <VStatusChip tone={checkpoint.resumable ? "warning" : checkpoint.status === "succeeded" ? "success" : "neutral"}>
                {researchRunStatusLabel(checkpoint.status)}
              </VStatusChip>
              <p>
                当前 checkpoint：{checkpoint.currentNodeLabel || checkpoint.currentNodeId || "起点"} · {checkpoint.completedCount}/{checkpoint.totalSteps}
              </p>
            </div>
          ) : (
            <p className={styles.questionScope}>尚无运行记录，开始后会从资料寻找进入流程并保存 checkpoint。</p>
          )}
        </VSurface>
      ) : null}
      <ResearchRunSafetyLimitPanel
        budget={safetyBudget}
        isDisabled={busy}
        onChange={setSafetyBudget}
      />
      {error ? <div role="alert" className={styles.error}>{error}</div> : null}
      <div className={styles.actions}>
        <VButton variant="ghost" onClick={onCancel} isDisabled={busy}>取消</VButton>
        <VButton
          isPending={busy}
          isDisabled={!selectedQuestion}
          onClick={() => {
            setError(null);
            if (checkpoint && onContinueRun) {
              onContinueRun({
                runId: checkpoint.runId,
                nodeId: checkpoint.currentNodeId || "source_finding",
              });
              return;
            }
            if (checkpoint && !onContinueRun) {
              setError("当前运行无法在此面板继续，请从运行列表打开。");
              return;
            }
            try {
              const input = buildResearchRunInput({ teamId, questionId, safetyBudget });
              void onSubmit(input)
                .then(() => clearResearchRunLaunchDraft(teamId))
                .catch((reason: unknown) => {
                  setError(reason instanceof Error ? reason.message : String(reason));
                });
            } catch (reason) {
              setError(reason instanceof Error ? reason.message : String(reason));
            }
          }}
        >
          {primaryLabel}
        </VButton>
      </div>
    </VSurface>
  );
}
