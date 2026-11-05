// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

// Server UI preferences are unrelated to editor mounting. Keep that read local
// while retaining the real ConversationView, composer and input elements.
vi.mock("../../api/client", async (original) => {
  const client = await original<typeof import("../../api/client")>();
  return { ...client, fetchJson: vi.fn(async () => ({})) };
});

it("keeps the real ordinary editor and its draft mounted while a question occupies the dock", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetchMock = vi.fn(() => { throw new Error("Visibility checks must not contact a backend"); });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  client.setQueryData(queryKeys.sessionMessageCuration("composer-visibility"), { sessionId: "composer-visibility", items: [] });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  function render(hidden = false) {
    return <QueryClientProvider client={client}><ConversationView sessionId="composer-visibility"
      title="Conversation" phase="ready" messages={[]} showHeader={false} showSessionOverview={false}
      composerValue="保留原草稿" composerPlaceholder="普通聊天" composerDisabled={hidden} composerPending={false}
      composerHidden={hidden} composerPrecedingContent={<section data-question-surface>独立回答区</section>}
      defaultFileContext="workspace" onComposerChange={() => undefined} onSubmit={() => undefined}
      onStop={() => undefined} onClear={() => undefined} onJumpToLatest={() => undefined}
      onCreateNewSession={() => undefined} /></QueryClientProvider>;
  }
  try {
    await act(async () => root.render(render()));
    const input = container.querySelector("textarea");
    expect(input).not.toBeNull();
    expect(input?.value).toBe("保留原草稿");
    expect(fetchMock).not.toHaveBeenCalled();
    const host = container.querySelector<HTMLElement>("[data-conversation-composer-host]")!;
    expect(host.hidden).toBe(false);
    await act(async () => root.render(render(true)));
    expect(container.querySelector("textarea")).toBe(input);
    expect(input?.value).toBe("保留原草稿");
    expect(host.hidden).toBe(true);
    expect(host.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector("[data-question-surface]")?.closest("[hidden]")).toBeNull();
    await act(async () => root.render(render(false)));
    expect(container.querySelector("textarea")).toBe(input);
    expect(host.hidden).toBe(false);
    expect(input?.value).toBe("保留原草稿");
  } finally {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    vi.unstubAllGlobals();
  }
});
