import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../client";
import type {
  ResearchWorkflowNodeDetail,
  ResearchWorkflowSnapshot,
} from "../types/research-workflow/core";
import {
  fetchResearchWorkflowNodeDetail,
  fetchResearchWorkflowSnapshot,
} from "./runs";

describe("research workflow guarded reads", () => {
  beforeEach(() => {
    resetControlTokenForTests();
    seedControlTokenForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it.each([
    {
      label: "snapshot",
      request: () =>
        fetchResearchWorkflowSnapshot({
          runId: "run-a",
          teamId: "research-team",
        }),
      payload: { run: { runId: "run-a" } } as ResearchWorkflowSnapshot,
      expectedUrl:
        "/api/research/workflow-runs/run-a/snapshot?teamId=research-team",
    },
    {
      label: "node detail",
      request: () =>
        fetchResearchWorkflowNodeDetail({
          runId: "run-a",
          nodeId: "hf_convergence_gate",
          teamId: "research-team",
        }),
      payload: { nodeId: "hf_convergence_gate" } as ResearchWorkflowNodeDetail,
      expectedUrl:
        "/api/research/workflow-runs/run-a/nodes/hf_convergence_gate?teamId=research-team",
    },
  ])("attaches the control token to the $label request", async ({ request, payload, expectedUrl }) => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => payload,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request()).resolves.toBe(payload);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(expectedUrl);
    expect(new Headers(init?.headers).get("X-Vibelution-Control-Token")).toBe(
      "test-control-token",
    );
  });
});
