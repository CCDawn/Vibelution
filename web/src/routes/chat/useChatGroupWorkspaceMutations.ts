/**
 * Group room create, rounds, update, delete, and reset, plus project-bus
 * send/revoke. Project-bus mutations sit between round stop and room update,
 * so they stay in this hook and the hook is called at the original site.
 */
import { useMutation } from "@tanstack/react-query";
import {
  createChatRoom,
  deleteChatRoom,
  resetChatRoom,
  startChatRoomRound,
  stopChatRoomRound,
  updateChatRoom,
} from "../../api/chat";
import {
  revokeProjectAgentBusMessage,
  sendProjectAgentBusMessage,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import { startUserAction } from "../../app/userActionTelemetry";
import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomParticipant,
} from "../../api/types";
import {
  createTempRoomId,
  insertTempGroupRoomConversation,
  removeTempGroupRoomConversations,
} from "../groupRoomOptimisticIds";
import type { UseChatWorkspaceLifecycleOptions } from "./useChatWorkspaceLifecycle";

export type UseChatGroupWorkspaceMutationsInput = Pick<
  UseChatWorkspaceLifecycleOptions,
  | "queryClient"
  | "chatWorkspaceCache"
  | "lang"
  | "describeError"
  | "syncChatRoomDetail"
  | "routeSelectionRef"
  | "chatRoute"
  | "setRightIndexPanel"
  | "setSessionFilter"
  | "setSessionComposerErrors"
  | "setGroupComposerOpen"
  | "setGroupTitleDraft"
  | "setGroupModeDraft"
  | "setGroupPurposeDraft"
  | "setGroupSelectedAgentIds"
  | "setGroupTopicDraft"
  | "setGroupRoomActionError"
  | "setGroupManageTitleDraft"
  | "setGroupManageSessionIds"
  | "setGroupManageModeDraft"
  | "setGroupManagePurposeDraft"
  | "setProjectBusDraft"
>;

