// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage } from "../../api/types";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";
import { resetToolExpandPersistenceForTests } from "./conversationToolExpandPersistence";

vi.mock("./LazyConversationMarkdownRenderer", () => ({
  LazyConversationMarkdownRenderer: ({ content }: { content: string }) => <div data-test-markdown="true">{content}</div>,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const LONG_PROGRESS = "先检查本地配置与缓存，再运行定向回归测试，确认没有新的回归，并补齐证据。".repeat(7);

function progressMessage(status: "running" | "completed", revision: number, text: string): ConversationMessage {
  return {
    id: "assistant-progress-commentary",
    role: "assistant",
    timestamp: "2026-09-11T06:30:00Z",
    turnId: "turn-progress-commentary",
    status,
    turnItems: [{
      id: `progress-commentary:${revision}`,
      itemId: "progress-commentary",
      version: 3,
      sessionId: "session-progress-commentary",
      turnId: "turn-progress-commentary",
      type: "agent_message",
      phase: "commentary",
      status,
      revision,
      sequence: 1,
      terminal: status === "completed",
      text,
    }],
  } as ConversationMessage;
}

function mixedMessage(status: "running" | "completed" | "failed", revision = 0): ConversationMessage {
  const message = progressMessage(status === "running" ? "running" : "completed", revision, LONG_PROGRESS);
  const base = { version: 3 as const, sessionId: "session-progress-commentary", turnId: message.turnId!, revision };
  return {
    ...message,
    status: status === "failed" ? "completed" : status,
    turnItems: [
      { ...base, id: `thought:${revision}`, itemId: "thought", sequence: 1, type: "reasoning", status: "completed", terminal: true, text: "已完成的前一段思考。" },
      { ...message.turnItems![0], sequence: 2 },
      {
        ...base, id: `tool:${revision}`, itemId: "tool", sequence: 3, type: "tool_call",
        callId: "read-config", toolName: "web_fetch_tool", status: status === "failed" ? "failed" : "completed", terminal: true,
        input: JSON.stringify({ url: "https://example.org/config.toml" }),
        output: status === "failed"
          ? "配置读取失败：访问被拒绝 HTTP 403 https://example.org/config.toml"
          : "HTTP 200 https://example.org/config.toml",
      },
      { ...message.turnItems![0], id: `second-progress:${revision}`, itemId: "second-progress", sequence: 4, text: "继续核对测试结果。" },
      { ...base, id: `current-thought:${revision}`, itemId: "current-thought", sequence: 5, type: "reasoning", status: status === "running" ? "running" : "completed", terminal: status !== "running", text: `思考摘要第 ${revision} 版。` },
    ],
  } as ConversationMessage;
}

describe("ConversationView visible progress flow", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let updateMessages: ((messages: ConversationMessage[]) => void) | null = null;

  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 1280, height: 900, top: 0, left: 0, right: 1280, bottom: 900, x: 0, y: 0, toJSON: () => ({}),
    });
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1280);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(900);
    window.localStorage.clear();
    resetToolExpandPersistenceForTests();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ controlToken: "test-control-token" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
    updateMessages = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function mount(initial: ConversationMessage[]) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(queryKeys.sessionMessageCuration("session-progress-commentary"), { items: [] });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [messages, setMessages] = useState(initial);
      updateMessages = setMessages;
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-progress-commentary"
            title="Session"
            phase="ready"
            messages={messages}
            showHeader={false}
            showSessionOverview={false}
            showComposer={false}
            processDisplayMode="trace"
            assistantDisplayName="洛天依"
            composerValue=""
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            defaultFileContext="workspace"
            onComposerChange={() => undefined}
            onSubmit={() => undefined}
            onStop={() => undefined}
            onClear={() => undefined}
            onJumpToLatest={() => undefined}
            onCreateNewSession={() => undefined}
          />
        </QueryClientProvider>
      );
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness />);
      await Promise.resolve();
    });
    return container;
  }

  function progressSection() {
    const section = container?.querySelector<HTMLElement>('section[data-codex-progress-cell="true"]');
    if (!section) {
      throw new Error("progress commentary cell not mounted");
    }
    return section;
  }

  it("keeps long commentary fully visible through streaming updates and full turn settlement", async () => {
    await mount([progressMessage("running", 0, LONG_PROGRESS)]);
    const section = progressSection();
    expect(section.textContent).toBe(LONG_PROGRESS);
    expect(section.querySelector("button[aria-expanded]")).toBeNull();
    expect(section.querySelector('[data-codex-progress-clamped="true"]')).toBeNull();
    expect(section.closest("[inert], [aria-hidden=true]")).toBeNull();
    expect(container?.querySelector('[data-codex-process-thought-toggle]')).toBeNull();

    await act(async () => {
      updateMessages?.([progressMessage("running", 1, `${LONG_PROGRESS} 仍在输出。`)]);
    });
    expect(progressSection().textContent).toBe(`${LONG_PROGRESS} 仍在输出。`);

    await act(async () => {
      updateMessages?.([progressMessage("completed", 2, `${LONG_PROGRESS} 输出完成。`)]);
    });
    expect(progressSection().textContent).toBe(`${LONG_PROGRESS} 输出完成。`);
    expect(progressSection().querySelector("button[aria-expanded]")).toBeNull();
    expect(progressSection().closest("details, [inert], [aria-hidden=true]")).toBeNull();
    expect(container?.querySelector('[data-codex-process-state="completed"]')).not.toBeNull();
  });

  it("keeps native thought order and an explicit open choice across updates, settlement, and remount", async () => {
    await mount([mixedMessage("running")]);
    const flow = () => container!.querySelector<HTMLElement>('[data-codex-process-presentation="flow"]')!;
    const thought = () => flow().querySelector<HTMLElement>('[data-thought-section="reasoning:current-thought"]')!;
    const thoughtToggle = () => thought().querySelector<HTMLButtonElement>("button")!;
    const initialThought = thought();
    expect(flow().querySelector("[data-codex-process-thought-toggle]")).toBeNull();
    expect([...flow().querySelectorAll("button")].some(button => button.textContent === "显示思考" || button.textContent === "收起思考")).toBe(false);
    expect(thought().getAttribute("data-conversation-part-key")).toBe("current-thought");
    const earlierThought = flow().querySelector('[data-thought-section="reasoning:thought"]')!;
    expect(earlierThought.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
    expect(earlierThought.closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();
    expect(thought().closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("false");
    expect(thought().querySelector('[data-thought-scroll-body="true"]')).toBeNull();
    expect(thought().querySelector('[data-thought-streaming-summary="true"]')?.textContent).toBe("思考摘要第 0 版。");
    expect(progressSection().textContent).toBe(LONG_PROGRESS);
    const tool = flow().querySelector<HTMLDetailsElement>('details[data-codex-tool-activity-item="true"]');
    expect(tool).not.toBeNull();
    expect(tool?.open).toBe(false);
    expect(tool?.closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();
    expect(tool?.querySelector('[data-codex-tool-detail-body="true"]')).toBeNull();
    expect(Array.from(flow().querySelectorAll("[data-codex-transcript-cell-kind]"))
      .map((cell) => cell.getAttribute("data-codex-transcript-cell-kind")))
      .toEqual(["reasoning_summary", "assistant_markdown", "tool_call", "assistant_markdown", "reasoning_summary"]);
    expect(thought().compareDocumentPosition(flow().querySelector('[data-codex-process-work-status="true"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await act(async () => tool?.querySelector("summary")?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(tool?.open).toBe(true);
    expect(tool?.querySelector('[data-codex-tool-detail-body="true"]')).not.toBeNull();

    // Opening this native unit leaves the earlier thought's own choice untouched.
    await act(async () => thoughtToggle().click());
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("true");
    expect(earlierThought.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
    expect(flow().querySelector('[data-thought-scroll-body="true"]')?.textContent).toContain("思考摘要第 0 版。");
    expect(thought().querySelectorAll("button")).toHaveLength(1);
    expect(flow().querySelector('[data-thought-section]')?.closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();

    await act(async () => updateMessages?.([mixedMessage("running", 1)]));
    expect(thought()).toBe(initialThought);
    expect(flow().querySelector('details[data-codex-tool-activity-item="true"]')).toBe(tool);
    expect(flow().querySelector('[data-thought-scroll-body="true"]')?.textContent).toContain("思考摘要第 1 版。");
    await act(async () => updateMessages?.([mixedMessage("completed", 2)]));
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("true");
    expect(flow().querySelector('[data-thought-scroll-body="true"]')?.textContent).toContain("思考摘要第 2 版。");
    expect(progressSection().textContent).toBe(LONG_PROGRESS);
    await act(async () => updateMessages?.([]));
    await act(async () => updateMessages?.([mixedMessage("completed", 2)]));
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("true");
    expect(flow().querySelector('[data-thought-scroll-body="true"]')?.textContent).toContain("思考摘要第 2 版。");
    await act(async () => {
      thoughtToggle().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(flow().querySelector('[data-thought-scroll-body="true"]')).toBeNull();
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("false");
    expect(thought().closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();
    expect(progressSection().textContent).toBe(LONG_PROGRESS);
    expect(flow().querySelector('[data-codex-tool-activity="items"]')).not.toBeNull();
  });

  it("preserves an explicit closed thought across live revisions, settlement, and row remount", async () => {
    await mount([mixedMessage("running")]);
    const thought = () => container!.querySelector<HTMLElement>('[data-thought-section="reasoning:current-thought"]')!;
    const toggle = () => thought().querySelector<HTMLButtonElement>("button")!;
    await act(async () => toggle().click());
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    await act(async () => toggle().click());
    const expectClosed = () => {
      expect(toggle().getAttribute("aria-expanded")).toBe("false");
      expect(thought().querySelector('[data-thought-scroll-body="true"]')).toBeNull();
      expect(thought().closest("[hidden], [inert], [aria-hidden=true]")).toBeNull();
      expect(container?.querySelector("[data-codex-process-thought-toggle]")).toBeNull();
      expect(progressSection().textContent).toBe(LONG_PROGRESS);
    };
    expectClosed();
    await act(async () => updateMessages?.([mixedMessage("running", 1)]));
    expectClosed();
    expect(thought().querySelector('[data-thought-streaming-summary="true"]')?.textContent).toBe("思考摘要第 1 版。");
    await act(async () => updateMessages?.([mixedMessage("completed", 2)]));
    expectClosed();
    expect(thought().querySelector('[data-thought-streaming-summary="true"]')).toBeNull();
    await act(async () => updateMessages?.([]));
    await act(async () => updateMessages?.([mixedMessage("completed", 2)]));
    expectClosed();
    await act(async () => toggle().click());
    expect(thought().querySelector('[data-thought-scroll-body="true"]')?.textContent).toBe("思考摘要第 2 版。");
  });

  it("preserves commentary and failed tool evidence when the turn ends", async () => {
    await mount([mixedMessage("running")]);
    await act(async () => updateMessages?.([mixedMessage("failed", 1)]));
    const flow = container!.querySelector<HTMLElement>('[data-codex-process-presentation="flow"]')!;
    expect(flow.getAttribute("data-codex-process-state")).toBe("failed");
    expect(flow.getAttribute("data-codex-process-work-expanded")).toBe("true");
    expect(flow.textContent).toContain(LONG_PROGRESS);
    expect(flow.textContent).toContain("继续核对测试结果。");
    expect(flow.querySelector('[data-codex-tool-status-kind="failed"]')).not.toBeNull();
    const tool = flow.querySelector<HTMLDetailsElement>('details[data-codex-tool-activity-item="true"]');
    await act(async () => tool?.querySelector("summary")?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(tool?.open).toBe(true);
    expect(tool?.querySelector('[data-codex-tool-detail-body="true"]')?.textContent).toContain("403");
  });
});
