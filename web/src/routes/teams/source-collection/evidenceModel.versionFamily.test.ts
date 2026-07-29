import { describe, expect, it } from "vitest";

import type { TeamWorkflowCandidate } from "../../../api/types";
import {
  sourceCollectionCandidateVersionFamily,
  sourceCollectionIndependentSourceCount,
} from "./evidenceModel";

function candidate(sourceVersionFamily?: Record<string, unknown>): TeamWorkflowCandidate {
  return {
    schemaVersion: 2,
    candidateId: "candidate-v1",
    candidateType: "source_manifest",
    teamId: "research-team",
    workflowId: "workflow-1",
    title: "Research Square preprint",
    summary: "Versioned source",
    currentWorkflowNode: "knowledge_collection",
    currentState: "captured",
    qualityStatus: "pending",
    metadata: {},
    createdByAgent: "A016",
    createdAt: "2026-06-16T00:00:00Z",
    updatedAt: "2026-06-16T00:00:00Z",
    sourceVersionFamily,
  };
}

describe("sourceCollectionCandidateVersionFamily", () => {
  it("marks an older preprint version as audit-only and non-reviewable", () => {
    expect(sourceCollectionCandidateVersionFamily(candidate({
      familyKey: "doi:10.21203/rs.3.rs-10024823",
      version: 1,
      versionLabel: "v1",
      state: "superseded",
      familySize: 2,
      currentCandidateId: "candidate-v2",
      currentVersionLabel: "v2",
      countsAsIndependentSource: false,
      sourceKind: "research_square_preprint",
      evidencePolicy: "hypothesis_generation_only",
    }), "zh")).toEqual({
      isVersioned: true,
      isCurrent: false,
      isSuperseded: true,
      statusLabel: "历史版本 v1",
      chainLabel: "版本链 2 个版本 · 当前 v2",
      evidenceLabel: "预印本 · 仅用于假设生成",
      reviewDisabledReason: "该记录已由 v2 取代，仅保留审计；请审核当前版本。",
    });
  });

  it("marks the latest member as the only current version", () => {
    expect(sourceCollectionCandidateVersionFamily(candidate({
      familyKey: "doi:10.21203/rs.3.rs-10024823",
      version: 2,
      versionLabel: "v2",
      state: "current",
      familySize: 2,
      currentCandidateId: "candidate-v2",
      currentVersionLabel: "v2",
      countsAsIndependentSource: true,
      sourceKind: "research_square_preprint",
      evidencePolicy: "hypothesis_generation_only",
    }), "zh")).toMatchObject({
      isVersioned: true,
      isCurrent: true,
      isSuperseded: false,
      statusLabel: "当前版本 v2",
      chainLabel: "版本链 2 个版本 · 采用最新版",
      evidenceLabel: "预印本 · 仅用于假设生成",
      reviewDisabledReason: "",
    });
  });

  it("does not add version UI to standalone sources", () => {
    expect(sourceCollectionCandidateVersionFamily(candidate(), "zh")).toBeNull();
  });

  it("counts a version chain once while preserving both records", () => {
    const v1 = candidate({
      familyKey: "doi:10.21203/rs.3.rs-10024823",
      version: 1,
      versionLabel: "v1",
      state: "superseded",
      familySize: 2,
      currentCandidateId: "candidate-v2",
      currentVersionLabel: "v2",
      countsAsIndependentSource: false,
      sourceKind: "research_square_preprint",
      evidencePolicy: "hypothesis_generation_only",
    });
    const v2 = {
      ...candidate({
        ...v1.sourceVersionFamily,
        version: 2,
        versionLabel: "v2",
        state: "current",
        countsAsIndependentSource: true,
      }),
      candidateId: "candidate-v2",
    };

    expect([v1, v2]).toHaveLength(2);
    expect(sourceCollectionIndependentSourceCount([v1, v2])).toBe(1);
  });
});
