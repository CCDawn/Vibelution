// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../../components/vui";
import {
  ChatConversationIndexPanelContent,
  type ChatConversationIndexPanelContentProps,
} from "./ChatConversationIndexPanelContent";

function props(patch: Partial<ChatConversationIndexPanelContentProps> = {}): ChatConversationIndexPanelContentProps {
  return {
    styles: { panelState: "panelState", panelNotice: "panelNotice" },
    loadingLabel: "正在加载会话",
    emptyTitle: "还没有会话",
    sessionsErrorMessage: "会话列表暂时无法加载",
    sessionsTransientError: false,
    sessionsBlockingError: false,
    conversationIndexLoading: false,
    isEmpty: false,
    children: <div data-testid="rail-list">rail-list</div>,
    ...patch,
  };
}

async function mount(initialProps: ChatConversationIndexPanelContentProps) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.append(host);
  const root: Root = createRoot(host);
  await act(async () => {
    root.render(<VuiProvider><ChatConversationIndexPanelContent {...initialProps} /></VuiProvider>);
  });
  return {
    host,
    update: async (nextProps: ChatConversationIndexPanelContentProps) => act(async () => {
      root.render(<VuiProvider><ChatConversationIndexPanelContent {...nextProps} /></VuiProvider>);
    }),
    unmount: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ChatConversationIndexPanelContent", () => {
  it("shows the skeleton before any list data has rendered", async () => {
    const preview = await mount(props({ conversationIndexLoading: true }));
    try {
      expect(preview.host.querySelector('[data-testid="conversation-index-loading-shell"]')).not.toBeNull();
      expect(preview.host.querySelector('[data-testid="rail-list"]')).toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("shows the empty surface only when loading completed without rows", async () => {
    const preview = await mount(props({ isEmpty: true }));
    try {
      expect(preview.host.querySelector('[data-tone="empty"]')).not.toBeNull();
      expect(preview.host.querySelector('[data-testid="rail-list"]')).toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("keeps the rendered list mounted through loading pulses and drops the skeleton", async () => {
    const preview = await mount(props());
    try {
      expect(preview.host.querySelector('[data-testid="rail-list"]')).not.toBeNull();
      // Simulate the ready-gate / poll loading pulse after the list rendered.
      await preview.update(props({ conversationIndexLoading: true }));
      expect(preview.host.querySelector('[data-testid="rail-list"]')).not.toBeNull();
      expect(preview.host.querySelector('[data-testid="conversation-index-loading-shell"]')).toBeNull();
      expect(preview.host.querySelector(".panelNotice")?.textContent).toBe("正在加载会话");
      // Back to settled state: the notice is gone, the list stays.
      await preview.update(props());
      expect(preview.host.querySelector('[data-testid="rail-list"]')).not.toBeNull();
      expect(preview.host.querySelector(".panelNotice")).toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("does not swap the held list for the empty surface while loading", async () => {
    const preview = await mount(props());
    try {
      await preview.update(props({ conversationIndexLoading: true, isEmpty: true }));
      expect(preview.host.querySelector('[data-testid="rail-list"]')).not.toBeNull();
      expect(preview.host.querySelector('[data-tone="empty"]')).toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("still replaces the list with a blocking error after the latch", async () => {
    const preview = await mount(props());
    try {
      await preview.update(props({ sessionsBlockingError: true, sessionsErrorMessage: "会话列表暂时无法加载" }));
      expect(preview.host.querySelector('[data-testid="rail-list"]')).toBeNull();
      expect(preview.host.querySelector('[data-tone="error"]')).not.toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("keeps the transient error banner alongside the list", async () => {
    const preview = await mount(props({ sessionsTransientError: true }));
    try {
      expect(preview.host.querySelector('[data-testid="rail-list"]')).not.toBeNull();
      expect(preview.host.textContent).toContain("会话列表暂时无法加载");
    } finally {
      await preview.unmount();
    }
  });
});
