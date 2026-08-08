/**
 * EvidenceGraphView contracts:
 * - idle state offers the generate action with an honest description;
 * - the pure graph renderer groups evidence/claim/source nodes, renders edges
 *   and explains an empty projection instead of faking a graph.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EvidenceGraphContent, type EvidenceGraphDto } from "./EvidenceGraphView";

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
