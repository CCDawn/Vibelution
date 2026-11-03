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

function mountCompletionFlow(ctx: TeamsWorkspacePanelRenderContext, presentation: "board" | "rail" = "board") {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  const { renderKnowledgeCollectionCompletionFlowPanel } = createTeamsWorkspacePanelRenderers(ctx);
  act(() => {
    root?.render(<MemoryRouter>{renderKnowledgeCollectionCompletionFlowPanel({ presentation })}</MemoryRouter>);
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
  it("disables Agent chat and explains why when its handler is not wired", () => {
    const ctx = completionFlowContext();
    delete ctx.openSourceCollectionStageAgentChat;
    const element = mountCompletionFlow(ctx);

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(true);
    expect(chat.title).toContain("暂不可用");
    expect(element.querySelector('[role="status"]')?.textContent).toContain("刷新");
    expect(() => act(() => chat.click())).not.toThrow();
    expect(assemblyErrors()).toHaveLength(0);
  });

  it("disables rerun and explains why when its handler is not wired", () => {
    const ctx = completionFlowContext();
    delete ctx.runKnowledgeCollectionCompletionAction;
    const element = mountCompletionFlow(ctx);

    const rerun = buttonByText(element, "重新执行搜集闭环");
    expect(rerun.disabled).toBe(true);
    expect(rerun.title).toContain("暂不可用");
    expect(element.querySelector('[role="status"]')?.textContent).toContain("刷新");
    expect(() => act(() => rerun.click())).not.toThrow();

    expect(assemblyErrors()).toHaveLength(0);
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

  it.each(["board", "rail"] as const)("explains blocked Agent chat before a run exists in %s presentation", (presentation) => {
    const openChat = vi.fn();
    const binding = { agentId: "source-agent", agent: { agentId: "source-agent" } };
    const state = vi.fn(() => ({ binding, route: "", status: "blocked" }));
    const element = mountCompletionFlow(completionFlowContext({
      openSourceCollectionStageAgentChat: openChat,
      sourceCollectionStagePrimaryAgentBinding: () => binding,
      sourceCollectionStageAgentChatState: state,
    }), presentation);

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(true);
    expect(chat.title).toContain("开始资料搜集");
    expect(element.textContent).toContain("开始资料搜集");
    act(() => chat.click());
    expect(openChat).not.toHaveBeenCalled();
    expect(state).toHaveBeenCalledWith("finding");
  });

  it("disables Agent chat while its context is loading", () => {
    const openChat = vi.fn();
    const element = mountCompletionFlow(completionFlowContext({
      openSourceCollectionStageAgentChat: openChat,
      sourceCollectionStageAgentChatState: () => ({ binding: null, route: "", status: "loading" }),
    }));

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(true);
    expect(chat.title).toContain("加载");
    act(() => chat.click());
    expect(openChat).not.toHaveBeenCalled();
  });

  it("keeps ready Agent chat callable", () => {
    const openChat = vi.fn();
    const element = mountCompletionFlow(completionFlowContext({
      openSourceCollectionStageAgentChat: openChat,
      sourceCollectionStageAgentChatState: () => ({ binding: { agent: { agentId: "source-agent" } }, route: "", status: "ready" }),
    }));

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(false);
    act(() => chat.click());
    expect(openChat).toHaveBeenCalledExactlyOnceWith("finding");
  });

  it.each(["stale-agent", ""])("keeps the Challenge Cup configuration fallback for blocked Agent %s", (agentId) => {
    const openChat = vi.fn();
    const binding = { agentId, agent: null };
    const element = mountCompletionFlow(completionFlowContext({
      selectedTeam: { teamId: "research-team", teamKind: "research", teamSource: "research_organization" },
      openSourceCollectionStageAgentChat: openChat,
      sourceCollectionStagePrimaryAgentBinding: () => binding,
      sourceCollectionStageAgentChatState: () => ({ binding, route: "", status: "blocked" }),
    }));

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(false);
    act(() => chat.click());
    expect(openChat).toHaveBeenCalledExactlyOnceWith("finding");
  });

  it.each(["repair", "error"])("keeps the existing %s action callable", (status) => {
    const openChat = vi.fn();
    const element = mountCompletionFlow(completionFlowContext({
      openSourceCollectionStageAgentChat: openChat,
      sourceCollectionStageAgentChatState: () => ({ binding: null, route: "", status }),
    }));

    const chat = buttonByText(element, "Agent 私聊");
    expect(chat.disabled).toBe(false);
    act(() => chat.click());
    expect(openChat).toHaveBeenCalledExactlyOnceWith("finding");
  });
});
