/** @vitest-environment happy-dom */
/**
 * Canvas mount for the shared missing-link waiver surface (缺陷⑰ + A05):
 * the knowledge sideflow 证据关系 read panel renders EvidenceGraphView plus
 * the waiver section, and the waiver face reads the RUN-SCOPED missing-link
 * authority of the selected child run — never the team-latest candidate_graph.
 * The waive call carries the CHILD workflow run id the panel received — never
 * a parent/formal run id.
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EvidenceGraphMissingLinksResponse } from "../../../api/researchWorkflow";

const mocks = vi.hoisted(() => ({
  fetchLedger: vi.fn(),
  fetchMissingLinks: vi.fn(),
  waive: vi.fn(),
}));
vi.mock("../../../api/research-workflow", () => ({
  fetchResearchWorkflowResearchLedger: mocks.fetchLedger,
}));
vi.mock("../../../api/researchWorkflow", () => ({
  fetchEvidenceGraphMissingLinks: mocks.fetchMissingLinks,
  waiveEvidenceGraphMissingLink: mocks.waive,
  fetchResearchWorkflowHandoffs: vi.fn(),
}));
vi.mock("../../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

import { KnowledgeChildReadPanel } from "./KnowledgeChildNodeInspector";

const TEAM = "research-team";
const CHILD_RUN_ID = "run-1ca97605acf3";
const OTHER_RUN_ID = "run-other-bbf9";
const MISSING_TARGET = "candidate-20260908171904-9143d4d6";

function missingLinksPayload(
  runId: string,
  missingLinks: Array<Record<string, unknown>>,
): EvidenceGraphMissingLinksResponse {
  return {
    runId,
    teamId: TEAM,
    sourceCollectionRunId: `sc-${runId}`,
    candidateGraphId: `graph-${runId}`,
    missingLinks: missingLinks as EvidenceGraphMissingLinksResponse["missingLinks"],
    summary: { missingLinkCount: missingLinks.length },
  };
}

/** Per-run authority fixtures: B's graph updated later, but A's inspector
 * must only ever see A's own gap. */
const PAYLOAD_A = missingLinksPayload(CHILD_RUN_ID, [
  { sourceCandidateId: "candidate-a", targetCandidateId: MISSING_TARGET, relation: "supports", edgeState: "" },
]);
const PAYLOAD_B = missingLinksPayload(OTHER_RUN_ID, [
  { sourceCandidateId: "candidate-a", targetCandidateId: "candidate-missing-b", relation: "contradicts", edgeState: "" },
]);

function setControlValue(element: Element, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text));
}

const missingLinkRows = () =>
  [...document.body.querySelectorAll('[data-testid="graph-missing-link-row"]')];

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
}

async function mountPanel(
  root: ReturnType<typeof createRoot>,
  container: HTMLElement,
  client: QueryClient,
  runId: string,
) {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <KnowledgeChildReadPanel teamId={TEAM} runId={runId} nodeId="knowledge_ingestion" panel="evidence" />
    </QueryClientProvider>,
  ));
  await settle();
}

beforeEach(() => {
  mocks.fetchLedger.mockReset();
  mocks.fetchMissingLinks.mockReset();
  mocks.waive.mockReset();
  document.body.innerHTML = "";
});

