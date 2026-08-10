/**
 * Behavioral command orchestration tests.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";

const adapter = vi.hoisted(() => ({
  executeNodeCommand: vi.fn(),
  childRunIdFromCommandResult: vi.fn(),
}));

vi.mock("./nodeCommandAdapter", () => adapter);

import { useResearchWorkflowCommands } from "./useResearchWorkflowCommands";

type HookValue = ReturnType<typeof useResearchWorkflowCommands>;

function Probe(props: {
  replaceParams: (patch: Record<string, string | null | undefined>) => void;
  refresh: () => Promise<void>;
  onValue: (value: HookValue) => void;
}) {
  const value = useResearchWorkflowCommands({
    teamId: "research-team",
    runId: "run-parent",
    selectedNodeId: "source_extraction",
    run: {
      runId: "run-parent",
      runVersion: 9,
      humanTasks: [],
    } as WorkflowRunRecord,
    nodeDetail: {
      commands: [{
        command: "fork_evidence_remediation",
        available: true,
        reason: "",
        idempotencyKey: "remediate-1",
        payload: { evidenceGapCandidateIds: ["candidate-a"] },
      }],
    } as ResearchWorkflowNodeDetail,
    createRun: vi.fn(),
    resolveHuman: vi.fn(),
    refresh: props.refresh,
    replaceParams: props.replaceParams,
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

  async function render(replaceParams: ReturnType<typeof vi.fn>, refresh: ReturnType<typeof vi.fn>) {
    await act(async () => {
      root.render(<Probe replaceParams={replaceParams} refresh={refresh} onValue={(value) => { latest = value; }} />);
    });
  }

  it("navigates to the remediation child run instead of refreshing the superseded parent", async () => {
    const replaceParams = vi.fn();
    const refresh = vi.fn().mockResolvedValue(undefined);
    adapter.executeNodeCommand.mockResolvedValue({
      command: "fork_evidence_remediation",
      message: "ok",
      raw: { childRunIds: ["run-child"] },
    });
    adapter.childRunIdFromCommandResult.mockReturnValue("run-child");
    await render(replaceParams, refresh);

    await act(async () => {
      await latest!.runInspectorCommand("fork_evidence_remediation", {
        operatorReason: "补齐正文证据锚点",
      });
    });

    expect(replaceParams).toHaveBeenCalledWith({
      runId: "run-child",
      node: "source_extraction",
      panel: "node",
    });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("fails visibly when the backend response has no child run id", async () => {
    const replaceParams = vi.fn();
    const refresh = vi.fn().mockResolvedValue(undefined);
    adapter.executeNodeCommand.mockResolvedValue({
      command: "fork_evidence_remediation",
      message: "ok",
      raw: { childRunIds: [] },
    });
    adapter.childRunIdFromCommandResult.mockReturnValue(null);
    await render(replaceParams, refresh);

    let captured: unknown;
    await act(async () => {
      try {
        await latest!.runInspectorCommand("fork_evidence_remediation");
      } catch (reason) {
        captured = reason;
      }
    });

    expect(captured).toBeInstanceOf(Error);
    expect((captured as Error).message).toContain("响应缺少 childRunIds");
    expect(replaceParams).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
    expect(latest!.error).toContain("响应缺少 childRunIds");
  });
});
