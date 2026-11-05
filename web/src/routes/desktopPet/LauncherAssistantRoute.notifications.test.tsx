/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LauncherNotificationTopbar } from "../../app/LauncherNotificationTopbar";
import { LauncherNotificationProvider } from "../../app/LauncherNotifications";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import { LauncherAssistantTaskCards } from "./assistantTasks/LauncherAssistantTaskCards";

// Keep the real route, bridge validation, queries and notification presentation.
// Only the transcript renderer is replaced with its public composer contract.
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return <div data-testid="native-conversation">
      {props.toolbarSlot}
      {props.composerPrecedingContent}
      <textarea aria-label="draft" value={props.composerValue}
        onChange={event => props.onComposerChange(event.target.value)} />
    </div>;
  },
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  operatorAssetsVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true,
      showCompletion: true, idleMessage: "在的，随时吩咐。" } },
};
const DETAIL = { id: "s", agentId: "a", status: "ready", messages: [] };
const USAGE_NUMBERS = { inputTokens: 100, cachedInputTokens: 75, cacheReadInputTokens: 75,
  cacheCreationInputTokens: 0, uncachedInputTokens: 25, outputTokens: 0, reasoningOutputTokens: 0,
  totalTokens: 100, latencyMs: 0, cacheHitRate: .75, cacheUsageObserved: true, cacheUsageMissingReason: "" };
const USAGE = { sessionId: "s", agentId: "a", lastTokenUsage: { ...USAGE_NUMBERS, source: "provider_usage" },
  sessionTokenUsage: { ...USAGE_NUMBERS, callCount: 1, observedCallCount: 1, estimatedCallCount: 0,
    missingCallCount: 0, notCalledCount: 0, cacheObservedInputTokens: 100, cacheObservedCallCount: 1,
    cacheUnobservedCallCount: 0, cacheUsageComplete: true } };
const READ_OPERATIONS = ["detail", "approvals", "dispatches", "operatorAsset"];

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let invoke: ReturnType<typeof vi.fn>;
let failing: Set<string>;
let readGates: Map<string, Promise<void>>;

async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}

