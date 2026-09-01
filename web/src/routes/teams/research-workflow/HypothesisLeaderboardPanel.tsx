/**
 * Challenge-cup hypothesis leaderboard (read-only inspector panel).
 *
 * Aggregates the team-level hypothesis review rounds behind the existing
 * `GET /workflow-orchestration/hypothesis-rounds` endpoint into a per-round
 * leaderboard. The review executor deliberately produces no Elo-style total
 * score, so this panel never ranks by one: the presentation order is
 * MetaReview recommendation → Pareto front → pairwise win record →
 * candidate id, and every candidate carries its five independent scores
 * (plus the two auxiliary diagnostics when present), its pairwise record,
 * its Pareto badge and its expandable seven-dimension review card.
 *
 * Wire parsing is fail-closed: malformed rounds / candidates / comparisons /
 * review rows are dropped instead of crashing the panel. Composes existing
 * VUI atoms only.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { fetchHypothesisRounds } from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type { HypothesisRoundListResponse } from "../../../api/types/hypothesisFirst";
import type { ChallengeQuestionDimensionReview } from "../../../api/types/teams";
import {
  VButton,
  VChip,
  VEmptyState,
  VErrorSummary,
  VSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import type { VStatusTone } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  challengeDimensionLabel,
  challengeRatingLabel,
} from "../challenge-cup/ChallengeQuestionDetailPrimitives";
import styles from "./HypothesisLeaderboardPanel.styles";

export type HypothesisLeaderboardPanelProps = {
  teamId: string;
  questionId: string;
  lang?: "zh" | "en";
};

// ---------------------------------------------------------------------------
// Bilingual labels (score dimensions are the executor's 5+2 axis set; the
// seven audit dimensions of the review card reuse the shared
// challengeDimensionLabel mapping — no third copy of it here).
// ---------------------------------------------------------------------------

const SCORE_DIMENSION_LABELS: Record<string, { zh: string; en: string }> = {
  novelty: { zh: "新颖性", en: "Novelty" },
  competitionFit: { zh: "竞赛契合", en: "Competition fit" },
  falsifiability: { zh: "可证伪性", en: "Falsifiability" },
  evidenceSupport: { zh: "证据支撑", en: "Evidence support" },
  feasibility: { zh: "可行性", en: "Feasibility" },
  replicability: { zh: "可复现性", en: "Replicability" },
  scopeAlignment: { zh: "范围对齐", en: "Scope alignment" },
};
const SCORE_DIMENSION_ORDER = [
  "novelty",
  "competitionFit",
  "falsifiability",
  "evidenceSupport",
  "feasibility",
  "replicability",
  "scopeAlignment",
];
const DIAGNOSTIC_DIMENSIONS = new Set(["replicability", "scopeAlignment"]);

const ROUND_STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  open: { zh: "进行中", en: "In progress" },
  reviewed: { zh: "已评审", en: "Reviewed" },
  closed: { zh: "已关闭", en: "Closed" },
};

const OUTCOME_LABELS: Record<string, { zh: string; en: string }> = {
  left_wins: { zh: "左方胜", en: "left wins" },
  right_wins: { zh: "右方胜", en: "right wins" },
  tie: { zh: "平局", en: "tie" },
};

const RATING_KEYS = new Set(["insufficient", "weak", "mixed", "adequate", "strong"]);

// ---------------------------------------------------------------------------
// Fail-closed wire parsing helpers
// ---------------------------------------------------------------------------

type RecordLike = Record<string, unknown>;

function asRecord(value: unknown): RecordLike {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordLike)
    : {};
}
function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}
function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function asStringList(value: unknown): string[] {
  return asArray(value)
    .map((item) => (typeof item === "string" ? item : ""))
    .filter((item) => item.length > 0);
}

// ---------------------------------------------------------------------------
// View model
// ---------------------------------------------------------------------------

export type LeaderboardScoreEntry = { dimension: string; value: number };

export type LeaderboardComparisonView = {
  comparisonId: string;
  opponentCandidateId: string;
  outcome: "win" | "loss" | "tie";
  outcomeKey: string;
  reviewerAgentId: string;
  justification: string;
};

export type LeaderboardDimensionReviewView = {
  dimension: string;
  rating: string;
  rationale: string;
  evidenceRefs: string[];
  reviewer: string;
};

export type LeaderboardCandidateView = {
  candidateId: string;
  claim: string;
  rationale: string;
  differenceFromAlternatives: string;
  status: string;
  reviewedBy: string;
  scores: LeaderboardScoreEntry[];
  diagnostics: LeaderboardScoreEntry[];
  wins: number;
  losses: number;
  ties: number;
  comparisons: LeaderboardComparisonView[];
  isParetoFront: boolean;
  isDominated: boolean;
  isRecommended: boolean;
  dimensionReviews: LeaderboardDimensionReviewView[];
};

export type LeaderboardRoundView = {
  roundId: string;
  status: string;
  question: string;
  createdAt: string;
  closedAt: string;
  /** 1-based position in chronological order (first round = 1). */
  displayIndex: number;
  paretoFrontCandidateIds: string[];
  dominatedCandidateIds: string[];
  paretoNotes: string;
  metaReview: {
    reviewerAgentId: string;
    recommendationCandidateId: string;
    rationale: string;
    riskNotes: string;
    accepted: boolean;
  } | null;
  candidates: LeaderboardCandidateView[];
};

