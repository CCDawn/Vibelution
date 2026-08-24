import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  activateResearchWorkflowExperiment,
  fetchResearchWorkflowLaunchOptions,
  type CreateResearchWorkflowRunInput,
  type ResearchWorkflowExperimentOption,
  type ResearchWorkflowLaunchOption,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VConfirmDialog,
  VFieldRow,
  VInput,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import {
  presentResearchWorkflowError,
  researchWorkflowErrorBody,
  researchWorkflowErrorInlineText,
  researchWorkflowErrorTitle,
} from "../researchWorkflowErrorModel";
import {
  clearResearchRunLaunchDraft,
  readResearchRunLaunchDraft,
  writeResearchRunLaunchDraft,
} from "./researchRunLaunchDraft";
import { buildResearchRunInput } from "./researchRunLaunchContract";
import { researchRunStatusLabel } from "./researchRunPresentation";
import { getNodeAdapter } from "./nodeAdapterModel";
import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import styles from "./ResearchRunLaunchPanel.styles";

const QUESTION_EMPTY_KEY = "__question_empty__";
type Language = "zh" | "en";

function nextActionLabel(experiment: ResearchWorkflowExperimentOption, lang: Language = "zh"): string {
  if (lang === "en") {
    switch (experiment.nextAction) {
      case "create_run":
        return "Ready to create run";
      case "activate_campaign":
        return "Activate formal campaign";
      case "await_formal_question_approval":
        return "Waiting for formal question approval";
      case "await_dev_readiness":
        return "Waiting for DEV readiness";
      default:
        return experiment.nextAction;
    }
  }
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
function nextActionCtaLabel(experiment: ResearchWorkflowExperimentOption, lang: Language = "zh"): string | null {
  if (lang === "en") {
    switch (experiment.nextAction) {
      case "await_dev_readiness":
        return "Complete platform readiness checks";
      case "await_formal_question_approval":
        return "Review question result";
      default:
        return null;
    }
  }
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
  const matches = experiments.filter((item) => item.questionId === questionId);
  return matches.length > 1 || Boolean(matches[0] && !matches[0].launchable);
}

export function ExperimentLaunchStatus(props: {
  lang?: Language;
  experiment: ResearchWorkflowExperimentOption;
  busy: boolean;
  activationPending: boolean;
  onActivate: () => void;
  onOpenProgress?: () => void;
}) {
  const { experiment, busy, activationPending, onActivate, onOpenProgress } = props;
  const lang = props.lang ?? "zh";
  const isZh = lang === "zh";
  const navigationCtaLabel = experiment.activationAllowed ? null : nextActionCtaLabel(experiment, lang);
  return (
    <VSurface tone="inset" padding="compact" className={styles.selectedExperiment}>
      <div className={styles.experimentHeader}>
        <strong className={styles.experimentTitle}>{experiment.name}</strong>
        <VStatusChip tone={experiment.activated ? "success" : "warning"}>
          {experiment.activated ? (isZh ? "已激活" : "Active") : (isZh ? "未激活" : "Not active")}
        </VStatusChip>
      </div>
      <div className={styles.experimentMeta}>
        <span>{experiment.experimentId}</span>
        <span>{isZh ? "主题" : "Theme"} {experiment.themeId}</span>
        <span>Campaign {experiment.campaignId}</span>
      </div>
      <div className={styles.experimentStatus}>
        {isZh ? "下一动作：" : "Next action: "}{nextActionLabel(experiment, lang)}
      </div>
      {!experiment.activated && !experiment.activationAllowed ? (
        <div className={styles.experimentBlockerText}>
          {isZh
            ? "完成 DEV readiness / dev-1 / dev-5 fixture 后才能激活正式 campaign。激活不会启动 Qwen / 网络采集 / GPU 任务。"
            : "Complete the DEV readiness / dev-1 / dev-5 fixtures before activating the formal campaign. Activation will not start Qwen, network collection, or GPU tasks."}
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
      {!experiment.activated && experiment.activationAllowed ? (
        <VButton
          type="button"
          variant="primary"
          isDisabled={busy || activationPending}
          isPending={activationPending}
          onClick={() => {
            onActivate();
          }}
        >
          {isZh ? "激活正式 Campaign" : "Activate formal campaign"}
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

const DOMAIN_LABELS_EN: Record<string, string> = {
  mathematical_sciences: "Mathematics",
  chemistry: "Chemistry",
  medicine_and_health: "Medicine & health",
  biology: "Biology",
  astronomy: "Astronomy",
  physics: "Physics",
  engineering_and_materials_science: "Engineering & materials",
  information_science: "Information science",
  neuroscience: "Neuroscience",
  ecology: "Ecology",
  energy_science: "Energy science",
  artificial_intelligence: "Artificial intelligence",
};

function domainLabel(domain: string, lang: Language = "zh"): string {
  const labels = lang === "zh" ? DOMAIN_LABELS : DOMAIN_LABELS_EN;
  return labels[domain] || domain;
}

function questionMatchesQuery(question: ResearchWorkflowLaunchOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [
    question.questionId,
    question.title,
    question.domain || "",
    domainLabel(question.domain || "", "zh"),
    domainLabel(question.domain || "", "en"),
  ].some((value) => value.toLowerCase().includes(needle));
}

function isRestartableCheckpoint(checkpoint: ResearchWorkflowLaunchOption["checkpoint"]): boolean {
  return checkpoint?.status === "failed" || checkpoint?.status === "cancelled";
}

function freshRunIdempotencyKey(baseKey: string): string {
  const random = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${baseKey}:fresh:${random}`;
}

function checkpointNodeLabel(
  checkpoint: NonNullable<ResearchWorkflowLaunchOption["checkpoint"]>,
  lang: Language,
): string {
  if (lang === "zh") return checkpoint.currentNodeLabel || checkpoint.currentNodeId || "起点";
  return getNodeAdapter(checkpoint.currentNodeId)?.labelEn || checkpoint.currentNodeId || "Start";
}

function launchErrorText(rawMessage: string, lang: Language): string {
  if (lang === "zh") {
    return researchWorkflowErrorInlineText(rawMessage, "暂时无法读取 125 题目录，请稍后重试。");
  }
  const message = rawMessage.trim();
  if (!message) return "The 125-question catalog is temporarily unavailable. Please try again.";
  const presentation = presentResearchWorkflowError(message);
  return presentation.bodyEn === message
    ? researchWorkflowErrorTitle(presentation, lang)
    : `${researchWorkflowErrorTitle(presentation, lang)}. ${researchWorkflowErrorBody(presentation, lang)}`;
}

export function ResearchRunLaunchPanel(props: {
  lang?: Language;
  teamId: string;
  busy: boolean;
  initialQuestionId?: string;
  onSubmit: (input: CreateResearchWorkflowRunInput) => Promise<void>;
  onCancel: () => void;
  onContinueRun?: (input: { runId: string; nodeId: string; questionId: string }) => void;
}) {
  const { teamId, busy, initialQuestionId, onSubmit, onCancel, onContinueRun } = props;
  const lang = props.lang ?? "zh";
  const isZh = lang === "zh";
  // Per-team session draft restores the form after panel switches; an explicit
  // deep-link questionId always wins over the remembered draft.
  const [draft] = useState(() => readResearchRunLaunchDraft(teamId));
  const [questionId, setQuestionId] = useState(initialQuestionId || draft?.questionId || "");
  const [query, setQuery] = useState(draft?.query ?? "");
  const [safetyBudget, setSafetyBudget] = useState(() => draft?.safetyBudget ?? createResearchRunSafetyBudget());
  const [error, setError] = useState<string | null>(null);
  const [activationDialogOpen, setActivationDialogOpen] = useState(false);
  useEffect(() => {
    writeResearchRunLaunchDraft(teamId, { questionId, query, safetyBudget });
  }, [teamId, questionId, query, safetyBudget]);
  useEffect(() => {
    const explicitQuestionId = initialQuestionId?.trim() ?? "";
    if (!explicitQuestionId) return;
    setQuestionId(explicitQuestionId);
    setError(null);
  }, [initialQuestionId, teamId]);
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
  const experiments = launchOptions.data?.experiments ?? [];
  const selectedQuestion = questions.find((question) => question.questionId === questionId) ?? null;
  const matchingExperiments = experiments.filter((experiment) => experiment.questionId === questionId);
  const selectedExperiment = matchingExperiments.length === 1 ? matchingExperiments[0] : null;
  const experimentMatchAmbiguous = matchingExperiments.length > 1;
  const checkpoint = selectedQuestion?.checkpoint ?? null;
  const restartableCheckpoint = isRestartableCheckpoint(checkpoint);
  const filteredQuestions = useMemo(
    () => questions.filter((question) => questionMatchesQuery(question, query)),
    [questions, query],
  );
  const visibleQuestions = selectedQuestion && !filteredQuestions.some((item) => item.questionId === questionId)
    ? [selectedQuestion, ...filteredQuestions]
    : filteredQuestions;
  async function activateSelectedExperiment(experimentId: string) {
    return activateResearchWorkflowExperiment(CHALLENGE_CUP_WORKFLOW_ID, experimentId, {
      teamId,
      confirmed: true,
    });
  }
  const activationMutation = useMutation({
    mutationFn: activateSelectedExperiment,
    onSuccess: async () => {
      setActivationDialogOpen(false);
      setError(null);
      await launchOptions.refetch();
    },
    onError: (reason: unknown) => {
      setError(reason instanceof Error ? reason.message : String(reason));
    },
  });

  if (launchOptions.isPending) {
    return <VStateSurface tone="loading" title={isZh ? "加载 125 题目录" : "Loading 125-question catalog"} fill className={styles.state} />;
  }
  if (launchOptions.isError) {
    const rawMessage = launchOptions.error instanceof Error
      ? launchOptions.error.message
      : String(launchOptions.error ?? "");
    return (
      <VStateSurface
        tone="error"
        title={isZh ? "题目目录加载失败" : "Question catalog failed to load"}
        fill
        className={styles.state}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void launchOptions.refetch()}>
            {isZh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        <p className={styles.error}>
          {launchErrorText(rawMessage, lang)}
        </p>
        {rawMessage ? (
          <details className={styles.techDetails}>
            <summary>{isZh ? "技术细节" : "Technical details"}</summary>
            <code>{rawMessage}</code>
          </details>
        ) : null}
      </VStateSurface>
    );
  }
  if (!questions.length) {
    return <VStateSurface tone="empty" title={isZh ? "暂无题目目录" : "No question catalog yet"} fill className={styles.state} />;
  }

  const primaryLabel = checkpoint
    ? (checkpoint.resumable
      ? (isZh ? "继续运行" : "Continue run")
      : restartableCheckpoint
        ? (isZh ? "新建运行" : "New run")
        : (isZh ? "查看进展" : "View progress"))
    : (isZh ? "开始实验" : "Start experiment");

  const submitNewRun = () => {
    try {
      const input = buildResearchRunInput({ teamId, questionId, safetyBudget });
      void onSubmit({
        ...input,
        // A failed/cancelled checkpoint must not be replayed by the old
        // deterministic key; explicitly starting again creates a new run.
        idempotencyKey: restartableCheckpoint
          ? freshRunIdempotencyKey(input.idempotencyKey)
          : input.idempotencyKey,
      })
        .then(() => clearResearchRunLaunchDraft(teamId))
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : String(reason));
        });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title={isZh ? "选择题目并开始实验" : "Choose a question and start an experiment"} headingLevel={3} />
      <VFieldRow label={isZh ? "搜索题目" : "Search questions"} description={isZh ? "题号、英文问题或学科" : "Question ID, English question, or field"}>
        <VInput
          aria-label={isZh ? "搜索 125 题" : "Search 125 questions"}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={isZh ? "SCI-003 或 Riemann" : "SCI-003 or Riemann"}
          isDisabled={busy}
        />
      </VFieldRow>
      <VFieldRow label={isZh ? "研究问题" : "Research question"}>
        <VSelect
          aria-label={isZh ? "选择 125 题" : "Choose a question from 125"}
          placeholder={isZh ? "选择一道题目" : "Choose a question"}
          selectedKey={questionId || QUESTION_EMPTY_KEY}
          options={[
            { id: QUESTION_EMPTY_KEY, label: isZh ? "请选择题目" : "Please choose a question" },
            ...visibleQuestions.map((question) => ({
              id: question.questionId,
              label: `${question.questionId} · ${question.title}`,
              description: [
                domainLabel(question.domain || question.scope, lang),
                question.checkpoint
                  ? `${checkpointNodeLabel(question.checkpoint, lang)} · ${question.checkpoint.completedCount}/${question.checkpoint.totalSteps}`
                  : (isZh ? "尚未开始" : "Not started"),
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
          <span className={styles.questionScope}>{domainLabel(selectedQuestion.domain || selectedQuestion.scope, lang)}</span>
          {checkpoint ? (
            <div className={styles.checkpoint} data-testid="question-checkpoint">
              <VStatusChip tone={checkpoint.resumable ? "warning" : checkpoint.status === "succeeded" ? "success" : "neutral"}>
                {researchRunStatusLabel(checkpoint.status, lang)}
              </VStatusChip>
              <p>
                {isZh ? "当前 checkpoint：" : "Current checkpoint: "}{checkpointNodeLabel(checkpoint, lang)} · {checkpoint.completedCount}/{checkpoint.totalSteps}
              </p>
            </div>
          ) : (
            <p className={styles.questionScope}>
              {isZh
                ? "尚无运行记录，开始后会从资料寻找进入流程并保存 checkpoint。"
                : "No run exists yet. Starting will enter the workflow at source finding and save a checkpoint."}
            </p>
          )}
        </VSurface>
      ) : null}
      {selectedExperiment ? (
        <ExperimentLaunchStatus
          lang={lang}
          experiment={selectedExperiment}
          busy={busy}
          activationPending={activationMutation.isPending}
          onActivate={() => {
            if (!selectedExperiment.activationAllowed || activationMutation.isPending) return;
            setError(null);
            setActivationDialogOpen(true);
          }}
        />
      ) : null}
      {experimentMatchAmbiguous ? (
        <div role="alert" className={styles.error}>
          {isZh
            ? "所选题目匹配到多个正式实验，已停止创建运行。"
            : "The selected question matches multiple formal experiments; run creation is blocked."}
        </div>
      ) : null}
      <ResearchRunSafetyLimitPanel
        budget={safetyBudget}
        isDisabled={busy}
        lang={lang}
        onChange={setSafetyBudget}
      />
      {error ? <div role="alert" className={styles.error}>{error}</div> : null}
      <details className={styles.techDetails}>
        <summary>{isZh ? "其他处理" : "Other actions"}</summary>
        <VButton variant="ghost" onClick={onCancel} isDisabled={busy}>{isZh ? "取消" : "Cancel"}</VButton>
        {restartableCheckpoint && onContinueRun ? (
          <VButton
            variant="ghost"
            onClick={() => onContinueRun({
              runId: checkpoint!.runId,
              nodeId: checkpoint!.currentNodeId || "source_finding",
              questionId,
            })}
            isDisabled={busy}
          >
            {isZh ? "查看失败运行" : "View failed run"}
          </VButton>
        ) : null}
      </details>
      <div className={styles.actions} data-vui-region="launch-primary-action">
        {(!selectedExperiment || selectedExperiment.launchable) && !experimentMatchAmbiguous ? <VButton
          isPending={busy}
          isDisabled={!selectedQuestion || isLaunchBlockedByExperiment(experiments, questionId)}
          onClick={() => {
            setError(null);
            if (checkpoint?.resumable && onContinueRun) {
              onContinueRun({
                runId: checkpoint.runId,
                nodeId: checkpoint.currentNodeId || "source_finding",
                questionId,
              });
              return;
            }
            if (checkpoint?.resumable && !onContinueRun) {
              setError(isZh ? "当前运行无法在此面板继续，请从运行列表打开。" : "This run cannot continue here; open it from the run list.");
              return;
            }
            if (restartableCheckpoint || !checkpoint) {
              submitNewRun();
              return;
            }
              setError(isZh ? "当前运行已完成，请从运行列表查看进展。" : "This run is complete; view its progress from the run list.");
          }}
        >
          {primaryLabel}
        </VButton> : null}
      </div>
      <VConfirmDialog
        open={activationDialogOpen}
        onOpenChange={(open) => {
          if (!activationMutation.isPending) setActivationDialogOpen(open);
        }}
        title={isZh ? "激活正式 Campaign？" : "Activate formal campaign?"}
        description={selectedExperiment
          ? (isZh
            ? `将激活 ${selectedExperiment.name} 的 Campaign ${selectedExperiment.campaignId}。此操作不会直接启动运行。`
            : `Activate Campaign ${selectedExperiment.campaignId} for ${selectedExperiment.name}. This does not start a run.`)
          : undefined}
        confirmLabel={isZh ? "确认激活" : "Confirm activation"}
        cancelLabel={isZh ? "取消" : "Cancel"}
        confirmPending={activationMutation.isPending}
        confirmDisabled={!selectedExperiment?.activationAllowed}
        onConfirm={() => {
          if (!selectedExperiment?.activationAllowed || activationMutation.isPending) return;
          activationMutation.mutate(selectedExperiment.experimentId);
        }}
      />
    </VSurface>
  );
}
