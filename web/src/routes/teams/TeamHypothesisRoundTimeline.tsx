import { useQuery } from "@tanstack/react-query";

import { fetchHypothesisRounds } from "../../api/hypothesisFirst";
import { queryKeys } from "../../api/queryKeys";
import type {
  HypothesisLineageRef,
  HypothesisRoundCandidate,
  HypothesisRoundRecord,
} from "../../api/types";
import {
  VEmptyState,
  VStateSurface,
  VStatusChip,
} from "../../components/vui";
import type { VStatusTone } from "../../components/vui";
import css from "./TeamHypothesisRoundTimeline.styles";

export type TeamHypothesisRoundTimelineProps = {
  teamId: string;
  questionId: string;
};

const SCORE_DIMENSION_LABELS: Record<string, string> = {
  novelty: "新颖性",
  competitionFit: "竞赛契合",
  falsifiability: "可证伪性",
  evidenceSupport: "证据支撑",
  feasibility: "可行性",
  replicability: "可复现性",
  scopeAlignment: "范围对齐",
};

const ROUND_STATUS_LABELS: Record<string, string> = {
  open: "进行中",
  reviewed: "已评审",
  closed: "已关闭",
};

function roundStatusTone(status: string): VStatusTone {
  if (status === "closed") return "success";
  if (status === "reviewed") return "accent";
  if (status === "open") return "warning";
  return "neutral";
}

function lineageLabel(ref: HypothesisLineageRef, roundIndex: number): string {
  if (ref.kind === "round") return `前轮 ${ref.id}`;
  if (ref.kind === "baseline") return `基线 ${ref.id}`;
  if (roundIndex === 0) return `赛题候选 ${ref.id}`;
  return `候选 ${ref.id}`;
}

function CandidateRow({ candidate }: { candidate: HypothesisRoundCandidate }) {
  const scoreEntries = Object.entries(candidate.scores ?? {});
  return (
    <div className={css.candidateRow} data-testid="hypothesis-round-candidate">
      <div className={css.candidateHead}>
        <strong>{candidate.candidateId}</strong>
        <small>{candidate.status}</small>
      </div>
      {candidate.claim ? <p className={css.hint}>{candidate.claim}</p> : null}
      {scoreEntries.length ? (
        <div className={css.scoreGrid}>
          {scoreEntries.map(([dimension, score]) => (
            <div key={dimension}>
              <span>{SCORE_DIMENSION_LABELS[dimension] ?? dimension}</span>
              <strong>{score}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RoundCard({ round, roundIndex }: { round: HypothesisRoundRecord; roundIndex: number }) {
  const paretoFront = round.pareto?.paretoFrontCandidateIds ?? [];
  const metaReview = round.metaReview;
  return (
    <article className={css.roundCard} data-testid="hypothesis-round-card">
      <div className={css.roundTopline}>
        <div className={css.roundTitle}>
          <strong>第 {roundIndex + 1} 轮</strong>
          <VStatusChip tone={roundStatusTone(round.status)}>
            {ROUND_STATUS_LABELS[round.status] ?? round.status}
          </VStatusChip>
        </div>
        <div className={css.roundMeta}>
          <span>{round.roundId}</span>
          <span>{round.createdAt || "—"}</span>
        </div>
      </div>

      <div className={css.lineage} data-testid="hypothesis-round-lineage">
        <span>lineage：</span>
        {(round.lineage ?? []).length ? (
          round.lineage.map((ref, index) => (
            <code key={`${ref.kind}-${ref.id}-${index}`}>{lineageLabel(ref, roundIndex)}</code>
          ))
        ) : (
          <code>赛题候选</code>
        )}
      </div>

      <div className={css.candidateList}>
        {(round.candidates ?? []).map((candidate) => (
          <CandidateRow candidate={candidate} key={candidate.candidateId} />
        ))}
      </div>

      {paretoFront.length ? (
        <div className={css.reviewCard}>
          <span>Pareto 前沿</span>
          <p>{paretoFront.join("、")}</p>
          {round.pareto?.notes ? <p>{round.pareto.notes}</p> : null}
        </div>
      ) : null}

      {metaReview ? (
        <div className={css.reviewCard} data-testid="hypothesis-round-metareview">
          <span>MetaReview {metaReview.accepted ? "（已接受）" : "（未接受）"}</span>
          <p>
            推荐 {metaReview.recommendationCandidateId || "—"} · {metaReview.rationale || "—"}
          </p>
          {metaReview.riskNotes ? <p>风险：{metaReview.riskNotes}</p> : null}
        </div>
      ) : null}
    </article>
  );
}

export function TeamHypothesisRoundTimeline({ teamId, questionId }: TeamHypothesisRoundTimelineProps) {
  const roundsQuery = useQuery({
    queryKey: queryKeys.teamHypothesisRounds(teamId),
    queryFn: () => fetchHypothesisRounds(teamId),
    enabled: Boolean(teamId),
    staleTime: 15_000,
  });

  if (roundsQuery.isPending) {
    return <VStateSurface title="正在读取假说评审轮次" tone="loading" />;
  }
  if (roundsQuery.isError || !roundsQuery.data) {
    return (
      <VEmptyState title="假说评审轮次不可用">
        {roundsQuery.error instanceof Error ? <code>{roundsQuery.error.message}</code> : null}
      </VEmptyState>
    );
  }

  const normalizedQuestionId = questionId.trim().toUpperCase();
  const rounds = (roundsQuery.data.rounds ?? [])
    .filter((round) => String(round.question ?? "").toUpperCase() === normalizedQuestionId)
    .sort((a, b) => String(a.createdAt ?? "").localeCompare(String(b.createdAt ?? "")));

  return (
    <section className={css.section} id="hypothesis-first-rounds">
      <div className={css.heading}>
        <div>
          <h3>假说评审轮次</h3>
          <p>首轮源自赛题候选，后续轮次源自前轮 lineage。</p>
        </div>
      </div>
      {rounds.length ? (
        <div className={css.timeline}>
          {rounds.map((round, index) => (
            <RoundCard key={round.roundId} round={round} roundIndex={index} />
          ))}
        </div>
      ) : (
        <p className={css.hint}>尚未生成评审轮次；会议关门后自动生成。</p>
      )}
    </section>
  );
}