export function useChatGroupWorkspaceMutations({
  queryClient,
  chatWorkspaceCache,
  lang,
  describeError,
  syncChatRoomDetail,
  routeSelectionRef,
  chatRoute,
  setRightIndexPanel,
  setSessionFilter,
  setSessionComposerErrors,
  setGroupComposerOpen,
  setGroupTitleDraft,
  setGroupModeDraft,
  setGroupPurposeDraft,
  setGroupSelectedAgentIds,
  setGroupTopicDraft,
  setGroupRoomActionError,
  setGroupManageTitleDraft,
  setGroupManageSessionIds,
  setGroupManageModeDraft,
  setGroupManagePurposeDraft,
  setProjectBusDraft,
}: UseChatGroupWorkspaceMutationsInput) {
  const createGroupRoomMutation = useMutation({
    mutationFn: async (
      { title, agentIds, mode, purpose }: { title: string; agentIds: string[]; mode: string; purpose: string },
    ) =>
      createChatRoom({ title, agentIds, mode, purpose }),
    onMutate: ({ title, agentIds, mode, purpose }) => {
      const telemetry = startUserAction("group_room_create", {
        agentCount: agentIds.length,
        mode,
      });
      const routeSelectionAtRequest = routeSelectionRef.current;
      // T0: mint a local temp room shell immediately (same skeleton as session
      // create). The real id arrives on success; the UI paints the room shell
      // instead of waiting on the POST round-trip.
      const tempRoomId = createTempRoomId();
      const nowIso = new Date().toISOString();
      const agents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [];
      const normalizedAgentIds = agentIds
        .map((agentId) => String(agentId || "").trim())
        .filter(Boolean);
      const optimisticRoom: ChatRoomDetail = {
        roomId: tempRoomId,
        title,
        mode,
        purpose,
        config: {},
        participants: normalizedAgentIds.map((agentId): ChatRoomParticipant => {
          const agentRow = agents.find((item) => String(item.agentId || "").trim() === agentId);
          return {
            participantId: agentId,
            kind: "session_agent",
            agentId,
            agentCode: String(agentRow?.agentCode || "").trim(),
            // Server-assigned direct sessions are unknown until the response.
            sessionId: "",
            title: String(agentRow?.displayName || agentRow?.agentCode || agentId).trim(),
            enabled: true,
            status: "ready",
          };
        }),
        rounds: [],
        status: "ready",
        activeRoundId: "",
        createdAt: nowIso,
        updatedAt: nowIso,
        availableModes: [],
        availablePurposes: [],
      };
      // Do not await cancelQueries — waiting freezes tab switching while catalog
      // lists settle, same as createSessionMutation.
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setRightIndexPanel("conversations");
      setSessionFilter("");
      // Cache first, then switch route — the room surface reads the cache on entry.
      queryClient.setQueryData(queryKeys.chatRoom(tempRoomId), optimisticRoom);
      insertTempGroupRoomConversation(queryClient, {
        conversationId: tempRoomId,
        type: "group_room",
        title,
        roomId: tempRoomId,
        status: "ready",
        summary: "",
        updatedAt: nowIso,
        workspacePath: "",
        participantCount: normalizedAgentIds.length,
        mode,
      });
      // The temp id enters the URL immediately; the route is the single authority.
      chatRoute.openRoom(tempRoomId);
      return { routeSelectionAtRequest, tempRoomId, telemetry };
    },
    onSuccess: (room, _variables, context) => {
      const tempRoomId = String(context?.tempRoomId || "").trim();
      // Seed real id cache BEFORE the route swaps so the UI never paints a hard loading shell.
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      // Compare-and-swap: only replace temp → real while the user still views
      // the temp room. A user who already left keeps their page; cache only.
      const stillOnTemp = tempRoomId
        ? chatRoute.replaceIfStillViewing(
            { kind: "room", roomId: tempRoomId },
            { kind: "room", roomId: room.roomId },
          )
        : false;
      context?.telemetry?.succeeded({
        roomId: room.roomId,
        participantCount: room.participants?.length ?? 0,
        tempRoomId,
        routeReplacedFromTemp: stillOnTemp,
      });
      if (tempRoomId) {
        // Drop the temp shell after the real id is active/cached.
        queryClient.removeQueries({ queryKey: queryKeys.chatRoom(tempRoomId), exact: true });
        removeTempGroupRoomConversations(queryClient);
      }
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupPurposeDraft("discussion");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
      const tempRoomId = String(context?.tempRoomId || "").trim();
      if (tempRoomId) {
        // Roll the optimistic shell back; only leave the temp room while the
        // user still views it (same compare-and-swap as success). Composer
        // drafts stay intact so the operator can retry create.
        chatRoute.replaceIfStillViewing(
          { kind: "room", roomId: tempRoomId },
          context?.routeSelectionAtRequest ?? { kind: "bare" },
        );
        queryClient.removeQueries({ queryKey: queryKeys.chatRoom(tempRoomId), exact: true });
        removeTempGroupRoomConversations(queryClient);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          lang === "zh" ? "创建群聊失败" : "Create group chat failed",
        ),
      }));
    },
  });

  const startGroupRoundMutation = useMutation({
    mutationFn: async (
      { roomId, topic, mode, purpose }: { roomId: string; topic: string; mode: string; purpose: string },
    ) =>
      startChatRoomRound(roomId, { topic, mode, purpose }, { preferAsync: true }),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_round_start", {
        roomId: variables.roomId,
        topicLength: variables.topic.length,
        mode: variables.mode,
      }),
    }),
    onSuccess: (accepted, _variables, context) => {
      context?.telemetry?.succeeded({
        roomId: accepted.roomId,
        roundId: accepted.roundId,
        asyncAccepted: true,
      });
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.kind === "room" ? routeSelectionRef.current.roomId : "");
    },
  });

  const stopGroupRoundMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      stopChatRoomRound(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_round_stop", { roomId: variables.roomId }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({ roomId: room.roomId });
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterGroupRoundStopped(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void chatWorkspaceCache.afterGroupRoundStopped(variables.roomId);
    },
  });

  const sendProjectBusMessageMutation = useMutation({
    mutationFn: async (
      {
        content,
        interruptTargets,
      }: {
        content: string;
        interruptTargets: boolean;
      },
    ) =>
      sendProjectAgentBusMessage({ content, interruptTargets }),
    onMutate: (variables) => ({
      telemetry: startUserAction("project_bus_send", {
        contentLength: variables.content.length,
        interruptTargets: variables.interruptTargets,
      }),
    }),
    onSuccess: (_payload, _variables, context) => {
      context?.telemetry?.succeeded();
      setProjectBusDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const revokeProjectBusMessageMutation = useMutation({
    mutationFn: async ({ eventId }: { eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "user_recalled_project_bus_message",
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("project_bus_revoke", { eventId: variables.eventId }, { destructive: true }),
    }),
    onSuccess: (_payload, _variables, context) => {
      context?.telemetry?.succeeded();
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { eventId: variables.eventId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const updateGroupRoomMutation = useMutation({
    mutationFn: async (
      { roomId, title, sessionIds, mode, purpose }: {
        roomId: string;
        title: string;
        sessionIds: string[];
        mode: string;
        purpose: string;
      },
    ) =>
      updateChatRoom(roomId, {
        title,
        participantSessionIds: sessionIds,
        mode,
        purpose,
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_update", {
        roomId: variables.roomId,
        participantCount: variables.sessionIds.length,
        mode: variables.mode,
      }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({
        roomId: room.roomId,
        participantCount: room.participants.length,
      });
      setGroupManageTitleDraft(room.title || "");
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
      setGroupManagePurposeDraft(room.purpose || "discussion");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (routeSelectionRef.current.kind === "room") {
        void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.roomId);
      }
    },
  });

  const deleteGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      deleteChatRoom(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_delete", { roomId: variables.roomId }, { destructive: true }),
    }),
    onSuccess: (_payload, variables, context) => {
      const routeReplaced = chatRoute.replaceIfStillViewing(
        { kind: "room", roomId: variables.roomId },
        { kind: "bare" },
      );
      context?.telemetry?.succeeded({
        roomId: variables.roomId,
        routeReplaced,
      });
      setRightIndexPanel("conversations");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      setGroupManageTitleDraft("");
      setGroupManageSessionIds([]);
      setGroupManageModeDraft("round_robin");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      // Only leave the deleted room while the user is still on its route.
      void chatWorkspaceCache.afterChatRoomChanged(variables.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const resetGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      resetChatRoom(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_reset", { roomId: variables.roomId }, { destructive: true }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({ roomId: room.roomId });
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "重置群聊失败" : "Reset group failed"));
      if (routeSelectionRef.current.kind === "room") {
        void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.roomId);
      }
    },
  });

  return {
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
  };
}
