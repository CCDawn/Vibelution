// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage } from "../../api/types";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", () => ({
  LazyConversationMarkdownRenderer: () => null,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const LONG_PROGRESS = "先检查本地配置与缓存，再运行定向回归测试，确认没有新的回归，并补齐证据。".repeat(7);

function progressMessage(status: "running" | "completed", revision: number, text: string): ConversationMessage {
  return {
    id: "assistant-progress-commentary",
    role: "assistant",
    timestamp: "2026-09-11T06:30:00Z",
    turnId: "turn-progress-commentary",
    // Keep the turn live while its commentary item updates/settles so the test
    // exercises the same mounted transcript cell and stable section identity.
    status: "running",
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

describe("ConversationView live progress commentary collapse", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let updateMessages: ((messages: ConversationMessage[]) => void) | null = null;

  beforeEach(() => {
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

  it("keeps a user expansion through live updates and item settlement, then allows collapsing", async () => {
    await mount([progressMessage("running", 0, LONG_PROGRESS)]);
    const section = progressSection();
    const toggle = section.querySelector<HTMLButtonElement>("button[aria-expanded]");

    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(section.querySelector('[data-codex-progress-clamped="true"]')).not.toBeNull();

    await act(async () => toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(progressSection().querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("true");
    expect(progressSection().querySelector('[data-codex-progress-body="true"]')).not.toBeNull();

    await act(async () => {
      updateMessages?.([progressMessage("running", 1, `${LONG_PROGRESS} 仍在输出。`)]);
    });
    expect(progressSection().querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("true");

    await act(async () => {
      updateMessages?.([progressMessage("completed", 2, `${LONG_PROGRESS} 输出完成。`)]);
    });
    const settledToggle = progressSection().querySelector<HTMLButtonElement>("button[aria-expanded]");
    expect(settledToggle?.getAttribute("aria-expanded")).toBe("true");

    await act(async () => settledToggle?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(progressSection().querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("false");
    expect(progressSection().querySelector('[data-codex-progress-clamped="true"]')).not.toBeNull();
  });

  it("keeps the default preview after a live commentary item settles", async () => {
    await mount([progressMessage("running", 0, LONG_PROGRESS)]);
    expect(progressSection().querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("false");

    await act(async () => {
      updateMessages?.([progressMessage("completed", 1, LONG_PROGRESS)]);
    });
    expect(progressSection().querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("false");
    expect(progressSection().querySelector('[data-codex-progress-clamped="true"]')).not.toBeNull();
  });
});
