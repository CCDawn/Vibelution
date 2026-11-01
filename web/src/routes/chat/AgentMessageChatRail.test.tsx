/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { AgentMessageRecord } from "../../components/agent-messages";
import { AgentMessageChatRail } from "./AgentMessageChatRail";
import { selectAgentMessage } from "./agentMessageSelectionStore";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const messageModel = vi.hoisted(() => ({
  records: [], loading: false, error: "", scanned: 0, hasMore: false, limit: 30, refresh: vi.fn(),
}));
vi.mock("./useAgentMessageRecords", () => ({ useAgentMessageRecords: () => messageModel }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
beforeEach(() => { messageModel.records = []; selectAgentMessage(null); });

it("reveals the conversation catalog when its group composer is opened from the toolbar", async () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  function Harness() {
    const [open, setOpen] = useState(false);
    return <><button onClick={() => setOpen(true)}>新建群聊</button>
      <AgentMessageChatRail sessionId="current" agentsById={new Map()} lang="zh" revealConversations={open}>
        {open ? <label>群聊名称<input aria-label="群聊名称" /></label> : null}
      </AgentMessageChatRail></>;
  }
  try {
    await act(async () => root.render(<MemoryRouter><Harness /></MemoryRouter>));
    expect(host.querySelector('[aria-label="群聊名称"]')).toBeNull();
    await act(async () => { host.querySelector("button")!.click(); });
    expect(host.querySelector('[aria-label="群聊名称"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="agent-message-chat-rail"]')).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it.each([false, true])("returns to the previous conversation before falling back to a reply source (direct center: %s)", async (directCenter) => {
  const reply: AgentMessageRecord = { id: "reply", type: "reply", sourceSessionId: "other-agent-session", replyToId: "request",
    sender: { agentId: "reviewer", name: "审查助手" }, recipients: [], title: "回复", body: "已检查", createdAt: "" };
  Object.assign(messageModel, { records: [reply] });
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  function Harness() {
    const location = useLocation();
    return <><output>{location.search}</output><AgentMessageChatRail
      sessionId={new URLSearchParams(location.search).get("session")} agentsById={new Map()} lang="zh"><span>会话索引</span>
    </AgentMessageChatRail></>;
  }
  const click = (label: string) => [...host.querySelectorAll("button")].find((button) => button.textContent === label)!.click();
  try {
    await act(async () => root.render(<MemoryRouter initialEntries={[directCenter ? "/chat?room=__project_agent_bus__" : "/chat?session=original-session"]}><Harness /></MemoryRouter>));
    if (!directCenter) await act(async () => click("消息中心"));
    await act(async () => selectAgentMessage("reply"));
    await act(async () => click("当前对话"));
    expect(host.querySelector("output")!.textContent).toBe(`?session=${directCenter ? "other-agent-session" : "original-session"}`);
  } finally { await act(async () => root.unmount()); host.remove(); selectAgentMessage(null); }
});