export type HypothesisLeaderboardModel = {
  rounds: LeaderboardRoundView[];
  /** True when the wire carries no question scope at all, so the whole
   * team ledger is shown with an explicit scope annotation. */
  scopeFallback: boolean;
  quarantinedCount: number;
};

function parseScoreEntries(raw: unknown): LeaderboardScoreEntry[] {
  const record = asRecord(raw);
  const entries: LeaderboardScoreEntry[] = [];
  for (const dimension of SCORE_DIMENSION_ORDER) {
    const value = asFiniteNumber(record[dimension]);
    if (value !== null) entries.push({ dimension, value });
  }
  // Unknown extra axes still surface (raw key) instead of being hidden.
  for (const [dimension, value] of Object.entries(record)) {
    if (SCORE_DIMENSION_ORDER.includes(dimension)) continue;
    const numeric = asFiniteNumber(value);
    if (numeric !== null) entries.push({ dimension, value: numeric });
  }
  return entries;
}

function parseDimensionReviews(raw: unknown): LeaderboardDimensionReviewView[] {
  const rows: LeaderboardDimensionReviewView[] = [];
  for (const rawRow of asArray(raw)) {
    const row = asRecord(rawRow);
    const dimension = asText(row.dimension).trim();
    if (!dimension) continue;
    rows.push({
      dimension,
      rating: asText(row.rating) || "insufficient",
      rationale: asText(row.rationale),
      evidenceRefs: asStringList(row.evidence_refs),
      reviewer: asText(row.reviewer),
    });
  }
  return rows;
}

function outcomeFromPerspective(outcomeKey: string, side: "left" | "right"): "win" | "loss" | "tie" {
  if (outcomeKey === "tie") return "tie";
  const winningSide = outcomeKey === "left_wins" ? "left" : outcomeKey === "right_wins" ? "right" : "";
  if (!winningSide) return "tie";
  return winningSide === side ? "win" : "loss";
}

function parseComparisons(rawComparisons: unknown): Array<{
  comparisonId: string;
  leftCandidateId: string;
  rightCandidateId: string;
  reviewerAgentId: string;
  outcomeKey: string;
  justification: string;
}> {
  const parsed = [];
  for (const raw of asArray(rawComparisons)) {
    const record = asRecord(raw);
    const leftCandidateId = asText(record.leftCandidateId).trim();
    const rightCandidateId = asText(record.rightCandidateId).trim();
    const outcomeKey = asText(record.outcome).trim();
    if (!leftCandidateId || !rightCandidateId) continue;
    if (!["left_wins", "right_wins", "tie"].includes(outcomeKey)) continue;
    parsed.push({
      comparisonId: asText(record.comparisonId),
      leftCandidateId,
      rightCandidateId,
      reviewerAgentId: asText(record.reviewerAgentId),
      outcomeKey,
      justification: asText(record.justification),
    });
  }
  return parsed;
}

/**
 * Presentation order only — never a total score: recommendation first,
 * then the Pareto front, then the pairwise win record, then candidate id.
 */
function compareCandidates(a: LeaderboardCandidateView, b: LeaderboardCandidateView): number {
  if (a.isRecommended !== b.isRecommended) return a.isRecommended ? -1 : 1;
  if (a.isParetoFront !== b.isParetoFront) return a.isParetoFront ? -1 : 1;
  if (a.wins !== b.wins) return b.wins - a.wins;
  if (a.losses !== b.losses) return a.losses - b.losses;
  return a.candidateId.localeCompare(b.candidateId);
}

