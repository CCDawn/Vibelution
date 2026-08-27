/**
 * R4.5 read-only single-question full-chain lineage panel.
 *
 * Renders the backend `question lineage` projection (claim → evidence →
 * candidate → review disagreement → candidate evolution) as a bounded,
 * read-only view: a timeline, per-candidate cards, belief chips and evidence
 * edges. No local aggregation: the backend projection is the single source of
 * truth, and each degraded segment is labeled with its missing reason instead
 * of hiding the gap. Composes existing VUI atoms only — no new controls.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchResearchWorkflowQuestionLineage } from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import type {
  ResearchQuestionLineageProjection,
  ResearchQuestionLineageSegment,
} from "../../../api/types/researchWorkflow";
import {
  VButton,
  VChip,
  VEmptyState,
  VErrorSummary,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./QuestionLineagePanel.styles";

export type QuestionLineagePanelProps = {
  teamId: string;
  questionId: string;
};

type RecordLike = Record<string, unknown>;

const SEGMENT_LABELS_ZH: Array<[string, string]> = [
  ["evolution", "演化事件"],
  ["reviewDisagreement", "评审差异"],
  ["claimBelief", "Claim 信念"],
  ["evidenceGraph", "证据引用"],
];
const SEGMENT_LABELS_EN: Array<[string, string]> = [
  ["evolution", "Evolution events"],
  ["reviewDisagreement", "Review disagreement"],
  ["claimBelief", "Claim belief"],
  ["evidenceGraph", "Evidence refs"],
];

const EVENT_KIND_LABELS_ZH: Record<string, string> = {
  introduced: "引入",
  screened_out: "筛除",
  revised: "修订",
  revision_exhausted: "修订预算耗尽",
  advanced: "晋级",
  finalist: "决胜候选",
  superseded: "被取代",
  converged: "收敛",
};
const EVENT_KIND_LABELS_EN: Record<string, string> = {
  introduced: "introduced",
  screened_out: "screened out",
  revised: "revised",
  revision_exhausted: "revision exhausted",
  advanced: "advanced",
  finalist: "finalist",
  superseded: "superseded",
  converged: "converged",
};

const BELIEF_TONES: Record<string, "neutral" | "accent" | "success" | "warning" | "danger"> = {
  supported: "success",
  weakly_supported: "accent",
  untested: "neutral",
  disputed: "warning",
  contradicted: "danger",
};
const BELIEF_LABELS_ZH: Record<string, string> = {
  supported: "已支持",
  weakly_supported: "弱支持",
  untested: "未检验",
  disputed: "有争议",
  contradicted: "已反驳",
};
const BELIEF_LABELS_EN: Record<string, string> = {
  supported: "supported",
  weakly_supported: "weakly supported",
  untested: "untested",
  disputed: "disputed",
  contradicted: "contradicted",
};

const EDGE_LABELS_ZH: Record<string, string> = {
  supports: "支持",
  contradicts: "反驳",
  insufficient: "证据不足",
  unverified: "未验证",
};
const EDGE_LABELS_EN: Record<string, string> = {
  supports: "supports",
  contradicts: "contradicts",
  insufficient: "insufficient",
  unverified: "unverified",
};

const MAX_TIMELINE_EVENTS = 50;
const MAX_EDGES = 40;
const MAX_CLAIM_CARDS = 24;

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
function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export type LineageEventView = {
  eventId: string;
  candidateId: string;
  kind: string;
  roundId: string;
  reason: string;
  occurredAt: string;
  actor: string;
  revisionAttempt: number;
  evidenceRefs: Array<{ kind: string; ref: string }>;
};

export type LineageCandidateView = {
  candidateId: string;
  pairCount: number;
  pairs: Array<{
    comparisonId: string;
    opposedCandidateId: string;
    outcome: string;
    inconsistentAxes: string[];
    artifactRef: string;
  }>;
  disagreementAxes: string[];
  escalationRequired: boolean;
};

export type LineageClaimView = {
  claimId: string;
  claimText: string;
  status: string;
  beliefState: string;
  acceptedSupportCount: number;
  acceptedCounterCount: number;
  pendingSupportCount: number;
  candidateIds: string[];
};

export type LineageEdgeView = {
  source: string;
  target: string;
  kind: string;
  reviewStatus: string;
  accepted: boolean;
};

export type QuestionLineageContentModel = {
  events: LineageEventView[];
  eventCount: number;
  candidates: LineageCandidateView[];
  claims: LineageClaimView[];
  claimCount: number;
  edges: LineageEdgeView[];
  edgeCount: number;
};

/** Pure projection → view-model (defensive against loose backend extras). */
export function questionLineageContentModel(
  projection: ResearchQuestionLineageProjection,
): QuestionLineageContentModel {
  const segments = asRecord(projection.segments);
  const evolution = asRecord(segments.evolution);
  const disagreement = asRecord(segments.reviewDisagreement);
  const belief = asRecord(segments.claimBelief);
  const graph = asRecord(segments.evidenceGraph);

  const events: LineageEventView[] = [];
  for (const rawLineage of asArray(evolution.lineages)) {
    const lineage = asRecord(rawLineage);
    for (const rawEvent of asArray(lineage.events)) {
      const event = asRecord(rawEvent);
      events.push({
        eventId: asText(event.eventId),
        candidateId: asText(event.candidateId),
        kind: asText(event.kind),
        roundId: asText(event.roundId),
        reason: asText(event.reason),
        occurredAt: asText(event.occurredAt),
        actor: asText(event.actor),
        revisionAttempt: asNumber(event.revisionAttempt),
        evidenceRefs: asArray(event.evidenceRefs).map((rawRef) => {
          const ref = asRecord(rawRef);
          return { kind: asText(ref.kind), ref: asText(ref.ref) };
        }),
      });
    }
  }

  const candidates: LineageCandidateView[] = Object.entries(
    asRecord(disagreement.candidates),
  ).map(([candidateId, rawEntry]) => {
    const entry = asRecord(rawEntry);
    return {
      candidateId,
      pairCount: asNumber(entry.pairCount),
      pairs: asArray(entry.pairs).map((rawPair) => {
        const pair = asRecord(rawPair);
        return {
          comparisonId: asText(pair.comparisonId),
          opposedCandidateId: asText(pair.opposedCandidateId),
          outcome: asText(pair.outcome),
          inconsistentAxes: asArray(pair.inconsistentAxes).map(String),
          artifactRef: asText(pair.artifactRef),
        };
      }),
      disagreementAxes: asArray(entry.disagreementAxes).map(String),
      escalationRequired: entry.escalationRequired === true,
    };
  });

  const claims: LineageClaimView[] = asArray(belief.claims)
    .map((rawClaim) => {
      const claim = asRecord(rawClaim);
      return {
        claimId: asText(claim.claimId),
        claimText: asText(claim.claimText),
        status: asText(claim.status),
        beliefState: asText(claim.beliefState),
        acceptedSupportCount: asNumber(claim.acceptedSupportCount),
        acceptedCounterCount: asNumber(claim.acceptedCounterCount),
        pendingSupportCount: asNumber(claim.pendingSupportCount),
        candidateIds: asArray(claim.candidateIds).map(String),
      };
    })
    .sort((a, b) => a.claimId.localeCompare(b.claimId));

  const edges: LineageEdgeView[] = asArray(graph.edges)
    .map((rawEdge) => {
      const edge = asRecord(rawEdge);
      return {
        source: asText(edge.source),
        target: asText(edge.target),
        kind: asText(edge.kind),
        reviewStatus: asText(edge.reviewStatus),
        accepted: edge.accepted === true,
      };
    })
    .sort((a, b) => `${a.source}${a.target}`.localeCompare(`${b.source}${b.target}`));

  return {
    events,
    eventCount: events.length,
    candidates,
    claims,
    claimCount: asNumber(belief.claimCount) || claims.length,
    edges,
    edgeCount: asNumber(graph.edgeCount) || edges.length,
  };
}

