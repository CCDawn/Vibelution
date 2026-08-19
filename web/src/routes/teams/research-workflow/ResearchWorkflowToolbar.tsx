import {
  VButton,
  VSelect,
  VToolbar,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  formatExperimentSwitchLabel,
  type ExperimentChromeIdentity,
  type ExperimentSwitchOption,
} from "./researchExperimentSwitchModel";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import styles from "./ResearchWorkflowToolbar.styles";

type WorkflowPhase = {
  step: number | null;
  zh: string;
  en: string;
};

export function researchWorkflowPhase(navigationLabel?: string): WorkflowPhase {
  const label = String(navigationLabel || "").trim();
  if (label.includes("假说收敛")) return { step: 5, zh: "假说收敛", en: "Convergence" };
  if (label.includes("资料搜集")) return { step: 4, zh: "资料搜集", en: "Evidence collection" };
  if (label.includes("假说选择")) return { step: 2, zh: "假说选择", en: "Hypothesis selection" };
  if (label.includes("候选")) return { step: 1, zh: "候选形成", en: "Candidate formation" };
  if (label.includes("评审") || label.includes("讨论") || label.includes("本轮")) {
    return { step: 3, zh: "团队评审", en: "Team review" };
  }
  return { step: null, zh: "流程进行中", en: "Workflow in progress" };
}

export function ResearchWorkflowToolbar(props: {
  identity: ExperimentChromeIdentity | null;
  runId: string;
  runStatus: string;
  experimentOptions: ExperimentSwitchOption[];
  panel: ResearchProcessPanel;
  createDisabled: boolean;
  createDisabledReason?: string;
  navigationLabel?: string;
  atCurrentTask?: boolean;
  onNavigateCurrent?: () => void;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const selectedQuestionId = props.identity?.questionId || null;
  const emptySwitcherLabel = props.identity
    ? formatExperimentSwitchLabel(props.identity.questionId, props.identity.hypothesisSummary)
    : (isZh ? "尚未选择实验" : "No experiment selected");
  const phase = researchWorkflowPhase(props.navigationLabel);
  const detailsPanel = props.panel === "question" ? "progress" : (
    props.panel === "agents"
    || props.panel === "timeline"
    || props.panel === "team"
    || props.panel === "progress"
    || props.panel === "launch"
      ? props.panel
      : null
  );
  const detailOptions: Array<{
    id: ResearchProcessPanel;
    label: string;
    description?: string;
    disabled?: boolean;
  }> = [
    { id: "agents", label: "Agent" },
    { id: "team", label: isZh ? "成员与讨论" : "Members & discussion" },
    { id: "timeline", label: isZh ? "运行记录" : "Run history" },
    { id: "progress", label: isZh ? "题目进度" : "Question progress" },
    ...(props.runId ? [{
      id: "launch" as const,
      label: isZh ? "新建运行" : "New run",
      description: props.createDisabled ? props.createDisabledReason : undefined,
      disabled: props.createDisabled,
    }] : []),
  ];
  return (
    <VToolbar ariaLabel={isZh ? "科研流程" : "Research workflow"} className={styles.root}>
      <div className={styles.switcher}>
        {props.experimentOptions.length > 0 ? (
          <VSelect
            density="compact"
            aria-label={isZh ? "切换实验" : "Switch experiment"}
            placeholder={isZh ? "选择实验" : "Select experiment"}
            selectedKey={selectedQuestionId}
            options={props.experimentOptions.map((item) => ({
              id: item.questionId,
              label: item.label,
              description: item.description,
            }))}
            onSelectionChange={(key) => {
              if (key == null) return;
              props.onSelectExperiment(String(key));
            }}
          />
        ) : (
          <span className={styles.empty}>{emptySwitcherLabel}</span>
        )}
      </div>
      {props.runId ? (
        <div className={styles.phase} data-vui="research-workflow-phase">
          {phase.step
            ? (isZh ? `第 ${phase.step}/5 步 · ${phase.zh}` : `Step ${phase.step}/5 · ${phase.en}`)
            : (isZh ? phase.zh : phase.en)}
        </div>
      ) : <span />}
      <div className={styles.actions}>
        <VSelect
          density="compact"
          className={styles.details}
          aria-label={isZh ? "查看详情" : "View details"}
          placeholder={isZh ? "查看详情" : "Details"}
          selectedKey={detailsPanel}
          options={detailOptions}
          onSelectionChange={(key) => {
            if (key == null) return;
            props.onOpenPanel(String(key) as ResearchProcessPanel);
          }}
        />
        {props.runId ? (
          <VButton
            type="button"
            density="compact"
            variant={props.atCurrentTask ? "ghost" : "primary"}
            isDisabled={props.atCurrentTask}
            onClick={() => props.onNavigateCurrent?.()}
          >
            {props.atCurrentTask
              ? (isZh ? "当前任务" : "Current task")
              : (props.navigationLabel || (isZh ? "前往当前任务" : "Go to current task"))}
          </VButton>
        ) : null}
        {!props.runId ? (
          <VButton
            type="button"
            density="compact"
            variant="primary"
            onClick={() => props.onOpenPanel("launch")}
            isDisabled={props.createDisabled}
            disabledReason={props.createDisabledReason}
          >
            {isZh ? "创建运行" : "Create run"}
          </VButton>
        ) : null}
      </div>
    </VToolbar>
  );
}
