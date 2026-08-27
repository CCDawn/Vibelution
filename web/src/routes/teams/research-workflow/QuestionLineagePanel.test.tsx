/**
 * QuestionLineagePanel contracts:
 * - the pure content renderer shows the full chain (evolution timeline,
 *   per-candidate disagreement, claim belief chips, evidence edges);
 * - degraded segments are labeled with their missing reason instead of being
 *   hidden, and an all-missing projection renders an honest empty state;
 * - the read-only surface renders loose/absent extras defensively.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  QuestionLineageContent,
  questionLineageContentModel,
} from "./QuestionLineagePanel";
import type { ResearchQuestionLineageProjection } from "../../../api/types/researchWorkflow";

function segment(
  status: "ready" | "missing",
  extra: Record<string, unknown> = {},
): { status: "ready" | "missing"; missingReason?: string } & Record<string, unknown> {
  return status === "missing"
    ? { status, missingReason: (extra.missingReason as string) ?? "missing" }
    : { status, ...extra };
}

const FULL: ResearchQuestionLineageProjection = {
  schemaVersion: 1,
  teamId: "team-1",
  questionId: "SCI-091",
  workflowRunId: "",
  roundId: "",
  boundaries: { readOnly: true },
  degradedSegments: [],
  segments: {
    evolution: segment("ready", {
      lineageCount: 1,
      lineages: [
        {
          lineageId: "evolution-lineage:SCI-091:round-1",
          roundId: "round-1",
          recordId: "rec-1",
          eventCount: 3,
          summary: { eventCount: 3, finalistCandidateIds: ["H1r2"] },
          events: [
            {
              eventId: "evt-1",
              candidateId: "H1",
              kind: "introduced",
              roundId: "round-1",
              reason: "",
              occurredAt: "2026-08-28T00:00:00Z",
              actor: "system_policy",
              revisionAttempt: 0,
              evidenceRefs: [],
            },
            {
              eventId: "evt-2",
              candidateId: "H1r2",
              kind: "revised",
              roundId: "round-1",
              reason: "pairwise disagreement on falsifiability",
              occurredAt: "2026-08-28T00:01:00Z",
              actor: "system_policy",
              revisionAttempt: 2,
              evidenceRefs: [{ kind: "disagreement_artifact", ref: "dis:round-1" }],
            },
            {
              eventId: "evt-3",
              candidateId: "H1r2",
              kind: "finalist",
              roundId: "round-1",
              reason: "",
              occurredAt: "2026-08-28T00:02:00Z",
              actor: "human_operator",
              revisionAttempt: 0,
              evidenceRefs: [],
            },
          ],
        },
      ],
    }),
    reviewDisagreement: segment("ready", {
      artifactCount: 1,
      candidates: {
        H1: {
          pairCount: 1,
          pairs: [
            {
              comparisonId: "cmp-1",
              opposedCandidateId: "H2",
              outcome: "left_wins",
              inconsistentAxes: ["falsifiability"],
              artifactRef: "rec-dis-1",
            },
          ],
          disagreementAxes: ["falsifiability"],
          escalationRequired: true,
        },
      },
    }),
    claimBelief: segment("ready", {
      claimCount: 2,
      beliefTableHash: "hash",
      claims: [
        {
          claimId: "claim-a",
          claimText: "腺苷假说成立",
          status: "supported",
          source: "agent",
          beliefState: "supported",
          acceptedSupportCount: 1,
          acceptedCounterCount: 0,
          pendingSupportCount: 0,
          pendingCounterCount: 0,
          neutralCount: 0,
          supportingEvidenceIds: ["ce-1"],
          counterEvidenceIds: [],
          lastEvaluatedAt: "2026-08-28T00:00:00Z",
          candidateIds: ["H1"],
        },
        {
          claimId: "claim-b",
          claimText: "备选机制",
          status: "proposed",
          source: "agent",
          beliefState: "disputed",
          acceptedSupportCount: 1,
          acceptedCounterCount: 1,
          pendingSupportCount: 0,
          pendingCounterCount: 0,
          neutralCount: 0,
          supportingEvidenceIds: ["ce-2"],
          counterEvidenceIds: ["ce-3"],
          lastEvaluatedAt: "2026-08-28T00:00:00Z",
          candidateIds: ["H2"],
        },
      ],
      candidates: {},
    }),
    evidenceGraph: segment("ready", {
      nodeCount: 4,
      edgeCount: 2,
      nodes: [],
      edges: [
        {
          source: "claim:claim-a",
          target: "evidence:ce-1",
          kind: "supports",
          reviewStatus: "accepted",
          accepted: true,
        },
        {
          source: "claim:claim-b",
          target: "evidence:ce-3",
          kind: "contradicts",
          reviewStatus: "pending",
          accepted: false,
        },
      ],
    }),
  },
};

const ALL_MISSING: ResearchQuestionLineageProjection = {
  ...FULL,
  degradedSegments: ["evolution", "reviewDisagreement", "claimBelief", "evidenceGraph"],
  segments: {
    evolution: segment("missing", { missingReason: "evolution_lineage_artifact_missing" }),
    reviewDisagreement: segment("missing", {
      missingReason: "review_disagreement_artifact_missing",
    }),
    claimBelief: segment("missing", { missingReason: "claim_ledger_empty_for_question" }),
    evidenceGraph: segment("missing", { missingReason: "claim_ledger_empty_for_question" }),
  },
};

describe("questionLineageContentModel", () => {
  it("flattens lineage events and keeps claim/edge views", () => {
    const model = questionLineageContentModel(FULL);
    expect(model.eventCount).toBe(3);
    expect(model.events.map((event) => event.eventId)).toEqual(["evt-1", "evt-2", "evt-3"]);
    expect(model.candidates).toHaveLength(1);
    expect(model.candidates[0].pairs[0].opposedCandidateId).toBe("H2");
    expect(model.claims.map((claim) => claim.claimId)).toEqual(["claim-a", "claim-b"]);
    expect(model.edgeCount).toBe(2);
  });

  it("tolerates loose segment payloads", () => {
    const model = questionLineageContentModel({
      ...FULL,
      segments: {
        evolution: { status: "ready" },
        reviewDisagreement: { status: "ready" },
        claimBelief: { status: "ready" },
        evidenceGraph: { status: "ready" },
      },
    });
    expect(model).toMatchObject({ events: [], candidates: [], claims: [], edges: [] });
  });
});

describe("QuestionLineageContent", () => {
  it("renders the full chain read-only", () => {
    const markup = renderToStaticMarkup(<QuestionLineageContent projection={FULL} />);
    expect(markup).toContain("候选演化事件（3）");
    expect(markup).toContain("引入");
    expect(markup).toContain("决胜候选");
    expect(markup).toContain("修订 2");
    expect(markup).toContain("pairwise disagreement on falsifiability");
    expect(markup).toContain("disagreement_artifact:dis:round-1");
    expect(markup).toContain("候选评审差异");
    expect(markup).toContain("差异升级标记");
    expect(markup).toContain("Claim 信念状态（2）");
    expect(markup).toContain("已支持");
    expect(markup).toContain("有争议");
    expect(markup).toContain("腺苷假说成立");
    expect(markup).toContain("证据引用边");
    expect(markup).toContain("—支持→");
    expect(markup).toContain("—反驳（待审）→");
  });

  it("labels degraded segments with their missing reason", () => {
    const partial: ResearchQuestionLineageProjection = {
      ...FULL,
      degradedSegments: ["evolution"],
      segments: {
        ...FULL.segments,
        evolution: segment("missing", {
          missingReason: "evolution_lineage_artifact_missing",
        }),
      },
    };
    const markup = renderToStaticMarkup(<QuestionLineageContent projection={partial} />);
    expect(markup).toContain("演化事件 · 缺失（evolution_lineage_artifact_missing）");
    expect(markup).toContain("Claim 信念状态（2）");
  });

  it("renders an honest empty state when every segment is missing", () => {
    const markup = renderToStaticMarkup(<QuestionLineageContent projection={ALL_MISSING} />);
    expect(markup).toContain("本题暂无全链谱系数据");
    expect(markup).toContain("evolution_lineage_artifact_missing");
    expect(markup).toContain("claim_ledger_empty_for_question");
  });

  it("supports English labels", () => {
    const markup = renderToStaticMarkup(
      <QuestionLineageContent projection={FULL} lang="en" />,
    );
    expect(markup).toContain("Candidate evolution events (3)");
    expect(markup).toContain("finalist");
    expect(markup).toContain("Claim belief states (2)");
    expect(markup).toContain("—supports→");
  });
});
