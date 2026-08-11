import { useMemo, useState } from "react";

import type { CreateResearchWorkflowRunInput } from "../../../api/researchWorkflow";
import {
  VButton,
  VFieldRow,
  VInput,
  VPanelHeader,
  VSurface,
  VTextarea,
} from "../../../components/vui";
import {
  buildResearchRunInput,
  RESEARCH_MODEL_ROUTING_PURPOSES,
  type ResearchRunLaunchDraft,
} from "./researchRunLaunchContract";
import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import {
  createResearchRunSafetyBudget,
  createResearchRunSafetyBudgetPolicy,
  readResearchRunSafetyBudget,
  writeResearchRunSafetyBudget,
} from "./researchRunSafetyBudget";
import styles from "./ResearchRunLaunchPanel.styles";

const INITIAL_SAFETY_BUDGET = createResearchRunSafetyBudget();

const INITIAL_CONTRACT = JSON.stringify(
  {
    metricContract: { primary: "competition_score", direction: "maximize" },
    constraintSnapshot: { formalWrites: false },
    trackAndRubricSnapshot: { track: "", blockingRules: [] },
    researchObjectiveContract: { question: "", falsifiableOutcome: "" },
    sourcePolicy: { minimumPrimarySources: 3, requireCounterEvidence: true },
    budgetPolicy: createResearchRunSafetyBudgetPolicy(INITIAL_SAFETY_BUDGET, {
      experiments: 12,
      computeUnits: 100,
      maxParallelTasks: 3,
      maxRetries: 2,
    }),
    stopPolicy: { maxNoImprovementRounds: 2, stopOnBudgetExhaustion: true },
    modelRoutingPolicy: Object.fromEntries(
      RESEARCH_MODEL_ROUTING_PURPOSES.map((purpose) => [
        purpose,
        "relay_openai/gpt-5.6-luna",
      ]),
    ),
    evaluationContract: { minimumClaimEvidenceCoverage: 0.9, requiredSeeds: [11, 29, 47] },
  },
  null,
  2,
);

export function ResearchRunLaunchPanel(props: {
  teamId: string;
  projectId: string;
  busy: boolean;
  onSubmit: (input: CreateResearchWorkflowRunInput) => Promise<void>;
  onCancel: () => void;
}) {
  const { teamId, projectId, busy, onSubmit, onCancel } = props;
  const [draft, setDraft] = useState<ResearchRunLaunchDraft>({
    questionId: "",
    researchBriefHash: "",
    datasetRefs: "",
    competitionRuleRef: "",
    competitionRuleVersion: "",
    environmentSnapshotRef: "",
    contractJson: INITIAL_CONTRACT,
  });
  const [error, setError] = useState<string | null>(null);
  const update = (key: keyof ResearchRunLaunchDraft, value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const safetyBudget = useMemo(() => {
    try {
      return { value: readResearchRunSafetyBudget(draft.contractJson), error: null };
    } catch (reason) {
      return { value: null, error: reason instanceof Error ? reason.message : String(reason) };
    }
  }, [draft.contractJson]);
  const updateSafetyBudget = (nextBudget: NonNullable<typeof safetyBudget.value>) => {
    try {
      update("contractJson", writeResearchRunSafetyBudget(draft.contractJson, nextBudget));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title="创建科研运行" headingLevel={3} />
      <VFieldRow label="题目 ID">
        <VInput
          value={draft.questionId}
          onChange={(event) => update("questionId", event.currentTarget.value)}
        />
      </VFieldRow>
      <VFieldRow label="研究简报 Hash">
        <VInput
          value={draft.researchBriefHash}
          onChange={(event) => update("researchBriefHash", event.currentTarget.value)}
        />
      </VFieldRow>
      <VFieldRow label="数据集引用">
        <VTextarea
          value={draft.datasetRefs}
          onChange={(event) => update("datasetRefs", event.currentTarget.value)}
          rows={3}
        />
      </VFieldRow>
      <VFieldRow label="竞赛规则引用">
        <VInput
          value={draft.competitionRuleRef}
          onChange={(event) => update("competitionRuleRef", event.currentTarget.value)}
        />
      </VFieldRow>
      <VFieldRow label="竞赛规则版本">
        <VInput
          value={draft.competitionRuleVersion}
          onChange={(event) => update("competitionRuleVersion", event.currentTarget.value)}
        />
      </VFieldRow>
      <VFieldRow label="环境快照引用">
        <VInput
          value={draft.environmentSnapshotRef}
          onChange={(event) => update("environmentSnapshotRef", event.currentTarget.value)}
        />
      </VFieldRow>
      {safetyBudget.value ? (
        <ResearchRunSafetyLimitPanel
          budget={safetyBudget.value}
          isDisabled={busy}
          onChange={updateSafetyBudget}
        />
      ) : <div role="alert" className={styles.error}>{safetyBudget.error}</div>}
      <details className={styles.advancedContract}>
        <summary className={styles.advancedContractSummary}>高级运行合同</summary>
        <div className={styles.advancedContractBody}>
          <VFieldRow label="运行合同 JSON">
            <VTextarea
              value={draft.contractJson}
              onChange={(event) => update("contractJson", event.currentTarget.value)}
              rows={18}
              isDisabled={busy}
              className={styles.contract}
            />
          </VFieldRow>
        </div>
      </details>
      {error ? <div role="alert" className={styles.error}>{error}</div> : null}
      <div className={styles.actions}>
        <VButton variant="ghost" onClick={onCancel} isDisabled={busy}>取消</VButton>
        <VButton
          isPending={busy}
          onClick={() => {
            setError(null);
            try {
              const input = buildResearchRunInput({ teamId, projectId, draft });
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
