import { VButton, VSelect } from "../../../components/vui";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import type { ResearchWorkflowStreamState } from "./useResearchWorkflowStream";
import styles from "./ResearchWorkflowToolbar.styles";

const STREAM_LABEL: Record<ResearchWorkflowStreamState, string> = {
  idle: "未连接",
  connecting: "连接中",
  connected: "实时",
  reconnecting: "重连中",
};

export function ResearchWorkflowToolbar(props: {
  teamName: string;
  questionId: string;
  runId: string;
  runStatus: string;
  activeProjectId: string;
  nextAction: string;
  streamState: ResearchWorkflowStreamState;
  runOptions: Array<{ runId: string; status: string }>;
  panel: ResearchProcessPanel;
  hasRuntimeNode: boolean;
  createDisabled: boolean;
  createDisabledReason?: string;
  onSelectRun: (runId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
  onJumpToRuntime: () => void;
}) {
  return (
    <div className={styles.root}>
      <div className={styles.context}>
        <strong className={styles.primary}>{props.teamName}</strong>
        <span className={styles.truncated}>{props.questionId || props.activeProjectId || "未选择题目"}</span>
        {props.runId ? <span className={styles.truncated}>{props.runStatus}</span> : null}
        {props.runId ? <span aria-label="事件连接状态">{STREAM_LABEL[props.streamState]}</span> : null}
        {props.nextAction ? <span className={styles.next}>下一步：{props.nextAction}</span> : null}
      </div>
      <div className={styles.actions}>
        {props.runOptions.length > 0 ? (
          <VSelect
            density="compact"
            className={styles.select}
            aria-label="运行切换"
            placeholder="选择运行"
            selectedKey={props.runId || null}
            options={props.runOptions.map((item) => ({
              id: item.runId,
              label: `${item.runId} · ${item.status}`,
            }))}
            onSelectionChange={(key) => props.onSelectRun(key == null ? "" : String(key))}
          />
        ) : null}
        <VButton type="button" variant={props.panel === "agents" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("agents")}>Agent</VButton>
        <VButton type="button" variant={props.panel === "timeline" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("timeline")}>时间线</VButton>
        <VButton type="button" variant={props.panel === "team" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("team")}>团队</VButton>
        <VButton type="button" variant={props.panel === "progress" || props.panel === "question" ? "secondary" : "ghost"} onClick={() => props.onOpenPanel("progress")}>题目进度</VButton>
        {props.hasRuntimeNode ? <VButton type="button" variant="ghost" onClick={props.onJumpToRuntime}>当前节点</VButton> : null}
        {!props.runId ? (
          <VButton
            type="button"
            variant={props.panel === "launch" ? "secondary" : "primary"}
            onClick={() => props.onOpenPanel("launch")}
            isDisabled={props.createDisabled}
            disabledReason={props.createDisabledReason}
          >
            创建运行
          </VButton>
        ) : null}
      </div>
    </div>
  );
}
