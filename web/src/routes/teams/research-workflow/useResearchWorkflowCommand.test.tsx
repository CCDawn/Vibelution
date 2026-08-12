/**
 * Behavioral tests for useResearchWorkflowCommand.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { CommandOffer } from "../../../api/types/research-workflow/commands";

const api = vi.hoisted(() => ({
  submitResearchWorkflowCommandOffer: vi.fn(),
}));

vi.mock("../../../api/research-workflow/commands", () => api);

import { useResearchWorkflowCommand } from "./useResearchWorkflowCommand";

function makeOffer(available: boolean): CommandOffer {
  return {
    command: "start_node",
    nodeId: "source_finding",
    available,
    label: "启动",
    reasonCode: available ? "ready" : "blocked",
    blockerIds: [],
    idempotencyKey: "offer:run-a:source_finding:start_node:v1",
    expectedRunVersion: 1,
    payload: {},
  };
}

type HookValue = ReturnType<typeof useResearchWorkflowCommand>;

function HookProbe(props: {
  runId: string;
  nodeId: string | null;
  onValue: (value: HookValue) => void;
}) {
  const value = useResearchWorkflowCommand("research-team", props.runId, props.nodeId);
  props.onValue(value);
  return null;
}

describe("useResearchWorkflowCommand", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function renderScope(runId: string, nodeId: string | null) {
    await act(async () => {
      root.render(
        <HookProbe
          runId={runId}
          nodeId={nodeId}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("rejects unavailable offers before calling the API", async () => {
    await renderScope("run-a", "source_finding");
    let captured: unknown;
    await act(async () => {
      try {
        await latest!.submit(makeOffer(false));
      } catch (reason) {
        captured = reason;
      }
    });
    expect(captured).toBeInstanceOf(Error);
    expect(api.submitResearchWorkflowCommandOffer).not.toHaveBeenCalled();
    expect(latest?.commandError).toBeTruthy();
  });

  it("clears commandError when runId or nodeId changes", async () => {
    api.submitResearchWorkflowCommandOffer.mockRejectedValue(new Error("command_http_409"));
    await renderScope("run-a", "source_finding");
    await act(async () => {
      try {
        await latest!.submit(makeOffer(true));
      } catch {
        // expected
      }
    });
    expect(latest?.commandError).toContain("command_http_409");

    await renderScope("run-b", "source_extraction");
    expect(latest?.commandError).toBeNull();
  });
});
