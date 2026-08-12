/**
 * Behavioral command orchestration tests.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { useResearchWorkflowCommands } from "./useResearchWorkflowCommands";

const offer: CommandOffer = {
  command: "start_node",
  nodeId: "source_finding",
  available: true,
  label: "启动 资料寻找",
  reasonCode: "ready",
  blockerIds: [],
  idempotencyKey: "offer:run-parent:source_finding:start_node:v9",
  expectedRunVersion: 9,
  payload: {},
};

type HookValue = ReturnType<typeof useResearchWorkflowCommands>;

function Probe(props: {
  submitFormalOffer?: (next: CommandOffer) => Promise<unknown>;
  refresh: () => Promise<void>;
  onValue: (value: HookValue) => void;
}) {
  const value = useResearchWorkflowCommands({
    teamId: "research-team",
    runId: "run-parent",
    selectedNodeId: "source_finding",
    run: {
      runId: "run-parent",
      runVersion: 9,
      humanTasks: [],
    } as WorkflowRunRecord,
    nodeDetail: {
      nodeId: "source_finding",
      commandOffers: [offer],
    } as ResearchWorkflowNodeDetail,
    commandOffers: [offer],
    submitFormalOffer: props.submitFormalOffer,
    createRun: vi.fn(),
    refresh: props.refresh,
    replaceParams: vi.fn(),
  });
  props.onValue(value);
  return null;
}

describe("useResearchWorkflowCommands", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(
    refresh: ReturnType<typeof vi.fn>,
    submitFormalOffer?: (next: CommandOffer) => Promise<unknown>,
  ) {
    await act(async () => {
      root.render(
        <Probe
          submitFormalOffer={submitFormalOffer}
          refresh={refresh}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
    });
  }

  it("submits the signed CommandOffer and refreshes the snapshot", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const submitFormalOffer = vi.fn().mockResolvedValue({ commandId: "cmd-1" });
    await render(refresh, submitFormalOffer);

    await act(async () => {
      await latest!.submitOffer(offer);
    });

    expect(submitFormalOffer).toHaveBeenCalledWith(offer);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(latest!.error).toBeNull();
  });

  it("fails visibly when the formal command channel is missing", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    await render(refresh);

    let captured: unknown;
    await act(async () => {
      try {
        await latest!.submitOffer(offer);
      } catch (reason) {
        captured = reason;
      }
    });

    expect(captured).toBeInstanceOf(Error);
    expect((captured as Error).message).toContain("正式命令通道未就绪");
    expect(refresh).not.toHaveBeenCalled();
    expect(latest!.error).toContain("正式命令通道未就绪");
  });
});