async function mount({ initiallyFail = [], withTaskOwner = false }: { initiallyFail?: string[]; withTaskOwner?: boolean } = {}) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  failing = new Set(initiallyFail);
  readGates = new Map();
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    const operation = String(request.operation);
    if (failing.has(operation)) throw new Error(`${operation} response unavailable`);
    if (readGates.has(operation)) await readGates.get(operation);
    switch (operation) {
      case "status": return STATUS;
      case "config": return { language: "zh" };
      case "detail": return DETAIL;
      case "usageSummary": return USAGE;
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      case "computerState": return { available: false, status: "idle", message: "测试驱动未连接",
        grantId: null, window: null, pending: null };
      default: throw new Error(`unexpected_operation:${operation}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: 0 } } });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={client}>
    <LauncherNotificationProvider>
      <header data-testid="topbar"><LauncherNotificationTopbar lang="zh" /></header>
      {withTaskOwner ? <LauncherAssistantTaskCards><main data-testid="assistant-body"><LauncherAssistantRoute embedded /></main></LauncherAssistantTaskCards>
        : <main data-testid="assistant-body"><LauncherAssistantRoute embedded /></main>}
    </LauncherNotificationProvider>
  </QueryClientProvider>));
  await settle(); await settle();
  if (!initiallyFail.includes("detail")) expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  if (!initiallyFail.length) expect(trigger().getAttribute("aria-label")).toContain("0 项提醒");
  expect(trigger().textContent).not.toMatch(/\d/);
}

function body() {
  return container.querySelector<HTMLElement>('[data-testid="assistant-body"]')!;
}

function trigger() {
  return container.querySelector<HTMLButtonElement>('[data-testid="topbar"] button[aria-haspopup="dialog"]')!;
}

function panel() {
  return document.querySelector<HTMLElement>('[role="dialog"][aria-label="运行提醒"]')!;
}

async function click(button: HTMLButtonElement) {
  await act(async () => button.click());
  await settle(); await settle();
}

function panelButton(label: string) {
  const found = [...panel().querySelectorAll("button")].find(button => button.textContent?.trim() === label);
  expect(found, `notification action: ${label}`).toBeTruthy();
  return found!;
}

function summaryButton(item: Element) {
  const button = item.querySelector<HTMLButtonElement>("button[aria-expanded]");
  expect(button).toBeTruthy();
  return button!;
}

function queryStatus(query: string) {
  return client.getQueryCache().findAll({ queryKey: ["launcher-assistant", query] }).map(item => item.state.status);
}

function operations() {
  return invoke.mock.calls.map(([request]) => String(request.operation));
}

async function failReads() {
  READ_OPERATIONS.forEach(operation => failing.add(operation));
  await act(async () => {
    await client.refetchQueries({ predicate: query => query.queryKey[0] === "launcher-assistant"
      && ["detail", "approvals", "dispatches", "operator-asset"].includes(String(query.queryKey[1])) });
  });
  await settle(); await settle();
}

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  client?.clear(); container?.remove(); conversation = undefined;
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals(); vi.restoreAllMocks();
});

describe("Launcher assistant hosted notifications", () => {
  it("recovers cache statistics from the page refresh button without a new detail marker", async () => {
    await mount({ initiallyFail: ["usageSummary"] });
    expect(conversation?.composerCacheUsage?.state).toBe("error");
    const draft = "刷新时保留草稿";
    await act(async () => conversation!.onComposerChange(draft));
    failing.delete("usageSummary");
    invoke.mockClear();
    const refresh = [...body().querySelectorAll("button")].find(button => button.textContent?.trim() === "刷新");
    expect(refresh).toBeTruthy();
    await click(refresh!);
    expect(conversation?.composerCacheUsage).toMatchObject({ state: "ready", sessionPercent: 75, lastCallPercent: 75 });
    expect(operations().filter(operation => operation === "usageSummary")).toHaveLength(1);
    expect(operations()).not.toContain("send");
    expect(body().querySelector("textarea")?.value).toBe(draft);
  });

  it("deduplicates shared status while retaining independent task-query failures", async () => {
    await mount({withTaskOwner:true});
    failing.add("status");
    await act(async()=>{await client.refetchQueries({queryKey:["launcher-assistant","status"]});});
    await settle(); await settle();
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    await click(trigger());
    expect(panel().querySelectorAll("li")).toHaveLength(1);
    expect(panel().textContent).toContain("暂时查不到任务进度");
    expect(queryStatus("status")).toEqual(["error"]);
    expect(queryStatus("dispatches")).toEqual(["success"]);
    expect(queryStatus("task-cards")).toEqual(["success"]);
    failing.delete("status");
    await click(panelButton("再试一次"));
    expect(trigger().getAttribute("aria-label")).toContain("0 项提醒");
    failing.add("dispatches");
    await act(async()=>{await client.refetchQueries({queryKey:["launcher-assistant","dispatches"]});});
    await settle(); await settle();
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel().querySelectorAll("li")).toHaveLength(1);
    expect(panel().textContent).toContain("暂时查不到任务进度");
    expect(queryStatus("dispatches")).toEqual(["error"]);
    expect(queryStatus("task-cards")).toEqual(["success"]);
    failing.delete("dispatches");
    invoke.mockClear();
    await click(panelButton("再试一次"));
    expect(operations()).toEqual(["dispatches"]);
    expect(trigger().getAttribute("aria-label")).toContain("0 项提醒");
    failing.add("dispatches");
    await act(async()=>{await client.refetchQueries({queryKey:["launcher-assistant","task-cards"]});});
    await settle(); await settle();
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel().textContent).toContain("暂时查不到任务进度");
    expect(queryStatus("dispatches")).toEqual(["success"]);
    expect(queryStatus("task-cards")).toEqual(["error"]);
    await click(summaryButton(panel().querySelector("li")!));
    expect(panel().querySelector("dl")?.textContent).toContain("任务进度");
    failing.delete("dispatches");
    invoke.mockClear();
    await click(panelButton("再试一次"));
    expect(operations().sort()).toEqual(["dispatches", "status"]);
    expect(trigger().getAttribute("aria-label")).toContain("0 项提醒");
  });

  it("combines page and task-owner failures into one read-only retry and retains unrecovered tasks", async () => {
    await mount({ withTaskOwner: true });
    await act(async () => conversation!.onComposerChange("合并重试仍保留草稿"));
    failing.add("detail");
    failing.add("dispatches");
    await act(async () => {
      await client.refetchQueries({ predicate: query => query.queryKey[0] === "launcher-assistant"
        && ["detail", "task-cards"].includes(String(query.queryKey[1])) });
    });
    await settle(); await settle();
    expect(queryStatus("detail")).toEqual(["error"]);
    expect(queryStatus("task-cards")).toEqual(["error"]);
    expect(queryStatus("dispatches")).toEqual(["success"]);
    expect(trigger().getAttribute("aria-label")).toContain("刷新没成功, 1 项提醒");
    expect(trigger().textContent?.trim()).toBe("刷新没成功");
    await click(trigger());
    expect(panel().querySelectorAll("li")).toHaveLength(1);
    expect(panel().textContent).toContain("聊天和任务进度没刷新");
    await click(summaryButton(panel().querySelector("li")!));
    expect([...panel().querySelectorAll("dt")].map(item => item.textContent).sort()).toEqual(["任务进度", "聊天记录"]);

    failing.delete("detail");
    invoke.mockClear();
    await click(panelButton("再试一次"));
    expect(operations().sort()).toEqual(["detail", "dispatches", "status"]);
    expect(operations()).not.toContain("send");
    expect(operations()).not.toContain("resolveApproval");
    expect(operations()).not.toContain("decideDispatchApproval");
    expect(queryStatus("detail")).toEqual(["success"]);
    expect(queryStatus("task-cards")).toEqual(["error"]);
    expect(trigger().getAttribute("aria-label")).toContain("刷新没成功, 1 项提醒");
    expect(panel().querySelectorAll("li")).toHaveLength(1);
    expect(panel().textContent).toContain("暂时查不到任务进度");
    expect([...panel().querySelectorAll("dt")].map(item => item.textContent)).toEqual(["任务进度"]);
    expect(body().querySelector("textarea")?.value).toBe("合并重试仍保留草稿");

    failing.delete("dispatches");
    invoke.mockClear();
    await click(panelButton("再试一次"));
    expect(operations().sort()).toEqual(["dispatches", "status"]);
    expect(trigger().getAttribute("aria-label")).toContain("暂无异常, 0 项提醒");
    expect(body().querySelector("textarea")?.value).toBe("合并重试仍保留草稿");
  });

  it("groups failed reads and appearance while retaining the mounted conversation and draft", async () => {
    await mount();
    const originalConversation = body().querySelector('[data-testid="native-conversation"]');
    const originalComposer = body().querySelector("textarea")!;
    await act(async () => conversation!.onComposerChange("这份草稿仍要保留"));
    await failReads();

    expect(trigger().getAttribute("aria-label")).toContain("刷新没成功, 2 项提醒");
    expect(trigger().textContent?.trim()).toBe("刷新没成功");
    expect(body().querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    expect(body().querySelector('[data-testid="native-conversation"]')).toBe(originalConversation);
    expect(body().querySelector("textarea")).toBe(originalComposer);
    expect(originalComposer.value).toBe("这份草稿仍要保留");
    await click(trigger());
    const items = [...panel().querySelectorAll("li")];
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("聊天和任务进度没刷新");
    expect(items[0].getAttribute("data-tone")).toBe("warning");
    expect(summaryButton(items[0]).getAttribute("aria-expanded")).toBe("false");
    expect(items[0].querySelector("dl")).toBeNull();
    expect(items[0].querySelector("details")).toBeNull();
    await click(summaryButton(items[0]));
    expect(summaryButton(items[0]).getAttribute("aria-expanded")).toBe("true");
    for (const label of ["聊天记录", "待你确认的操作", "任务进度"]) expect(items[0].querySelector("dl")?.textContent).toContain(label);
    const details = items[0].querySelector("details")!;
    expect(details.open).toBe(false);
    await act(async () => details.querySelector("summary")!.click());
    expect(details.open).toBe(true);
    for (const label of ["会话刷新", "待授权查询", "任务状态"]) expect(details.textContent).toContain(label);
    expect(items[1].textContent).toContain("外观图片未加载");
    expect(items[1].getAttribute("data-tone")).toBe("info");
    expect(items[1].textContent).not.toContain("暂时使用默认外观");
    expect(items[1].textContent).not.toContain("用户头像");
    await click(summaryButton(items[1]));
    expect(items[1].textContent).toContain("暂时使用默认外观，不影响聊天。");
    expect(items[1].textContent).toContain("用户头像");
    expect(items[1].textContent).toContain("背景图片");
    expect(operations()).not.toContain("send");
  });

  it("retries only failed reads and clears each group when those sources recover", async () => {
    await mount();
    await failReads();
    await click(trigger());
    for (const operation of ["detail", "approvals", "dispatches"]) failing.delete(operation);
    invoke.mockClear();
    await click(panelButton("再试一次"));

    expect(operations().sort()).toEqual(["approvals", "detail", "dispatches"]);
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel().querySelectorAll("li")).toHaveLength(1);
    expect(panel().textContent).not.toContain("聊天和任务进度没刷新");
    expect(panel().textContent).toContain("外观图片未加载");

    failing.delete("operatorAsset");
    invoke.mockClear();
    await click(panelButton("重试"));
    expect(operations()).toEqual(["operatorAsset", "operatorAsset"]);
    expect(invoke.mock.calls.map(([request]) => request.kind).sort()).toEqual(["avatar", "background"]);
    expect(trigger().getAttribute("aria-label")).toContain("暂无异常, 0 项提醒");
    expect(panel().textContent).toContain("当前没有异常");
    expect(body().querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
  });

  it.each([
    { operation: "detail", query: "detail", title: "聊天没能刷新", retry: "再试一次" },
    { operation: "approvals", query: "approvals", title: "暂时查不到待确认的操作", retry: "再试一次" },
    { operation: "operatorAsset", query: "operator-asset", title: "外观图片未加载", retry: "重试" },
  ])("retains a first-load $operation failure throughout a pending retry", async ({ operation, query, title, retry }) => {
    await mount({ initiallyFail: [operation] });
    const queries = client.getQueryCache().findAll({ queryKey: ["launcher-assistant", query] });
    expect(queries.length).toBeGreaterThan(0);
    for (const item of queries) {
      expect(item.state.data).toBeUndefined();
      expect(item.state.status).toBe("error");
    }
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(body().querySelector('[data-vui="state-surface"][data-tone="error"]')).toBeNull();
    await click(trigger());
    expect(panel().textContent).toContain(title);

    let release!: () => void;
    readGates.set(operation, new Promise<void>(resolve => { release = resolve; }));
    failing.delete(operation);
    invoke.mockClear();
    await click(panelButton(retry));

    // React Query clears isError while this no-data retry remains pending.
    // The previous failure must stay visible until there is a successful read.
    for (const item of queries) {
      expect(item.state.status).toBe("pending");
      expect(item.state.fetchStatus).toBe("fetching");
      expect(item.state.errorUpdatedAt).toBeGreaterThan(0);
    }
    expect(new Set(operations())).toEqual(new Set([operation]));
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel().textContent).toContain(operation === "operatorAsset" ? title : "正在刷新…");
    expect(panelButton(operation === "operatorAsset" ? retry : "请稍等").disabled).toBe(true);
    expect(panel().textContent).not.toContain("当前没有异常");

    await act(async () => release());
    await settle(); await settle();
    expect(queries.every(item => item.state.status === "success")).toBe(true);
    expect(trigger().getAttribute("aria-label")).toContain("暂无异常, 0 项提醒");
    expect(panel().textContent).toContain("当前没有异常");
  });

  it("keeps an unknown send outcome beside the composer instead of publishing a runtime notice", async () => {
    await mount();
    failing.add("send");
    await act(async () => conversation!.onComposerChange("核对这条消息"));
    await act(async () => conversation!.onSubmit());
    await settle(); await settle();

    expect(operations().filter(operation => operation === "send")).toHaveLength(1);
    const error = body().querySelector('[data-vui="state-surface"][data-tone="error"]');
    expect(error?.textContent).toContain("尚未确认消息是否收到");
    expect(body().querySelector("textarea")?.value).toBe("核对这条消息");
    expect(conversation?.composerError).toContain("尚未确认消息是否收到");
    expect(trigger().getAttribute("aria-label")).toContain("0 项提醒");
    await click(trigger());
    expect(panel().textContent).toContain("当前没有异常");
    expect(panel().textContent).not.toContain("尚未确认消息是否收到");
  });
});
