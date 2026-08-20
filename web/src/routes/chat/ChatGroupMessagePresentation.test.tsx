import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChatRoomMessage } from "../../api/types";
import { ChatGroupMessageBody } from "./ChatGroupMessagePresentation";
import styles from "./ChatGroupMessagePresentation.styles";

function message(patch: Partial<ChatRoomMessage> = {}): ChatRoomMessage {
  return {
    messageId: "msg-1",
    participantId: "p1",
    sessionId: "s1",
    speakerTitle: "planner",
    status: "completed",
    content: "短回复",
    summary: "",
    timestamp: "2026-08-20T00:00:00Z",
    ...patch,
  };
}

const bodyProps = {
  identityName: "顾言初",
  lang: "zh" as const,
  expandedMessageIds: [] as string[],
  mentionTargets: [],
  onOpenMentionTarget: () => undefined,
  onToggleExpanded: () => undefined,
};

describe("ChatGroupMessageBody", () => {
  it("keeps internal discussion visible instead of hiding the body", () => {
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        message={message({
          audience: "internal",
          visibility: "collapsed_by_default",
          content: "内部讨论仍应能直接读到开头。",
        })}
      />,
    );
    expect(html).toContain("内部讨论仍应能直接读到开头。");
    expect(html).not.toContain("展开全文");
    expect(html).not.toContain(styles.groupBubbleBodyCollapsed);
  });

  it("clamps long speech without using hidden", () => {
    const content = "先看主诉。".repeat(80);
    const html = renderToStaticMarkup(
      <ChatGroupMessageBody
        {...bodyProps}
        message={message({
          audience: "internal",
          visibility: "collapsed_by_default",
          content,
        })}
      />,
    );
    expect(html).toContain("先看主诉。");
    expect(html).toContain("展开全文");
    expect(html).toContain(styles.groupBubbleBodyCollapsed);
    expect(styles.groupBubbleBodyCollapsed).toContain("[-webkit-line-clamp:8]");
    expect(styles.groupBubbleBodyCollapsed).not.toMatch(/(?:^|\s)hidden(?:\s|$)/);
  });
});
