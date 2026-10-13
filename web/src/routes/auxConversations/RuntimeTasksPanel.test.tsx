/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { RuntimeTaskCard, RuntimeTaskListPayload } from "../../api/runtimeTasks";
import type { SessionDetail } from "../../api/types";
import { RuntimeTasksPanel } from "./RuntimeTasksPanel";

const runtimeApi = vi.hoisted(() => ({
  listRuntimeTasksRevisionAware: vi.fn(),
  listRuntimeTasks: vi.fn(),
  getRuntimeTask: vi.fn(),
  stopRuntimeTask: vi.fn(),
}));

vi.mock("../../api/runtimeTasks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/runtimeTasks")>();
  return { ...actual, ...runtimeApi };
});

const streamApi = vi.hoisted(() => ({ fetchSessionDetailWindow: vi.fn() }));

vi.mock("../chat/chatSessionDetailHelpers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../chat/chatSessionDetailHelpers")>();
  return { ...actual, ...streamApi };
});

const conversationView = vi.hoisted(() => ({ views: [] as Array<Record<string, unknown>> }));

vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: Record<string, unknown>) => {
    conversationView.views.push(props);
    return <div data-bridge-probe="lazy-conversation" />;
  },
  prefetchConversationView: () => undefined,
}));

const pollingState = vi.hoisted(() => ({ visible: true }));

vi.mock("../../app/pollingPolicy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../app/pollingPolicy")>();
  return { ...actual, usePageVisibility: () => pollingState.visible };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.now();

function task(overrides: Partial<RuntimeTaskCard> & { taskId: string }): RuntimeTaskCard {
  return {
    kind: "cli_agent",
    status: "running",
    title: `任务 ${overrides.taskId}`,
    parentSessionId: "parent-session-1",
    childSessionId: "",
    startedAt: new Date(NOW - 30_000).toISOString(),
    endedAt: "",
    summary: "正在执行",
    ...overrides,
  };
}

const runningTask = task({ taskId: "task-1", title: "CLI 检查任务" });
const endedTask = task({
  taskId: runningTask.taskId,
  status: "cancelled",
  title: runningTask.title,
  endedAt: new Date(NOW).toISOString(),
});

function payload(
  running: RuntimeTaskCard[] = [runningTask],
  ended: RuntimeTaskCard[] = [],
  revision = "revision-1",
): RuntimeTaskListPayload {
  return {
    revision,
    running,
    ended: { items: ended, total: ended.length, nextCursor: "" },
  };
}

