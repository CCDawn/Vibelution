import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";

function makeCache() {
  const invalidateQueries = vi.fn();
  const removeQueries = vi.fn();
  const cache = createChatWorkspaceCache({ invalidateQueries, removeQueries });
  const queryKeysFromCalls = () => invalidateQueries.mock.calls.map(([options]) => options.queryKey);
  return { cache, invalidateQueries, removeQueries, queryKeysFromCalls };
}

describe("createChatWorkspaceCache", () => {
  it("refreshes the conversation index through one semantic Interface", async () => {
    const { cache, invalidateQueries, queryKeysFromCalls } = makeCache();

    await cache.refreshConversationIndex();

    expect(invalidateQueries).toHaveBeenCalledTimes(2);
    expect(queryKeysFromCalls()).toEqual([queryKeys.sessions(), queryKeys.conversations()]);
  });

  it("invalidates direct turn state without leaking route-level recipes", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterDirectTurnAccepted("session-a");

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.sessions(),
      queryKeys.conversations(),
      queryKeys.runtimeSummary(),
      queryKeys.session("session-a"),
    ]);
  });

  it("deduplicates team conversation membership keys", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterTeamRoomMembershipChanged("team-a", "room-a");

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.teams(),
      queryKeys.team("team-a"),
      queryKeys.chatRooms(),
      queryKeys.chatRoom("room-a"),
      queryKeys.conversations(),
      queryKeys.agentConfigWorkspace(),
    ]);
  });

  it("keeps project bus success refresh broader than failure refresh", async () => {
    const success = makeCache();
    const failure = makeCache();

    await success.cache.afterProjectBusChanged();
    await failure.cache.afterProjectBusFailed();

    expect(success.queryKeysFromCalls()).toEqual([
      queryKeys.projectAgentBus(),
      queryKeys.sessions(),
      queryKeys.conversations(),
      queryKeys.runtimeSummary(),
    ]);
    expect(failure.queryKeysFromCalls()).toEqual([queryKeys.projectAgentBus()]);
  });

  it("refreshes the chat room index without requiring a selected room", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterChatRoomsChanged();

    expect(queryKeysFromCalls()).toEqual([queryKeys.chatRooms(), queryKeys.conversations()]);
  });

  it("refreshes Agent chat-room membership without a route-level recipe", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterAgentChatRoomsChanged();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.agentConfigWorkspace(),
      queryKeys.chatRooms(),
      queryKeys.conversations(),
    ]);
  });

  it("refreshes Agent and chat-room indexes after a Team archive cascades Agent archival", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterTeamArchived("team-a", "room-a");

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.teams(),
      queryKeys.team("team-a"),
      queryKeys.agents(),
      queryKeys.agentModeBindings(),
      queryKeys.chatRooms(),
      queryKeys.chatRoom("room-a"),
      queryKeys.sessions(),
      queryKeys.conversations(),
      queryKeys.agentConfigWorkspace(),
      queryKeys.projectAgentBus(),
    ]);
  });

  it("removes stale session detail caches after destructive chat reset", async () => {
    const { cache, removeQueries, queryKeysFromCalls } = makeCache();

    await cache.afterChatWorkspaceReset();

    expect(removeQueries).toHaveBeenCalledWith({ queryKey: queryKeys.sessions() });
    expect(queryKeysFromCalls()).toEqual([
      queryKeys.sessions(),
      queryKeys.conversations(),
      queryKeys.chatRooms(),
      queryKeys.runtimeSummary(),
    ]);
  });
});
