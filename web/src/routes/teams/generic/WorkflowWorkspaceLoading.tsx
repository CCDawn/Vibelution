import type { ComponentProps } from "react";
import styles from "./WorkflowWorkspaceLoading.styles";
import { readWorkflowLoadingShape, unknownWorkflowLoadingShape } from "./workflowLoadingShape";
import { WorkflowInspectorLoading } from "./WorkflowInspector";
import { WorkbenchShell } from "./WorkbenchShell";

const noop = () => undefined;

/** The actual product shell, with pending data slots instead of a second layout. */
export function WorkflowWorkspaceLoading({
  teamId = "", teams = [], label = "正在读取团队工作台…",
}: {
  teamId?: string;
  teams?: { id: string; label: string }[];
  label?: string;
}) {
  const flows = readWorkflowLoadingShape(teamId) ?? unknownWorkflowLoadingShape();
  const flow = flows[0];
  const props: ComponentProps<typeof WorkbenchShell> = {
    teamId, teams, teamPending: !teams.some(team => team.id === teamId), membersPending: true,
    flows, flow, members: [], runs: [], mode: "design", selectedId: "",
    saving: false, pending: false, dirty: false, loading: true, loadingLabel: label,
    error: "", notice: "", inspector: flow ? <WorkflowInspectorLoading flow={flow}/> : null, inspectorOpen: false,
    onTeam: noop, onDiscussion: noop, onHistory: noop, onReload: noop,
    onInspectorOpen: noop, onMode: noop, onFlow: noop, onStep: noop, onRun: noop,
    onSave: noop, onStart: noop, onStop: noop, onCreate: noop, onTemplate: noop,
    onAddStep: noop, onMembers: noop, onArtifact: noop, onDismiss: noop,
  };
  return <div aria-busy="true" className={styles.frame}>
    <span role="status" className={styles.status}>{label}</span>
    <div inert className={styles.frame}><WorkbenchShell {...props}/></div>
  </div>;
}
