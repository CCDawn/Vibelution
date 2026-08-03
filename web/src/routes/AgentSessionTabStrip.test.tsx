import { renderToStaticMarkup } from "react-dom/server";
import React, { type ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary } from "../api/types";
import { AgentSessionTabStrip, agentSessionStatusTone } from "./AgentSessionTabStrip";
import { markSessionActivitySeen, sessionActivityStamp } from "./sessionActivityIndicator";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  const status = overrides.status ?? "idle";
  const currentPhase = overrides.currentPhase ?? status;
  return {
    id: "session-root",
    title: "顾明澈",
    agentId: "agent-1",
    agentCode: "A030",
    agentDisplayName: "顾明澈",
    dialogueModelId: "gpt-5-5-gpt-5-5",
    taskSummary: "主会话摘要",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    sessionKind: "main",
    ...overrides,
    status,
    currentPhase,
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
    contextMenuSessionId: "",
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
    onCreateSession: () => undefined,
    onDeleteSession: () => undefined,
    onRenameTitleChange: () => undefined,
    onSetActiveTab: () => undefined,
    onSubmitRename: () => undefined,
    ...overrides,
  };
  return renderToStaticMarkup(<AgentSessionTabStrip {...props} />);
}

describe("AgentSessionTabStrip", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
      clear: () => store.clear(),
    });
  });

  it("maps status: green running, red error, yellow approval, blue completed, none idle", () => {
    expect(agentSessionStatusTone("running")).toBe("running");
    expect(agentSessionStatusTone("thinking")).toBe("running");
    expect(agentSessionStatusTone("failed")).toBe("error");
    expect(agentSessionStatusTone("failed_runtime")).toBe("error");
    expect(agentSessionStatusTone("blocked")).toBe("error");
    expect(agentSessionStatusTone("idle")).toBe("none");
    expect(agentSessionStatusTone("ready")).toBe("completed");
    expect(agentSessionStatusTone("completed")).toBe("completed");
    expect(agentSessionStatusTone("needs_continue")).toBe("completed");
    expect(agentSessionStatusTone("running", { needsApproval: true })).toBe("approval");
    expect(agentSessionStatusTone("ready", { needsApproval: true })).toBe("approval");
  });

  it("renders legacy root and child records as flat session tabs", () => {
    const markup = renderStrip();

    expect(markup).toContain("Agent 会话");
    expect(markup).toContain("顾明澈");
    expect(markup).not.toContain("idle · GPT 5.5</span>");
    expect(markup).not.toContain(">子对话</span>");
    expect(markup).toContain("子任务标题");
    // Hover detail (model/summary/status) lives only in VButton VTooltip — no nested native title.
    expect(markup).not.toMatch(/data-agent-session-tab-container[^>]*\stitle=/);
    expect(markup).not.toMatch(/agentSessionTabTitle[^>]*\stitle="/);
    expect(markup).not.toMatch(/agentSessionTabStatusIndicator[^>]*\stitle="/);
    expect(markup).not.toContain("agentSessionTabChild");
    expect(markup).not.toContain(">会话进行</span>");
    expect(markup).not.toContain("空闲");
    expect(markup).not.toContain("agentSessionTabStatusDotIdle");
    expect(markup).toContain("当前会话");
    expect(markup).toContain("data-session-tab-active=\"true\"");
    expect(markup).toContain("data-session-tab-active=\"false\"");
    expect(markup).toContain("agentSessionTabStatusRunning");
    expect(markup).toContain("agentSessionTabMainActionActive");
    expect(markup).not.toContain("agentSessionTabCurrentBadge");
    expect(markup).toContain("agentSessionTabTitleActive");
    expect(markup).toContain("aria-current=\"true\"");
    expect(markup).toContain("role=\"tablist\"");
    expect(markup.match(/role="tab"/g)?.length).toBe(2);
    expect(markup.match(/role="presentation"/g)?.length).toBe(2);
    expect(markup).toContain("aria-selected=\"true\"");
    expect(markup).toContain("aria-selected=\"false\"");
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain('tabindex="-1"');
  });

  it("uses a browser-style tab rail for one Agent managing multiple sessions", () => {
    const markup = renderStrip({
      activeSessionId: "session-child-a",
      sessions: [
        session({ id: "session-root", title: "主线会话" }),
        session({
          id: "session-child-a",
          title: "资料核对",
          taskTitle: "资料核对",
          sessionKind: "child",
          parentSessionId: "session-root",
          rootSessionId: "session-root",
        }),
        session({
          id: "session-child-b",
          title: "结果整理",
          taskTitle: "结果整理",
          sessionKind: "child",
          parentSessionId: "session-root",
          rootSessionId: "session-root",
        }),
      ],
    });

    expect(markup).toContain("agentSessionTabGroup");
    expect(markup).toContain("flex-nowrap");
    expect(markup).toContain("agentSessionTabRail");
    expect(markup).toContain("overflow-x-auto");
    expect(markup.match(/role="tab"/g)?.length).toBe(3);
    expect(markup).toContain("资料核对");
    expect(markup).toContain("结果整理");
    expect(markup).toContain("aria-selected=\"true\"");
    expect(markup).toContain("aria-selected=\"false\"");
  });

  it("keeps activity semantics in accessible labels without visible status copy", () => {
    const markup = renderStrip({
      sessions: [
        session({ id: "session-running", status: "running" }),
        session({ id: "session-error", status: "error" }),
        session({ id: "session-done", status: "completed", updatedAt: "2026-06-10T00:00:00.000Z" }),
      ],
      sessionIdsNeedingApproval: ["session-running"],
    });

    // Approval overrides running → yellow.
    expect(markup).toContain("agentSessionTabStatusApproval");
    expect(markup).toContain("agentSessionTabStatusError");
    expect(markup).toContain("agentSessionTabStatusCompleted");
    expect(markup).not.toContain("agentSessionTabStatusDotIdle");
    expect(markup).not.toContain(">需审批</span>");
    expect(markup).not.toContain(">出错</span>");
    expect(markup).not.toContain(">已完成</span>");
    expect(markup).not.toContain("空闲");
    expect(markup).not.toContain(">running</span>");
    expect(markup).not.toContain(">error</span>");
    expect(markup).not.toContain(">completed</span>");
  });

  it("uses green spinner for in-session running without approval", () => {
    const markup = renderStrip({
      sessions: [session({ id: "session-running", status: "running" })],
      sessionIdsNeedingApproval: [],
    });
    expect(markup).toContain("agentSessionTabStatusRunning");
    expect(markup).toContain("agentSessionTabStatusSpinner");
    expect(markup).not.toContain(">会话进行</span>");
  });

  it("hides completed indicator after the session activity is marked seen", () => {
    const done = session({
      id: "session-done",
      status: "completed",
      updatedAt: "2026-06-11T00:00:00.000Z",
    });
    markSessionActivitySeen(done.id, sessionActivityStamp(done));
    const markup = renderStrip({
      activeSessionId: "session-other",
      sessions: [done],
    });
    expect(markup).not.toContain("agentSessionTabStatusCompleted");
    expect(markup).not.toContain("已完成");
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
    expect(markup).toContain("agentSessionTabEditActions");
    // Single-row edit chrome: no stacked kicker above the field.
    expect(markup).not.toMatch(/agentSessionTabKicker[\s\S]*agentSessionTabTitleInput/);
    // Hide create + while renaming so check/cancel are not crowded by another icon.
    expect(markup).not.toContain("agentSessionTabCreateButton");
  });

  it("renders CLI agent run tabs with activity indicators", () => {
    const markup = renderStrip({
      activeSessionId: null,
      sessions: [],
      activeCliAgentRunId: "cli-1",
      cliAgentRuns: [
        {
          id: "cli-1",
          title: "终端 A",
          summary: "codex",
          status: "running",
          agentType: "codex",
          mode: "interactive",
        },
      ],
    });
    expect(markup).toContain("终端 A");
    expect(markup).toContain("agentSessionTabStatusRunning");
    expect(markup).not.toContain(">会话进行</span>");
  });

  it("renders close controls inside each session card shell and a final icon-only create control", () => {
    const markup = renderStrip();

    expect(markup.match(/agentSessionTabCloseButton/g)?.length).toBe(2);
    expect(markup.match(/agentSessionTabClosable/g)?.length).toBe(2);
    // Close is a sibling of the tab hit target, still inside the card shell (data-agent-session-tab-container).
    expect(markup).toMatch(
      /data-agent-session-tab-container[\s\S]*?agentSessionTabCloseButton[\s\S]*?<\/div>/,
    );
    expect(markup).toContain('aria-label="deleteSession 顾明澈"');
    expect(markup).toContain('aria-label="deleteSession 子任务标题"');
    expect(markup).toContain("agentSessionTabCreateButton");
    expect(markup).toContain('aria-label="在当前 Agent 下新建会话"');
    expect(markup).not.toContain(">新建会话</span>");
  });

  it("wires roving tab focus keys while keeping close controls outside tab semantics", () => {
    const markup = renderStrip();

    expect(markup.match(/role="tab"/g)?.length).toBe(2);
    expect(markup.match(/role="presentation"/g)?.length).toBe(2);
    expect(markup).toContain('id="agent-session-tab-session-session-root"');
    expect(markup).toContain('id="agent-session-tab-session-session-child"');
  });

  it("keeps the create control outside tablist ownership when there are no sessions", () => {
    const markup = renderStrip({ activeSessionId: null, sessions: [], cliAgentRuns: [] });

    expect(markup).not.toContain('role="tablist"');
    expect(markup).not.toContain('role="tab"');
    expect(markup).toContain("agentSessionTabCreateButton");
  });

  it("keeps one session keyboard-focusable while a file workspace tab is active", () => {
    const markup = renderStrip({
      activeSessionId: "session-root",
      workspaceActiveTab: "file:C:/workspace/report.md",
      sessions: [session({ id: "session-root" }), session({ id: "session-two" })],
    });

    expect(markup.match(/tabindex="0"/g)?.length).toBe(1);
    expect(markup.match(/tabindex="-1"/g)?.length).toBe(1);
  });

  it("does not declare an empty tablist while the only session is being renamed", () => {
    const markup = renderStrip({
      activeSessionId: "session-root",
      sessions: [session({ id: "session-root" })],
      editingSessionId: "session-root",
      editingSessionTitle: "新名称",
    });

    expect(markup).not.toContain('role="tablist"');
    expect(markup).not.toContain('role="tab"');
    expect(markup).toContain("agentSessionTabTitleInput");
  });

  it("disables close for a busy session and create while pending", () => {
    const markup = renderStrip({
      sessions: [session({ id: "session-running", status: "running" })],
      createPending: true,
    });

    expect(markup).toContain('aria-label="deleteSessionBusy 顾明澈"');
    expect(markup.match(/disabled=""/g)?.length).toBe(2);
  });

  it("disables only the deleting session close control while delete is pending", () => {
    const markup = renderStrip({
      sessions: [
        session({ id: "session-one", status: "idle" }),
        session({ id: "session-two", status: "idle" }),
      ],
      deletePendingSessionId: "session-one",
    });

    // Create button stays enabled; only the target tab close is busy.
    expect(markup.match(/aria-label="deleteSessionBusy 顾明澈"/g)?.length).toBe(1);
    expect(markup).toContain('aria-label="deleteSession 顾明澈"');
  });

  it("uses currentPhase before stale summary status for delete availability", () => {
    const markup = renderStrip({
      sessions: [session({ id: "session-transitioning", status: "idle", currentPhase: "running" })],
    });

    expect(markup).toContain('aria-label="deleteSessionBusy 顾明澈"');
    expect(markup).toContain('disabled=""');
  });

  it("marks the active session tab with selection chrome independent of status color", () => {
    const markup = renderStrip({
      activeSessionId: "session-root",
      sessions: [
        session({ id: "session-root", status: "running" }),
        session({ id: "session-other", status: "error" }),
      ],
    });
    expect(markup).toContain("agentSessionTabMainActionActive");
    expect(markup).toContain("agentSessionTabStatusRunning");
    expect(markup).toContain("agentSessionTabStatusError");
  });
});
