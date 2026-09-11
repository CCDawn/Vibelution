import { describe, expect, it } from "vitest";

import type { ConversationIndexGroup } from "../conversationIndexModel";
import {
  buildGroupedGroupConversations,
  buildSessionIndexProgressPresentation,
  countGroupedGroupConversations,
  toSessionIndexProgressQuerySlice,
} from "./chatSessionIndexRailPresentation";

describe("chatSessionIndexRailPresentation", () => {
  it("toSessionIndexProgressQuerySlice copies only progress fields", () => {
    expect(toSessionIndexProgressQuerySlice({
      loadedCount: 12,
      totalEstimate: 40,
      hasMore: true,
      isLoadingMore: false,
    })).toEqual({
      loadedCount: 12,
      totalEstimate: 40,
      hasMore: true,
      isLoadingMore: false,
    });
  });

  it("buildGroupedGroupConversations keeps only group_room conversations", () => {
    const groups: ConversationIndexGroup[] = [
      {
        key: "today",
        label: "Today",
        items: [
          { id: "g1", type: "group_room", title: "Group" } as never,
          { id: "d1", type: "direct", title: "Direct" } as never,
        ],
      },
      {
        key: "empty",
        label: "Empty",
        items: [{ id: "d2", type: "direct", title: "Direct 2" } as never],
      },
    ];
    const filtered = buildGroupedGroupConversations(groups);
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.items.map((item) => item.id)).toEqual(["g1"]);
    expect(countGroupedGroupConversations(filtered)).toBe(1);
  });

  it("buildGroupedGroupConversations drops only team groups owned by the Agent directory", () => {
    const groups: ConversationIndexGroup[] = [
      {
        groupKey: "team:research-team",
        label: "挑战杯ai科研团队",
        groupKind: "team",
        teamId: "research-team",
        items: [{ conversationId: "r1", roomId: "room-1", type: "group_room", title: "SCI-009" } as never],
      },
      {
        groupKey: "team:orphan-team",
        label: "orphan",
        groupKind: "team",
        teamId: "orphan-team",
        items: [{ conversationId: "r2", roomId: "room-2", type: "group_room", title: "room" } as never],
      },
      {
        groupKey: "standaloneGroups",
        label: "未归属群聊",
        items: [{ conversationId: "g1", roomId: "room-3", type: "group_room", title: "cache" } as never],
      },
    ];
    const filtered = buildGroupedGroupConversations(groups, new Set(["research-team"]));
    expect(filtered.map((group) => group.groupKey)).toEqual(["team:orphan-team", "standaloneGroups"]);
    expect(countGroupedGroupConversations(filtered)).toBe(2);
  });

  it("buildSessionIndexProgressPresentation formats load-more and progress labels", () => {
    const formatter = new Intl.NumberFormat("en-US");
    expect(buildSessionIndexProgressPresentation({
      loadedCount: 50,
      totalEstimate: 120,
      hasMore: true,
      isLoadingMore: false,
    }, "en", formatter)).toMatchObject({
      sessionIndexLoadMoreLabel: "Load more chats",
      sessionIndexProgressLabel: "50 / 120",
      sessionIndexProgressVisible: true,
    });
    expect(buildSessionIndexProgressPresentation({
      loadedCount: 50,
      totalEstimate: 50,
      hasMore: false,
      isLoadingMore: true,
    }, "zh", formatter).sessionIndexLoadMoreLabel).toBe("加载中");
  });
});
