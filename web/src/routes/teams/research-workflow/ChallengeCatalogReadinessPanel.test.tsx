/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryState = vi.hoisted(() => ({
  isPending: false,
  isError: false,
  error: null as unknown,
  data: undefined as unknown,
  refetch: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => queryState,
}));
vi.mock("../../../api/teamExperiment", () => ({
  fetchChallengeCatalogReadiness: vi.fn(),
}));

import { ChallengeCatalogReadinessPanel } from "./ChallengeCatalogReadinessPanel";

function readiness(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: 1,
    reportKind: "CatalogHypothesisFlowReadinessReport",
    status: "NOT_READY",
    researchAuthorizationRequired: true,
    realCampaignAllowed: false,
    nextLegalAction: "repair_catalog_hypothesis_flow_readiness",
    sourceCommit: "",
    programContract: {},
    catalogPolicy: {},
    modelPolicySha256: "",
    catalogResultSet: {
      catalogId: "science-125",
      catalogVersion: "1",
      scopeHash: "scope",
      counts: {
        present_count: 12,
        missing_count: 113,
        duplicate_count: 0,
        submission_eligible_count: 0,
        package_backed_count: 12,
        quality_approved_count: 4,
        human_gate_approved_count: 4,
        receipt_complete_count: 2,
        required_question_count: 125,
      },
      selectionApprovedCount: 4,
      researchPlanApprovedCount: 4,
      receiptCompleteCount: 2,
      modelPolicyMatchedCount: 12,
      resultManifest: {},
    },
    evidence: {
      r0: { status: "PASS", locator: "r0" },
      r1: { status: "MISSING", locator: "" },
      api: { status: "BLOCKED", locator: "" },
      frontend: { status: "MISSING", locator: "" },
      browser: { status: "MISSING", locator: "" },
    },
    blockers: ["real_batch_missing", "a very long blocker that should wrap instead of pushing the right rail wider"],
    readinessReportSha256: "hash",
    generatedAt: "2026-08-23T05:00:00Z",
    ...overrides,
  };
}

describe("ChallengeCatalogReadinessPanel", () => {
  beforeEach(() => {
    Object.assign(queryState, {
      isPending: false,
      isError: false,
      error: null,
      data: readiness(),
      refetch: vi.fn(),
    });
  });

  it("uses a separate compact readiness surface and fail-closed evidence", () => {
    const markup = renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" lang="zh" />);
    expect(markup).toContain('data-testid="catalog-readiness"');
    expect(markup).toContain("125");
    expect(markup).toContain("已有结果");
    expect(markup).toContain("R0 来源");
    expect(markup).toContain("缺失");
    expect(markup).toContain("真实批次保持关闭");
    expect(markup).toContain("real-125 结果包尚未生成");
    expect(markup).not.toContain("submission-readiness");
  });

  it("keeps READY honest when real campaigns remain disabled", () => {
    queryState.data = readiness({
      status: "READY",
      blockers: [],
      realCampaignAllowed: false,
      catalogResultSet: {
        ...readiness().catalogResultSet,
        counts: {
          ...readiness().catalogResultSet.counts,
          present_count: 125,
          missing_count: 0,
          submission_eligible_count: 125,
          package_backed_count: 125,
          quality_approved_count: 125,
          human_gate_approved_count: 125,
          receipt_complete_count: 125,
        },
      },
      evidence: {
        r0: { status: "PASS", locator: "r0" },
        r1: { status: "PASS", locator: "r1" },
        api: { status: "PASS", locator: "api" },
        frontend: { status: "PASS", locator: "frontend" },
        browser: { status: "PASS", locator: "browser" },
      },
    });
    const markup = renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" lang="zh" />);
    expect(markup).toContain("主链就绪");
    expect(markup).toContain("仍需单独科研授权");
    expect(markup).toContain("realCampaignAllowed=false");
  });

  it("does not call an incomplete READY payload ready", () => {
    queryState.data = readiness({ status: "READY", blockers: [] });
    const markup = renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" lang="zh" />);
    expect(markup).toContain("边界异常，已阻断");
    expect(markup).not.toContain(">主链就绪</span>");
  });

  it("shows loading, error, and malformed payload states without success fallback", () => {
    queryState.isPending = true;
    expect(renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" />)).toContain("读取 125 题主链状态");

    queryState.isPending = false;
    queryState.isError = true;
    queryState.error = new Error("catalog unavailable");
    expect(renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" />)).toContain("125 题主链状态不可用");

    queryState.isError = false;
    queryState.error = null;
    queryState.data = { status: "READY", realCampaignAllowed: true };
    const malformed = renderToStaticMarkup(<ChallengeCatalogReadinessPanel teamId="team-1" />);
    expect(malformed).toContain("125 题主链未就绪");
    expect(malformed).not.toContain("主链就绪");
  });
});
