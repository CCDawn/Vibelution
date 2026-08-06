import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentReferencesPanel } from "./AgentReferencesPanel";

describe("AgentReferencesPanel", () => {
  it("keeps reference metadata available through focusable tooltips without permanent helper rows", () => {
    const markup = renderToStaticMarkup(
      <AgentReferencesPanel
        copy={{
          chatRoomMembership: "会话室",
          references: "引用",
          noChatRooms: "暂无会话室",
          selectAgent: "暂无引用",
          readOnlyLabel: "只读",
          membershipHelp: "成员关系由会话室维护",
        }}
        showChatRoomMembership
        chatRoomSummary="2 个会话室"
        referenceCount={1}
        chatRooms={[{
          id: "room-1",
          statusLabel: "活跃",
          statusTone: "active",
          title: "科研协作室",
          meta: "最近同步于 10:20",
          route: "/chat/room-1",
          actionLabel: "打开",
        }]}
        references={[{
          id: "reference-1",
          label: "数据集 v3",
          statusLabel: "活跃",
          statusTone: "active",
          sourceLabel: "data.gov.cn",
          meta: "引用于实验协议",
          route: "/memory/reference-1",
          actionLabel: "查看",
        }]}
        onOpenRoute={() => undefined}
      />,
    );

    expect(markup).toContain("科研协作室");
    expect(markup).toContain("data.gov.cn");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain("<small");
    expect(markup).not.toMatch(/<p[^>]*>成员关系由会话室维护<\/p>/);
  });
});
