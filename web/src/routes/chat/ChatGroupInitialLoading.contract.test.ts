import { describe, expect, it } from "vitest";

import conversationIndexSource from "./ChatConversationIndexRail.tsx?raw";
import workbenchSource from "./ChatCodingRouteWorkbench.tsx?raw";

describe("group room initial loading contract", () => {
  it("derives initial loading from pending-without-data instead of any fetch", () => {
    expect(workbenchSource).toContain(
      "standardGroupRoomActive && activeGroupRoomQuery.isPending && !activeGroupRoomQuery.data",
    );
    expect(workbenchSource).toContain("groupRoomInitialLoading={groupRoomInitialLoading}");
    expect(workbenchSource).not.toContain(
      "standardGroupRoomActive && activeGroupRoomQuery.isFetching && !activeGroupRoom",
    );
  });

  it("shows loading slots instead of a zero-member roster before detail arrives", () => {
    expect(conversationIndexSource).toContain("groupRoomInitialLoading ? (");
    expect(conversationIndexSource).toContain("正在加载群聊成员摘要");
    expect(conversationIndexSource).toContain("正在加载群聊成员");
  });
});