function missingReasonOf(segment: ResearchQuestionLineageSegment): string {
  return segment.status === "missing" ? segment.missingReason : "";
}

function segmentChips(
  projection: ResearchQuestionLineageProjection,
  labels: Array<[string, string]>,
): Array<{ label: string; ready: boolean; reason: string }> {
  const segments = asRecord(projection.segments);
  return labels.map(([key, label]) => {
    const segmentRaw = segments[key];
    const segment = (
      segmentRaw && typeof segmentRaw === "object" && "status" in (segmentRaw as RecordLike)
        ? segmentRaw
        : { status: "missing", missingReason: "segment_unavailable" }
    ) as ResearchQuestionLineageSegment;
    return {
      label,
      ready: segment.status === "ready",
      reason: missingReasonOf(segment),
    };
  });
}

/** Pure read-only renderer (separate from fetch state for testability). */
export function QuestionLineageContent({
  projection,
  lang = "zh",
}: {
  projection: ResearchQuestionLineageProjection;
  lang?: "zh" | "en";
}) {
  const isZh = lang === "zh";
  const kindLabels = isZh ? EVENT_KIND_LABELS_ZH : EVENT_KIND_LABELS_EN;
  const beliefLabels = isZh ? BELIEF_LABELS_ZH : BELIEF_LABELS_EN;
  const edgeLabels = isZh ? EDGE_LABELS_ZH : EDGE_LABELS_EN;
  const model = questionLineageContentModel(projection);
  const chips = segmentChips(projection, isZh ? SEGMENT_LABELS_ZH : SEGMENT_LABELS_EN);
  const degraded = model.events.length === 0 && model.candidates.length === 0 && model.claims.length === 0;

  if (degraded) {
    const reasons = chips
      .filter((chip) => !chip.ready)
      .map((chip) => `${chip.label}: ${chip.reason}`)
      .join(" · ");
    return (
      <VEmptyState
        title={isZh ? "本题暂无全链谱系数据" : "No lineage data for this question yet"}
        className={styles.empty}
      >
        {isZh
          ? "尚未产生演化事件、评审差异或 claim 信念记录。"
          : "No evolution events, review disagreements, or claim beliefs recorded yet."}
        {reasons ? <span className={styles.missingHint}>{reasons}</span> : null}
      </VEmptyState>
    );
  }

  const visibleEvents = model.events.slice(0, MAX_TIMELINE_EVENTS);
  const visibleClaims = model.claims.slice(0, MAX_CLAIM_CARDS);
  const visibleEdges = model.edges.slice(0, MAX_EDGES);

  return (
    <>
      <div className={styles.segmentChips}>
        {chips.map((chip) => (
          <VStatusChip
            key={chip.label}
            tone={chip.ready ? "success" : "warning"}
            title={chip.ready ? undefined : chip.reason}
          >
            {chip.ready
              ? chip.label
              : `${chip.label} · ${isZh ? "缺失" : "missing"}${chip.reason ? `（${chip.reason}）` : ""}`}
          </VStatusChip>
        ))}
      </div>

      {model.events.length > 0 ? (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {isZh
              ? `候选演化事件（${model.eventCount}）`
              : `Candidate evolution events (${model.eventCount})`}
          </div>
          <ol className={styles.timeline}>
            {visibleEvents.map((event) => (
              <li className={styles.timelineItem} key={event.eventId}>
                <span className={styles.timelineMarker} aria-hidden="true" />
                <div className={styles.section}>
                  <div className={styles.timelineTopline}>
                    <span className={styles.eventKind}>
                      {kindLabels[event.kind] ?? event.kind}
                    </span>
                    <VChip tone="neutral">{event.candidateId}</VChip>
                    {event.revisionAttempt > 0 ? (
                      <VChip tone="accent">
                        {isZh ? `修订 ${event.revisionAttempt}` : `rev ${event.revisionAttempt}`}
                      </VChip>
                    ) : null}
                    <VChip tone={event.actor === "system_policy" ? "neutral" : "info"}>
                      {event.actor}
                    </VChip>
                    <span className={styles.eventMeta}>
                      {event.roundId}
                      {event.occurredAt ? ` · ${event.occurredAt}` : ""}
                    </span>
                  </div>
                  {event.reason ? (
                    <div className={styles.eventReason}>{event.reason}</div>
                  ) : null}
                  {event.evidenceRefs.length > 0 ? (
                    <div className={styles.eventMeta}>
                      {event.evidenceRefs
                        .map((ref) => `${ref.kind}:${ref.ref}`)
                        .join(" · ")}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
          {model.events.length > visibleEvents.length ? (
            <div className={styles.more}>
              {isZh
                ? `…其余 ${model.events.length - visibleEvents.length} 条事件已省略`
                : `…${model.events.length - visibleEvents.length} more events omitted`}
            </div>
          ) : null}
        </div>
      ) : null}

      {model.candidates.length > 0 ? (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {isZh ? "候选评审差异" : "Per-candidate review disagreement"}
          </div>
          <div className={styles.cardGrid}>
            {model.candidates.map((candidate) => (
              <div className={styles.card} key={candidate.candidateId}>
                <div className={styles.timelineTopline}>
                  <span className={styles.cardTitle}>{candidate.candidateId}</span>
                  {candidate.escalationRequired ? (
                    <VStatusChip tone="warning">
                      {isZh ? "差异升级标记" : "escalation flagged"}
                    </VStatusChip>
                  ) : null}
                </div>
                {candidate.pairs.map((pair) => (
                  <div className={styles.detail} key={pair.comparisonId}>
                    {isZh ? "对峙" : "vs"} {pair.opposedCandidateId} · {pair.outcome}
                    {pair.inconsistentAxes.length > 0
                      ? ` · ${pair.inconsistentAxes.join(", ")}`
                      : ""}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {model.claims.length > 0 ? (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {isZh
              ? `Claim 信念状态（${model.claimCount}）`
              : `Claim belief states (${model.claimCount})`}
          </div>
          <div className={styles.cardGrid}>
            {visibleClaims.map((claim) => (
              <div className={styles.card} key={claim.claimId}>
                <div className={styles.timelineTopline}>
                  <VStatusChip tone={BELIEF_TONES[claim.beliefState] ?? "neutral"}>
                    {beliefLabels[claim.beliefState] ?? claim.beliefState}
                  </VStatusChip>
                  <span className={styles.cardTitle}>{claim.claimId}</span>
                </div>
                {claim.claimText ? (
                  <div className={styles.detail}>{claim.claimText}</div>
                ) : null}
                <div className={styles.eventMeta}>
                  {isZh ? "支持" : "support"} {claim.acceptedSupportCount} ·{" "}
                  {isZh ? "反驳" : "counter"} {claim.acceptedCounterCount} ·{" "}
                  {isZh ? "待审" : "pending"} {claim.pendingSupportCount}
                  {claim.candidateIds.length > 0
                    ? ` · ${isZh ? "候选" : "candidates"} ${claim.candidateIds.join(", ")}`
                    : ""}
                </div>
              </div>
            ))}
          </div>
          {model.claims.length > visibleClaims.length ? (
            <div className={styles.more}>
              {isZh
                ? `…其余 ${model.claims.length - visibleClaims.length} 条 claim 已省略`
                : `…${model.claims.length - visibleClaims.length} more claims omitted`}
            </div>
          ) : null}
        </div>
      ) : null}

      {model.edges.length > 0 ? (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            {isZh ? "证据引用边" : "Claim → evidence edges"}
          </div>
          <ul className={styles.edgeList}>
            {visibleEdges.map((edge) => (
              <li className={styles.edge} key={`${edge.source}->${edge.target}`}>
                {edge.source} —{edgeLabels[edge.kind] ?? edge.kind}
                {edge.accepted ? "" : isZh ? "（待审）" : " (pending)"}→ {edge.target}
              </li>
            ))}
          </ul>
          {model.edges.length > visibleEdges.length ? (
            <div className={styles.more}>
              {isZh
                ? `…其余 ${model.edges.length - visibleEdges.length} 条边已省略`
                : `…${model.edges.length - visibleEdges.length} more edges omitted`}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export function QuestionLineagePanel({ teamId, questionId }: QuestionLineagePanelProps) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const enabled = Boolean(teamId.trim() && questionId.trim());
  const query = useQuery({
    queryKey: queryKeys.researchQuestionLineage(teamId, questionId),
    queryFn: () => fetchResearchWorkflowQuestionLineage(questionId, { teamId }),
    enabled,
    staleTime: 30_000,
    retry: false,
  });

  const projection = query.data;

  return (
    <VSurface tone="panel" className={styles.root} data-vui="question-lineage-panel">
      <div className={styles.header}>
        <span className={styles.eyebrow}>
          {isZh
            ? `全链谱系 · 只读${questionId ? ` · ${questionId}` : ""}`
            : `Question lineage · read only${questionId ? ` · ${questionId}` : ""}`}
        </span>
      </div>
      {!enabled ? (
        <VEmptyState
          title={isZh ? "缺少题目标识" : "Missing question id"}
          className={styles.empty}
        >
          {isZh
            ? "未提供 questionId，无法聚合该题的全链谱系。"
            : "No questionId provided; the lineage cannot be aggregated."}
        </VEmptyState>
      ) : query.isPending ? (
        <VStateSurface
          tone="loading"
          title={isZh ? "正在聚合全链谱系" : "Aggregating question lineage"}
          className={styles.fill}
        />
      ) : query.isError || !projection ? (
        <>
          <VErrorSummary
            tone="warning"
            label={isZh ? "全链谱系暂不可用" : "Question lineage unavailable"}
            summary={
              isZh
                ? "谱系投影暂不可用，但不会影响题目本身的数据。"
                : "The lineage projection is temporarily unavailable; question data is unaffected."
            }
          />
          <div>
            <VButton type="button" variant="secondary" onClick={() => void query.refetch()}>
              {isZh ? "重试" : "Retry"}
            </VButton>
          </div>
        </>
      ) : (
        <QuestionLineageContent projection={projection} lang={lang} />
      )}
    </VSurface>
  );
}
