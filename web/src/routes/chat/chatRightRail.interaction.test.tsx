/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { VuiProvider } from "../../components/vui";
import { ChatRightRail, type ChatRightRailSideClient } from "./ChatRightRail";
import {
  EMPTY_CHAT_RIGHT_RAIL,
  openChatRightRailTab,
  openFreshChatRightRailSideTab,
  type ChatRightRailModel,
} from "./chatRightRailModel";

const filesApi = vi.hoisted(() => ({
  fetchFileContent: vi.fn(async (path: string) => ({
    path,
    language: "markdown",
    content: "文件正文",
    truncated: false,
  })),
}));

vi.mock("../../api/files", () => filesApi);

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const emptyReview = {
  sessionTitle: "这次对话",
  sessionEmptyLabel: "这次对话还没有改动文件",
  sessionPaths: [] as string[],
  sessionSelectedPath: null,
  sessionChangedPaths: new Set<string>(),
  gitTitle: "仓库",
  gitEmptyLabel: "工作区是干净的",
  gitPending: false,
  gitPendingLabel: "正在读取仓库",
  gitUnavailableLabel: "",
  gitPaths: [] as string[],
  gitSelectedPath: null,
  diff: undefined,
  diffLoading: false,
  hasDiff: false,
  file: null,
  fileLoading: false,
  fileError: "",
  sourceLabel: "当前会话",
  onSelectSessionFile: () => undefined,
  onSelectGitFile: () => undefined,
};

function Harness({ client, initialModel = EMPTY_CHAT_RIGHT_RAIL }: {
  client: ChatRightRailSideClient;
  initialModel?: ChatRightRailModel;
}) {
  const [model, setModel] = useState<ChatRightRailModel>(initialModel);
  const activeSideTab = model.tabs.find((tab) => tab.id === model.activeId && tab.kind === "side");
  return (
    <>
      <output data-testid="pending-readback-generation">{JSON.stringify(activeSideTab?.pendingReadbackGeneration ?? null)}</output>
      <output data-testid="model-state">{JSON.stringify(model)}</output>
      <ChatRightRail
        className="rail"
        lang="zh"
        sessionId="parent-1"
        model={model}
        onModelChange={setModel}
        onCollapse={() => undefined}
        devtools={{ phase: "idle", status: "ready", messages: [] }}
        terminalRun={null}
        terminalMountedInCenter={false}
        onOpenFile={() => undefined}
        review={emptyReview}
        sideClient={client}
      />
    </>
  );
}

