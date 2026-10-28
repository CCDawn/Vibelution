// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { ConversationMessage } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { projectConversationDisplayMessages } from "./conversationDisplayMessages";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { ConversationView } from "./ConversationView";

let root: ReturnType<typeof createRoot>;
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.innerHTML = ""; vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("reports mounted user IDs and folded source IDs as the virtual window moves", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 1280, height: 900, top: 0, left: 0, right: 1280, bottom: 900, x: 0, y: 0, toJSON: () => ({}) });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1280);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(900);
  const users = Array.from({ length: 30 }, (_, i) => ({ id: `user-${i}`, role: "user", content: `message ${i}`, timestamp: new Date(1700000000000 + i * 1000).toISOString() })) as ConversationMessage[];
  const assistant = (id: string, seq: number) => ({ id, role: "assistant", content: "", timestamp: new Date(1700000040000 + seq * 1000).toISOString(), turnId: "turn-1", status: "completed", turnItems: [{ id, itemId: id, sessionId: "s", turnId: "turn-1", version: 3, revision: 1, sequence: seq, type: "agent_message", phase: "final_answer", text: id, status: "completed", terminal: true }] }) as unknown as ConversationMessage;
  const messages = [...users, assistant("a1", 1), assistant("a2", 2)];
  const projected = projectAgentMessageTimelineMessages({ timelineMessages: projectConversationDisplayMessages(messages) });
  expect(projected.messages.map(m => m.id)).toContain("a1");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" }); client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  const onVisible = vi.fn();
  const container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => { root.render(createElement(QueryClientProvider, { client }, createElement(ConversationView, {
    sessionId: "s", title: "s", phase: "ready", messages, showHeader: false, showSessionOverview: false, autoScrollToLatest: false,
    composerValue: "", composerPlaceholder: "", composerDisabled: false, onComposerChange: () => undefined, onSubmit: () => undefined,
    onVisibleTimelineMessageIds: onVisible,
  }))); await new Promise(resolve => setTimeout(resolve, 60)); });
  const timeline = container.querySelector<HTMLElement>(".timeline")!;
  expect(timeline).toBeTruthy();
  const initial: string[] = onVisible.mock.lastCall![0];
  expect(initial).toContain("user-0");
  expect(initial.length).toBeLessThan(messages.length);
  await act(async () => { timeline.scrollTop = 28000; timeline.dispatchEvent(new Event("scroll")); await new Promise(resolve => setTimeout(resolve, 100)); });
  const scrolled: string[] = onVisible.mock.lastCall![0];
  expect(scrolled).not.toContain("user-0");
  expect(scrolled).toContain("user-29");
  expect(scrolled).toContain("a1"); expect(scrolled).toContain("a2");
});
