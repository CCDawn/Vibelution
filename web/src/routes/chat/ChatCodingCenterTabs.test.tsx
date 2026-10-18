/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ChatCodingCenterTabs, type ChatCodingCenterTabsProps } from "./ChatCodingCenterTabs";
import { subscribeChatRightRailOpen } from "./chatRightRailRequests";

vi.mock("./ChatFileWorkspaceTabs", () => ({ ChatFileWorkspaceTabs: () => null }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function messages(completed = false, content = "补齐测试", settled = completed): ConversationMessage[] {
  return [{
    id: "a1", role: "assistant", timestamp: "2026-10-18T04:00:00Z", status: settled ? "completed" : "running",
    turnId: "turn-1", turnItems: [{
      id: "todo-1", itemId: "todo-1", version: 3, sessionId: "session-1", turnId: "turn-1",
      type: "tool_call", status: "completed", revision: 1, sequence: 1, callId: "call-1", toolName: "todo_write",
      input: JSON.stringify({ todos: [{ content, activeForm: `正在${content}`, status: completed ? "completed" : "in_progress" }] }),
    }, ...(settled ? [{
      id: "answer-1", itemId: "answer-1", version: 3 as const, sessionId: "session-1", turnId: "turn-1",
      type: "agent_message" as const, status: "completed" as const, revision: 1, sequence: 2,
      phase: "final_answer" as const, terminal: true, text: "已处理本轮",
    }] : [])],
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
  it("toggles an independent floating checklist without changing the right rail or session browser", async () => {
    const open = vi.fn(() => true);
    unsubscribe = subscribeChatRightRailOpen(open);
    const input = props({ changeRailVisible: true });
    const element = await render(input);
    const trigger = element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!;
    await act(async () => trigger.click());
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')?.textContent).toContain("正在补齐测试");
    expect(open).not.toHaveBeenCalled();
    expect(input.setSessionBrowserOpen).not.toHaveBeenCalled();
    expect(input.toggleChangeRail).not.toHaveBeenCalled();
    expect(input.setResponsiveOverlayPane).not.toHaveBeenCalled();
    await render({ ...input, changeRailVisible: true });
    await act(async () => trigger.click());
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')).toBeNull();
    expect(input.toggleChangeRail).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });

  it("closes on Escape and restores focus to the task entry", async () => {
    const element = await render(props());
    const trigger = element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!;
    await act(async () => { trigger.focus(); trigger.click(); });
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on an outside pointer without toggling the side pane", async () => {
    const input = props();
    const element = await render(input);
    const trigger = element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!;
    await act(async () => trigger.click());
    // Radix installs its outside-pointer listener on the next task.
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    await act(async () => {
      const pointer = new PointerEvent("pointerdown", { pointerType: "mouse", button: 0, bubbles: true });
      // happy-dom clears event.target after dispatch; Radix reads it on click.
      Object.defineProperty(pointer, "target", { value: document.body });
      document.body.dispatchEvent(pointer);
      document.body.click();
    });
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(input.toggleChangeRail).not.toHaveBeenCalled();
  });

  it("closes a previous session's card before showing a new session's checklist", async () => {
    const input = props();
    const element = await render(input);
    await act(async () => element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!.click());
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')).not.toBeNull();
    await render({ ...input, activeSessionId: "session-2", conversationModel: { sessionId: "session-2", messages: messages(true) } });
    expect(document.querySelector('[data-vui="conversation-todo-popover"]')).toBeNull();
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.getAttribute("aria-expanded")).toBe("false");
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.textContent).toContain("1/1");
  });

  it("keeps long Chinese content and the latest settled snapshot in the open card", async () => {
    const longText = "检查会话切换后的任务清单与当前会话完全一致并保留全部中文内容".repeat(5);
    const input = props({ conversationModel: { sessionId: "session-1", messages: messages(false, longText) } });
    const element = await render(input);
    await act(async () => element.querySelector<HTMLButtonElement>('[data-testid="conversation-todo-progress"]')!.click());
    expect(document.querySelector('[data-testid="todo-checklist-items"]')?.textContent).toBe(`正在${longText}`);
    await render({ ...input, conversationModel: { sessionId: "session-1", messages: messages(false, longText, true) } });
    expect(document.querySelector('[data-testid="todo-checklist-items"]')?.textContent).toBe(longText);
    expect(document.querySelector('[data-testid="todo-checklist-warning"]')?.textContent).toBeTruthy();
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')?.getAttribute("data-todo-progress-status")).toBe("paused");
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
    { verifiedCompanionMode: true }, { groupPanelActive: true }, { financeSurface: true }, { ordinaryChangeRail: false },
    { conversationModel: { sessionId: "session-1", messages: [] } },
  ])("keeps the entry out of unrelated or empty surfaces: %j", async (overrides) => {
    const element = await render(props(overrides));
    expect(element.querySelector('[data-testid="conversation-todo-progress"]')).toBeNull();
  });
});
