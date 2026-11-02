/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Resolve the lazy completion-flow panel synchronously so clicks hit the real buttons.
vi.mock("./teamLazyPanels", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./teamLazyPanels")>();
  const panel = await import("../TeamKnowledgeCollectionCompletionFlowPanel");
  return { ...actual, TeamKnowledgeCollectionCompletionFlowPanel: panel.TeamKnowledgeCollectionCompletionFlowPanel };
});

import { createTeamsWorkspacePanelRenderers, type TeamsWorkspacePanelRenderContext } from "./teamsWorkspacePanelRenderers";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => undefined;

/** Minimal ctx for the completion-flow renderer with one failed node so the rerun CTA is mounted. */
function completionFlowContext(overrides: TeamsWorkspacePanelRenderContext = {}): TeamsWorkspacePanelRenderContext {
  return {
    lang: "zh",
    researchWorkflowTeamSelected: true,
    researchCanvasReadOnly: true,
    selectedTeamKnowledgeCollectionWorkRun: null,
    sourceCollectionCompletionFlow: { status: "failed", currentStageId: "finding" },
    sourceCollectionCompletionFlowNodes: [
      { stageId: "finding", status: "failed", label: "资料搜集", agentRole: "searcher", inputCount: 0, outputCount: 0 },
    ],
    sourceCollectionStageModules: [{ id: "finding", label: "资料搜集" }],
    workflowIngestionToneBound: () => "",
    sourceCollectionStagePrimaryAgentBinding: () => null,
    sourceCollectionStageReturnRoute: () => "/teams/team/stage/finding",
    openSourceCollectionStageAgentChat: noop,
    sourceCollectionStepClassName: () => "",
    runKnowledgeCollectionCompletionAction: noop,
    sourceCollectionCompletionActionDisabled: false,
    selectedTeamKnowledgeCollectionIngestPending: false,
    sourceCollectionActionDisabledTitle: () => undefined,
    sourceCollectionCompletionActionReadiness: null,
    ...overrides,
  };
}

function spyConsoleError() {
  return vi.spyOn(console, "error").mockImplementation(() => undefined);
}

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let errorSpy: ReturnType<typeof spyConsoleError>;

beforeEach(() => {
  errorSpy = spyConsoleError();
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
  }
  host?.remove();
  host = null;
  root = null;
  errorSpy.mockRestore();
});

function mountCompletionFlow(ctx: TeamsWorkspacePanelRenderContext) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  const { renderKnowledgeCollectionCompletionFlowPanel } = createTeamsWorkspacePanelRenderers(ctx);
  act(() => {
    root?.render(<MemoryRouter>{renderKnowledgeCollectionCompletionFlowPanel()}</MemoryRouter>);
  });
  return host;
}

function buttonByText(element: HTMLElement, text: string) {
  const button = Array.from(element.querySelectorAll<HTMLButtonElement>("button"))
    .find((item) => item.textContent?.includes(text));
  if (!button) {
    throw new Error(`button "${text}" not rendered`);
  }
  return button;
}

/** Only the assembly-assertion messages; React's own console.error noise (if any) is ignored. */
function assemblyErrors() {
  return errorSpy.mock.calls
    .map((call) => String(call[0]))
    .filter((message) => message.includes("装配缺失"));
}

describe("renderKnowledgeCollectionCompletionFlowPanel assembly fallbacks", () => {
  it("logs 装配缺失 instead of failing silently when openSourceCollectionStageAgentChat is not wired", () => {
    const ctx = completionFlowContext();
    delete ctx.openSourceCollectionStageAgentChat;
    const element = mountCompletionFlow(ctx);

    const chat = buttonByText(element, "Agent 私聊");
    expect(() => act(() => chat.click())).not.toThrow();

    const errors = assemblyErrors();
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("openSourceCollectionStageAgentChat");
  });

  it("logs 装配缺失 instead of failing silently when runKnowledgeCollectionCompletionAction is not wired", () => {
    const ctx = completionFlowContext();
    delete ctx.runKnowledgeCollectionCompletionAction;
    const element = mountCompletionFlow(ctx);

    const rerun = buttonByText(element, "重新执行搜集闭环");
    expect(rerun.disabled).toBe(false);
    expect(() => act(() => rerun.click())).not.toThrow();

    const errors = assemblyErrors();
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("runKnowledgeCollectionCompletionAction");
  });

  it("forwards clicks to wired handlers without logging", () => {
    const openChat = vi.fn();
    const rerun = vi.fn();
    const element = mountCompletionFlow(completionFlowContext({
      openSourceCollectionStageAgentChat: openChat,
      runKnowledgeCollectionCompletionAction: rerun,
    }));

    act(() => buttonByText(element, "Agent 私聊").click());
    act(() => buttonByText(element, "重新执行搜集闭环").click());

    expect(openChat).toHaveBeenCalledWith("finding");
    expect(rerun).toHaveBeenCalledOnce();
    expect(assemblyErrors()).toHaveLength(0);
  });
});
