import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type {
  EffectiveAgentBinding,
  WorkflowCanvasProjection,
} from "../../../api/types/researchWorkflow";
import { VPanelHeader, VRouteLinkButton, VSurface } from "../../../components/vui";
import { teamChatRoomRoute } from "../researchStageAgentPresentation";
import { teamWorkspaceRoute } from "../researchWorkspaceModel";
import styles from "./ResearchTeamPanel.styles";

export function ResearchTeamPanel(props: {
  teamId: string;
  teamName: string;
  linkedChatRoomId: string;
  run: WorkflowRunRecord | null;
  projection: WorkflowCanvasProjection | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
}) {
  const agentNodeIds = props.projection?.definition.nodes
    .filter((node) => node.actorKind === "agent")
    .map((node) => node.nodeId) ?? [];
  const bindingByNode = new Map(
    (props.effectiveBindings ?? []).map((binding) => [binding.nodeId, binding]),
  );
  const boundCount = agentNodeIds.filter((nodeId) => bindingByNode.get(nodeId)?.agentId).length;
  const blockers = Object.values(props.projection?.run.nodeRuns ?? {})
    .filter((node) => node.status === "blocked" || node.status === "failed" || node.status === "waiting_human")
    .map((node) => ({
      nodeId: node.nodeId,
      label: props.projection?.definition.nodes.find((item) => item.nodeId === node.nodeId)?.label || node.nodeId,
      owner: node.primaryAgentId || bindingByNode.get(node.nodeId)?.agentId || "人工处理",
    }));
  const coordinatorAgentId = props.effectiveBindings?.find(
    (binding) => binding.roleKey === "research_coordinator",
  )?.agentId;
  const returnTo = teamWorkspaceRoute(props.teamId, {
    runId: props.run?.runId,
    panel: "team",
  });
  const roomRoute = teamChatRoomRoute(props.linkedChatRoomId, returnTo, "返回科研流程");

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title="团队治理" headingLevel={3} />
      <dl className={styles.details}>
        <dt className={styles.label}>团队</dt>
        <dd className={styles.valueBreak}>{props.teamName || props.teamId}</dd>
        <dt className={styles.label}>协调 Agent</dt>
        <dd className={styles.valueBreak}>{coordinatorAgentId || "未绑定"}</dd>
        <dt className={styles.label}>绑定覆盖</dt>
        <dd className={styles.value}>{boundCount}/{agentNodeIds.length}</dd>
        <dt className={styles.label}>流程版本</dt>
        <dd className={styles.valueBreak}>{props.run?.workflowVersionId || "未创建运行"}</dd>
        <dt className={styles.label}>运行版本</dt>
        <dd className={styles.value}>{props.run?.runVersion ?? "—"}</dd>
      </dl>
      {blockers.length ? (
        <section>
          <h4 className={styles.sectionTitle}>当前阻塞</h4>
          <ul className={styles.blockers}>
            {blockers.map((blocker) => (
              <li key={blocker.nodeId} className={styles.blocker}>
                <span>{blocker.label}</span>
                <span className={styles.owner} title={blocker.owner}>{blocker.owner}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {roomRoute ? (
        <VRouteLinkButton to={roomRoute} variant="secondary">打开团队讨论</VRouteLinkButton>
      ) : (
        <div className={styles.roomMissing} role="status">
          团队尚未关联讨论会话
        </div>
      )}
    </VSurface>
  );
}
