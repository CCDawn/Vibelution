import type { QueryKey } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";
import { markSessionDeleteTombstone } from "./sessionDeleteTombstone";

// Cache role split (phase 2 timeline swap): the room detail cache
// (queryKeys.chatRoom) carries metadata/participants/operation results only;
// the group transcript authority is the timeline query
// (queryKeys.chatRoomTimeline = ["chat-rooms", roomId, "timeline"]). The
// timeline key nests under the chatRoom key, so the room-scoped invalidations
// below reach it by prefix without dedicated entries. The live SSE path does
// NOT go through this module: useGroupRoomStream's syncChatRoomDetail writes
// the detail snapshot and invalidates the timeline key directly.

type QueryClientLike = {
  invalidateQueries: (options: { queryKey: QueryKey }) => Promise<unknown> | unknown;
  removeQueries?: (options: { queryKey: QueryKey; exact?: boolean }) => void;
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
    afterSessionSelected() {
      return invalidateAll(queryClient, [queryKeys.runtimeSummary()]);
    },
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
        queryKeys.conversations(),
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
    afterSessionDeleted(options: {
      deletedSessionId: string;
      roomId?: string;
    }) {
      const deletedSessionId = String(options.deletedSessionId || "").trim();
      if (deletedSessionId) {
        // Survive brief list refetch races after optimistic delete.
        markSessionDeleteTombstone(deletedSessionId);
        queryClient.removeQueries?.({ queryKey: queryKeys.session(deletedSessionId), exact: true });
        queryClient.removeQueries?.({ queryKey: queryKeys.sessionLlmOptions(deletedSessionId), exact: true });
      }
      // Idle-session delete changes indexes, not runtime summary or the already
      // prefetched replacement detail. Keep both warm across the handoff.
      return invalidateAll(queryClient, [
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.agents(),
        ...(options.roomId ? [queryKeys.chatRooms(), queryKeys.chatRoom(options.roomId)] : []),
      ]);
    },
    /**
     * Config save / model pin: refresh Agent config and directory projections.
     * Chat directory renders avatarImageUrl from the Agent summary, so it must
     * observe a model-derived default avatar change without invalidating
     * sessions/conversations (which freezes the active chat tab).
     */
    afterAgentConfigSaved(agentId?: string) {
      const normalizedAgentId = String(agentId || "").trim();
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.agentSummary(true),
        queryKeys.agents(),
        ...(normalizedAgentId ? [queryKeys.agent(normalizedAgentId)] : []),
      ]);
    },
    /**
     * Single-Agent display-layer PATCH (persona/task/prompt, tool & memory
     * policy, runtime policy, avatar, governance, inbox consume). The caller
     * already patched the workspace cache in place, so only the Agent-directory
     * projections refetch. Deliberately NOT the ["agents"] prefix: mounted
     * runs/inbox/evidence queries are untouched by display edits.
     */
    afterAgentDisplaySaved(agentId?: string) {
      const normalizedAgentId = String(agentId || "").trim();
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.agentSummary(true),
        queryKeys.agentSummary(false),
        ...(normalizedAgentId ? [queryKeys.agent(normalizedAgentId)] : []),
      ]);
    },
    /**
     * Mode-membership PATCH: touches the shared mode-slot collection, so the
     * mode-bindings key joins the display-level refresh. Still no ["agents"]
     * prefix and no sessions/conversations — chat indexes are unaffected.
     */
    afterAgentMembershipSaved(agentId?: string) {
      const normalizedAgentId = String(agentId || "").trim();
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.agentSummary(true),
        queryKeys.agentSummary(false),
        queryKeys.agentModeBindings(),
        ...(normalizedAgentId ? [queryKeys.agent(normalizedAgentId)] : []),
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
        ...(options.teamId ? [queryKeys.teams(), queryKeys.teamDetails(options.teamId)] : []),
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
      // Structural agent changes (create/archive/purge/reset, bulk edits) may
      // affect chat indexes. Prefer afterAgentDisplaySaved for single-agent
      // display PATCH and afterAgentMembershipSaved for mode-membership saves;
      // afterAgentConfigSaved stays the routine config-PATCH recipe.
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        queryKeys.agents(),
        queryKeys.agentModeBindings(),
        queryKeys.sessions(),
        queryKeys.conversations(),
      ]);
    },
    afterAgentRenamed(agentId?: string) {
      // Display-name PATCH is not structural. Keep the agents-list cache order
      // (already patched in place) and skip session/conversation reshuffles.
      const normalizedAgentId = String(agentId || "").trim();
      return invalidateAll(queryClient, [
        queryKeys.agentConfigWorkspace(),
        ...(normalizedAgentId ? [queryKeys.agent(normalizedAgentId)] : []),
      ]);
    },
    afterChatWorkspaceReset() {
      queryClient.removeQueries?.({ queryKey: queryKeys.sessions() });
      return invalidateAll(queryClient, [
        queryKeys.sessions(),
        queryKeys.conversations(),
        queryKeys.chatRooms(),
        queryKeys.runtimeSummary(),
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
        queryKeys.agentConfigWorkspace(),
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
        ...(teamId ? [queryKeys.teamDetails(teamId)] : []),
      ]);
    },
    afterTeamArchived(teamId: string, roomId?: string) {
      return invalidateAll(queryClient, [
        queryKeys.teams(),
        queryKeys.teamDetails(teamId),
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
        queryKeys.teamDetails(teamId),
        queryKeys.chatRooms(),
        queryKeys.chatRoom(roomId),
        queryKeys.conversations(),
        queryKeys.agentConfigWorkspace(),
      ]);
    },
  };
}
