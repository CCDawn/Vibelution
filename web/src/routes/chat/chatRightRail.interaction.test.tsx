/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { VuiProvider } from "../../components/vui";
import { ChatRightRail, type ChatRightRailSideClient } from "./ChatRightRail";
import { EMPTY_CHAT_RIGHT_RAIL, type ChatRightRailModel } from "./chatRightRailModel";

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

function Harness({ client }: { client: ChatRightRailSideClient }) {
  const [model, setModel] = useState<ChatRightRailModel>(EMPTY_CHAT_RIGHT_RAIL);
  return (
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
  });

  async function mount(client: ChatRightRailSideClient) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root?.render(
        <VuiProvider>
          <QueryClientProvider client={queryClient}>
            <Harness client={client} />
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
});