function parseLeaderboardRound(raw: unknown, displayIndex: number): LeaderboardRoundView | null {
  const round = asRecord(raw);
  const roundId = asText(round.roundId).trim();
  if (!roundId) return null;

  const comparisons = parseComparisons(round.pairwiseComparisons);
  const pareto = asRecord(round.pareto);
  const paretoFrontCandidateIds = asStringList(pareto.paretoFrontCandidateIds);
  const dominatedCandidateIds = asStringList(pareto.dominatedCandidateIds);
  const paretoFront = new Set(paretoFrontCandidateIds);
  const dominated = new Set(dominatedCandidateIds);

  const rawMetaReview = round.metaReview;
  const metaReviewRecord = asRecord(rawMetaReview);
  const metaReview = rawMetaReview && asText(metaReviewRecord.recommendationCandidateId).trim()
    ? {
      reviewerAgentId: asText(metaReviewRecord.reviewerAgentId),
      recommendationCandidateId: asText(metaReviewRecord.recommendationCandidateId).trim(),
      rationale: asText(metaReviewRecord.rationale),
      riskNotes: asText(metaReviewRecord.riskNotes),
      accepted: metaReviewRecord.accepted === true,
    }
    : null;

  const candidates: LeaderboardCandidateView[] = [];
  for (const rawCandidate of asArray(round.candidates)) {
    const candidate = asRecord(rawCandidate);
    const candidateId = asText(candidate.candidateId).trim();
    if (!candidateId) continue;
    const comparisonsView: LeaderboardComparisonView[] = [];
    let wins = 0;
    let losses = 0;
    let ties = 0;
    for (const comparison of comparisons) {
      const side = comparison.leftCandidateId === candidateId
        ? "left"
        : comparison.rightCandidateId === candidateId
          ? "right"
          : null;
      if (!side) continue;
      const outcome = outcomeFromPerspective(comparison.outcomeKey, side);
      if (outcome === "win") wins += 1;
      else if (outcome === "loss") losses += 1;
      else ties += 1;
      comparisonsView.push({
        comparisonId: comparison.comparisonId,
        opponentCandidateId: side === "left" ? comparison.rightCandidateId : comparison.leftCandidateId,
        outcome,
        outcomeKey: comparison.outcomeKey,
        reviewerAgentId: comparison.reviewerAgentId,
        justification: comparison.justification,
      });
    }
    const allScores = parseScoreEntries(candidate.scores);
    candidates.push({
      candidateId,
      claim: asText(candidate.claim),
      rationale: asText(candidate.rationale),
      differenceFromAlternatives: asText(candidate.differenceFromAlternatives),
      status: asText(candidate.status),
      reviewedBy: asText(candidate.reviewedBy),
      scores: allScores.filter((entry) => !DIAGNOSTIC_DIMENSIONS.has(entry.dimension)),
      diagnostics: allScores.filter((entry) => DIAGNOSTIC_DIMENSIONS.has(entry.dimension)),
      wins,
      losses,
      ties,
      comparisons: comparisonsView,
      isParetoFront: paretoFront.has(candidateId),
      isDominated: dominated.has(candidateId),
      isRecommended: metaReview?.recommendationCandidateId === candidateId,
      dimensionReviews: parseDimensionReviews(candidate.dimensionReviews),
    });
  }
  candidates.sort(compareCandidates);

  return {
    roundId,
    status: asText(round.status),
    question: asText(round.question),
    createdAt: asText(round.createdAt),
    closedAt: asText(round.closedAt),
    displayIndex,
    paretoFrontCandidateIds,
    dominatedCandidateIds,
    paretoNotes: asText(pareto.notes),
    metaReview,
    candidates,
  };
}

