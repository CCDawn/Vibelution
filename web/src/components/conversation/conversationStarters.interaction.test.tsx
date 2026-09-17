/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage, SkillLibraryItem } from "../../api/types";
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

const backendStarters = [
  { heading: "修复问题", command: "修复 lint 报错" },
  { heading: "理解代码", command: "agent.py 是怎么工作的？" },
  { heading: "编写测试", command: "给 agent.py 写个测试" },
];

function skillItem(command: string): SkillLibraryItem {
  return {
    name: command.replace("/", ""),
    aliases: [],
    command,
    description: `${command} skill`,
    source: "codex",
    rootPath: "C:/Users/17533/.codex/skills",
    path: `C:/Users/17533/.codex/skills/${command.replace("/", "")}/SKILL.md`,
    directoryName: command.replace("/", ""),
    hash: "hash",
    contentLength: 100,
    preview: "",
    previewTruncated: false,
  };
}

function fetchRoutes(starters: unknown) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.includes("/composer-example")) {
      return new Response(JSON.stringify(starters), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

const llmControl = {
  model: {
    modelId: "model-1",
    modelRef: "provider/model-1",
    label: "测试模型",
    model: "model-1",
    providerId: "provider",
    providerLabel: "Provider",
    providerKind: "openai",
    apiKeyConfigured: true,
    missingApiKey: false,
    supportsReasoningEffort: true,
    reasoningEffortValues: ["low", "medium", "high"],
    reasoningEffortOptions: [
      { value: "low", label: "低", description: "" },
      { value: "medium", label: "中", description: "" },
      { value: "high", label: "高", description: "" },
    ],
    defaultReasoningEffort: "medium",
    isDefault: true,
  },
  currentReasoningEffort: "medium",
  disabled: false,
  pending: false,
  onReasoningEffortChange: () => undefined,
};

function keydown(key: string, init: KeyboardEventInit = {}) {
  return new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
}

describe("conversation starter cards and builtin slash commands", () => {
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

  async function renderConversation(options: {
    messages?: ConversationMessage[];
    composerValue?: string;
    onCreateSession?: () => void;
    onOpenComposerContextDetail?: () => void;
    onComposerChange: (value: string) => void;
    onSubmit?: () => void;
    slashCommandSuggestions?: SkillLibraryItem[];
    withLlmControl?: boolean;
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
            messages={options.messages ?? []}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={options.composerValue ?? ""}
            composerPlaceholder=""
            composerDisabled={false}
            composerActionMode="send"
            composerPending={false}
            onCreateSession={options.onCreateSession}
            onOpenComposerContextDetail={options.onOpenComposerContextDetail}
            llmControl={options.withLlmControl ? llmControl : undefined}
            slashCommandSuggestions={options.slashCommandSuggestions ?? []}
            onComposerChange={options.onComposerChange}
            onSubmit={options.onSubmit ?? (() => undefined)}
            onEditUserMessage={() => undefined}
          />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it("renders backend starter cards in an empty session and fills the composer without submitting", async () => {
    const fetchMock = fetchRoutes({ command: backendStarters[0].command, starters: backendStarters });
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    const onComposerChange = vi.fn();
    const onSubmit = vi.fn();

    await renderConversation({ onComposerChange, onSubmit });

    const cards = Array.from(container?.querySelectorAll<HTMLButtonElement>('[data-vui="conversation-starter-card"]') ?? []);
    expect(cards).toHaveLength(3);
    expect(cards[0]?.textContent).toContain("修复问题");
    expect(cards[0]?.textContent).toContain("修复 lint 报错");
    expect(cards[0]?.className).toContain("!flex-col");
    expect(cards[0]?.className).toContain("!items-stretch");
    expect(cards[0]?.children[0]?.className).toContain("emptyStateStarterCardHeading");
    expect(cards[0]?.children[1]?.className).toContain("emptyStateStarterCardCommand");

    await act(async () => {
      cards[1]?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(onComposerChange).toHaveBeenCalledWith("agent.py 是怎么工作的？");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("falls back to dictionary starters when the backend returns none", async () => {
    const fetchMock = fetchRoutes({ command: "", starters: [] });
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    const onComposerChange = vi.fn();

    await renderConversation({ onComposerChange });

    const cards = Array.from(container?.querySelectorAll<HTMLButtonElement>('[data-vui="conversation-starter-card"]') ?? []);
    expect(cards).toHaveLength(3);
    expect(cards[0]?.textContent).toContain("梳理思路");
    expect(cards[0]?.textContent).toContain(dictionary.zh.sessionStarterOrganizeCommand);

    await act(async () => {
      cards[0]?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(onComposerChange).toHaveBeenCalledWith(dictionary.zh.sessionStarterOrganizeCommand);
  });

  it("does not render starter cards once the session has messages", async () => {
    const fetchMock = fetchRoutes({ command: backendStarters[0].command, starters: backendStarters });
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();

    await renderConversation({ messages: [userMessage], onComposerChange: () => undefined });

    expect(container?.querySelector('[data-vui="conversation-starter-cards"]')).toBeNull();
  });

  it("executes the /新会话 builtin on Enter and clears the draft without submitting", async () => {
    vi.stubGlobal("fetch", fetchRoutes({ command: "", starters: [] }));
    seedControlTokenForTests();
    const onComposerChange = vi.fn();
    const onSubmit = vi.fn();
    const onCreateSession = vi.fn();

    await renderConversation({
      composerValue: "/新",
      onCreateSession,
      onComposerChange,
      onSubmit,
    });

    const listbox = container?.querySelector('[role="listbox"]');
    expect(listbox).toBeTruthy();
    expect(listbox?.textContent).toContain("/新会话");
    expect(listbox?.textContent).toContain("内置");

    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    expect(textarea?.getAttribute("aria-expanded")).toBe("true");

    await act(async () => {
      textarea?.dispatchEvent(keydown("Enter"));
    });
    expect(onCreateSession).toHaveBeenCalledTimes(1);
    expect(onComposerChange).toHaveBeenCalledWith("");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("executes the /压缩 builtin through the context detail channel", async () => {
    vi.stubGlobal("fetch", fetchRoutes({ command: "", starters: [] }));
    seedControlTokenForTests();
    const onOpenComposerContextDetail = vi.fn();

    await renderConversation({
      composerValue: "/压",
      onOpenComposerContextDetail,
      onComposerChange: () => undefined,
    });

    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    await act(async () => {
      textarea?.dispatchEvent(keydown("Enter"));
    });
    expect(onOpenComposerContextDetail).toHaveBeenCalledTimes(1);
  });

  it("opens the inference menu via the /模型 builtin", async () => {
    vi.stubGlobal("fetch", fetchRoutes({ command: "", starters: [] }));
    seedControlTokenForTests();

    await renderConversation({
      composerValue: "/模",
      withLlmControl: true,
      onComposerChange: () => undefined,
    });

    const trigger = container?.querySelector<HTMLButtonElement>('[data-testid="conversation-inference-control"] button');
    expect(trigger?.getAttribute("aria-expanded")).toBe("false");

    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    await act(async () => {
      textarea?.dispatchEvent(keydown("Enter"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(trigger?.getAttribute("aria-expanded")).toBe("true");
  });

  it("merges builtins before skills, supports keyboard navigation, and Tab-completes a skill", async () => {
    vi.stubGlobal("fetch", fetchRoutes({ command: "", starters: [] }));
    seedControlTokenForTests();
    const onComposerChange = vi.fn();
    const onCreateSession = vi.fn();

    await renderConversation({
      composerValue: "/",
      onCreateSession,
      onOpenComposerContextDetail: () => undefined,
      withLlmControl: true,
      slashCommandSuggestions: [skillItem("/research-plan")],
      onComposerChange,
    });

    const options = Array.from(container?.querySelectorAll('[role="option"]') ?? []);
    expect(options).toHaveLength(4);
    expect(options[0]?.getAttribute("aria-label")).toBe("/新会话");
    expect(options[3]?.getAttribute("aria-label")).toBe("/research-plan");
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");

    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    // Four downs from "no active row" land on the fourth option (skill row).
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        textarea?.dispatchEvent(keydown("ArrowDown"));
      });
    }
    const optionsAfter = Array.from(container?.querySelectorAll('[role="option"]') ?? []);
    expect(optionsAfter[3]?.getAttribute("aria-selected")).toBe("true");
    expect(textarea?.getAttribute("aria-activedescendant")).toBe(optionsAfter[3]?.id);

    await act(async () => {
      textarea?.dispatchEvent(keydown("Tab"));
    });
    expect(onComposerChange).toHaveBeenCalledWith("/research-plan ");
    expect(onCreateSession).not.toHaveBeenCalled();
  });

  it("closes the suggestion list on Escape while keeping the draft", async () => {
    vi.stubGlobal("fetch", fetchRoutes({ command: "", starters: [] }));
    seedControlTokenForTests();

    await renderConversation({
      composerValue: "/新",
      onCreateSession: () => undefined,
      onComposerChange: () => undefined,
    });

    expect(container?.querySelector('[role="listbox"]')).toBeTruthy();
    const textarea = container?.querySelector<HTMLTextAreaElement>("textarea");
    await act(async () => {
      textarea?.dispatchEvent(keydown("Escape"));
    });
    expect(container?.querySelector('[role="listbox"]')).toBeNull();
    expect(textarea?.value).toBe("/新");
  });
});
