/** @vitest-environment happy-dom */
import React, { act, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ChatCodingGroupSurface, type ChatCodingGroupSurfaceProps } from "./ChatCodingGroupSurface";

vi.mock("./ChatGroupCenterSurface", () => ({
  ChatGroupCenterSurface: ({ showRoundTopics }: { showRoundTopics: boolean }) =>
    <div data-testid="topic-policy">{showRoundTopics ? "full-room" : "member-feed"}</div>,
}));

describe("team member feed presentation", () => {
  it("hides task inputs only on Teams and restores them when opening the full room", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    function Surface() {
      const navigate = useNavigate();
      return <><button onClick={() => navigate("/chat?room=room-1&returnTo=%2Fteams")}>Full room</button>
        <Suspense fallback={null}><ChatCodingGroupSurface {...({
          lang: "zh", standardGroupRoomActive: false, activeGroupRoom: null,
        } as ChatCodingGroupSurfaceProps)} /></Suspense></>;
    }
    try {
      await act(async () => root.render(<MemoryRouter initialEntries={["/teams?room=room-1&teamConversation=group"]}><Surface /></MemoryRouter>));
      await vi.waitFor(() => expect(host.textContent).toContain("member-feed"));
      await act(async () => host.querySelector("button")!.click());
      expect(host.textContent).toContain("full-room");
    } finally {
      act(() => root.unmount());
      host.remove();
    }
  });
});
