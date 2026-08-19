/**
 * Inspector summary for hypothesis-first region cards (HFC-4).
 *
 * Region cards are display-layer constructs without a backend node detail, so
 * this panel reads the shared hypothesis-first chain query cache and offers a
 * deep link into the matching question-detail panel (selection / meeting
 * rounds / hypothesis timeline).
 */
import {
  VButton,
  VEmptyState,
  VStateRow,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import { useHypothesisFirstChain } from "./useHypothesisFirstChain";
import styles from "./HypothesisFirstNodeInspector.styles";

export type HypothesisFirstNodeInspectorProps = {
  teamId: string;
  questionId: string;
  nodeId: string;
  onOpenQuestion: (questionId: string) => void;
};

const MEETING_STATUS_LABEL: Record<string, string> = {
  open: "讨论进行中",
  summarizing: "纪要整理中",
  awaiting_approval: "等待人工确认闭环",
  closed: "已关闭",
};

const COLLECTION_STATUS_LABEL: Record<string, string> = {
  pending: "等待搜集完成",
  running: "搜集中",
  collecting: "搜集中",
  handed_off: "已交接",
  failed: "搜集失败",
};

function formatTime(value: string | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
}

export function HypothesisFirstNodeInspector({
  teamId,
  questionId,
  nodeId,
  onOpenQuestion,
}: HypothesisFirstNodeInspectorProps) {
  const chain = useHypothesisFirstChain(teamId, questionId);

  if (!questionId) {
    return <VEmptyState title="缺少题目上下文">该卡片需要题目上下文才能展示链摘要。</VEmptyState>;
  }
  if (chain.loading) {
    return <VStateSurface tone="loading" title="加载假说先行链" fill className={styles.fill} />;
  }
  if (chain.error) {
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-error">
        <div role="alert">假说先行链加载失败：{chain.error}</div>
      </VSurface>
    );
  }

  const openQuestion = (
    <VButton type="button" onClick={() => onOpenQuestion(questionId)}>
      打开赛题详情
    </VButton>
  );

  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) {
    const generation = chain.meetings.find(
      (item) => item.meetingType === "hypothesis_candidate_generation",
    );
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
        <header>
          <div className={styles.stage}>假说先行</div>
          <h3 className={styles.title}>候选假说生成</h3>
        </header>
        <div className={styles.facts}>
          <VStateRow tone={generation?.status === "closed" ? "success" : "accent"}>
            状态：{generation ? (MEETING_STATUS_LABEL[generation.status] ?? generation.status) : "未找到生成讨论"}
          </VStateRow>
          <VStateRow>已产出候选：{chain.chainState?.candidateCount ?? 0} 条</VStateRow>
          {generation ? (
            <VStateRow>开始时间：{formatTime(generation.startedAt)}</VStateRow>
          ) : null}
        </div>
        <p className={styles.description}>团队讨论产出候选假说，闭环后即可在赛题详情中人工选择。</p>
        <div className={styles.actions}>{openQuestion}</div>
      </VSurface>
    );
  }

  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) {
    const selection = chain.selection;
    const candidateCount = chain.chainState?.candidateCount ?? 0;
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
        <header>
          <div className={styles.stage}>假说先行</div>
          <h3 className={styles.title}>假说选择</h3>
        </header>
        <div className={styles.facts}>
          <VStateRow tone={selection ? "success" : candidateCount > 0 ? "warning" : "neutral"}>
            {selection
              ? "已完成人工选择"
              : candidateCount > 0
                ? `已产出 ${candidateCount} 条候选，等待人工选择`
                : "等待候选假说生成"}
          </VStateRow>
          {selection ? (
            <>
              <VStateRow>已选候选：{selection.selectedCandidateIds.length} 个</VStateRow>
              <VStateRow>决策人：{selection.decidedBy || "—"}</VStateRow>
              <VStateRow>选择时间：{formatTime(selection.createdAt)}</VStateRow>
            </>
          ) : null}
        </div>
        <p className={styles.description}>在赛题详情的选择面板中查看候选详情或调整选择。</p>
        <div className={styles.actions}>{openQuestion}</div>
      </VSurface>
    );
  }

  if (nodeId.startsWith("hf_meeting_")) {
    const roundIndex = Number(nodeId.slice("hf_meeting_".length));
    const meeting = chain.meetings.find(
      (item) => item.meetingType === "hypothesis_review" && (item.roundIndex ?? 0) === roundIndex,
    );
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
        <header>
          <div className={styles.stage}>假说先行</div>
          <h3 className={styles.title}>第 {roundIndex} 轮讨论·评审</h3>
        </header>
        <div className={styles.facts}>
          <VStateRow tone={meeting?.status === "closed" ? (meeting.digestRef ? "success" : "danger") : "accent"}>
            状态：{meeting ? (MEETING_STATUS_LABEL[meeting.status] ?? meeting.status) : "未找到会议记录"}
          </VStateRow>
          {meeting ? (
            <>
              <VStateRow>参与 Agent：{meeting.participants.length} 个</VStateRow>
              <VStateRow>开始时间：{formatTime(meeting.startedAt)}</VStateRow>
              {meeting.closedAt ? <VStateRow>闭环时间：{formatTime(meeting.closedAt)}</VStateRow> : null}
              <VStateRow>纪要：{meeting.digestRef ? "已生成" : "未生成"}</VStateRow>
            </>
          ) : null}
        </div>
        <p className={styles.description}>在赛题详情的团队讨论面板中查看讨论记录、纪要与决策。</p>
        <div className={styles.actions}>{openQuestion}</div>
      </VSurface>
    );
  }

  if (nodeId.startsWith("hf_collection_")) {
    const requestId = nodeId.slice("hf_collection_".length);
    const request = chain.collectionRequests.find((item) => item.requestId === requestId);
    const envelopeText = request ? JSON.stringify(request.searchEnvelope, null, 2) : "";
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
        <header>
          <div className={styles.stage}>假说先行</div>
          <h3 className={styles.title}>资料搜集</h3>
        </header>
        <div className={styles.facts}>
          <VStateRow tone={request?.status === "handed_off" || request?.handoffRef ? "success" : "accent"}>
            状态：{request ? (COLLECTION_STATUS_LABEL[request.status] ?? request.status) : "未找到搜集请求"}
          </VStateRow>
          {request ? (
            <>
              <VStateRow>搜集子运行：{request.collectionRunId || "—"}</VStateRow>
              <VStateRow>交接：{request.handoffRef ? `已完成（${request.handoffRef}）` : "未交接"}</VStateRow>
              <VStateRow>发起时间：{formatTime(request.createdAt)}</VStateRow>
            </>
          ) : null}
        </div>
        {envelopeText && envelopeText !== "{}" ? (
          <pre className={styles.envelope} data-vui="hypothesis-first-search-envelope">{envelopeText}</pre>
        ) : null}
        <p className={styles.description}>在赛题详情的团队讨论面板中查看搜集决策与知识包交接。</p>
        <div className={styles.actions}>{openQuestion}</div>
      </VSurface>
    );
  }

  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) {
    const state = chain.chainState;
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
        <header>
          <div className={styles.stage}>假说先行</div>
          <h3 className={styles.title}>假说收敛门</h3>
        </header>
        <div className={styles.facts}>
          <VStateRow tone={state?.hypothesisConverged ? "success" : state?.budgetExhausted ? "danger" : "neutral"}>
            {state?.hypothesisConverged
              ? "假说集已收敛"
              : state?.budgetExhausted
                ? "轮次预算耗尽，等待人工决策"
                : "待收敛"}
          </VStateRow>
          {state ? (
            <>
              <VStateRow>讨论轮次：{state.meetingCount} / 预算 {state.roundBudget}</VStateRow>
              <VStateRow>假说评审轮次：{state.hypothesisRoundCount}</VStateRow>
            </>
          ) : null}
          {state?.convergenceDetail ? <VStateRow>{state.convergenceDetail}</VStateRow> : null}
        </div>
        <p className={styles.description}>在赛题详情的假说轮次时间线中查看评审过程与收敛依据。</p>
        <div className={styles.actions}>{openQuestion}</div>
      </VSurface>
    );
  }

  return <VEmptyState title="未知的假说先行卡片" />;
}
