/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { openProjectUtilityRail, resetProjectUtilityRailForTests } from "../../app/projectUtilityRail";
import { closeChatRightRailTab, openFreshChatRightRailSideTab, updateChatRightRailSideDraft } from "./chatRightRailModel";
import { useProjectAwareRightRail } from "./useProjectAwareRightRail";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let latest: ReturnType<typeof useProjectAwareRightRail>;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
function Harness({ sessionId }: { sessionId: string }) {
  latest = useProjectAwareRightRail(sessionId);
  return null;
}
beforeEach(() => {
  resetProjectUtilityRailForTests();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetProjectUtilityRailForTests();
});
async function render(sessionId: string) { await act(async () => root.render(<Harness sessionId={sessionId} />)); }

describe("project-aware right rail hook", () => {
  it("keeps side drafts and closed tabs in their own session while project tabs follow the window", async () => {
    await render("session-a");
    await act(async () => latest.updateRailModel((current) => openFreshChatRightRailSideTab(current, { titleBase: "Side", draft: "draft-a" })));
    await act(async () => openProjectUtilityRail("project_git"));
    await render("session-b");
    expect(latest.railModel.tabs.map((tab) => tab.id)).toEqual(["project_git"]);
    await act(async () => latest.updateRailModel((current) => openFreshChatRightRailSideTab(current, { titleBase: "Side", draft: "draft-b" })));
    expect(latest.railModel.tabs.find((tab) => tab.id === "side")?.draft).toBe("draft-b");
    await act(async () => latest.updateRailModel((current) => closeChatRightRailTab(current, "side")));
    await render("session-a");
    expect(latest.railModel.tabs.find((tab) => tab.id === "side")?.draft).toBe("draft-a");
    expect(latest.railModel.closed).toEqual([]);
    await render("session-b");
    expect(latest.railModel.closed.find((tab) => tab.id === "side")?.draft).toBe("draft-b");
  });

  it("applies consecutive functional updates to the latest model without losing newer drafts", async () => {
    await render("session-a");
    await act(async () => {
      latest.updateRailModel((current) => openFreshChatRightRailSideTab(current, { titleBase: "Side", draft: "first" }));
      latest.updateRailModel((current) => updateChatRightRailSideDraft(current, "side", "second"));
      latest.updateRailModel((current) => openFreshChatRightRailSideTab(current, { titleBase: "Side", draft: "another" }));
    });
    expect(latest.railModel.tabs.filter((tab) => tab.kind === "side").map((tab) => [tab.id, tab.draft])).toEqual([["side", "second"], ["side:2", "another"]]);
  });
});
