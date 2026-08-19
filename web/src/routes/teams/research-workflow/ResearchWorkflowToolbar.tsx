import {
  VActionGroup,
  VButton,
  VSelect,
  VStatusChip,
  VToolbar,
  type VStatusTone,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  formatExperimentSwitchLabel,
  type ExperimentChromeIdentity,
  type ExperimentSwitchOption,
} from "./researchExperimentSwitchModel";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import { researchRunStatusLabel } from "./researchRunPresentation";
import styles from "./ResearchWorkflowToolbar.styles";

function runStatusTone(status: string): VStatusTone {
  if (status === "waiting_human" || status === "blocked") return "warning";
  if (status === "running") return "accent";
  if (status === "succeeded") return "success";
  if (status === "failed") return "danger";
  return "neutral";
}

export function ResearchWorkflowToolbar(props: {
  identity: ExperimentChromeIdentity | null;
  runId: string;
  runStatus: string;
  experimentOptions: ExperimentSwitchOption[];
  panel: ResearchProcessPanel;
  createDisabled: boolean;
  createDisabledReason?: string;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const selectedQuestionId = props.identity?.questionId || null;
  const emptySwitcherLabel = props.identity
    ? formatExperimentSwitchLabel(props.identity.questionId, props.identity.hypothesisSummary)
    : (isZh ? "尚未选择实验" : "No experiment selected");
  return (
    <VToolbar ariaLabel={isZh ? "科研流程" : "Research workflow"} className={styles.root}>
      <div className={styles.switcher}>
        {props.experimentOptions.length > 0 ? (
          <VSelect
            density="compact"
            aria-label={isZh ? "切换假说" : "Switch hypothesis"}
            placeholder={isZh ? "选择假说" : "Select hypothesis"}
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
      <div className={styles.status}>
        <span className={styles.statusLabel}>{isZh ? "状态" : "Status"}</span>
        {props.runId ? (
          <VStatusChip tone={runStatusTone(props.runStatus)}>
            {researchRunStatusLabel(props.runStatus)}
          </VStatusChip>
        ) : (
          <span className={styles.statusEmpty}>—</span>
        )}
      </div>
      <div className={styles.actions}>
        <VActionGroup ariaLabel={isZh ? "工具面板" : "Tool panels"} className={styles.nav}>
          <VButton type="button" density="compact" variant={props.panel === "agents" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("agents")}>Agent</VButton>
          <VButton type="button" density="compact" variant={props.panel === "timeline" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("timeline")}>{isZh ? "时间线" : "Timeline"}</VButton>
          <VButton type="button" density="compact" variant={props.panel === "team" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("team")}>{isZh ? "团队" : "Team"}</VButton>
          <VButton type="button" density="compact" variant={props.panel === "progress" || props.panel === "question" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("progress")}>{isZh ? "题目进度" : "Progress"}</VButton>
        </VActionGroup>
        <VButton
          type="button"
          density="compact"
          variant={props.panel === "launch" ? "secondary" : "primary"}
          onClick={() => props.onOpenPanel("launch")}
          isDisabled={props.createDisabled}
          disabledReason={props.createDisabledReason}
        >
          {props.runId ? (isZh ? "新建运行" : "New run") : (isZh ? "创建运行" : "Create run")}
        </VButton>
      </div>
    </VToolbar>
  );
}
