import { renderToStaticMarkup } from "react-dom/server";
import type { ComponentProps } from "react";
import { describe, expect, it } from "vitest";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary } from "../api/types";
import { AgentSessionTabStrip } from "./AgentSessionTabStrip";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-root",
    title: "顾明澈",
    agentId: "agent-1",
    agentCode: "A030",
    agentDisplayName: "顾明澈",
    dialogueModelId: "gpt-5-5-gpt-5-5",
    status: "idle",
    taskSummary: "主会话摘要",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "idle",
    sessionKind: "main",
    ...overrides,
  };
}

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A030",
    displayName: "知识管理员",
    kind: "persistent",
    primaryMode: "chat",
    roleKey: "knowledge_steward",
    llmBindings: { dialogue: { modelId: "gpt-5-5-gpt-5-5" } },
    promptTemplateId: "prompt-knowledge",
    directSessionId: "session-root",
    workspacePath: "C:/workspace",
    toolPolicyId: "",
    memoryPolicyId: "",
    createdBy: "",
    status: "ready",
    metadata: {},
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}

function renderStrip(overrides: Partial<ComponentProps<typeof AgentSessionTabStrip>> = {}) {
  const root = session();
  const child = session({
    id: "session-child",
    title: "子任务标题",
    taskTitle: "接续分析",
    taskSummary: "子会话摘要",
    sessionKind: "child",
    parentSessionId: "session-root",
    rootSessionId: "session-root",
    childStatus: "running",
    resultCard: {
      title: "接续分析报告",
      summary: "结果摘要",
    },
  });
  const props: ComponentProps<typeof AgentSessionTabStrip> = {
    activeSessionId: "session-child",
    agentsById: new Map([["agent-1", agent()]]),
    buildSessionReferencePayload: (item: SessionSummary, displayName: string, summary: string): SessionReferenceAttachment => ({
      referenceId: `session:${item.id}`,
      kind: "session",
      sessionId: item.id,
      title: item.title,
      agentDisplayName: displayName,
      summary,
      createdAt: "2026-06-09T00:00:00.000Z",
    }),
    editingSessionId: null,
    editingSessionTitle: "",
    lang: "zh",
    renamePending: false,
    renameSessionId: "",
    resolveModelLabel: (modelId: string) => (modelId === "gpt-5-5-gpt-5-5" ? "GPT 5.5" : undefined),
    sessions: [root, child],
    statusLabel: (status: string) => status,
    t: (key) => key,
    workspaceActiveTab: "agent",
    onCancelRename: () => undefined,
    onContextMenu: () => undefined,
    onDragReference: () => undefined,
    onOpenDirectSession: () => undefined,
    onOpenCliAgentRun: () => undefined,
    onRenameTitleChange: () => undefined,
    onSetActiveTab: () => undefined,
    onSubmitRename: () => undefined,
    ...overrides,
  };
  return renderToStaticMarkup(<AgentSessionTabStrip {...props} />);
}

describe("AgentSessionTabStrip", () => {
  it("renders root and child sessions with model and child task labels", () => {
    const markup = renderStrip();

    expect(markup).toContain("Agent 会话");
    expect(markup).toContain("知识管理员");
    expect(markup).toContain("GPT 5.5");
    expect(markup).toContain("子对话");
    expect(markup).toContain("接续分析");
    expect(markup).toContain("结果摘要");
    expect(markup).toContain("running");
    expect(markup).toContain("aria-current=\"true\"");
  });

  it("renders the rename input for the edited session", () => {
    const markup = renderStrip({
      editingSessionId: "session-child",
      editingSessionTitle: "新的子任务名",
      renamePending: true,
      renameSessionId: "session-child",
    });

    expect(markup).toContain("新的子任务名");
    expect(markup).toContain("agentSessionTabTitleInput");
    expect(markup).toContain("disabled=\"\"");
  });

  it("renders CLI agent tool runs as top-level command tabs", () => {
    const markup = renderStrip({
      activeSessionId: "session-root",
      activeCliAgentRunId: "run-1",
      sessions: [session()],
      cliAgentRuns: [
        {
          id: "run-1",
          title: "Codex Code",
          summary: "Inspect repository",
          status: "ok",
          agentType: "codex_code",
          mode: "readonly",
        },
      ],
    });

    expect(markup).toContain("CLI Agent");
    expect(markup).toContain("Codex Code");
    expect(markup).toContain("readonly");
    expect(markup).toContain("aria-current=\"true\"");
    expect(markup).toContain("agentSessionTabCli");
  });

  it("renders nothing when there is only one session", () => {
    const markup = renderStrip({ sessions: [session()] });

    expect(markup).toBe("");
  });
});
