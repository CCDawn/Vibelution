/** @vitest-environment happy-dom */
/**
 * EvidenceGraphView contracts:
 * - entering the panel reads existing evidence without a second click;
 * - the pure graph renderer groups evidence/claim/source nodes, renders edges
 *   and explains an empty projection instead of faking a graph.
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { EvidenceGraphView, EvidenceGraphContent, type EvidenceGraphDto } from "./EvidenceGraphView";
const fetchLedger = vi.hoisted(() => vi.fn());
vi.mock("../../../api/research-workflow", () => ({ fetchResearchWorkflowResearchLedger: fetchLedger }));
vi.mock("../../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

it("loads evidence automatically and clears the previous run while the next run loads", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  fetchLedger.mockResolvedValueOnce({ graph: {nodes: [{id: "one", type: "source", title: "First run source"}], edges: []} });
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const container = document.createElement("div"); const root = createRoot(container);
  const view = (runId: string) => <QueryClientProvider client={client}><EvidenceGraphView runId={runId} teamId="team" /></QueryClientProvider>;
  await act(async () => root.render(view("run-one")));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(fetchLedger).toHaveBeenCalledWith("run-one", {teamId: "team"});
  expect(container.textContent).toContain("First run source");
  expect(container.textContent).not.toContain("生成证据图");
  fetchLedger.mockImplementationOnce(() => new Promise(() => undefined));
  await act(async () => root.render(view("run-two")));
  expect(container.textContent).not.toContain("First run source");
  expect(container.textContent).toContain("读取证据记录");
  await act(async () => root.unmount()); client.clear();
});

const GRAPH: EvidenceGraphDto = {
  nodes: [
    { id: "evidence:ev-1", type: "evidence", evidenceId: "ev-1", claim: "hypothesis A holds", evidenceType: "benchmark_result", status: "passed" },
    { id: "claim:ev-1", type: "claim", claim: "hypothesis A holds" },
    { id: "source:s-1", type: "source", title: "source-1" },
  ],
  edges: [
    { source: "source:s-1", target: "evidence:ev-1", kind: "supports" },
    { source: "evidence:ev-1", target: "claim:ev-1", kind: "derives" },
  ],
};

describe("EvidenceGraphContent", () => {
  it("renders grouped nodes with claims and edges", () => {
    const markup = renderToStaticMarkup(<EvidenceGraphContent graph={GRAPH} />);
    expect(markup).toContain("证据（1）");
    expect(markup).toContain("声明（1）");
    expect(markup).toContain("来源（1）");
    expect(markup).toContain("hypothesis A holds");
    expect(markup).toContain("benchmark_result");
    expect(markup).toContain("source-1");
    expect(markup).toContain("—支持→");
    expect(markup).toContain("—推导→");
    expect(markup).toContain("3 节点 / 2 关系");
  });

  it("explains an empty projection instead of inventing nodes", () => {
    const markup = renderToStaticMarkup(
      <EvidenceGraphContent graph={{ nodes: [], edges: [] }} />,
    );
    expect(markup).toContain("暂无图数据");
    expect(markup).toContain("0 节点 / 0 关系");
  });

  it("labels unknown edge kinds verbatim", () => {
    const markup = renderToStaticMarkup(
      <EvidenceGraphContent
        graph={{
          nodes: [{ id: "a", type: "evidence" }],
          edges: [{ source: "a", target: "b", kind: "contradicts" }],
        }}
      />,
    );
    expect(markup).toContain("contradicts");
  });
});