/** Fail-closed payload → per-round leaderboard views (chronological). */
export function buildHypothesisLeaderboardModel(
  payload: HypothesisRoundListResponse | null | undefined,
  questionId: string,
): HypothesisLeaderboardModel {
  const rawRounds = asArray(asRecord(payload).rounds);
  const rounds: LeaderboardRoundView[] = [];
  for (const raw of rawRounds) {
    const round = parseLeaderboardRound(raw, 0);
    if (round) rounds.push(round);
  }
  rounds.sort((a, b) =>
    (a.createdAt || "").localeCompare(b.createdAt || "") || a.roundId.localeCompare(b.roundId),
  );
  rounds.forEach((round, index) => {
    round.displayIndex = index + 1;
  });

  const normalizedQuestionId = questionId.trim().toUpperCase();
  let visible = rounds;
  let scopeFallback = false;
  if (normalizedQuestionId) {
    const matching = rounds.filter(
      (round) => round.question.trim().toUpperCase() === normalizedQuestionId,
    );
    if (matching.length > 0) {
      visible = matching;
    } else {
      const scopeCarrying = rounds.filter((round) => round.question.trim().length > 0);
      if (scopeCarrying.length === 0) {
        // The wire carries no question scope at all; show the team ledger
        // with an explicit annotation instead of an empty board.
        scopeFallback = true;
      } else {
        visible = [];
      }
    }
  }

  const quarantined = asFiniteNumber(asRecord(payload).corruptQuarantinedLineCount) ?? 0;
  return { rounds: visible, scopeFallback, quarantinedCount: quarantined };
}