describe("KnowledgeChildReadPanel evidence waiver mount", () => {
  it("renders waiver rows under the evidence graph and waives with the child run id", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({
      graph: { nodes: [{ id: "evidence:ev-1", type: "evidence", claim: "hypothesis A holds" }], edges: [] },
    });
    mocks.fetchMissingLinks.mockResolvedValue(PAYLOAD_A);
    mocks.waive.mockResolvedValue({
      status: "waived",
      alreadyWaived: false,
      teamId: TEAM,
      runId: CHILD_RUN_ID,
      sourceCollectionRunId: "sc-child",
      waiverCount: 1,
      missingLinkCount: 1,
      graphCandidateIds: ["candidate-graph-1"],
      waiver: { by: "local-control-operator", at: "2026-09-08T00:00:00Z", justification: "audited reason" },
    });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);

      // The read-only evidence graph still renders.
      expect(container.textContent).toContain("hypothesis A holds");
      // A05: the run-scoped missing-link read carries the child run + team.
      expect(mocks.fetchMissingLinks).toHaveBeenCalledWith(
        expect.objectContaining({ runId: CHILD_RUN_ID, teamId: TEAM }),
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
      await settle();

      // The waive call carries the CHILD sideflow run id, not a formal run id.
      expect(mocks.waive).toHaveBeenCalledTimes(1);
      expect(mocks.waive.mock.calls[0][0]).toEqual(expect.objectContaining({
        runId: CHILD_RUN_ID,
        teamId: TEAM,
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

  it("stays quiet when the run-scoped graph has no gaps", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    mocks.fetchMissingLinks.mockResolvedValue(
      missingLinksPayload(CHILD_RUN_ID, []),
    );

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);

      expect(document.body.querySelector('[data-testid="graph-missing-link-graph-unavailable"]')).toBeNull();
      expect(missingLinkRows()).toHaveLength(0);
      expect(buttonByText("豁免")).toBeFalsy();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  // The scoped endpoint answers 404 graph_not_found when this run has no
  // candidate graph at all: the surface degrades to the hint.
  it("shows the graph-unavailable hint while the run-scoped graph has not loaded", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    mocks.fetchMissingLinks.mockRejectedValue(
      Object.assign(new Error("graph_not_found"), { name: "FetchJsonHttpError", status: 404, code: "graph_not_found" }),
    );

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);

      expect(document.body.querySelector('[data-testid="graph-missing-link-graph-unavailable"]')).not.toBeNull();
      expect(buttonByText("豁免")).toBeFalsy();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  // A05: same team, two child runs; B's graph updated later. Opening A must
  // only ever render A's gaps — switching runs must not leak B's authority.
  it("renders only the selected run's gaps across A/B switches without cache leakage", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    mocks.fetchMissingLinks.mockImplementation((options: { runId: string }) =>
      options.runId === CHILD_RUN_ID ? Promise.resolve(PAYLOAD_A) : Promise.resolve(PAYLOAD_B));

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);
      expect(missingLinkRows()).toHaveLength(1);
      expect(missingLinkRows()[0].textContent).toContain(`supports: candidate-a → ${MISSING_TARGET}`);

      await mountPanel(root, container, client, OTHER_RUN_ID);
      expect(missingLinkRows()).toHaveLength(1);
      expect(missingLinkRows()[0].textContent).toContain("contradicts: candidate-a → candidate-missing-b");
      expect(missingLinkRows()[0].textContent).not.toContain(MISSING_TARGET);

      await mountPanel(root, container, client, CHILD_RUN_ID);
      expect(missingLinkRows()).toHaveLength(1);
      expect(missingLinkRows()[0].textContent).toContain(MISSING_TARGET);
      expect(missingLinkRows()[0].textContent).not.toContain("candidate-missing-b");
      const fetchedRuns = mocks.fetchMissingLinks.mock.calls.map((call) => call[0].runId);
      expect(fetchedRuns).toContain(CHILD_RUN_ID);
      expect(fetchedRuns).toContain(OTHER_RUN_ID);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  // A05: an unreadable scoped graph must degrade to the hint, never fall back
  // to another run's gap list.
  it("keeps the unavailable hint when the scoped read fails instead of showing another run's gaps", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    mocks.fetchMissingLinks.mockImplementation((options: { runId: string }) =>
      options.runId === CHILD_RUN_ID ? Promise.reject(new Error("graph_not_found")) : Promise.resolve(PAYLOAD_B));

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);
      expect(document.body.querySelector('[data-testid="graph-missing-link-graph-unavailable"]')).not.toBeNull();
      expect(missingLinkRows()).toHaveLength(0);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  // A05 acceptance: after a confirmed waiver the same run-scoped query is
  // refetched and the row flips to the waived badge.
  it("refetches the run-scoped missing-link query after a confirmed waiver", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.fetchLedger.mockResolvedValue({ graph: { nodes: [], edges: [] } });
    let fetchCount = 0;
    mocks.fetchMissingLinks.mockImplementation((options: { runId: string }) => {
      if (options.runId !== CHILD_RUN_ID) return Promise.reject(new Error("unexpected run"));
      fetchCount += 1;
      return fetchCount === 1 ? Promise.resolve(PAYLOAD_A) : Promise.resolve(missingLinksPayload(CHILD_RUN_ID, [
        {
          sourceCandidateId: "candidate-a",
          targetCandidateId: MISSING_TARGET,
          relation: "supports",
          edgeState: "",
          waived: true,
          status: "waived",
          waiver: { by: "local-control-operator", at: "2026-09-09T00:00:00Z", justification: "audited decision text" },
        },
      ]));
    });
    mocks.waive.mockResolvedValue({
      status: "waived",
      alreadyWaived: false,
      teamId: TEAM,
      runId: CHILD_RUN_ID,
      sourceCollectionRunId: `sc-${CHILD_RUN_ID}`,
      waiverCount: 1,
      missingLinkCount: 1,
      graphCandidateIds: ["graph-child"],
      waiver: { by: "local-control-operator", at: "2026-09-09T00:00:00Z", justification: "audited decision text" },
    });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      await mountPanel(root, container, client, CHILD_RUN_ID);
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
      await settle();

      expect(mocks.waive).toHaveBeenCalledTimes(1);
      expect(mocks.waive.mock.calls[0][0]).toMatchObject({ runId: CHILD_RUN_ID, teamId: TEAM });
      expect(document.body.querySelector('[data-testid="graph-missing-link-waived"]')).not.toBeNull();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });
});
