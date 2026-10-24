// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, QueryObserver, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { prefetchConversationView } from "../../components/conversation/prefetchConversationView";
import { isSessionDeleteTombstoned, markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import { readCurrentChatSelectionPreference } from "./useChatSelectionPersistence";
import { useChatStartupSessionPrefetch } from "./useChatStartupSessionPrefetch";

vi.mock("./chatSessionDetailHelpers", () => ({ fetchSessionDetailWindow: vi.fn(), SESSION_DETAIL_PREFETCH_STALE_MS: 30_000 }));
vi.mock("./useChatSelectionPersistence", () => ({ readCurrentChatSelectionPreference: vi.fn() }));
vi.mock("../../components/conversation/prefetchConversationView", () => ({ prefetchConversationView: vi.fn() }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => { vi.mocked(prefetchConversationView).mockResolvedValue(undefined); });
afterEach(() => { vi.resetAllMocks(); resetSessionDeleteTombstonesForTests(); });

describe("remembered session startup overlap", () => {
  async function mount(options: { enabled?: boolean; requestedSessionId?: string; observe?: boolean } = {}) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
    const container = document.createElement("div");
    const root = createRoot(container);
    function Observer() {
      useQuery({ queryKey: queryKeys.session("remembered"), queryFn: () => fetchSessionDetailWindow("remembered") });
      return null;
    }
    function Page({ observe = options.observe }: { observe?: boolean }) {
      useChatStartupSessionPrefetch({ queryClient: client, enabled: options.enabled ?? true, requestedSessionId: options.requestedSessionId ?? "" });
      return observe ? <Observer /> : null;
    }
    const render = (observe?: boolean) => act(async () => { root.render(<QueryClientProvider client={client}><Page observe={observe} /></QueryClientProvider>); });
    await render();
    const unmount = () => act(async () => root.unmount());
    return { client, render, unmount, close: async () => { await unmount(); client.clear(); } };
  }

  it("starts the remembered body before a catalog response and shares the in-flight read with the committed route", async () => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
    let resolve!: (value: Awaited<ReturnType<typeof fetchSessionDetailWindow>>) => void;
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise(done => { resolve = done; }));
    vi.mocked(prefetchConversationView).mockReturnValue(new Promise(() => {}));
    const page = await mount();
    try {
      expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
      expect(page.client.getQueryData(queryKeys.sessions())).toBeUndefined();
      expect(prefetchConversationView).toHaveBeenCalledOnce();
      await page.render(true);
      expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
      await act(async () => resolve({ id: "remembered", messages: [] } as Awaited<ReturnType<typeof fetchSessionDetailWindow>>));
      expect(page.client.getQueryData(queryKeys.session("remembered"))).toMatchObject({ id: "remembered" });
    } finally { await page.close(); }
  });

  it("does not turn an early missing response into a deletion or a selected session", async () => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
    vi.mocked(fetchSessionDetailWindow).mockRejectedValue(Object.assign(new Error("not ready"), { status: 404 }));
    const page = await mount();
    try {
      expect(isSessionDeleteTombstoned("remembered")).toBe(false);
      expect(page.client.getQueryData(queryKeys.sessions())).toBeUndefined();
    } finally { await page.close(); }
  });

  it.each(["disabled", "other-route", "temp", "deleted"])("skips %s targets", async mode => {
    const sessionId = mode === "temp" ? "temp-session-startup" : "remembered";
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId });
    if (mode === "deleted") markSessionDeleteTombstone(sessionId);
    const page = await mount({ enabled: mode !== "disabled", requestedSessionId: mode === "other-route" ? "different" : "" });
    try {
      expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
      expect(prefetchConversationView).not.toHaveBeenCalled();
    } finally { await page.close(); }
  });

  it("keeps the data read available if speculative module loading fails", async () => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
    vi.mocked(prefetchConversationView).mockRejectedValue(new Error("module unavailable"));
    vi.mocked(fetchSessionDetailWindow).mockResolvedValue({ id: "remembered", messages: [] } as Awaited<ReturnType<typeof fetchSessionDetailWindow>>);
    const page = await mount();
    try {
      expect(page.client.getQueryData(queryKeys.session("remembered"))).toMatchObject({ id: "remembered" });
      expect(prefetchConversationView).toHaveBeenCalledOnce();
    } finally { await page.close(); }
  });

  it("aborts an abandoned read without an observer", async () => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise(() => {}));
    const page = await mount();
    const signal = vi.mocked(fetchSessionDetailWindow).mock.calls[0][1]?.signal;
    await page.close();
    expect(signal?.aborted).toBe(true);
  });

  it("keeps the same pending read alive after a real consumer adopts it", async () => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise(() => {}));
    const page = await mount();
    const signal = vi.mocked(fetchSessionDetailWindow).mock.calls[0][1]?.signal;
    const observer = new QueryObserver(page.client, { queryKey: queryKeys.session("remembered"), queryFn: () => fetchSessionDetailWindow("remembered") });
    const unsubscribe = observer.subscribe(() => {});
    try {
      await page.unmount();
      expect(signal?.aborted).toBe(false);
      expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
    } finally { unsubscribe(); page.client.clear(); }
  });
});
