// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import { fetchSessionComposerExample, fetchSessionPromptSuggestion } from "../../api/chat";
import { fetchSessionUsageSummary } from "../../api/usage";
import { buildComposerContextRingModel } from "../../routes/chat/composerContextModel";
import { ConversationView } from "./ConversationView";
import type { ConversationViewProps } from "./conversationViewTypes";

vi.mock("../../api/chat", async importOriginal => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  fetchSessionComposerExample: vi.fn(async () => ({ command: "" })),
  fetchSessionPromptSuggestion: vi.fn(async () => ({ suggestion: "" })),
}));
vi.mock("../../api/usage", () => ({ fetchSessionUsageSummary: vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let container: HTMLDivElement;
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; container?.remove(); vi.clearAllMocks(); });

async function renderComposer(props: Pick<ConversationViewProps, "composerModelControl" | "turnModelControl" | "runtimeApi" | "promptSuggestionEnabled">
  & Partial<Pick<ConversationViewProps, "messages" | "composerValue" | "composerContextRing" | "composerCacheUsage">>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  client.setQueryData(queryKeys.sessionMessageCuration("model-toolbar"), { items: [] });
  if (props.runtimeApi) {
    client.setQueryData([props.runtimeApi.cacheKey, "config"], { language: "zh" });
    client.setQueryData([props.runtimeApi.cacheKey, "curation", "model-toolbar"], { items: [] });
  }
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={client}>
    <ConversationView sessionId="model-toolbar" title="Conversation" phase="ready" messages={[]}
      showHeader={false} showSessionOverview={false} composerVariant="codex" composerValue="draft"
      composerPlaceholder="" onComposerChange={vi.fn()} onSubmit={vi.fn()} {...props} />
  </QueryClientProvider>));
}

const nativeControl = {
  sessionId: "model-toolbar", model: null, currentReasoningEffort: "", onSave: vi.fn(),
};

describe("shared composer host model slot", () => {
  it("places the host model inside the standard right toolbar beside send, without a second model control", async () => {
    await renderComposer({ composerModelControl: <button data-testid="host-model">Native model</button>, turnModelControl: nativeControl });
    const host = container.querySelector('[data-testid="host-model"]')!;
    expect(host).toBeTruthy();
    expect(host.parentElement?.className).toContain("composerToolbarEnd");
    expect(host.parentElement?.parentElement?.parentElement?.querySelector("textarea")).toBeTruthy();
    expect(container.querySelector('[data-testid="conversation-turn-model-control"]')).toBeNull();
    expect(container.querySelector<HTMLTextAreaElement>("textarea")?.value).toBe("draft");
  });

  it("leaves the ordinary Agent model control and default attachment action unchanged when omitted", async () => {
    await renderComposer({ turnModelControl: nativeControl });
    expect(container.querySelector('[data-testid="conversation-turn-model-control"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="host-model"]')).toBeNull();
    expect(container.querySelector('input[type="file"]')).toBeTruthy();
    expect(fetchSessionComposerExample).toHaveBeenCalledOnce();
  });

  it.each([false, true])("does not query ordinary Session prompt endpoints in a native host (hasConversation=%s)", async hasConversation => {
    type RuntimeApi = NonNullable<ConversationViewProps["runtimeApi"]>;
    await renderComposer({ runtimeApi: {
      cacheKey: "native-model-toolbar",
      fetchConfigBootstrap: vi.fn<RuntimeApi["fetchConfigBootstrap"]>(),
      fetchMessageCuration: vi.fn<RuntimeApi["fetchMessageCuration"]>(),
      setMessageCuration: vi.fn<RuntimeApi["setMessageCuration"]>(),
    }, promptSuggestionEnabled: true, composerValue: "",
      messages: hasConversation ? [{ id: "user-1", role: "user", content: "你好", timestamp: "2026-11-03T00:00:00Z" }] : [] });
    expect(container.querySelector("textarea")).toBeTruthy();
    expect(fetchSessionComposerExample).not.toHaveBeenCalled();
    expect(fetchSessionPromptSuggestion).not.toHaveBeenCalled();
  });

  it("uses supplied native usage in one entry without reading ordinary Session statistics", async () => {
    type RuntimeApi = NonNullable<ConversationViewProps["runtimeApi"]>;
    await renderComposer({
      runtimeApi: {
        cacheKey: "native-usage-toolbar",
        fetchConfigBootstrap: vi.fn<RuntimeApi["fetchConfigBootstrap"]>(),
        fetchMessageCuration: vi.fn<RuntimeApi["fetchMessageCuration"]>(),
        setMessageCuration: vi.fn<RuntimeApi["setMessageCuration"]>(),
      },
      composerContextRing: buildComposerContextRingModel({
        usageUsed: 64_000, usageLimit: 128_000, hitPercent: 0,
        detailAvailable: false, segments: [], lang: "zh",
      }),
      composerCacheUsage: {
        state: "ready", sessionPercent: 40, lastCallPercent: 60,
        observedCalls: 2, totalCalls: 2, updating: false,
      },
    });
    const entries = container.querySelectorAll<HTMLButtonElement>('[data-testid="conversation-composer-metrics-trigger"]');
    expect(entries).toHaveLength(1);
    expect(container.querySelector('[data-testid="composer-context-ring"]')).toBeNull();
    expect(container.querySelector('[data-testid="composer-cache-indicator"]')).toBeNull();
    await act(async () => entries[0].click());
    expect(document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBe("50");
    expect(document.querySelector('[data-composer-session-cache="true"]')?.textContent).toContain("40%");
    expect(fetchSessionUsageSummary).not.toHaveBeenCalled();
    expect(fetchSessionComposerExample).not.toHaveBeenCalled();
    expect(fetchSessionPromptSuggestion).not.toHaveBeenCalled();
  });
});
