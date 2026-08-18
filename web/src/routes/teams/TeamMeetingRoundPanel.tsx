import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  closeHypothesisReviewMeeting,
  fetchHypothesisSelectionContext,
  fetchMeetingRound,
  fetchMeetingRoundSourceMessages,
} from "../../api/hypothesisFirst";
import { queryKeys } from "../../api/queryKeys";
import type {
  MeetingClosureApprovePayload,
  MeetingDigestDraft,
  MeetingRoundRecord,
  MeetingSourceMessage,
} from "../../api/types";
import {
  VButton,
  VConfirmDialog,
  VEmptyState,
  VErrorSummary,
  VStateSurface,
  VStatusChip,
} from "../../components/vui";
import type { VStatusTone } from "../../components/vui";
import css from "./TeamMeetingRoundPanel.styles";

export type TeamMeetingRoundPanelProps = {
  teamId: string;
  questionId: string;
};

const STATUS_LABELS: Record<string, string> = {
  open: "讨论中",
  summarizing: "纪要生成中",
  awaiting_approval: "待人工确认",
  closed: "已关门",
};

function statusTone(status: string): VStatusTone {
  if (status === "closed") return "success";
  if (status === "awaiting_approval") return "warning";
  if (status === "open" || status === "summarizing") return "accent";
  return "neutral";
}

function candidateRefsFromRound(round: MeetingRoundRecord): string[] {
  return (round.discussionItemRefs ?? [])
    .filter((ref) => ref.startsWith("hypothesis_candidate:"))
    .map((ref) => ref.slice("hypothesis_candidate:".length))
    .filter(Boolean);
}

function markerText(value: Record<string, unknown>): string {
  const issue = value.issue;
  const action = value.action;
  if (typeof issue === "string" && issue.trim()) return issue;
  if (typeof action === "string" && action.trim()) return action;
  return JSON.stringify(value);
}

