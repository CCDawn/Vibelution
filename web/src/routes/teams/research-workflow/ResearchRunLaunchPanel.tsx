import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import {
  fetchResearchWorkflowLaunchOptions,
  type CreateResearchWorkflowRunInput,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VFieldRow,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import { buildResearchRunInput } from "./researchRunLaunchContract";
import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import styles from "./ResearchRunLaunchPanel.styles";

export function ResearchRunLaunchPanel(props: {
  teamId: string;
  busy: boolean;
  onSubmit: (input: CreateResearchWorkflowRunInput) => Promise<void>;
  onCancel: () => void;
}) {
  const { teamId, busy, onSubmit, onCancel } = props;
  const [questionId, setQuestionId] = useState("");
  const [safetyBudget, setSafetyBudget] = useState(createResearchRunSafetyBudget);
  const [error, setError] = useState<string | null>(null);
  const launchOptions = useQuery({
    queryKey: queryKeys.researchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, teamId),
    queryFn: () => fetchResearchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled: Boolean(teamId),
    staleTime: 60_000,
  });
  const selectedQuestion = launchOptions.data?.questions.find(
    (question) => question.questionId === questionId,
  );

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
  if (!launchOptions.data?.questions.length) {
    return <VStateSurface tone="empty" title="暂无可启动题目" fill className={styles.state} />;
  }

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title="创建科研运行" headingLevel={3} />
      <VFieldRow label="研究命题">
        <VSelect
          aria-label="选择已审核题目"
          placeholder="选择已审核题目"
          selectedKey={questionId || null}
          options={launchOptions.data.questions.map((question) => ({
            id: question.questionId,
            label: `${question.questionId} · ${question.title}`,
          }))}
          onSelectionChange={(key) => {
            setQuestionId(key == null ? "" : String(key));
            setError(null);
          }}
          isDisabled={busy}
        />
      </VFieldRow>
      {selectedQuestion ? (
        <VSurface tone="inset" padding="compact" className={styles.selectedQuestion}>
          <strong className={styles.questionTitle}>{selectedQuestion.title}</strong>
          {selectedQuestion.scope ? <span className={styles.questionScope}>{selectedQuestion.scope}</span> : null}
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
    </VSurface>
  );
}
