/**
 * Node-detail state hook contracts: loading / error(retry) / empty states and
 * cross-node switch cleanup (no stale detail flash on the new selection).
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  fetchResearchWorkflowNodeDetail: vi.fn(),
}));

vi.mock("../../../api/researchWorkflow", () => api);

import { useNodeDetailState, type NodeDetailState } from "./useNodeDetailState";

function Probe({
  teamId,
  runId,
  nodeId,
  onValue,
}: {
  teamId: string;
  runId: string;
  nodeId: string | null;
  onValue: (state: NodeDetailState, retry: () => void) => void;
}) {
  const { state, retry } = useNodeDetailState(teamId, runId, nodeId);
  onValue(state, retry);
  return null;
}

describe("useNodeDetailState", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: NodeDetailState = { kind: "idle" };
  let latestRetry: () => void = () => {};

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = { kind: "idle" };
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
    api.fetchResearchWorkflowNodeDetail.mockReset();
  });

  async function renderWith(runId: string, nodeId: string | null) {
    await act(async () => {
      root.render(
        <Probe
          teamId="team-1"
          runId={runId}
          nodeId={nodeId}
          onValue={(state, retry) => {
            latest = state;
            latestRetry = retry;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("goes idle without a node selection", async () => {
    await renderWith("run-1", null);
    expect(latest.kind).toBe("idle");
  });

  it("transitions loading -> ready with the node detail", async () => {
    api.fetchResearchWorkflowNodeDetail.mockResolvedValue({
      runId: "run-1",
      nodeId: "source_finding",
      label: "资料寻找",
      commands: [],
    });
    await renderWith("run-1", "source_finding");
    expect(latest.kind).toBe("ready");
    if (latest.kind === "ready") {
      expect(latest.detail.nodeId).toBe("source_finding");
    }
    expect(api.fetchResearchWorkflowNodeDetail).toHaveBeenCalledWith(
      "run-1",
      "source_finding",
      { teamId: "team-1" },
    );
  });

  it("surfaces a retryable error state on failure and retries", async () => {
    api.fetchResearchWorkflowNodeDetail.mockRejectedValueOnce(new Error("boom"));
    await renderWith("run-1", "source_finding");
    expect(latest.kind).toBe("error");
    if (latest.kind === "error") {
      expect(latest.message).toContain("boom");
    }

    api.fetchResearchWorkflowNodeDetail.mockResolvedValueOnce({
      runId: "run-1",
      nodeId: "source_finding",
      label: "资料寻找",
      commands: [],
    });
    await act(async () => {
      latestRetry();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(latest.kind).toBe("ready");
  });

  it("clears the previous node detail when the selection switches (no flash)", async () => {
    api.fetchResearchWorkflowNodeDetail.mockResolvedValue({
      runId: "run-1",
      nodeId: "source_finding",
      label: "资料寻找",
      commands: [],
    });
    await renderWith("run-1", "source_finding");
    expect(latest.kind).toBe("ready");

    // Switch to another node. The state sequence observed after the switch
    // render must never show the OLD node's ready detail: it goes loading
    // (old detail cleared) and then ready with the NEW node.
    const observed: NodeDetailState[] = [];
    api.fetchResearchWorkflowNodeDetail.mockImplementation(() => {
      observed.push(latest);
      return Promise.resolve({
        runId: "run-1",
        nodeId: "protocol_design",
        label: "协议设计",
        commands: [],
      });
    });
    await act(async () => {
      root.render(
        <Probe
          teamId="team-1"
          runId="run-1"
          nodeId="protocol_design"
          onValue={(state, retry) => {
            latest = state;
            latestRetry = retry;
            observed.push(state);
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    // No observed state after the switch may carry the old node detail.
    for (const state of observed) {
      if (state.kind === "ready") {
        expect(state.detail.nodeId).toBe("protocol_design");
      }
    }
    expect(latest.kind).toBe("ready");
    if (latest.kind === "ready") {
      expect(latest.detail.nodeId).toBe("protocol_design");
    }
    expect(observed.some((state) => state.kind === "loading")).toBe(true);
  });
});
