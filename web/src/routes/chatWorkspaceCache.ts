import type { QueryKey } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";

type QueryClientLike = {
  invalidateQueries: (options: { queryKey: QueryKey }) => Promise<unknown> | unknown;
};

type ChatWorkspaceCacheOptions = {
  sessionId?: string;
  roomId?: string;
  teamId?: string;
  agentId?: string;
};

function uniqueQueryKeys(keys: QueryKey[]): QueryKey[] {
  const seen = new Set<string>();
  return keys.filter((key) => {
    const fingerprint = JSON.stringify(key);
    if (seen.has(fingerprint)) {
      return false;
    }
    seen.add(fingerprint);
    return true;
  });
}

function invalidateAll(queryClient: QueryClientLike, keys: QueryKey[]) {
  return Promise.all(
    uniqueQueryKeys(keys).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
  );
}

export function createChatWorkspaceCache(queryClient: QueryClientLike) {
  return {
    refreshConversationIndex() {
      return invalidateAll(queryClient, [queryKeys.sessions(), queryKeys.conversations()]);
    },
    refreshSessionRuntime(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.session(sessionId),
        queryKeys.sessions(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterDirectTurnAccepted(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.runtimeSummary(),
        queryKeys.session(sessionId),
      ]);
    },
    afterDirectTurnFailed(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.session(sessionId),
        queryKeys.sessions(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterSessionChanged(options: ChatWorkspaceCacheOptions = {}) {
      return invalidateAll(queryClient, [
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.runtimeSummary(),
        ...(options.sessionId ? [queryKeys.session(options.sessionId)] : []),
        ...(options.agentId ? [queryKeys.agent(options.agentId)] : []),
        ...(options.agentId ? [queryKeys.agentRuns(options.agentId)] : []),
      ]);
    },
    afterSessionAgentChanged(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.agents(),
        queryKeys.session(sessionId),
      ]);
    },
    afterChatRoomChanged(roomId: string, options: ChatWorkspaceCacheOptions = {}) {
      return invalidateAll(queryClient, [
        queryKeys.chatRooms(),
        queryKeys.chatRoom(roomId),
        queryKeys.conversations(),
        ...(options.teamId ? [queryKeys.teams(), queryKeys.team(options.teamId)] : []),
      ]);
    },
    afterGroupRoundStarted(roomId: string) {
      return invalidateAll(queryClient, [
        queryKeys.chatRooms(),
        queryKeys.chatRoom(roomId),
        queryKeys.conversations(),
      ]);
    },
    afterChatRoomsChanged() {
      return invalidateAll(queryClient, [queryKeys.chatRooms(), queryKeys.conversations()]);
    },
    afterGroupRoundStopped(roomId: string) {
      return invalidateAll(queryClient, [
        queryKeys.chatRooms(),
        queryKeys.chatRoom(roomId),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterProjectBusChanged() {
      return invalidateAll(queryClient, [
        queryKeys.projectAgentBus(),
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterProjectBusFailed() {
      return invalidateAll(queryClient, [queryKeys.projectAgentBus()]);
    },
    afterAgentWorkspaceChanged() {
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.agents(),
        queryKeys.agentModeBindings(),
        queryKeys.sessions(),
        queryKeys.conversations(),
      ]);
    },
    afterAgentChatRoomsChanged() {
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.chatRooms(),
        queryKeys.conversations(),
      ]);
    },
    afterAgentArchived() {
      return invalidateAll(queryClient, [
        queryKeys.agents(),
        queryKeys.agentModeBindings(),
        queryKeys.chatRooms(),
        queryKeys.sessions(),
        queryKeys.conversations(),
      ]);
    },
    afterTeamChanged(teamId?: string) {
      return invalidateAll(queryClient, [
        queryKeys.teams(),
        queryKeys.agentConfigWorkspace(),
        queryKeys.projectAgentBus(),
        ...(teamId ? [queryKeys.team(teamId)] : []),
      ]);
    },
    afterTeamArchived(teamId: string, roomId?: string) {
      return invalidateAll(queryClient, [
        queryKeys.teams(),
        queryKeys.team(teamId),
        queryKeys.agents(),
        queryKeys.agentModeBindings(),
        queryKeys.chatRooms(),
        ...(roomId ? [queryKeys.chatRoom(roomId)] : []),
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.agentConfigWorkspace(),
        queryKeys.projectAgentBus(),
      ]);
    },
    afterTeamRoomMembershipChanged(teamId: string, roomId: string) {
      return invalidateAll(queryClient, [
        queryKeys.teams(),
        queryKeys.team(teamId),
        queryKeys.chatRooms(),
        queryKeys.chatRoom(roomId),
        queryKeys.conversations(),
        queryKeys.agentConfigWorkspace(),
      ]);
    },
  };
}
