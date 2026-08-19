import { VButton, VSelect } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import { researchRunStatusLabel, type ResearchRunOption } from "./researchRunPresentation";
import type { ResearchWorkflowEventStreamState } from "./useResearchWorkflowEventStream";
import styles from "./ResearchWorkflowToolbar.styles";

function streamStateLabel(state: ResearchWorkflowEventStreamState, isZh: boolean): string {
  if (isZh) {
    const zh: Record<ResearchWorkflowEventStreamState, string> = {
      idle: "未连接",
      connecting: "连接中",
      connected: "实时",
      reconnecting: "重连中",
    };
    return zh[state];
  }
  const en: Record<ResearchWorkflowEventStreamState, string> = {
    idle: "Offline",
    connecting: "Connecting",
    connected: "Live",
    reconnecting: "Reconnecting",
  };
  return en[state];
}

export function ResearchWorkflowToolbar(props: {
  teamName: string;
  questionId: string;
  runId: string;
  runStatus: string;
  nextAction: string;
  streamState: ResearchWorkflowEventStreamState;
  runOptions: ResearchRunOption[];
  panel: ResearchProcessPanel;
  hasRuntimeNode: boolean;
  createDisabled: boolean;
  createDisabledReason?: string;
  onSelectRun: (runId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
  onJumpToRuntime: () => void;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  return (
    <div className={styles.root}>
      <div className={styles.context}>
        <strong className={styles.primary}>{props.teamName}</strong>
        {props.questionId ? <span className={styles.truncated}>{props.questionId}</span> : null}
        {props.runId ? <span className={styles.truncated}>{researchRunStatusLabel(props.runStatus)}</span> : null}
        {props.runId ? (
          <span aria-label={isZh ? "事件连接状态" : "Event stream state"}>
            {streamStateLabel(props.streamState, isZh)}
          </span>
        ) : null}
        {props.nextAction && props.hasRuntimeNode ? (
          <VButton
            type="button"
            variant="ghost"
            className={styles.nextAction}
            data-vui="research-next-action"
            title={isZh ? "跳到当前节点处理下一步" : "Jump to the current node for the next step"}
            onClick={props.onJumpToRuntime}
          >
            {isZh ? `下一步：${props.nextAction}` : `Next: ${props.nextAction}`}
          </VButton>
        ) : props.nextAction ? (
          <span className={styles.next}>{isZh ? `下一步：${props.nextAction}` : `Next: ${props.nextAction}`}</span>
        ) : null}
      </div>
      <div className={styles.actions}>
        {props.runOptions.length > 0 ? (
          <VSelect
            density="compact"
            className={styles.select}
            aria-label={isZh ? "运行切换" : "Switch run"}
            placeholder={isZh ? "切换运行" : "Switch run"}
            selectedKey={props.runId || null}
            options={props.runOptions.map((item) => ({
              id: item.runId,
              label: item.label,
            }))}
            onSelectionChange={(key) => props.onSelectRun(key == null ? "" : String(key))}
          />
        ) : null}
        <VButton type="button" variant={props.panel === "agents" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("agents")}>Agent</VButton>
        <VButton type="button" variant={props.panel === "timeline" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("timeline")}>{isZh ? "时间线" : "Timeline"}</VButton>
        <VButton type="button" variant={props.panel === "team" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("team")}>{isZh ? "团队" : "Team"}</VButton>
        <VButton type="button" variant={props.panel === "progress" || props.panel === "question" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("progress")}>{isZh ? "题目进度" : "Progress"}</VButton>
        <VButton
          type="button"
          variant={props.panel === "launch" ? "secondary" : "primary"}
          onClick={() => props.onOpenPanel("launch")}
          isDisabled={props.createDisabled}
          disabledReason={props.createDisabledReason}
        >
          {props.runId ? (isZh ? "新建运行" : "New run") : (isZh ? "创建运行" : "Create run")}
        </VButton>
      </div>
    </div>
  );
}
