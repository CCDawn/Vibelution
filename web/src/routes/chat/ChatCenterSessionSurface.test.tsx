// @vitest-environment happy-dom
import React, { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ChatCenterSessionSurface } from "./ChatCenterSessionSurface";

describe("ChatCenterSessionSurface browsing", () => {
  it("keeps the conversation and terminal mounted while browsing and restores them on return", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    let mounts = 0;
    let unmounts = 0;
    function Workspace() {
      useEffect(() => {
        mounts += 1;
        return () => { unmounts += 1; };
      }, []);
      return <textarea defaultValue="会话草稿"/>;
    }
    const show = (browsing: boolean) => root.render(
      <ChatCenterSessionSurface
        terminal={<span data-terminal>终端运行</span>}
        groupPanelActive={false}
        groupSurface={null}
        sessionWorkspace={<Workspace/>}
        browser={browsing ? <span data-browser>全部会话</span> : undefined}
      />,
    );
    try {
      await act(async () => show(false));
      const draft = container.querySelector("textarea")!;
      draft.value = "编辑后的草稿";
      await act(async () => show(true));
      expect(container.querySelector("[data-browser]")).not.toBeNull();
      expect(container.querySelector("[data-terminal]")?.parentElement?.className).toBe("hidden");
      expect(container.querySelector("textarea")).toBe(draft);
      expect(mounts).toBe(1);
      expect(unmounts).toBe(0);
      await act(async () => show(false));
      expect(container.querySelector("[data-browser]")).toBeNull();
      expect(container.querySelector("textarea")?.value).toBe("编辑后的草稿");
      expect(container.querySelector("[data-terminal]")?.parentElement?.className).toBe("contents");
      expect(unmounts).toBe(0);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });
});
