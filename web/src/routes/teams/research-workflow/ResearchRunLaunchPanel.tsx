import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateResearchWorkflowExperiment,
  fetchResearchWorkflowLaunchOptions,
  type CreateResearchWorkflowRunInput,
  type ResearchWorkflowExperimentOption,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VConfirmDialog,
  VFieldRow,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { buildResearchRunInput } from "./researchRunLaunchContract";
import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import styles from "./ResearchRunLaunchPanel.styles";

const EXPERIMENT_EMPTY_KEY = "__experiment_empty__";
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

export function ResearchRunLaunchPanel(props: {
  teamId: string;
  busy: boolean;
  onSubmit: (input: CreateResearchWorkflowRunInput) => Promise<void>;
  onCancel: () => void;
  onOpenProgress?: () => void;
}) {
  const { teamId, busy, onSubmit, onCancel, onOpenProgress } = props;
  const [questionId, setQuestionId] = useState("");
  const [experimentId, setExperimentId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [safetyBudget, setSafetyBudget] = useState(createResearchRunSafetyBudget);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
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
  const experiments = launchOptions.data?.experiments ?? [];
  const questions = launchOptions.data?.questions ?? [];
  const selectedExperiment = experiments.find(
    (experiment) => experiment.experimentId === experimentId,
  ) ?? null;
  const selectedQuestion = questions.find((question) => question.questionId === questionId) ?? null;
  const launchBlockedByExperiment = selectedQuestion
    ? isLaunchBlockedByExperiment(experiments, selectedQuestion.questionId, experimentId)
    : false;

  const activateMutation = useMutation({
    mutationFn: (input: { experimentId: string; teamId: string }) =>
      activateResearchWorkflowExperiment(CHALLENGE_CUP_WORKFLOW_ID, input.experimentId, {
        teamId: input.teamId,
        confirmed: true,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: launchOptionsKey });
      setConfirmOpen(false);
    },
    onError: (reason: unknown) => {
      setError(reason instanceof Error ? reason.message : String(reason));
      setConfirmOpen(false);
    },
  });

  if (launchOptions.isPending) {
    return <VStateSurface tone="loading" title="加载可启动题目" fill className={styles.state} />;
  }
  if (launchOptions.isError) {
    return (
      <VStateSurface tone="error" title="题目加载失败" fill className={styles.state}>
        {launchOptions.error instanceof Error ? launchOptions.error.message : "暂时无法读取题目审核结果"}
      </VStateSurface>
    );
  }
  if (!questions.length && !experiments.length) {
    return <VStateSurface tone="empty" title="暂无可启动题目" fill className={styles.state} />;
  }

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title="创建科研运行" headingLevel={3} />
      {experiments.length ? (
        <VFieldRow
          label="深度实验"
          description="两个必须的独立实验。选择后不会自动创建运行；正式 campaign 激活前不会启动 Qwen / 网络 / GPU 任务。"
        >
          <VSelect
            aria-label="选择深度实验"
            placeholder="选择深度实验"
            selectedKey={experimentId || EXPERIMENT_EMPTY_KEY}
            options={[
              { id: EXPERIMENT_EMPTY_KEY, label: "不选择深度实验" },
              ...experiments.map((experiment) => ({
                id: experiment.experimentId,
                label: `${experiment.experimentId} · ${experiment.name}`,
              })),
            ]}
            onSelectionChange={(key) => {
              const next = key == null ? "" : String(key);
              setExperimentId(next === EXPERIMENT_EMPTY_KEY ? "" : next);
              setError(null);
              if (next && next !== EXPERIMENT_EMPTY_KEY) {
                const matching = experiments.find((experiment) => experiment.experimentId === next);
                setQuestionId(
                  matching
                  && questions.some((question) => question.questionId === matching.questionId)
                    ? matching.questionId
                    : "",
                );
              }
            }}
            isDisabled={busy || activateMutation.isPending}
          />
        </VFieldRow>
      ) : null}
      {selectedExperiment ? (
        <ExperimentLaunchStatus
          experiment={selectedExperiment}
          busy={busy}
          activationPending={activateMutation.isPending}
          onActivate={() => {
            setError(null);
            setConfirmOpen(true);
          }}
          onOpenProgress={onOpenProgress}
        />
      ) : null}
      {questions.length ? (
        <>
          <VFieldRow label="研究命题">
            <VSelect
              aria-label="选择已审核题目"
              placeholder="选择已审核题目"
              selectedKey={questionId || QUESTION_EMPTY_KEY}
              options={[
                { id: QUESTION_EMPTY_KEY, label: "不选择已审核题目" },
                ...questions.map((question) => ({
                  id: question.questionId,
                  label: `${question.questionId} · ${question.title}`,
                })),
              ]}
              onSelectionChange={(key) => {
                setQuestionId(
                  key == null || key === QUESTION_EMPTY_KEY ? "" : String(key),
                );
                setError(null);
              }}
              isDisabled={busy}
            />
          </VFieldRow>
          {selectedQuestion ? (
            <VSurface tone="inset" padding="compact" className={styles.selectedQuestion}>
              <strong className={styles.questionTitle}>{selectedQuestion.title}</strong>
              {selectedQuestion.scope ? (
                <span className={styles.questionScope}>{selectedQuestion.scope}</span>
              ) : null}
            </VSurface>
          ) : null}
        </>
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
          isDisabled={!selectedQuestion || launchBlockedByExperiment}
          onClick={() => {
            setError(null);
            try {
              const input = buildResearchRunInput({ teamId, questionId, safetyBudget });
              void onSubmit(input).catch((reason: unknown) => {
                setError(reason instanceof Error ? reason.message : String(reason));
              });
            } catch (reason) {
              setError(reason instanceof Error ? reason.message : String(reason));
            }
          }}
        >
          创建运行
        </VButton>
      </div>
      <VConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="激活正式 Campaign"
        description="激活只会启用正式 Campaign 的受管运行；不会启动 Qwen / 网络采集 / GPU 任务。"
        confirmLabel="确认激活"
        cancelLabel="取消"
        confirmPending={activateMutation.isPending}
        onConfirm={() => {
          if (selectedExperiment) {
            activateMutation.mutate({
              experimentId: selectedExperiment.experimentId,
              teamId,
            });
          }
        }}
        onCancel={() => {
          setError(null);
        }}
      />
    </VSurface>
  );
}
