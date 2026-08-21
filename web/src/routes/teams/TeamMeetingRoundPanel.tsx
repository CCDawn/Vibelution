import { useQuery } from "@tanstack/react-query";

import {
  fetchHypothesisSelectionContext,
  fetchMeetingRound,
  fetchMeetingRoundSourceMessages,
} from "../../api/hypothesisFirst";
import { queryKeys } from "../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../app/pollingPolicy";
import {
  VEmptyState,
  VStateSurface,
} from "../../components/vui";
import { MeetingRoundDisplay } from "./meetingRoundDisplay";
import css from "./TeamMeetingRoundPanel.styles";

export type TeamMeetingRoundPanelProps = {
  teamId: string;
  questionId: string;
};

export function TeamMeetingRoundPanel({ teamId, questionId }: TeamMeetingRoundPanelProps) {
  const contextQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
    queryFn: () => fetchHypothesisSelectionContext(teamId, questionId),
    enabled: Boolean(teamId && questionId),
    staleTime: 15_000,
  });
  const review = contextQuery.data?.reviewMeeting;
  const generation = contextQuery.data?.generationMeeting;
  // Mirror the next-action model: a live (non-closed) meeting wins over an
  // older closed review so a reopened generation stays visible.
  const liveMeetingId = [generation, review]
    .filter((item): item is NonNullable<typeof item> =>
      Boolean(item?.meetingRoundId) && item?.status !== "closed")
    .map((item) => item.meetingRoundId)[0] ?? "";
  const meetingRoundId = liveMeetingId || review?.meetingRoundId || generation?.meetingRoundId || "";

  const pageVisible = usePageVisibility();
  const roundQuery = useQuery({
    queryKey: queryKeys.teamMeetingRound(teamId, meetingRoundId),
    queryFn: () => fetchMeetingRound(teamId, meetingRoundId),
    enabled: Boolean(teamId && meetingRoundId),
    refetchInterval: (query) => {
      const status = query.state.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing"
        ? resolvePollingInterval(pageVisible, 5_000)
        : false;
    },
  });
  const messagesQuery = useQuery({
    queryKey: queryKeys.teamMeetingRoundSourceMessages(teamId, meetingRoundId),
    queryFn: () => fetchMeetingRoundSourceMessages(teamId, meetingRoundId),
    enabled: Boolean(teamId && meetingRoundId),
    refetchInterval: () => {
      const status = roundQuery.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing"
        ? resolvePollingInterval(pageVisible, 5_000)
        : false;
    },
  });

  if (contextQuery.isPending) {
    return (
      <section className={css.section} id="hypothesis-first-meeting">
        <VStateSurface title="正在解析讨论入口" tone="loading" />
      </section>
    );
  }
  if (contextQuery.isError) {
    return (
      <section className={css.section} id="hypothesis-first-meeting">
        <VEmptyState title="讨论入口读取失败">
          <p className={css.hint}>请稍后重试。</p>
          <button type="button" className={css.hint} onClick={() => void contextQuery.refetch()}>
            重试
          </button>
        </VEmptyState>
      </section>
    );
  }
  if (!meetingRoundId) {
    return (
      <section className={css.section} id="hypothesis-first-meeting">
        <VEmptyState title="尚未开启讨论">
          <p className={css.hint}>候选生成或记录假说选择后，系统会开启对应讨论。</p>
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

  return (
    <section className={css.section} id="hypothesis-first-meeting">
      <MeetingRoundDisplay
        round={roundQuery.data.meetingRound}
        messages={messagesQuery.data?.messages ?? []}
      />
    </section>
  );
}
