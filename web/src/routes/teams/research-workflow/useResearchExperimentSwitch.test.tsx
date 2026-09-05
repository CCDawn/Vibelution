/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import type { ExperimentSwitchOption } from "./researchExperimentSwitchModel";
import { useResearchExperimentSwitch } from "./useResearchExperimentSwitch";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("./hypothesisFirstFocus", () => ({
  fetchHypothesisFirstFocusNode: vi.fn(),
}));

const mockedFocus = vi.mocked(fetchHypothesisFirstFocusNode);
const experiments: ExperimentSwitchOption[] = [
  {
    questionId: "SCI-001",
    title: "First",
    runId: "run-1",
    currentNodeId: "hf_collection",
    label: "SCI-001",
    description: "First",
  },
  {
    questionId: "SCI-002",
    title: "Second",
    runId: "run-2",
    currentNodeId: "hf_selection",
    label: "SCI-002",
    description: "Second",
  },
];

type HookValue = ReturnType<typeof useResearchExperimentSwitch>;

function Probe(props: {
  replaceParams: (patch: Record<string, string | null | undefined>) => void;
  onValue: (value: HookValue) => void;
}) {
  props.onValue(useResearchExperimentSwitch({
    teamId: "research-team",
    experiments,
    replaceParams: props.replaceParams,
  }));
  return null;
}

describe("useResearchExperimentSwitch", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null;

  beforeEach(async () => {
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

  async function render(replaceParams: ReturnType<typeof vi.fn>) {
    await act(async () => {
      root.render(<Probe replaceParams={replaceParams} onValue={(value) => { latest = value; }} />);
    });
  }

  it("keeps the latest experiment when an older focus request resolves last", async () => {
    const resolvers = new Map<string, (node: string) => void>();
    mockedFocus.mockImplementation((_teamId, questionId) => new Promise((resolve) => {
      resolvers.set(questionId, resolve);
    }));
    const replaceParams = vi.fn();
    await render(replaceParams);

    act(() => {
      latest!.selectExperiment("SCI-001");
      latest!.selectExperiment("SCI-002");
    });
    await act(async () => {
      resolvers.get("SCI-002")?.("hf_generation");
      await Promise.resolve();
      resolvers.get("SCI-001")?.("hf_collection");
      await Promise.resolve();
    });

    expect(replaceParams).toHaveBeenCalledTimes(1);
    expect(replaceParams).toHaveBeenCalledWith(expect.objectContaining({
      questionId: "SCI-002",
      runId: "run-2",
      node: "hf_generation",
    }));
  });

  it("switches to the checkpoint and exposes an error when focus lookup fails", async () => {
    mockedFocus.mockRejectedValue(new Error("offline"));
    const replaceParams = vi.fn();
    await render(replaceParams);

    await act(async () => {
      latest!.selectExperiment("SCI-002");
      await Promise.resolve();
    });

    expect(replaceParams).toHaveBeenCalledWith({
      questionId: "SCI-002",
      runId: "run-2",
      node: "hf_selection",
      panel: "node",
    });
    expect(latest!.error).toContain("实验焦点读取失败");
    expect(latest!.error).toContain("offline");
  });
});