describe("RuntimeTasksPanel", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;
  let queryClient: QueryClient;

  function mountPanel(seed?: RuntimeTaskListPayload, activeSessionId = "session-1") {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (seed) {
      queryClient.setQueryData(queryKeys.runtimeTasks("", ""), seed);
    }
    host = document.createElement("div");
    host.style.height = "560px";
    document.body.appendChild(host);
    root = createRoot(host);
    return act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/chat"]}>
            <RuntimeTasksPanel lang="zh" activeSessionId={activeSessionId} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
  }

  async function flushUntil(predicate: () => boolean, tries = 30) {
    for (let index = 0; index < tries && !predicate(); index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await act(async () => {});
    }
  }

  function button(label: string): HTMLButtonElement {
    const found = [...(host?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find(
      (candidate) => candidate.textContent?.includes(label) || candidate.getAttribute("aria-label") === label,
    );
    expect(found, `button "${label}" should exist`).toBeTruthy();
    return found!;
  }

  beforeEach(() => {
    pollingState.visible = true;
    runtimeApi.listRuntimeTasksRevisionAware.mockReset().mockResolvedValue(payload());
    runtimeApi.listRuntimeTasks.mockReset().mockResolvedValue(payload([], []));
    runtimeApi.getRuntimeTask.mockReset().mockResolvedValue(runningTask);
    runtimeApi.stopRuntimeTask.mockReset().mockResolvedValue({ accepted: true, taskId: "task-1", status: "stopping" });
    streamApi.fetchSessionDetailWindow.mockReset().mockImplementation(async (sessionId: string) => ({
      id: sessionId,
      title: "子会话",
      status: "running",
      taskSummary: "",
      defaultFileContext: "",
      runtimeNotices: [],
      messages: [
        { id: "m1", role: "user", timestamp: new Date(NOW - 20_000).toISOString(), content: "检查任务" },
        { id: "m2", role: "assistant", timestamp: new Date(NOW - 10_000).toISOString(), status: "completed", turnItems: [] },
      ],
    } as unknown as SessionDetail));
    conversationView.views.length = 0;
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    host?.remove();
    root = null;
    host = null;
    document.querySelectorAll('[data-vui="dialog-content"]').forEach((node) => node.remove());
  });

  it("keeps accepted stop pending until a later task-list poll moves it to ended", async () => {
    let latest = payload();
    runtimeApi.listRuntimeTasksRevisionAware.mockImplementation(async () => latest);
    await mountPanel(latest);
    await act(async () => button("CLI 检查任务").click());
    await act(async () => button("停止").click());

    const dialog = document.querySelector('[data-vui="dialog-content"]');
    expect(dialog?.textContent).toContain("停止该任务？");
    const confirm = [...(dialog?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find(
      (candidate) => candidate.textContent?.includes("停止"),
    );
    expect(confirm).toBeTruthy();
    await act(async () => confirm!.click());
    await vi.waitFor(() => expect(runtimeApi.stopRuntimeTask).toHaveBeenCalledWith("task-1"));
    await flushUntil(() => Boolean(host?.textContent?.includes("等待任务列表确认结束")));

    expect(host!.textContent).toContain("停止中");
    expect(host!.textContent).toContain("已请求停止，等待任务列表确认结束。");

    latest = payload([], [endedTask], "revision-2");
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.runtimeTasks("", "") });
    });
    await flushUntil(() => Boolean(host?.textContent?.includes("已取消")));
    expect(host!.textContent).not.toContain("等待任务列表确认结束");
    expect(host!.textContent).not.toContain("停止中…");
  });

  it("recovers from an initial list error and returns from task detail to the selection list", async () => {
    runtimeApi.listRuntimeTasksRevisionAware
      .mockRejectedValueOnce(new Error("临时不可用"))
      .mockResolvedValue(payload());
    await mountPanel();
    await flushUntil(() => Boolean(host?.textContent?.includes("临时不可用")));

    expect(host!.textContent).toContain("任务读取失败");
    await act(async () => button("重试").click());
    await flushUntil(() => Boolean(host?.textContent?.includes("CLI 检查任务")));

    await act(async () => button("CLI 检查任务").click());
    expect(host!.textContent).toContain("CLI 检查任务");
    await act(async () => button("任务列表").click());
    expect(host!.textContent).toContain("辅助任务");
  });

  it("uses the read-only transcript window and keeps the full-session action callback", async () => {
    const childTask = task({ taskId: "child-task", title: "子会话任务", childSessionId: "child-session-1" });
    const onOpenSession = vi.fn();
    runtimeApi.listRuntimeTasksRevisionAware.mockResolvedValue(payload([childTask]));
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.runtimeTasks("", ""), payload([childTask]));
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/chat"]}>
            <RuntimeTasksPanel lang="zh" activeSessionId="session-1" onOpenSession={onOpenSession} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    await flushUntil(() => Boolean(host?.textContent?.includes("子会话任务")));
    await act(async () => button("子会话任务").click());
    await flushUntil(() => Boolean(host?.querySelector('[data-bridge-probe="lazy-conversation"]')));

    expect(streamApi.fetchSessionDetailWindow).toHaveBeenCalledWith(
      "child-session-1",
      expect.objectContaining({ transcriptScope: "window", includeSecondary: false }),
    );
    expect(conversationView.views.at(-1)).toMatchObject({ sessionId: "child-session-1", autoScrollToLatest: true });
    await act(async () => button("打开会话").click());
    expect(onOpenSession).toHaveBeenCalledWith("child-session-1");
  });

  it("falls back to the native chat route when no session navigation callback is supplied", async () => {
    const childTask = task({ taskId: "child-task", title: "子会话任务", childSessionId: "child-session-1" });
    runtimeApi.listRuntimeTasksRevisionAware.mockResolvedValue(payload([childTask]));
    await mountPanel(payload([childTask]));
    await flushUntil(() => Boolean(host?.textContent?.includes("子会话任务")));
    await act(async () => button("子会话任务").click());
    await flushUntil(() => Boolean(host?.textContent?.includes("打开会话")));

    const openSession = [...(host?.querySelectorAll<HTMLAnchorElement>("a") ?? [])].find(
      (candidate) => candidate.textContent?.includes("打开会话"),
    );
    expect(openSession?.getAttribute("href")).toBe("/chat?session=child-session-1");
  });
});
