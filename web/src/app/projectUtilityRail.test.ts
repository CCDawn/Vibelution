import { beforeEach, describe, expect, it } from "vitest";
import { closeAllChatRightRailTabs, closeChatRightRailTab, EMPTY_CHAT_RIGHT_RAIL, noteReviewAutoOpen, openChatRightRailTab, openFreshChatRightRailSideTab, reorderChatRightRailTab } from "../routes/chat/chatRightRailModel";
import { collapseProjectUtilityRail, composeUtilityRail, getProjectUtilityRail, openProjectUtilityRail, resetProjectUtilityRailForTests, selectSessionUtilityRail, setProjectUtilityModel, splitUtilityRail } from "./projectUtilityRail";

describe("project and session utility rail", () => {
  beforeEach(resetProjectUtilityRailForTests);

  it("keeps project Git distinct from session review and retains side-chat identities and drafts", () => {
    let session = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话", draft: "草稿", sendDraft: true });
    session = openChatRightRailTab(session, { kind: "browser", url: "https://example.com/reference" });
    const noted = noteReviewAutoOpen(session, "审查").model;
    openProjectUtilityRail("project_git");
    const project = getProjectUtilityRail().model;
    const merged = composeUtilityRail(noted, project, true);
    expect(merged.tabs.map((tab) => tab.id)).toEqual(["project_git", "side", "browser", "review"]);
    expect(merged.activeId).toBe("project_git");
    const split = splitUtilityRail(merged, noted, project);
    expect(split.session).toEqual(noted);
    expect(split.project.reviewAutoOpened).toBe(false);
    expect(split.session.tabs.find((tab) => tab.kind === "side")?.draft).toBe("草稿");
    expect(composeUtilityRail(EMPTY_CHAT_RIGHT_RAIL, split.project, true).tabs).toHaveLength(1);
  });

  it("dispatches reorder, close, restore and close-all to the correct scope", () => {
    const session = openChatRightRailTab(openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话", draft: "保留" }), { kind: "terminal" });
    const project = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "project_tasks" });
    const combined = composeUtilityRail(session, project, true);
    const reordered = reorderChatRightRailTab(combined, "terminal", "project_tasks");
    let split = splitUtilityRail(reordered, session, project);
    expect(composeUtilityRail(split.session, split.project, split.projectSelected, split.order).tabs).toEqual(reordered.tabs);
    const closed = closeChatRightRailTab(reordered, "project_tasks");
    split = splitUtilityRail(closed, session, project);
    expect(split.project.closed.map((tab) => tab.id)).toEqual(["project_tasks"]);
    expect(split.projectSelected).toBe(false);
    const restored = openChatRightRailTab(composeUtilityRail(split.session, split.project, false, split.order), split.project.closed[0]);
    expect(splitUtilityRail(restored, split.session, split.project).projectSelected).toBe(true);
    split = splitUtilityRail(closeAllChatRightRailTabs(restored), session, project);
    expect(split.session.tabs).toEqual([]);
    expect(split.project.tabs).toEqual([]);
    expect(split.session.closed.find((tab) => tab.kind === "side")?.draft).toBe("保留");
  });

  it("opens from the launcher, toggles from the top bar and lets explicit session requests take selection", () => {
    const model = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "project_notices" });
    setProjectUtilityModel(model, true);
    expect(getProjectUtilityRail().opened).toBe(true);
    openProjectUtilityRail("project_notices");
    expect(getProjectUtilityRail().opened).toBe(false);
    openProjectUtilityRail("project_notices");
    selectSessionUtilityRail();
    expect(getProjectUtilityRail().selected).toBe(false);
    openProjectUtilityRail("project_notices");
    expect(getProjectUtilityRail().opened).toBe(true);
    collapseProjectUtilityRail();
    expect(getProjectUtilityRail().model.tabs).toEqual(model.tabs);
  });
});
