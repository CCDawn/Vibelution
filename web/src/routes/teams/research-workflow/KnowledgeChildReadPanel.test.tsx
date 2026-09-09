/** @vitest-environment happy-dom */
/**
 * Canvas mount for the shared missing-link waiver surface (缺陷⑰):
 * the knowledge sideflow 证据关系 read panel renders EvidenceGraphView plus
 * the waiver section, and the waive call carries the CHILD workflow run id
 * the panel received — never a parent/formal run id.
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchLedger: vi.fn(),
  fetchCandidates: vi.fn(),
  waive: vi.fn(),
}));
vi.mock("../../../api/research-workflow", () => ({
  fetchResearchWorkflowResearchLedger: mocks.fetchLedger,
}));
vi.mock("../../../api/teamExperiment", () => ({
  fetchTeamWorkflowCandidates: mocks.fetchCandidates,
}));
vi.mock("../../../api/researchWorkflow", () => ({
  waiveEvidenceGraphMissingLink: mocks.waive,
}));
vi.mock("../../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

import { KnowledgeChildReadPanel } from "./KnowledgeChildNodeInspector";

const CHILD_RUN_ID = "run-1ca97605acf3";
const MISSING_TARGET = "candidate-20260908171904-9143d4d6";

function candidateGraphRecord() {
  return {
    candidateId: "candidate-graph-1",
    candidateType: "candidate_graph",
    teamId: "research-team",
    workflowId: "wf",
    title: "graph",
    summary: "",
    currentWorkflowNode: "candidate_graph",
    currentState: "ready",
    qualityStatus: "preview_ready",
    metadata: {
      graph: {
        schemaVersion: 1,
        teamId: "research-team",
        workflowId: "wf",
        graphKind: "candidate_only",
        nodes: [],
        edges: [],
        missingLinks: [
          {
            sourceCandidateId: "candidate-a",
            targetCandidateId: MISSING_TARGET,
            relation: "supports",
            edgeState: "",
          },
        ],
        unreviewedNodes: [],
        officialBoundary: {
          writesOfficialKnowledge: false,
          writesOfficialRag: false,
          writesOfficialGraph: false,
          requiresIngestionApproval: true,
        },
        summary: { nodeCount: 0, edgeCount: 0, missingLinkCount: 1, unreviewedNodeCount: 0 },
        createdAt: "2026-09-08T00:00:00Z",
      },
    },
    createdByAgent: "agent",
    createdAt: "2026-09-08T00:00:00Z",
    updatedAt: "2026-09-08T00:00:00Z",
  };
}

function setControlValue(element: Element, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text));
}

beforeEach(() => {
  mocks.fetchLedger.mockReset();
  mocks.fetchCandidates.mockReset();
  mocks.waive.mockReset();
  document.body.innerHTML = "";
});

describe("KnowledgeChildReadPanel evidence waiver mount", () => {
  it("renders waiver rows under the evidence graph and waives with the child run id", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({
      graph: { nodes: [{ id: "evidence:ev-1", type: "evidence", claim: "hypothesis A holds" }], edges: [] },
    });
    mocks.fetchCandidates.mockResolvedValue({ candidates: [candidateGraphRecord()] });
    mocks.waive.mockResolvedValue({
      status: "waived",
      alreadyWaived: false,
      teamId: "research-team",
      runId: CHILD_RUN_ID,
      sourceCollectionRunId: "sc-child",
      waiverCount: 1,
      missingLinkCount: 0,
      graphCandidateIds: ["candidate-graph-1"],
      waiver: { by: "local-control-operator", at: "2026-09-08T00:00:00Z", justification: "audited reason" },
    });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await act(async () => root.render(
        <QueryClientProvider client={client}>
          <KnowledgeChildReadPanel teamId="research-team" runId={CHILD_RUN_ID} nodeId="knowledge_ingestion" panel="evidence" />
        </QueryClientProvider>,
      ));
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });

      // The read-only evidence graph still renders.
      expect(container.textContent).toContain("hypothesis A holds");
      // Candidate graph read through the shared team-scope query.
      expect(mocks.fetchCandidates).toHaveBeenCalledWith(
        "research-team",
        expect.objectContaining({ candidateType: "candidate_graph" }),
      );
      // Waiver rows mount with the evidence view.
      expect(document.body.querySelector('[data-testid="graph-missing-link-row"]')).not.toBeNull();
      expect(container.textContent).toContain(`supports: candidate-a → ${MISSING_TARGET}`);

      await act(async () => {
        buttonByText("豁免")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      const input = document.body.querySelector('input[aria-label="豁免理由"]') as HTMLInputElement;
      await act(async () => {
        setControlValue(input, "relation mapper asserted a random candidate id typo; reviewed and accepted");
      });
      await act(async () => {
        (
          document.body.querySelector('[data-testid="graph-missing-link-waive-confirm"]') as HTMLButtonElement
        ).dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });

      // The waive call carries the CHILD sideflow run id, not a formal run id.
      expect(mocks.waive).toHaveBeenCalledTimes(1);
      expect(mocks.waive.mock.calls[0][0]).toEqual(expect.objectContaining({
        runId: CHILD_RUN_ID,
        teamId: "research-team",
        sourceCandidateId: "candidate-a",
        targetCandidateId: MISSING_TARGET,
        relation: "supports",
        confirmed: true,
      }));
      expect(document.body.querySelector('[data-testid="graph-missing-link-notice"]')?.textContent).toContain(
        "不再阻塞知识入库就绪门",
      );
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it("shows the graph-unavailable hint while no candidate graph is loaded", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    mocks.fetchCandidates.mockResolvedValue({ candidates: [] });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await act(async () => root.render(
        <QueryClientProvider client={client}>
          <KnowledgeChildReadPanel teamId="research-team" runId={CHILD_RUN_ID} nodeId="knowledge_ingestion" panel="evidence" />
        </QueryClientProvider>,
      ));
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });

      expect(document.body.querySelector('[data-testid="graph-missing-link-graph-unavailable"]')).not.toBeNull();
      expect(buttonByText("豁免")).toBeFalsy();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });
});
