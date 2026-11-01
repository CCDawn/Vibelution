/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { AgentMessageChatRail } from "./AgentMessageChatRail";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("./useAgentMessageRecords", () => ({ useAgentMessageRecords: () => ({
  records: [], loading: false, error: "", scanned: 0, hasMore: false, limit: 30, refresh: vi.fn(),
}) }));

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