/** Newest round is the default view; unknown ids fall back to it. */
export function selectLeaderboardRound(
  rounds: LeaderboardRoundView[],
  requestedRoundId: string,
): LeaderboardRoundView | null {
  if (rounds.length === 0) return null;
  const requested = requestedRoundId.trim();
  if (requested) {
    const match = rounds.find((round) => round.roundId === requested);
    if (match) return match;
  }
  return rounds[rounds.length - 1];
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function roundStatusLabel(status: string, lang: "zh" | "en"): string {
  const label = ROUND_STATUS_LABELS[status];
  if (!label) return status;
  return lang === "en" ? label.en : label.zh;
}

function roundStatusTone(status: string): VStatusTone {
  if (status === "closed") return "success";
  if (status === "reviewed") return "accent";
  if (status === "open") return "warning";
  return "neutral";
}

function outcomeLabel(outcome: LeaderboardComparisonView["outcome"], lang: "zh" | "en"): string {
  if (outcome === "win") return lang === "en" ? "Win" : "胜";
  if (outcome === "loss") return lang === "en" ? "Loss" : "负";
  return lang === "en" ? "Tie" : "平";
}

function outcomeTone(outcome: LeaderboardComparisonView["outcome"]): VStatusTone {
  if (outcome === "win") return "success";
  if (outcome === "loss") return "danger";
  return "neutral";
}

function scoreEntryLabel(dimension: string, lang: "zh" | "en"): string {
  const label = SCORE_DIMENSION_LABELS[dimension];
  if (!label) return dimension;
  return lang === "en" ? label.en : label.zh;
}

function ScoreGrid({ entries, lang }: { entries: LeaderboardScoreEntry[]; lang: "zh" | "en" }) {
  if (entries.length === 0) return null;
  return (
    <div className={styles.scoreGrid} data-testid="leaderboard-score-grid">
      {entries.map((entry) => (
        <div key={entry.dimension}>
          <span>{scoreEntryLabel(entry.dimension, lang)}</span>
          <strong>{entry.value}</strong>
        </div>
      ))}
    </div>
  );
}

function PairwiseDetails({
  candidate,
  lang,
  isZh,
}: {
  candidate: LeaderboardCandidateView;
  lang: "zh" | "en";
  isZh: boolean;
}) {
  if (candidate.comparisons.length === 0) {
    return <p className={styles.mutedText}>{isZh ? "本轮无两两对决记录。" : "No pairwise comparison recorded in this round."}</p>;
  }
  return (
    <ul className={styles.detailList}>
      {candidate.comparisons.map((comparison) => (
        <li
          className={styles.detailItem}
          key={comparison.comparisonId || `${candidate.candidateId}-vs-${comparison.opponentCandidateId}`}
        >
          <div className={styles.detailTopline}>
            <VChip tone="neutral">{isZh ? "对阵" : "vs"} {comparison.opponentCandidateId}</VChip>
            <VStatusChip tone={outcomeTone(comparison.outcome)}>
              {outcomeLabel(comparison.outcome, lang)}
            </VStatusChip>
            {comparison.reviewerAgentId ? (
              <span className={styles.reviewMeta}>{comparison.reviewerAgentId}</span>
            ) : null}
          </div>
          {comparison.justification ? (
            <p className={styles.detailText}>{comparison.justification}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function DimensionReviewCard({
  candidate,
  lang,
  isZh,
}: {
  candidate: LeaderboardCandidateView;
  lang: "zh" | "en";
  isZh: boolean;
}) {
  if (candidate.dimensionReviews.length === 0) {
    return (
      <p className={styles.mutedText} data-testid="leaderboard-dimension-reviews-empty">
        {isZh ? "本轮未产出七维评审正文。" : "No seven-dimension review notes were produced for this round."}
      </p>
    );
  }
  return (
    <div className={styles.reviewList}>
      {candidate.dimensionReviews.map((review, index) => {
        const ratingLabel = RATING_KEYS.has(review.rating)
          ? challengeRatingLabel(review.rating as ChallengeQuestionDimensionReview["rating"], lang)
          : review.rating;
        return (
          <div
            className={styles.reviewRow}
            key={`${review.dimension}-${index}`}
            data-testid="leaderboard-dimension-review-row"
          >
            <div className={styles.reviewHead}>
              <strong>{challengeDimensionLabel(review.dimension, lang)}</strong>
              <VStatusChip
                tone={
                  review.rating === "strong" || review.rating === "adequate"
                    ? "success"
                    : review.rating === "weak" || review.rating === "insufficient"
                      ? "warning"
                      : "neutral"
                }
              >
                {ratingLabel}
              </VStatusChip>
              {review.reviewer ? <span className={styles.reviewMeta}>{review.reviewer}</span> : null}
            </div>
            {review.rationale ? <p className={styles.reviewText}>{review.rationale}</p> : null}
            {review.evidenceRefs.length > 0 ? (
              <p className={styles.reviewMeta}>
                {isZh ? "证据" : "Evidence"}: {review.evidenceRefs.join("、")}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function CandidateCard({
  candidate,
  stateKey,
  lang,
  isZh,
  expanded,
  onToggle,
}: {
  candidate: LeaderboardCandidateView;
  /** Expansion state is keyed per round so same-id candidates in different
   * rounds never share expand state. */
  stateKey: string;
  lang: "zh" | "en";
  isZh: boolean;
  expanded: { pairs: boolean; reviews: boolean };
  onToggle: (stateKey: string, kind: "pairs" | "reviews") => void;
}) {
  const rankOf = (value: number, unit: { zh: string; en: string }) =>
    isZh ? `${value} ${unit.zh}` : `${value} ${unit.en}`;
  return (
    <article
      className={styles.candidateCard}
      data-candidate-id={candidate.candidateId}
      data-recommended={candidate.isRecommended}
      data-testid="leaderboard-candidate-card"
    >
      <div className={styles.candidateHead}>
        <span className={styles.candidateId}>{candidate.candidateId}</span>
        {candidate.isRecommended ? (
          <VStatusChip tone="accent" data-testid="leaderboard-recommended-badge">
            {isZh ? "MetaReview 推荐" : "MetaReview pick"}
          </VStatusChip>
        ) : null}
        {candidate.isParetoFront ? (
          <VStatusChip tone="success" data-testid="leaderboard-pareto-badge">
            {isZh ? "Pareto 前沿" : "Pareto front"}
          </VStatusChip>
        ) : null}
        {candidate.status ? (
          <VChip tone="neutral">{candidate.status}</VChip>
        ) : null}
      </div>
      {candidate.claim ? <p className={styles.claimText}>{candidate.claim}</p> : null}
      {candidate.rationale ? <p className={styles.mutedText}>{candidate.rationale}</p> : null}
      <ScoreGrid entries={[...candidate.scores, ...candidate.diagnostics]} lang={lang} />
      <div className={styles.recordRow} data-testid="leaderboard-pairwise-record">
        <span>
          {isZh
            ? `两两对决 ${rankOf(candidate.wins, { zh: "胜", en: "W" })} ${rankOf(candidate.losses, { zh: "负", en: "L" })} ${rankOf(candidate.ties, { zh: "平", en: "T" })}`
            : `Pairwise ${candidate.wins}W ${candidate.losses}L ${candidate.ties}T`}
        </span>
        <VButton
          type="button"
          density="compact"
          variant="secondary"
          aria-expanded={expanded.pairs}
          onClick={() => onToggle(stateKey, "pairs")}
          data-testid={`leaderboard-toggle-pairs-${candidate.candidateId}`}
        >
          {expanded.pairs
            ? (isZh ? "收起对决明细" : "Hide comparison details")
            : (isZh ? "展开对决明细" : "Comparison details")}
        </VButton>
        <VButton
          type="button"
          density="compact"
          variant="secondary"
          aria-expanded={expanded.reviews}
          onClick={() => onToggle(stateKey, "reviews")}
          data-testid={`leaderboard-toggle-reviews-${candidate.candidateId}`}
        >
          {expanded.reviews
            ? (isZh ? "收起七维评分卡" : "Hide review card")
            : (isZh ? "七维评分卡" : "Seven-dimension review card")}
        </VButton>
      </div>
      {expanded.pairs ? (
        <div data-testid={`leaderboard-pairs-${candidate.candidateId}`}>
          <PairwiseDetails candidate={candidate} lang={lang} isZh={isZh} />
        </div>
      ) : null}
      {expanded.reviews ? (
        <div data-testid={`leaderboard-reviews-${candidate.candidateId}`}>
          <DimensionReviewCard candidate={candidate} lang={lang} isZh={isZh} />
        </div>
      ) : null}
    </article>
  );
}

function LeaderboardContent({
  model,
  lang,
  isZh,
}: {
  model: HypothesisLeaderboardModel;
  lang: "zh" | "en";
  isZh: boolean;
}) {
  const [requestedRoundId, setRequestedRoundId] = useState("");
  const [expanded, setExpanded] = useState<Record<string, { pairs: boolean; reviews: boolean }>>({});
  const activeRound = selectLeaderboardRound(model.rounds, requestedRoundId);
  if (!activeRound) return null;
  const toggle = (stateKey: string, kind: "pairs" | "reviews") => {
    setExpanded((previous) => ({
      ...previous,
      [stateKey]: {
        pairs: previous[stateKey]?.pairs ?? false,
        reviews: previous[stateKey]?.reviews ?? false,
        [kind]: !(previous[stateKey]?.[kind] ?? false),
      },
    }));
  };
  return (
    <>
      <div className={styles.topline}>
        {model.rounds.length > 1 ? (
          <div className={styles.switcher}>
            <VSelect
              density="compact"
              aria-label={isZh ? "切换评审轮次" : "Switch review round"}
              selectedKey={activeRound.roundId}
              options={model.rounds.map((round) => ({
                id: round.roundId,
                label: isZh
                  ? `第 ${round.displayIndex} 轮 · ${roundStatusLabel(round.status, lang)}`
                  : `Round ${round.displayIndex} · ${roundStatusLabel(round.status, lang)}`,
              }))}
              onSelectionChange={(key) => {
                if (key == null) return;
                setRequestedRoundId(String(key));
              }}
            />
          </div>
        ) : null}
        <VStatusChip tone={roundStatusTone(activeRound.status)}>
          {roundStatusLabel(activeRound.status, lang)}
        </VStatusChip>
        {model.scopeFallback ? (
          <VStatusChip tone="warning" data-testid="leaderboard-scope-fallback">
            {isZh ? "轮次未携带题目范围，展示团队全部轮次" : "Rounds carry no question scope; showing the whole team ledger"}
          </VStatusChip>
        ) : null}
        {model.quarantinedCount > 0 ? (
          <VStatusChip tone="warning" data-testid="leaderboard-quarantined">
            {isZh
              ? `${model.quarantinedCount} 条损坏记录已隔离`
              : `${model.quarantinedCount} corrupted ledger line(s) quarantined`}
          </VStatusChip>
        ) : null}
      </div>
      <div className={styles.metaRow}>
        <span>{activeRound.roundId}</span>
        {activeRound.question ? (
          <span>{isZh ? "范围" : "Scope"}: {activeRound.question}</span>
        ) : null}
        {activeRound.createdAt ? <span>{activeRound.createdAt}</span> : null}
        {activeRound.closedAt ? <span>{isZh ? "关闭" : "Closed"}: {activeRound.closedAt}</span> : null}
      </div>

      {activeRound.paretoFrontCandidateIds.length > 0 ? (
        <div className={styles.summaryCard} data-testid="leaderboard-pareto-summary">
          <span>{isZh ? "Pareto 前沿" : "Pareto front"}</span>
          <div className={styles.badgeRow}>
            {activeRound.paretoFrontCandidateIds.map((candidateId) => (
              <VChip key={candidateId} tone="success">{candidateId}</VChip>
            ))}
          </div>
          {activeRound.paretoNotes ? <p>{activeRound.paretoNotes}</p> : null}
        </div>
      ) : null}

      {activeRound.metaReview ? (
        <div className={styles.summaryCard} data-testid="leaderboard-metareview">
          <span>{isZh ? "MetaReview 推荐" : "MetaReview recommendation"}</span>
          <div className={styles.badgeRow}>
            <VChip tone="accent">{activeRound.metaReview.recommendationCandidateId}</VChip>
            <VStatusChip tone={activeRound.metaReview.accepted ? "success" : "warning"}>
              {activeRound.metaReview.accepted
                ? (isZh ? "已接受" : "Accepted")
                : (isZh ? "未接受" : "Not accepted")}
            </VStatusChip>
            {activeRound.metaReview.reviewerAgentId ? (
              <span className={styles.reviewMeta}>{activeRound.metaReview.reviewerAgentId}</span>
            ) : null}
          </div>
          {activeRound.metaReview.rationale ? <p>{activeRound.metaReview.rationale}</p> : null}
          {activeRound.metaReview.riskNotes ? (
            <p>{isZh ? "风险：" : "Risks: "}{activeRound.metaReview.riskNotes}</p>
          ) : null}
        </div>
      ) : null}

      <div className={styles.candidateList} data-testid="leaderboard-candidate-list">
        {activeRound.candidates.map((candidate) => {
          const stateKey = `${activeRound.roundId}:${candidate.candidateId}`;
          const state = expanded[stateKey] ?? { pairs: false, reviews: false };
          return (
            <CandidateCard
              key={candidate.candidateId}
              candidate={candidate}
              stateKey={stateKey}
              lang={lang}
              isZh={isZh}
              expanded={state}
              onToggle={toggle}
            />
          );
        })}
      </div>
    </>
  );
}

export function HypothesisLeaderboardPanel({
  teamId,
  questionId,
  lang: langProp,
}: HypothesisLeaderboardPanelProps) {
  const shell = useShellI18n();
  const lang = langProp ?? shell.lang;
  const isZh = lang === "zh";
  const enabled = Boolean(teamId.trim());
  const query = useQuery({
    queryKey: queryKeys.teamHypothesisRounds(teamId),
    queryFn: ({ signal }) => fetchHypothesisRounds(teamId, { signal }),
    enabled,
    staleTime: 15_000,
    retry: false,
  });
  const model = useMemo(
    () => buildHypothesisLeaderboardModel(query.data, questionId),
    [query.data, questionId],
  );

  return (
    <VSurface tone="panel" className={styles.root} data-vui="hypothesis-leaderboard-panel">
      <div className={styles.header}>
        <span className={styles.eyebrow}>
          {isZh
            ? `假说排行榜 · 只读${questionId ? ` · ${questionId}` : ""}`
            : `Hypothesis leaderboard · read only${questionId ? ` · ${questionId}` : ""}`}
        </span>
      </div>
      {!enabled ? (
        <VEmptyState title={isZh ? "缺少团队标识" : "Missing team id"} className={styles.empty}>
          {isZh
            ? "未提供 teamId，无法读取假说评审轮次。"
            : "No teamId provided; review rounds cannot be read."}
        </VEmptyState>
      ) : query.isPending ? (
        <VStateSurface
          tone="loading"
          title={isZh ? "正在读取假说评审轮次" : "Reading hypothesis review rounds"}
          className={styles.fill}
        />
      ) : query.isError || !query.data ? (
        <>
          <VErrorSummary
            tone="warning"
            label={isZh ? "假说评审轮次暂不可用" : "Hypothesis review rounds unavailable"}
            summary={
              isZh
                ? "评审轮次暂不可读，排行榜暂时无法呈现。"
                : "Review rounds cannot be read; the leaderboard is unavailable."
            }
          />
          <div>
            <VButton type="button" variant="secondary" onClick={() => void query.refetch()}>
              {isZh ? "重试" : "Retry"}
            </VButton>
          </div>
        </>
      ) : model.rounds.length === 0 ? (
        <VEmptyState
          title={isZh ? "暂无假说评审轮次" : "No hypothesis review rounds yet"}
          className={styles.empty}
        >
          {isZh
            ? "评审会议关门后自动生成轮次记录，届时这里会呈现候选排行榜。"
            : "Round records are generated when review meetings close; the leaderboard will appear then."}
        </VEmptyState>
      ) : (
        <LeaderboardContent model={model} lang={lang} isZh={isZh} />
      )}
    </VSurface>
  );
}