function DigestDraftView({ draft }: { draft: MeetingDigestDraft }) {
  const agreements = draft.agreements ?? [];
  const disagreements = draft.disagreements ?? [];
  const actionItems = draft.actionItems ?? [];
  const knowledgeCandidates = draft.knowledgeCandidates ?? [];
  return (
    <div className={css.digestGrid} data-testid="meeting-digest-draft">
      <article className={css.digestCard}>
        <span>纪要摘要</span>
        <p>{draft.summary || draft.agendaSummary || "（空）"}</p>
      </article>
      <article className={css.digestCard}>
        <span>共识（{agreements.length}）</span>
        <ul className={css.digestList}>
          {agreements.map((item, index) => (
            <li key={`agreement-${index}`}>{item}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>分歧（{disagreements.length}）</span>
        <ul className={css.digestList}>
          {disagreements.map((item, index) => (
            <li key={`disagreement-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>行动项（{actionItems.length}）</span>
        <ul className={css.digestList}>
          {actionItems.map((item, index) => (
            <li key={`action-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>知识候选（{knowledgeCandidates.length}）</span>
        <ul className={css.digestList}>
          {knowledgeCandidates.map((item, index) => (
            <li key={`knowledge-${index}`}>{item}</li>
          ))}
        </ul>
      </article>
    </div>
  );
}

function MessageList({ messages }: { messages: MeetingSourceMessage[] }) {
  if (!messages.length) {
    return <p className={css.hint}>房间内尚无讨论消息。</p>;
  }
  return (
    <div className={css.messageList} data-testid="meeting-source-messages">
      {messages.map((message, index) => (
        <article className={css.messageCard} key={message.messageId || `message-${index}`}>
          <div className={css.messageMeta}>
            <span>{message.agentId || "unknown"}</span>
            {message.role ? <span>{message.role}</span> : null}
            <span>{message.createdAt || "—"}</span>
          </div>
          <p>{message.content}</p>
        </article>
      ))}
    </div>
  );
}

export function TeamMeetingRoundPanel({ teamId, questionId }: TeamMeetingRoundPanelProps) {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const contextQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
    queryFn: () => fetchHypothesisSelectionContext(teamId, questionId),
    enabled: Boolean(teamId && questionId),
    staleTime: 15_000,
  });
  const meetingRoundId = contextQuery.data?.reviewMeeting?.meetingRoundId ?? "";

  const roundQuery = useQuery({
    queryKey: queryKeys.teamMeetingRound(teamId, meetingRoundId),
    queryFn: () => fetchMeetingRound(teamId, meetingRoundId),
    enabled: Boolean(teamId && meetingRoundId),
    refetchInterval: (query) => {
      const status = query.state.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing" ? 5_000 : false;
    },
  });
  const messagesQuery = useQuery({
    queryKey: queryKeys.teamMeetingRoundSourceMessages(teamId, meetingRoundId),
    queryFn: () => fetchMeetingRoundSourceMessages(teamId, meetingRoundId),
    enabled: Boolean(teamId && meetingRoundId),
    refetchInterval: () => {
      const status = roundQuery.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing" ? 5_000 : false;
    },
  });

  const closeMutation = useMutation({
    mutationFn: (input: MeetingClosureApprovePayload) =>
      closeHypothesisReviewMeeting(teamId, meetingRoundId, input),
    onSuccess: () => {
      setConfirmOpen(false);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamMeetingRound(teamId, meetingRoundId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamHypothesisRounds(teamId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
      });
    },
  });

  if (contextQuery.isPending) {
    return <VStateSurface title="正在解析评审讨论入口" tone="loading" />;
  }
  if (!meetingRoundId) {
    return (
      <section className={css.section} id="hypothesis-first-meeting">
        <VEmptyState title="尚未开启评审讨论">
          <p className={css.hint}>记录假说选择后，系统会自动开启评审讨论。</p>
        </VEmptyState>
      </section>
    );
  }
  if (roundQuery.isPending) {
    return <VStateSurface title={`正在读取会议轮次 ${meetingRoundId}`} tone="loading" />;
  }
  if (roundQuery.isError || !roundQuery.data) {
    return (
      <VEmptyState title="会议轮次不可用">
        {roundQuery.error instanceof Error ? <code>{roundQuery.error.message}</code> : null}
      </VEmptyState>
    );
  }

  const round = roundQuery.data.meetingRound;
  const status = round.status;
  const digestDraft = round.digestDraft;
  const messages = messagesQuery.data?.messages ?? [];

  const confirmClosure = () => {
    const candidateRefs = candidateRefsFromRound(round);
    closeMutation.mutate({
      closedBy: "operator",
      decisions: [
        {
          decision: "select_candidate",
          rationale: digestDraft?.summary || digestDraft?.agendaSummary || "确认评审结论",
          decidedBy: "operator",
          candidateRefs,
          evidenceRefs: [],
          status: "adopted",
        },
      ],
    });
  };

  return (
    <section className={css.section} id="hypothesis-first-meeting">
      <div className={css.heading}>
        <div>
          <h3>评审讨论</h3>
          <p>
            {round.meetingRoundId} · 参与者 {round.participants.length} 人 · 房间{" "}
            {round.linkedChatRoomId || "—"}
          </p>
        </div>
        <div className={css.headingActions}>
          <VStatusChip tone={statusTone(status)} data-testid="meeting-round-status">
            {STATUS_LABELS[status] ?? status}
          </VStatusChip>
        </div>
      </div>

      {(round.agendaQuestions ?? []).length ? (
        <article className={css.digestCard}>
          <span>议程序列</span>
          <ul className={css.digestList}>
            {(round.agendaQuestions ?? []).map((question, index) => (
              <li key={`agenda-${index}`}>{question}</li>
            ))}
          </ul>
        </article>
      ) : null}

      <MessageList messages={messages} />

      {digestDraft ? <DigestDraftView draft={digestDraft} /> : null}

      {(round.decisionRefs ?? []).length ? (
        <article className={css.digestCard}>
          <span>决策记录（{(round.decisionRefs ?? []).length}）</span>
          <div className={css.decisionList}>
            {(round.decisionRefs ?? []).map((ref) => (
              <div key={ref}>
                <code>{ref}</code>
              </div>
            ))}
          </div>
        </article>
      ) : null}

      {status === "closed" ? (
        <p className={css.hint}>
          已于 {round.closedAt || "—"} 由 {round.closedBy || "unknown"} 确认关门。
        </p>
      ) : null}

      {closeMutation.isError ? (
        <VErrorSummary
          label="关门确认失败"
          summary={
            closeMutation.error instanceof Error
              ? closeMutation.error.message
              : "close_review_meeting_failed"
          }
        />
      ) : null}

      {status === "awaiting_approval" ? (
        <div className={css.actions}>
          <VButton
            density="compact"
            onPress={() => setConfirmOpen(true)}
            variant="primary"
          >
            人工确认关门
          </VButton>
        </div>
      ) : null}

      <VConfirmDialog
        confirmLabel="确认关门"
        confirmPending={closeMutation.isPending}
        description="确认后会议关门，纪要固化为 artifact，并生成假说评审轮次。"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={confirmClosure}
        onOpenChange={setConfirmOpen}
        open={confirmOpen}
        title="确认关门本次评审讨论？"
      />
    </section>
  );
}
