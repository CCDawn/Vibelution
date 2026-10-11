import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  CHAT_RIGHT_RAIL_CLOSED_CAP,
  EMPTY_CHAT_RIGHT_RAIL,
  chatRightRailLauncherKinds,
  chatRightRailTranscriptLines,
  closeChatRightRailTab,
  consumeChatRightRailSideDraft,
  confirmChatRightRailSideReadback,
  normalizeChatRightRailBrowserUrl,
  noteReviewAutoOpen,
  openChatRightRailTab,
  openFreshChatRightRailSideTab,
  projectChatRightRailDevtools,
  rememberChatRightRailSideChild,
  searchChatRightRailTabs,
  trackChatRightRailSideSubmission,
  updateChatRightRailSideDraft,
} from "./chatRightRailModel";

describe("chat right rail model", () => {
  it("opens a new side tab for each explicit request and keeps the child on that tab", () => {
    const first = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "> 这段",
    });
    const second = openFreshChatRightRailSideTab(first, {
      titleBase: "辅助对话",
      draft: "只问这一句",
      sendDraft: true,
    });
    expect(second.tabs.map((tab) => tab.id)).toEqual(["side", "side:2"]);
    expect(second.activeId).toBe("side:2");
    expect(second.tabs[1]).toEqual(expect.objectContaining({ draft: "只问这一句", sendDraft: true }));
    const bound = rememberChatRightRailSideChild(second, "side:2", "child-2");
    expect(bound.tabs[1]?.childSessionId).toBe("child-2");
    expect(bound.tabs[1]?.draft).toBe("只问这一句");
    expect(bound.tabs[0]?.draft).toBe("> 这段");
  });

  it("keeps side drafts scoped to their tab and consumes only the one-shot send intent", () => {
    const first = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "首条预填",
      sendDraft: true,
    });
    const second = openFreshChatRightRailSideTab(first, {
      titleBase: "辅助对话",
      draft: "第二场草稿",
    });
    const consumed = consumeChatRightRailSideDraft(second, first.tabs[0]!.id);
    const edited = updateChatRightRailSideDraft(consumed, second.tabs[1]!.id, "第二场修改后草稿");

    expect(edited.tabs[0]).toEqual(expect.objectContaining({ draft: "首条预填", sendDraft: undefined }));
    expect(edited.tabs[1]).toEqual(expect.objectContaining({ draft: "第二场修改后草稿" }));
    expect(updateChatRightRailSideDraft(edited, "missing", "ignored")).toBe(edited);
  });

  it("uses draft revisions so a late send callback cannot clear a newer edit", () => {
    const opened = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "同一段草稿",
    });
    const changed = updateChatRightRailSideDraft(opened, "side", "临时修改");
    const restored = updateChatRightRailSideDraft(changed, "side", "同一段草稿");
    const lateClear = updateChatRightRailSideDraft(restored, "side", "", 0);

    expect(restored.tabs[0]).toEqual(expect.objectContaining({ draft: "同一段草稿", draftRevision: 2 }));
    expect(lateClear).toBe(restored);
  });

  it("uses a monotonic readback generation and ignores stale confirmations", () => {
    const opened = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, { titleBase: "辅助对话" });
    const first = trackChatRightRailSideSubmission(opened, "side");
    const second = trackChatRightRailSideSubmission(first, "side");
    expect(second.tabs[0]).toEqual(expect.objectContaining({
      submissionGeneration: 2,
      pendingReadbackGeneration: 2,
    }));

    const stale = confirmChatRightRailSideReadback(second, "side", 1);
    expect(stale).toBe(second);
    const confirmed = confirmChatRightRailSideReadback(second, "side", 2);
    expect(confirmed.tabs[0]).toEqual(expect.objectContaining({
      submissionGeneration: 2,
      pendingReadbackGeneration: undefined,
    }));
  });

  it("retains a closed side chat draft, child binding, and readback marker when reopened", () => {
    let model = openFreshChatRightRailSideTab(EMPTY_CHAT_RIGHT_RAIL, {
      titleBase: "辅助对话",
      draft: "保留的草稿",
    });
    model = closeChatRightRailTab(model, "side");
    model = rememberChatRightRailSideChild(model, "side", "child-late");
    model = trackChatRightRailSideSubmission(model, "side");

    const reopened = openChatRightRailTab(model, { kind: "side", title: "辅助对话" });
    expect(reopened.tabs[0]).toEqual(expect.objectContaining({
      id: "side",
      childSessionId: "child-late",
      draft: "保留的草稿",
      submissionGeneration: 1,
      pendingReadbackGeneration: 1,
    }));
  });

  it("hides side chat when the current session is already a child", () => {
    expect(chatRightRailLauncherKinds("main")).toEqual([
      "side",
      "review",
      "terminal",
      "browser",
      "devtools",
    ]);
    expect(chatRightRailLauncherKinds("child")).not.toContain("side");
  });

  it("reuses one tab for review, terminal, browser, devtools, side, and the directory", () => {
    const once = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "review", title: "审查" });
    const twice = openChatRightRailTab(once, { kind: "review", title: "审查" });
    expect(twice.tabs).toHaveLength(1);
    expect(twice.activeId).toBe("review");
    const withUrl = openChatRightRailTab(twice, { kind: "browser", title: "浏览器", url: "https://example.com/" });
    const replaced = openChatRightRailTab(withUrl, { kind: "browser", title: "浏览器", url: "https://example.org/" });
    expect(replaced.tabs.filter((tab) => tab.kind === "browser")).toEqual([
      expect.objectContaining({ id: "browser", url: "https://example.org/" }),
    ]);
  });

  it("keeps at most eight recently closed tabs and can reopen one", () => {
    let model = EMPTY_CHAT_RIGHT_RAIL;
    for (let index = 0; index < CHAT_RIGHT_RAIL_CLOSED_CAP + 2; index += 1) {
      model = openChatRightRailTab(model, {
        kind: "file",
        title: `file-${index}`,
        filePath: `src/${index}.ts`,
      });
      model = closeChatRightRailTab(model, `file:src/${index}.ts`);
    }
    expect(model.closed).toHaveLength(CHAT_RIGHT_RAIL_CLOSED_CAP);
    expect(model.closed.some((tab) => tab.filePath === "src/0.ts")).toBe(false);
    const newest = model.closed[0];
    const reopened = openChatRightRailTab(model, newest);
    expect(reopened.activeId).toBe(newest.id);
    expect(reopened.closed.some((tab) => tab.id === newest.id)).toBe(false);
  });

  it("opens review once when files appear and does not steal an existing tab", () => {
    const side = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "side", title: "辅助对话" });
    const first = noteReviewAutoOpen(side, "审查");
    expect(first.opened).toBe(true);
    expect(first.model.activeId).toBe("side");
    expect(first.model.tabs.map((tab) => tab.kind)).toEqual(["side", "review"]);
    const second = noteReviewAutoOpen(first.model, "审查");
    expect(second.opened).toBe(false);
    expect(second.model).toBe(first.model);
  });

  it("searches open and closed tabs", () => {
    const open = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "terminal", title: "终端" });
    const closed = closeChatRightRailTab(
      openChatRightRailTab(open, { kind: "file", title: "chat.ts", filePath: "web/src/chat.ts" }),
      "file:web/src/chat.ts",
    );
    expect(searchChatRightRailTabs(closed, "chat").closed.map((tab) => tab.filePath)).toEqual(["web/src/chat.ts"]);
    expect(searchChatRightRailTabs(closed, "终端").open).toHaveLength(1);
  });

  it("accepts only http and https browser addresses", () => {
    expect(normalizeChatRightRailBrowserUrl("example.com/a")).toBe("https://example.com/a");
    expect(normalizeChatRightRailBrowserUrl("javascript:alert(1)")).toBeNull();
    expect(normalizeChatRightRailBrowserUrl("")).toBeNull();
  });

  it("projects developer tools from the loaded session and fails open", () => {
    expect(projectChatRightRailDevtools(null).empty).toBe(true);
    const view = projectChatRightRailDevtools({
      phase: "running",
      status: "active",
      messages: [
        { role: "assistant", turnItems: [{ type: "tool_call" }, { type: "agent_message" }], usageStats: { totalTokens: 12 } },
        { role: "user" },
      ],
    });
    expect(view.rows.find((row) => row.id === "toolCalls")?.value).toBe("1");
    expect(view.rows.find((row) => row.id === "tokens")?.value).toBe("12");
    expect(view.rows.find((row) => row.id === "messages")?.value).toBe("2");
  });

  it("remembers the side-chat child and reads a final answer", () => {
    const side = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "side", title: "辅助对话" });
    const remembered = rememberChatRightRailSideChild(side, "side", "child-1");
    expect(remembered.tabs[0]?.childSessionId).toBe("child-1");
    const messages = [
      { id: "u1", role: "user", timestamp: "", content: "你好" },
      {
        id: "a1",
        role: "assistant",
        timestamp: "",
        turnId: "turn-1",
        status: "completed",
        turnItems: [{
          id: "answer-1-r1",
          itemId: "answer-1",
          version: 3,
          sessionId: "child-1",
          turnId: "turn-1",
          type: "agent_message",
          phase: "final_answer",
          text: "收到",
          status: "completed",
          revision: 1,
          sequence: 1,
        }],
      },
    ] as ConversationMessage[];
    expect(chatRightRailTranscriptLines(messages).map((line) => line.text)).toEqual(["你好", "收到"]);
  });
});
