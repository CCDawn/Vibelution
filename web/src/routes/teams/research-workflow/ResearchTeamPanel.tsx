import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { MeetingRoundRecord } from "../../../api/types/hypothesisFirst";
import type {
  EffectiveAgentBinding,
  WorkflowCanvasProjection,
} from "../../../api/types/researchWorkflow";
import { VPanelHeader, VRouteLinkButton, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { ResearchProjectSwitcher } from "../research-projects/ResearchProjectSwitcher";
import { teamChatRoomRoute } from "../researchStageAgentPresentation";
import { teamWorkspaceRoute } from "../researchWorkspaceModel";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";
import styles from "./ResearchTeamPanel.styles";

function noopProjectActivated() {
  // Project activation propagates through researchProjectQueryKey invalidation;
  // this panel holds no local project draft to update.
}

export function ResearchTeamPanel(props: {
  teamId: string;
  teamName: string;
  linkedChatRoomId: string;
  run: WorkflowRunRecord | null;
  projection: WorkflowCanvasProjection | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  meetingRoundId?: string;
  questionId?: string;
  discussionModel?: ScopedDiscussionModel;
  meetings?: readonly MeetingRoundRecord[];
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
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
      owner: node.primaryAgentId || bindingByNode.get(node.nodeId)?.agentId || (isZh ? "人工处理" : "Manual follow-up"),
    }));
  const coordinatorAgentId = props.effectiveBindings?.find(
    (binding) => binding.roleKey === "research_coordinator",
  )?.agentId;
  const scopedQuestionId = String(props.questionId || "").trim();
  const scopedDiscussionReady = Boolean(
    scopedQuestionId
    && props.discussionModel?.status === "ready"
    && props.discussionModel.questionId === scopedQuestionId
    && props.discussionModel.deepLink,
  );
  const returnTo = teamWorkspaceRoute(props.teamId, {
    runId: props.run?.runId,
    questionId: scopedQuestionId,
    panel: "team",
  });
  const pastDiscussions = (props.meetings ?? []).filter((meeting) =>
    meeting.question.toUpperCase() === scopedQuestionId.toUpperCase()
    && meeting.status === "closed" && meeting.linkedChatRoomId,
  );
  const roomRoute = scopedQuestionId
    ? (scopedDiscussionReady ? props.discussionModel?.deepLink || "" : "")
    : teamChatRoomRoute(
        props.linkedChatRoomId,
        returnTo,
        isZh ? "返回科研流程" : "Back to research workflow",
        props.meetingRoundId,
      );

  return (
    <VSurface tone="panel" className={styles.root}>
      <VPanelHeader title={isZh ? "团队治理" : "Team governance"} headingLevel={3} />
      {!scopedQuestionId ? (
        <ResearchProjectSwitcher
          teamId={props.teamId}
          lang={lang}
          currentTopic=""
          currentExperimentMethod=""
          onProjectActivated={noopProjectActivated}
        />
      ) : null}
      <dl className={styles.details}>
        {scopedQuestionId ? (
          <>
            <dt className={styles.label}>{isZh ? "当前题目" : "Current question"}</dt>
            <dd className={styles.valueBreak}>{scopedQuestionId}</dd>
          </>
        ) : null}
        <dt className={styles.label}>{isZh ? "团队" : "Team"}</dt>
        <dd className={styles.valueBreak}>{props.teamName || props.teamId}</dd>
        <dt className={styles.label}>{isZh ? "协调 Agent" : "Coordinator agent"}</dt>
        <dd className={styles.valueBreak}>{coordinatorAgentId || (isZh ? "未绑定" : "Not bound")}</dd>
        <dt className={styles.label}>{isZh ? "绑定覆盖" : "Binding coverage"}</dt>
        <dd className={styles.value}>{boundCount}/{agentNodeIds.length}</dd>
        <dt className={styles.label}>{isZh ? "流程版本" : "Workflow version"}</dt>
        <dd className={styles.valueBreak}>{props.run?.workflowVersionId || (isZh ? "未创建运行" : "No run yet")}</dd>
        <dt className={styles.label}>{isZh ? "运行版本" : "Run version"}</dt>
        <dd className={styles.value}>{props.run?.runVersion ?? "—"}</dd>
      </dl>
      {blockers.length ? (
        <section>
          <h4 className={styles.sectionTitle}>{isZh ? "当前阻塞" : "Current blockers"}</h4>
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
        <VRouteLinkButton to={roomRoute} variant="secondary">
          {scopedQuestionId
            ? (isZh ? "打开本题讨论" : "Open question discussion")
            : (isZh ? "打开团队讨论" : "Open team chat")}
        </VRouteLinkButton>
      ) : (
        <div className={styles.roomMissing} role="status">
          {scopedQuestionId
            ? (isZh ? "当前题目没有可打开的活动讨论" : "No active discussion is available for this question")
            : (isZh ? "团队尚未关联讨论会话" : "No chat room is linked to this team yet")}
        </div>
      )}
      {pastDiscussions.length ? (
        <section>
          <h4 className={styles.sectionTitle}>{isZh ? "本题历史讨论" : "Question discussion history"}</h4>
          {pastDiscussions.map((meeting) => (
            <VRouteLinkButton key={meeting.meetingRoundId} variant="secondary" to={teamChatRoomRoute(
              meeting.linkedChatRoomId || "", returnTo,
              isZh ? "返回科研流程" : "Back to research workflow", meeting.meetingRoundId,
            )}>
              {meeting.meetingType === "hypothesis_candidate_generation" ? (isZh ? "候选生成" : "Candidate generation") : (isZh ? "假说评审" : "Hypothesis review")}
              {` · ${isZh ? "第 " : "Round "}${(meeting.roundIndex ?? 0) + 1}${isZh ? " 轮" : ""} · ${new Date(meeting.closedAt || meeting.startedAt).toLocaleString(isZh ? "zh-CN" : "en-US", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })}`}
            </VRouteLinkButton>
          ))}
        </section>
      ) : null}
    </VSurface>
  );
}