describe("chat right rail interaction", () => {
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
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function mount(
    client: ChatRightRailSideClient,
    initialModel = EMPTY_CHAT_RIGHT_RAIL,
    prepare?: (queryClient: QueryClient) => void,
  ) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    prepare?.(queryClient);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <QueryClientProvider client={queryClient}>
            <Harness client={client} initialModel={initialModel} />
          </QueryClientProvider>
        </VuiProvider>,
      );
    });
    return container;
  }

  it("starts from the launcher and sends a side chat without a canned reply", async () => {
    const created: Array<{ announceOnParent?: boolean; switchToChild?: boolean; source?: string }> = [];
    const messages: ConversationMessage[] = [];
    const client: ChatRightRailSideClient = {
      createChild: async (_sessionId, payload) => {
        created.push(payload);
        messages.push({ id: "u1", role: "user", timestamp: "", content: payload.userRequest });
        return { childSessionId: "child-1", parentSessionId: "parent-1" };
      },
      submit: async () => undefined,
      fetchDetail: async () => ({
        currentPhase: "idle",
        status: "ready",
        messages: [...messages],
      }),
    };
    const host = await mount(client);
    expect(host.textContent).toContain("打开标签页");
    expect(host.textContent).toContain("辅助对话");
    expect(host.textContent).not.toContain("画板");

    const openSide = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "辅助对话");
    expect(openSide).toBeTruthy();
    await act(async () => {
      openSide?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const input = host.querySelector("textarea");
    expect(input).toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "只在右栏问");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "发送");
    await act(async () => {
      send?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(created).toEqual([
      expect.objectContaining({
        announceOnParent: false,
        switchToChild: false,
        source: "side_pane",
      }),
    ]);
    expect(host.textContent).toContain("只在右栏问");
    expect(host.textContent).not.toContain("预览回复");
  });

  it("restores each side-chat draft after switching between side and non-side tabs", async () => {
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "A 的草稿",
    });
    model = openFreshChatRightRailSideTab(model, { titleBase: "辅助对话", draft: "B 的草稿" });
    model = openChatRightRailTab(model, { kind: "review", title: "审查" });
    model = { ...model, activeId: "side:2" };
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child", parentSessionId: "parent-1" }),
      submit: async () => undefined,
      fetchDetail: async () => ({ currentPhase: "idle", status: "ready", messages: [] }),
    };
    const host = await mount(client, model);
    const clickTab = async (label: string) => {
      const button = Array.from(host.querySelectorAll("[role=tab] button"))
        .find((item) => item.textContent === label);
      await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    };
    const changeDraft = async (value: string) => {
      const input = host.querySelector("textarea");
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
        setter?.call(input, value);
        input?.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };

    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("B 的草稿");
    await changeDraft("B 的新草稿");
    await clickTab("辅助对话");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("A 的草稿");
    await changeDraft("A 的新草稿");
    await clickTab("审查");
    expect(host.querySelector("textarea")).toBeNull();
    await clickTab("辅助对话 2");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("B 的新草稿");
    await clickTab("辅助对话");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("A 的新草稿");
  });

  it("does not let an earlier auto-send clear a draft entered after returning to its tab", async () => {
    let resolveCreate!: (value: { childSessionId: string; parentSessionId: string }) => void;
    const client: ChatRightRailSideClient = {
      createChild: () => new Promise((resolve) => { resolveCreate = resolve; }),
      submit: async () => undefined,
      fetchDetail: async () => ({ currentPhase: "idle", status: "ready", messages: [] }),
    };
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "自动发送的旧草稿",
      sendDraft: true,
    });
    const sideId = model.activeId;
    model = openChatRightRailTab(model, { kind: "review", title: "审查" });
    model = { ...model, activeId: sideId };
    const host = await mount(client, model);
    await act(async () => { await Promise.resolve(); });

    const clickTab = async (label: string) => {
      const button = Array.from(host.querySelectorAll("[role=tab] button"))
        .find((item) => item.textContent === label);
      await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    };
    await clickTab("审查");
    await clickTab("辅助对话");
    const input = host.querySelector("textarea");
    expect((input as HTMLTextAreaElement).value).toBe("自动发送的旧草稿");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "切换期间的新草稿");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await act(async () => {
      resolveCreate({ childSessionId: "child-late", parentSessionId: "parent-1" });
      await Promise.resolve();
    });
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("切换期间的新草稿");
  });

  it("cancels an older detail request and forces a fresh readback after submit", async () => {
    let fetches = 0;
    let initialReadAborted = false;
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-race", parentSessionId: "parent-1" }),
      submit: async () => undefined,
      fetchDetail: async (_sessionId, signal) => {
        fetches += 1;
        if (fetches === 1) {
          return new Promise((_, reject) => {
            signal?.addEventListener("abort", () => {
              initialReadAborted = true;
              reject(new DOMException("Aborted", "AbortError"));
            }, { once: true });
          });
        }
        return { currentPhase: "idle", status: "ready", messages: [] };
      },
    };
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话" });
    model = {
      ...model,
      tabs: model.tabs.map((tab) => ({ ...tab, childSessionId: "child-race" })),
    };
    const host = await mount(client, model);
    await act(async () => { await Promise.resolve(); });
    expect(fetches).toBe(1);

    const input = host.querySelector("textarea");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "取消旧请求");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "发送");
    await act(async () => send?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(initialReadAborted).toBe(true);
    expect(fetches).toBe(2);
    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent).toBe("null");
  });

  it("restores a successful send's child binding and readback marker after its tab was closed", async () => {
    let resolveCreate!: (value: { childSessionId: string; parentSessionId: string }) => void;
    let fetches = 0;
    const client: ChatRightRailSideClient = {
      createChild: () => new Promise((resolve) => { resolveCreate = resolve; }),
      submit: async () => undefined,
      fetchDetail: async () => {
        fetches += 1;
        return { currentPhase: "idle", status: "ready", messages: [] };
      },
    };
    const model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话" });
    const host = await mount(client, model);
    const input = host.querySelector("textarea");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "关闭期间创建");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "发送");
    await act(async () => send?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

    const close = host.querySelector('[aria-label="关闭辅助对话"]');
    await act(async () => close?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => {
      resolveCreate({ childSessionId: "child-closed", parentSessionId: "parent-1" });
      await Promise.resolve();
    });

    const saved = JSON.parse(host.querySelector('[data-testid="model-state"]')?.textContent || "{}") as ChatRightRailModel;
    expect(saved.closed[0]).toEqual(expect.objectContaining({
      childSessionId: "child-closed",
      submissionGeneration: 1,
      pendingReadbackGeneration: 1,
    }));

    const search = host.querySelector('[aria-label="搜索标签"]');
    await act(async () => search?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const reopen = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "重新打开 辅助对话");
    await act(async () => reopen?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(fetches).toBe(2);
    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent).toBe("null");
  });

  it("reads a freshly created side chat immediately after binding", async () => {
    const now = Date.parse("2026-10-11T10:20:30.456Z");
    vi.spyOn(Date, "now").mockReturnValue(now);
    const userTimestamp = new Date(Math.floor(now / 1000) * 1000).toISOString();
    const userMessage = { id: "u-created", role: "user", timestamp: userTimestamp, content: "首条消息" } as ConversationMessage;
    const answer = {
      id: "a-created",
      role: "assistant",
      timestamp: userTimestamp,
      turnId: "turn-created",
      status: "completed",
      turnItems: [{
        id: "answer-created-v1",
        itemId: "answer-created",
        version: 1,
        sessionId: "child-created",
        turnId: "turn-created",
        type: "agent_message",
        phase: "final_answer",
        text: "创建后的回复",
        status: "completed",
        revision: 1,
        sequence: 1,
      }],
    } as ConversationMessage;
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-created", parentSessionId: "parent-1" }),
      submit: async () => undefined,
      fetchDetail: async () => ({
        currentPhase: "idle",
        status: "ready",
        messages: [userMessage, answer],
      }),
    };
    const model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "首条消息",
      sendDraft: true,
    });
    const host = await mount(client, model);
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

    expect(Date.now() % 1000).toBe(456);
    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent, host.textContent).toBe("null");
    expect(host.textContent).toContain("创建后的回复");
  });

  it("forces a readback after submit and keeps polling beyond two minutes until native completion", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T10:20:30.456Z"));
    let acceptedAt = 0;
    let submitted = false;
    let fetchesAfterSubmit = 0;
    let finalFetches = 0;
    const user = (id: string, timestamp: string, content: string): ConversationMessage => ({
      id, role: "user", timestamp, content,
    });
    const assistant = (id: string, turnId: string, timestamp: string, text: string, status: "running" | "completed") => ({
      id,
      role: "assistant",
      timestamp,
      turnId,
      status,
      turnItems: status === "completed" ? [{
        id: `${id}-answer-v1`,
        itemId: `${id}-answer`,
        version: 1,
        sessionId: "child-existing",
        turnId,
        type: "agent_message",
        phase: "final_answer",
        text,
        status: "completed",
        revision: 1,
        sequence: 1,
      }] : [],
    } as ConversationMessage);
    const oldUser = user("u-old", "2026-10-11T10:00:00.000Z", "第一轮");
    const oldAssistant = assistant("a-old", "turn-old", "2026-10-11T10:00:01.000Z", "旧回答", "completed");
    const newUserTimestamp = "2026-10-11T10:20:30.000Z";
    const newUser = user("u-new", newUserTimestamp, "第二轮请求");
    const runningAssistant = assistant("a-new", "turn-new", "2026-10-11T10:20:31.000Z", "", "running");
    const finalAssistant = assistant("a-new", "turn-new", "2026-10-11T10:22:31.000Z", "第二轮回答完成", "completed");
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-existing", parentSessionId: "parent-1" }),
      submit: async () => {
        submitted = true;
        acceptedAt = Date.now();
      },
      fetchDetail: async () => {
        if (!submitted) {
          return {
            currentPhase: "idle",
            status: "ready",
            messages: [oldUser, oldAssistant],
          };
        }
        fetchesAfterSubmit += 1;
        if (Date.now() - acceptedAt <= 120_000) {
          return {
            currentPhase: "running",
            status: "running",
            messages: [oldUser, oldAssistant, newUser, runningAssistant],
          };
        }
        finalFetches += 1;
        return {
          currentPhase: "idle",
          status: "ready",
          messages: [oldUser, oldAssistant, newUser, finalAssistant],
        };
      },
    };
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话" });
    model = {
      ...model,
      tabs: model.tabs.map((tab) => ({ ...tab, childSessionId: "child-existing" })),
    };
    model = openChatRightRailTab(model, { kind: "review", title: "审查" });
    model = { ...model, activeId: "side" };
    const host = await mount(client, model);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const input = host.querySelector("textarea");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "第二轮请求");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "发送");
    await act(async () => send?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent).toBe("null");
    expect(host.textContent).toContain("旧回答");

    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    expect(host.textContent).toContain("第二轮请求");
    const clickTab = async (label: string) => {
      const button = Array.from(host.querySelectorAll("[role=tab] button"))
        .find((item) => item.textContent === label);
      await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    };
    await clickTab("审查");
    await clickTab("辅助对话");

    await act(async () => { await vi.advanceTimersByTimeAsync(123_000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchesAfterSubmit).toBeGreaterThan(100);
    expect(Date.now() - acceptedAt).toBeGreaterThan(120_000);
    expect(finalFetches).toBeGreaterThan(0);
    expect(host.textContent).toContain("第二轮回答完成");
    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent).toBe("null");
  });

  it("stops polling on a native failure without an assistant message", async () => {
    vi.useFakeTimers();
    let submitted = false;
    let fetchesAfterSubmit = 0;
    const userMessage = {
      id: "u-failed",
      role: "user",
      timestamp: "2026-10-11T10:20:30.000Z",
      content: "失败请求",
    } as ConversationMessage;
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-failed", parentSessionId: "parent-1" }),
      submit: async () => { submitted = true; },
      fetchDetail: async () => {
        if (!submitted) {
          return { currentPhase: "idle", status: "ready", messages: [] };
        }
        fetchesAfterSubmit += 1;
        return {
          currentPhase: "blocked",
          status: "failed",
          lastTurnStatus: "failed",
          messages: [userMessage],
        };
      },
    };
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话" });
    model = {
      ...model,
      tabs: model.tabs.map((tab) => ({ ...tab, childSessionId: "child-failed" })),
    };
    const host = await mount(client, model);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const input = host.querySelector("textarea");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(input, "失败请求");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "发送");
    await act(async () => send?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    expect(host.querySelector('[data-testid="pending-readback-generation"]')?.textContent).toBe("null");
    expect(host.textContent).toContain("失败请求");
    expect(fetchesAfterSubmit).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(fetchesAfterSubmit).toBe(1);
  });

  it("closes other tabs from the menu, closes a tab on middle click, and reorders by drag", async () => {
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-1", parentSessionId: "parent-1" }),
      submit: async () => undefined,
      fetchDetail: async () => ({ currentPhase: "idle", status: "ready", messages: [] }),
    };
    let model = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "side", title: "辅助对话" });
    model = openChatRightRailTab(model, { kind: "review", title: "审查" });
    model = openChatRightRailTab(model, { kind: "terminal", title: "终端" });
    const host = await mount(client, model);
    const moving = host.querySelector<HTMLElement>('[data-chat-right-rail-tab="side"]');
    const over = host.querySelector<HTMLElement>('[data-chat-right-rail-tab="terminal"]');
    const data = typeof DataTransfer === "undefined" ? undefined : new DataTransfer();
    await act(async () => {
      moving?.dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: data }));
      over?.dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer: data }));
    });
    const stored = JSON.parse(host.querySelector('[data-testid="model-state"]')?.textContent || "{}") as ChatRightRailModel;
    expect(stored.tabs.map((tab) => tab.id)).toEqual(["review", "terminal", "side"]);
    expect(stored.activeId).toBe("terminal");

    const reviewTab = host.querySelector<HTMLElement>('[data-chat-right-rail-tab="review"]');
    await act(async () => {
      reviewTab?.dispatchEvent(new MouseEvent("contextmenu", {
        bubbles: true,
        cancelable: true,
        clientX: 24,
        clientY: 32,
      }));
    });
    const closeOthers = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => (
      item.textContent === "关闭其他标签"
    ));
    expect(closeOthers).toBeTruthy();
    await act(async () => {
      closeOthers?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(host.querySelector('[data-chat-right-rail-tab="review"]')).toBeTruthy();
    expect(host.querySelector('[data-chat-right-rail-tab="side"]')).toBeNull();
    expect(host.querySelector('[data-chat-right-rail-tab="terminal"]')).toBeNull();

    await act(async () => {
      host.querySelector('[data-chat-right-rail-tab="review"]')?.dispatchEvent(new MouseEvent("auxclick", {
        bubbles: true,
        cancelable: true,
        button: 1,
      }));
    });
    expect(host.textContent).toContain("打开标签页");
  });

  it("shows a file tab's text and keeps the center-open action", async () => {
    const client: ChatRightRailSideClient = {
      createChild: async () => ({ childSessionId: "child-1", parentSessionId: "parent-1" }),
      submit: async () => undefined,
      fetchDetail: async () => ({ currentPhase: "idle", status: "ready", messages: [] }),
    };
    const model = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, {
      kind: "file",
      title: "a.md",
      filePath: "C:/repo/a.md",
    });
    const host = await mount(client, model, (queryClient) => {
      queryClient.setQueryData(queryKeys.fileContent("C:/repo/a.md"), {
        path: "C:/repo/a.md",
        language: "markdown",
        content: "文件正文",
        truncated: true,
      });
    });
    expect(host.textContent).toContain("文件正文");
    expect(host.textContent).toContain("只显示了前面一部分");
    expect(host.textContent).toContain("在对话中打开");
    expect(host.textContent).toContain("C:/repo/a.md");
  });
});
