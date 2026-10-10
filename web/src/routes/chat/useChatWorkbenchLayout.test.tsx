/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { useChatWorkbenchLayout, type UseChatWorkbenchLayoutResult } from "./useChatWorkbenchLayout";

it("opens groups with a quiet directory and preserves the ordinary-chat directory choice", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let layout: UseChatWorkbenchLayoutResult;
  function Probe({ group }: { group: boolean }) {
    layout = useChatWorkbenchLayout({ standardGroupRoomActive: group, statusRailEnabled: false });
    return null;
  }
  try {
    await act(async () => root.render(<Probe group={false} />));
    expect(layout!.conversationIndexCollapsed).toBe(false);
    await act(async () => root.render(<Probe group />));
    expect(layout!.conversationIndexCollapsed).toBe(true);
    await act(async () => layout!.setLeftRailCollapsed(false));
    expect(layout!.conversationIndexCollapsed).toBe(false);
    await act(async () => root.render(<Probe group={false} />));
    expect(layout!.conversationIndexCollapsed).toBe(false);
    await act(async () => layout!.setLeftRailCollapsed(true));
    await act(async () => root.render(<Probe group />));
    expect(layout!.conversationIndexCollapsed).toBe(false);
    await act(async () => root.render(<Probe group={false} />));
    expect(layout!.conversationIndexCollapsed).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
