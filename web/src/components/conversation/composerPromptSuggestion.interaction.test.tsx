/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const userMessage: ConversationMessage = {
  id: "message-1",
  role: "user",
  content: "先跑一遍测试",
  timestamp: "2026-01-01T00:00:00Z",
};

function fetchRoutes(suggestion: string) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.includes("/prompt-suggestion")) {
      return new Response(
        JSON.stringify({ sessionId: "session-1", turnId: "turn-1", suggestion, reason: "ok" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/composer-example")) {
      return new Response(JSON.stringify({ command: "" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

describe("composer prompt suggestion interaction", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    clearControlToken();
    vi.unstubAllGlobals();
  });

  async function renderComposer(options: {
    composerValue: string;
    composerActionMode?: "send" | "stop";
    promptSuggestionEnabled?: boolean;
    onComposerChange: (value: string) => void;
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-1"
            title="Session"
            phase="ready"
            messages={[userMessage]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={options.composerValue}
            composerPlaceholder=""
            composerDisabled={false}
            composerActionMode={options.composerActionMode}
            composerPending={false}
            promptSuggestionEnabled={options.promptSuggestionEnabled ?? true}
            onComposerChange={options.onComposerChange}
            onSubmit={() => undefined}
            onEditUserMessage={() => undefined}
          />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it("shows the fetched suggestion as a Tab-completable ghost and accepts it", async () => {
    const fetchMock = fetchRoutes("修复构建错误");
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    const onComposerChange = vi.fn();

    await renderComposer({ composerValue: "", onComposerChange });

    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    expect(textarea).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/prompt-suggestion"))).toBe(true);
    expect(textarea?.placeholder).toBe("修复构建错误（Tab 补全）");
    expect(textarea?.getAttribute("data-composer-prompt-suggestion")).toBe("true");

    const tabEvent = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    await act(async () => {
      textarea?.dispatchEvent(tabEvent);
    });
    expect(tabEvent.defaultPrevented).toBe(true);
    expect(onComposerChange).toHaveBeenCalledWith("修复构建错误");
  });

  it("stays silent once the composer has a draft and while a turn is running", async () => {
    const fetchMock = fetchRoutes("修复构建错误");
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();

    await renderComposer({
      composerValue: "已经在写了",
      onComposerChange: () => undefined,
    });
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/prompt-suggestion"))).toBe(false);
    expect(container?.querySelector("[data-composer-prompt-suggestion]")).toBeNull();

    await act(async () => {
      root?.unmount();
    });
    container?.remove();
    root = null;
    container = null;
    fetchMock.mockClear();

    await renderComposer({
      composerValue: "",
      composerActionMode: "stop",
      onComposerChange: () => undefined,
    });
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/prompt-suggestion"))).toBe(false);
    expect(container?.querySelector("[data-composer-prompt-suggestion]")).toBeNull();
  });

  it("attempts only one suggestion request per turn", async () => {
    const fetchMock = fetchRoutes("继续跑剩余测试");
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    const onComposerChange = vi.fn();

    await renderComposer({ composerValue: "", onComposerChange });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const calls = fetchMock.mock.calls.filter(([input]) => String(input).includes("/prompt-suggestion"));
    expect(calls).toHaveLength(1);
  });
});
