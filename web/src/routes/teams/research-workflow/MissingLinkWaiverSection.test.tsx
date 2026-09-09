/** @vitest-environment happy-dom */
/**
 * Shared missing-link waiver section (缺陷⑰):
 * rows render from the candidate-graph payload, the two-step confirm posts
 * waiveEvidenceGraphMissingLink with the CHILD workflow run id, controls hide
 * without run context, waived rows badge, success refetches the graph.
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { waiveEvidenceGraphMissingLink } from "../../../api/researchWorkflow";
import type { TeamWorkflowCandidateGraphPayload } from "../../../api/types";
import {
  MissingLinkWaiverSection,
  type MissingLinkWaiverSectionProps,
} from "./MissingLinkWaiverSection";

vi.mock("../../../api/researchWorkflow", () => ({
  waiveEvidenceGraphMissingLink: vi.fn(),
}));

const waiveMock = vi.mocked(waiveEvidenceGraphMissingLink);
const refetchMock = vi.fn(async () => undefined);

const MISSING_TARGET = "candidate-20260908171904-9143d4d6";
/** The knowledge sideflow CHILD run — the authority the waive endpoint needs. */
const CHILD_RUN_ID = "run-1ca97605acf3";

function graphPayload(): TeamWorkflowCandidateGraphPayload {
  return {
    nodes: [],
    edges: [],
    missingLinks: [
      {
        sourceCandidateId: "candidate-a",
        targetCandidateId: MISSING_TARGET,
        relation: "supports",
        edgeState: "",
      },
      {
        sourceCandidateId: "candidate-a",
        targetCandidateId: "candidate-b",
        relation: "contradicts",
        edgeState: "",
        waived: true,
        status: "waived",
        waiver: { by: "local-control-operator", at: "2026-09-08T00:00:00Z", justification: "earlier audit decision" },
      },
    ],
    unreviewedNodes: [],
    officialBoundary: {
      writesOfficialKnowledge: false,
      writesOfficialRag: false,
      writesOfficialGraph: false,
      requiresIngestionApproval: true,
    },
    summary: {
      nodeCount: 0,
      edgeCount: 0,
      missingLinkCount: 2,
      unreviewedNodeCount: 0,
    },
    createdAt: "2026-09-08T00:00:00Z",
  } as unknown as TeamWorkflowCandidateGraphPayload;
}

function baseProps(): MissingLinkWaiverSectionProps {
  return {
    lang: "zh",
    teamId: "research-team",
    childWorkflowRunId: CHILD_RUN_ID,
    graph: graphPayload(),
    refetchGraph: refetchMock,
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

async function mountSection(props: MissingLinkWaiverSectionProps) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<MissingLinkWaiverSection {...props} />);
  });
  return {
    root,
    container,
    async unmount() {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

beforeEach(() => {
  waiveMock.mockReset();
  refetchMock.mockClear();
  document.body.innerHTML = "";
});

describe("MissingLinkWaiverSection", () => {
  it("lists missing links from the graph payload with waive button and waived badge", async () => {
    const view = await mountSection(baseProps());

    expect(document.body.querySelector('[data-testid="graph-missing-links"]')).not.toBeNull();
    const rows = document.body.querySelectorAll('[data-testid="graph-missing-link-row"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain(`supports: candidate-a → ${MISSING_TARGET}`);
    expect(buttonByText("豁免")).toBeTruthy();
    expect(document.body.querySelector('[data-testid="graph-missing-link-waived"]')).not.toBeNull();
    expect(rows[1].textContent).toContain("已豁免");

    await view.unmount();
  });

  it("renders a graph-unavailable hint instead of rows when graph data is missing", async () => {
    const props = baseProps();
    props.graph = null;
    const view = await mountSection(props);

    expect(document.body.querySelector('[data-testid="graph-missing-link-graph-unavailable"]')).not.toBeNull();
    expect(document.body.querySelectorAll('[data-testid="graph-missing-link-row"]')).toHaveLength(0);
    expect(buttonByText("豁免")).toBeFalsy();

    await view.unmount();
  });

  it("renders nothing when the loaded graph has no missing links", async () => {
    const props = baseProps();
    props.graph = { ...graphPayload(), missingLinks: [] };
    const view = await mountSection(props);

    expect(document.body.querySelector('[data-testid="graph-missing-links"]')).toBeNull();

    await view.unmount();
  });

  it("hides waive controls and shows a hint without child run context", async () => {
    const props = baseProps();
    props.childWorkflowRunId = "";
    const view = await mountSection(props);

    expect(buttonByText("豁免")).toBeFalsy();
    expect(document.body.textContent).toContain("缺少正式运行上下文");

    await view.unmount();
  });

  it("keeps confirm disabled until the justification reaches the audit minimum", async () => {
    const view = await mountSection(baseProps());

    await act(async () => {
      buttonByText("豁免")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const input = document.body.querySelector('input[aria-label="豁免理由"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const confirm = document.body.querySelector(
      '[data-testid="graph-missing-link-waive-confirm"]',
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    await act(async () => {
      setControlValue(input, "太短");
    });
    expect(
      (document.body.querySelector('[data-testid="graph-missing-link-waive-confirm"]') as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(waiveMock).not.toHaveBeenCalled();

    await view.unmount();
  });

  it("posts the confirmed waiver with the CHILD workflow run id and refetches the graph", async () => {
    waiveMock.mockResolvedValue({
      status: "waived",
      alreadyWaived: false,
      teamId: "research-team",
      runId: CHILD_RUN_ID,
      sourceCollectionRunId: "sc-child",
      waiverCount: 1,
      missingLinkCount: 1,
      graphCandidateIds: ["candidate-graph-1"],
      waiver: { by: "local-control-operator", at: "2026-09-08T00:00:00Z", justification: "audited reason" },
    });
    const view = await mountSection(baseProps());

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

    expect(waiveMock).toHaveBeenCalledTimes(1);
    expect(waiveMock.mock.calls[0][0]).toEqual({
      runId: CHILD_RUN_ID,
      teamId: "research-team",
      sourceCandidateId: "candidate-a",
      targetCandidateId: MISSING_TARGET,
      relation: "supports",
      justification: "relation mapper asserted a random candidate id typo; reviewed and accepted",
      confirmed: true,
    });
    expect(refetchMock).toHaveBeenCalledTimes(1);
    expect(document.body.querySelector('[data-testid="graph-missing-link-notice"]')?.textContent).toContain(
      "不再阻塞知识入库就绪门",
    );
    expect(document.body.querySelector('[data-testid="graph-missing-link-editor"]')).toBeNull();

    await view.unmount();
  });

  it("surfaces backend rejection instead of a silent failure", async () => {
    waiveMock.mockRejectedValue(new Error("waiver_justification_required"));
    const view = await mountSection(baseProps());

    await act(async () => {
      buttonByText("豁免")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const input = document.body.querySelector('input[aria-label="豁免理由"]') as HTMLInputElement;
    await act(async () => {
      setControlValue(input, "an intentionally long justification for the audit trail");
    });
    await act(async () => {
      (
        document.body.querySelector('[data-testid="graph-missing-link-waive-confirm"]') as HTMLButtonElement
      ).dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.body.querySelector('[data-testid="graph-missing-link-error"]')?.textContent).toContain(
      "waiver_justification_required",
    );
    expect(refetchMock).not.toHaveBeenCalled();

    await view.unmount();
  });
});
