import { describe, expect, it } from "vitest";

import type { DataProcessingRecord, TeamWorkflowCandidate } from "../../../api/types";
import {
  deriveSourceCollectionExcludedRecoveryState,
  sourceCollectionCandidateEmptyStateText,
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerActionLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionFilterCounts,
  sourceCollectionRecordProvenance,
  sourceCollectionRecordSourceCategory,
} from "./evidenceModel";

function candidateFixture(
  extra: Partial<TeamWorkflowCandidate> & Record<string, unknown> = {},
): TeamWorkflowCandidate {
  return {
    schemaVersion: 1,
    candidateId: "candidate-1",
    candidateType: "source",
    teamId: "research-team",
    workflowId: "workflow-1",
    title: "Candidate",
    summary: "Summary",
    currentWorkflowNode: "source_extraction",
    currentState: "ready",
    qualityStatus: "pending",
    metadata: {},
    createdByAgent: "source_extractor",
    createdAt: "2026-07-13T00:00:00Z",
    updatedAt: "2026-07-13T00:00:00Z",
    ...extra,
  } as TeamWorkflowCandidate;
}

function recordFixture(extra: Partial<DataProcessingRecord> = {}): DataProcessingRecord {
  return {
    schemaVersion: 1,
    recordId: "record-1",
    runId: "run-1",
    sourceType: "file",
    sourceRef: "",
    rawLocation: "C:\\knowledge\\paper.pdf",
    title: "Record",
    summary: "Summary",
    status: "ready",
    metadata: {},
    qualitySignals: {},
    collectionTrace: {},
    createdAt: "2026-07-13T00:00:00Z",
    updatedAt: "2026-07-13T00:00:00Z",
    ...extra,
  };
}

describe("source collection evidence model", () => {
  it("prefers DOI anchors and classifies them as paper-web sources", () => {
    const candidate = candidateFixture({ metadata: { doi: "doi:10.1234/example.1" } });

    expect(sourceCollectionCandidateProvenance(candidate, "zh")).toEqual({
      kind: "doi",
      label: "DOI",
      value: "10.1234/example.1",
      href: "https://doi.org/10.1234/example.1",
    });
    expect(sourceCollectionCandidateSourceCategory(candidate, "zh")).toBe("paper_web");
  });

  it.each([
    [{ sourceUrl: "https://example.org/paper.pdf" }, "pdf"],
    [{ sourceKind: "dataset", sourceUrl: "https://example.org/data" }, "dataset"],
    [{ sourcePath: "C:\\knowledge\\note.md", sourceKind: "file" }, "local_file"],
    [{ sourceUrl: "https://api.crossref.org/works/10.1/test" }, "missing"],
    [{}, "missing"],
  ] as const)("classifies candidate source facts %#", (extra, expected) => {
    expect(sourceCollectionCandidateSourceCategory(candidateFixture(extra), "zh")).toBe(expected);
  });

  it("keeps machine-search evidence non-clickable instead of presenting it as a source", () => {
    expect(sourceCollectionCandidateProvenance(
      candidateFixture({ sourceUrl: "https://api.openalex.org/works/W123" }),
      "zh",
    )).toEqual({
      kind: "search_evidence",
      label: "仅搜索记录",
      value: "api.openalex.org/works/W123",
      href: "",
    });
  });

  it("classifies local PDF records and preserves their open target", () => {
    const record = recordFixture();

    expect(sourceCollectionRecordProvenance(record, "zh")).toEqual({
      kind: "file",
      label: "本地文件",
      value: "C:\\knowledge\\paper.pdf",
      href: "",
    });
    expect(sourceCollectionRecordSourceCategory(record, "zh")).toBe("pdf");
  });

  it("counts every source category while keeping the aggregate total", () => {
    expect(sourceCollectionFilterCounts(["pdf", "pdf", "paper_web", "missing"])).toEqual({
      all: 4,
      pdf: 2,
      paper_web: 1,
      dataset: 0,
      local_file: 0,
      missing: 1,
    });
  });

  it("projects Evidence Ledger missing-anchor facts without UI component types", () => {
    const summary = sourceCollectionEvidenceLedgerSummary(candidateFixture({
      metadata: {
        contentExtraction: {
          evidenceLedger: {
            status: "missing_evidence_anchor",
            claims: [{ claim: "Claim A" }],
            keyFindings: [{ finding: "Finding A" }],
            citations: [],
            sourceRefs: [],
            evidenceRefs: [],
            limitations: ["Small sample"],
            nextAction: "Attach a page anchor",
          },
        },
      },
    }));

    expect(summary).toMatchObject({
      status: "missing_evidence_anchor",
      missingAnchor: true,
      claimCount: 1,
      keyFindingCount: 1,
      sourceRefCount: 0,
      evidenceRefCount: 0,
      limitations: ["Small sample"],
      nextAction: "Attach a page anchor",
    });
    expect(summary && sourceCollectionEvidenceLedgerActionLabel(summary, "zh")).toBe("补证据锚点");
    expect(summary && sourceCollectionEvidenceLedgerTone(summary)).toBe("warning");
  });

  it("reconstructs candidate trace identity from record metadata and evidence refs", () => {
    const candidate = candidateFixture({
      metadata: {
        assignmentId: "assignment-1",
        queryId: "query-1",
        importedFromDataRecord: {
          recordId: "record-1",
          runId: "run-1",
          rawLocation: "C:\\knowledge\\paper.pdf",
        },
      },
      evidenceRefs: [
        { type: "data_record", id: "record-fallback" },
        { type: "data_processing_run", id: "run-fallback" },
      ],
    });

    expect(sourceCollectionCandidateTrace(candidate)).toMatchObject({
      assignmentId: "assignment-1",
      queryId: "query-1",
      recordId: "record-1",
      runId: "run-1",
      rawLocation: "C:\\knowledge\\paper.pdf",
    });
  });

  it("treats a fully excluded extraction gap as progressable recovery", () => {
    const state = deriveSourceCollectionExcludedRecoveryState({
      lang: "zh",
      excludedCount: 10,
      missingCount: 10,
      importFailedCount: 10,
      importPendingRecordCount: 10,
    });

    expect(state).toMatchObject({
      blockedByExcludedSources: true,
      excludedCount: 10,
      tone: "progressable",
      panelTitle: "提炼排除项确认",
      statusLabel: "可继续推进",
      recoverText: "已排除 10",
      primaryActionText: "查看排除原因",
    });
    expect(state.summary).toContain("剩余 10 条资料已被排除");
  });

  it("keeps normal recovery when exclusions cover only part of the gap", () => {
    expect(deriveSourceCollectionExcludedRecoveryState({
      lang: "zh",
      excludedCount: 2,
      missingCount: 10,
      importFailedCount: 2,
      importPendingRecordCount: 10,
    }).blockedByExcludedSources).toBe(false);
  });

  it("keeps candidate empty-state loading and stage recovery facts explicit", () => {
    expect(sourceCollectionCandidateEmptyStateText({
      lang: "zh",
      loading: true,
      awaitingRefresh: false,
      displayedCandidateCount: 0,
      filteredCandidateCount: 0,
      rawRecordCount: 0,
    })).toBe("正在加载资料提炼结果...");
    expect(sourceCollectionCandidateEmptyStateText({
      lang: "zh",
      loading: false,
      awaitingRefresh: false,
      displayedCandidateCount: 0,
      filteredCandidateCount: 0,
      rawRecordCount: 3,
    })).toContain("已收到 3 条原始资料");
  });
});
