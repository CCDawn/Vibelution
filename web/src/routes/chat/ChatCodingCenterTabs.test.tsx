/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ChatCodingCenterTabs, type ChatCodingCenterTabsProps } from "./ChatCodingCenterTabs";
import { subscribeChatRightRailOpen } from "./chatRightRailRequests";
import { EMPTY_CHAT_RIGHT_RAIL, openChatRightRailTab } from "./chatRightRailModel";

vi.mock("./ChatFileWorkspaceTabs", () => ({ ChatFileWorkspaceTabs: () => null }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function messages(completed = false): ConversationMessage[] {
  return [{
    id: "a1", role: "assistant", timestamp: "2026-10-18T04:00:00Z", status: completed ? "completed" : "running",
    turnId: "turn-1", turnItems: [{
      id: "todo-1", itemId: "todo-1", version: 3, sessionId: "session-1", turnId: "turn-1",
      type: "tool_call", status: "completed", revision: 1, sequence: 1, callId: "call-1", toolName: "todo_write",
      input: JSON.stringify({ todos: [{ content: "补齐测试", activeForm: "正在补齐测试", status: completed ? "completed" : "in_progress" }] }),
    }],
  }];
}

function props(overrides: Partial<ChatCodingCenterTabsProps> = {}): ChatCodingCenterTabsProps {
  return {
    lang: "zh", chatReturnTarget: null, chatReturnLabel: "", groupPanelActive: false, projectBusActive: false,
    financeSurface: false, verifiedCompanionMode: false, selectedChatAgentId: "", agentSessionTabs: [], cliAgentRunTabs: [],
    activeCompanion: null, leftOverlayVisible: true, rightOverlayVisible: true, conversationIndexCollapsed: false,
    setLeftRailCollapsed: vi.fn(), conversationWorkspaceTab: "agent", sessionBrowserVisible: false,
    setSessionBrowserOpen: vi.fn(), headerExportVisible: false, conversationModel: { sessionId: "session-1", messages: messages() },
    conversationIndexOverlayOpen: false, ordinaryChangeRail: true, changeRailVisible: false, statusRailOverlayOpen: false,
    toggleChangeRail: vi.fn(), setResponsiveOverlayPane: vi.fn(), activeSessionId: "session-1", setActiveTab: vi.fn(),
    activeCliAgentRunId: "", agentsById: new Map(), buildSessionReferencePayload: () => null,
    contextMenuSessionId: "", createSessionPending: false, deleteSessionPending: false, pendingDeleteSessionId: "",
    editingSessionId: null, editingSessionTitle: "", renamePending: false, renameSessionId: "", resolveModelLabel: () => "",
    teams: [], runtimeRunningSessionIds: [], sessionIdsNeedingApproval: [], statusLabel: (status) => status, t: (key) => key,
    onCancelRename: vi.fn(), onContextMenu: vi.fn(), onDragReference: vi.fn(), closeCliAgentRun: vi.fn(async () => {}),
    onCreateSession: vi.fn(), onDeleteSession: vi.fn(), onOpenDirectSession: vi.fn(), onRenameTitleChange: vi.fn(),
    onSubmitRename: vi.fn(), workspace: { activeTab: "agent", openTabs: [] }, closePreviewTab: vi.fn(),
    ...overrides,
  };
}

let root: Root | undefined;
let host: HTMLDivElement | undefined;
let unsubscribe: (() => void) | undefined;
async function render(input: ChatCodingCenterTabsProps) {
  if (!host) {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  }
  await act(async () => { root!.render(<ChatCodingCenterTabs {...input} />); });
  return host;
}
afterEach(async () => {
  unsubscribe?.();
  unsubscribe = undefined;
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
});

describe("ChatCodingCenterTabs task progress entry", () => {
  it("opens the existing session plan rail and collapses only the selected plan", async () => {
    let model = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "plan", title: "计划", host: "center" });
    const open = vi.fn((request) => {
      model = openChatRightRailTab(model, request);
      return true;
    });
    unsubscribe = subscribeChatRightRailOpen(open);
    const input = props({ changeRailVisible: true });
    const element = await render(input);
    await act(async () => element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!.click());
    expect(open).toHaveBeenCalledExactlyOnceWith({ sessionId: "session-1", kind: "plan", title: "计划", host: "rail" });
    expect(input.setSessionBrowserOpen).toHaveBeenCalledWith(false);
    expect(input.toggleChangeRail).not.toHaveBeenCalled();
    expect(model.tabs).toHaveLength(1);
    expect(model.tabs[0].host).toBeUndefined();
    await render({ ...input, taskPlanOpen: true, changeRailVisible: true });
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.getAttribute("aria-expanded")).toBe("true");
    await act(async () => element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!.click());
    expect(input.toggleChangeRail).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledOnce();
  });

  it("updates counts without opening the rail and drops another session's plan", async () => {
    const open = vi.fn(() => true);
    unsubscribe = subscribeChatRightRailOpen(open);
    const input = props();
    const element = await render(input);
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.textContent).toContain("0/1");
    await render({ ...input, conversationModel: { sessionId: "session-1", messages: messages(true) } });
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.textContent).toContain("1/1");
    expect(open).not.toHaveBeenCalled();
    await render({ ...input, activeSessionId: "session-2" });
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')).toBeNull();
  });

  it.each([
    { verifiedCompanionMode: true }, { groupPanelActive: true }, { financeSurface: true },
    { conversationModel: { sessionId: "session-1", messages: [] } },
  ])("keeps the entry out of unrelated or empty surfaces: %j", async (overrides) => {
    const element = await render(props(overrides));
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')).toBeNull();
  });
});
