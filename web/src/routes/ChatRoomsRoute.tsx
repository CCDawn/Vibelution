import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, MessageSquareText, Pencil, Play, Plus, RefreshCw, Trash2, UsersRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ChatRoomDetail, ChatRoomMode, SessionDetail, SessionSummary } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./ChatRoomsRoute.module.css";

function roomStatusLabel(status: string, lang: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "running") {
    return lang === "en" ? "Running" : "运行中";
  }
  if (normalized === "failed") {
    return lang === "en" ? "Failed" : "失败";
  }
  return lang === "en" ? "Ready" : "就绪";
}

function modeLabel(mode: ChatRoomMode, lang: string) {
  if (mode.id === "round_robin") {
    return lang === "en" ? "Round robin" : "轮询讨论";
  }
  if (mode.id === "opportunistic") {
    return lang === "en" ? "Opportunistic" : "抢占式讨论";
  }
  return mode.label || mode.id;
}

function latestRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function apiKeyMissingText(value: string) {
  return /api key|api_key|未设置\s*api\s*key/i.test(value);
}

export function ChatRoomsRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [roomTitle, setRoomTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([]);
  const [selectedModeId, setSelectedModeId] = useState("");
  const [editingSessionId, setEditingSessionId] = useState("");
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionActionError, setSessionActionError] = useState("");
  const [roomActionError, setRoomActionError] = useState("");
  const requestedRoomId = useMemo(() => new URLSearchParams(location.search).get("room") ?? "", [location.search]);

  const roomsQuery = useQuery({
    queryKey: queryKeys.chatRooms(),
    queryFn: () => fetchJson<ChatRoomDetail[]>("/api/chat-rooms"),
  });
  const modesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
  });
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => fetchJson<SessionSummary[]>("/api/sessions"),
  });
  const detailQuery = useQuery({
    queryKey: queryKeys.chatRoom(selectedRoomId),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${selectedRoomId}`),
    enabled: Boolean(selectedRoomId),
  });

  const rooms = roomsQuery.data ?? [];
  const sessions = sessionsQuery.data ?? [];
  const modes = modesQuery.data ?? [];
  const activeRoom = detailQuery.data ?? rooms.find((room) => room.roomId === selectedRoomId) ?? rooms[0] ?? null;
  const readyModes = useMemo(() => modes.filter((mode) => mode.status === "ready"), [modes]);
  const selectedMode = modes.find((mode) => mode.id === selectedModeId) ?? readyModes[0] ?? modes[0] ?? null;
  const selectedModeReady = selectedMode?.status === "ready";
  const runnableModeId = selectedModeReady ? selectedMode.id : readyModes[0]?.id ?? "round_robin";
  const currentRound = latestRound(activeRoom);
  const activeRoomSessionIds = useMemo(
    () => new Set((activeRoom?.participants ?? []).map((participant) => participant.sessionId)),
    [activeRoom?.participants],
  );
  const currentRoundApiKeyError = Boolean(
    currentRound?.messages?.some((message) => apiKeyMissingText(`${message.summary} ${message.content}`)),
  );

  useEffect(() => {
    if (requestedRoomId && rooms.some((room) => room.roomId === requestedRoomId) && selectedRoomId !== requestedRoomId) {
      setSelectedRoomId(requestedRoomId);
      const room = rooms.find((item) => item.roomId === requestedRoomId);
      if (room) {
        setSelectedSessionIds(room.participants.map((participant) => participant.sessionId));
      }
      return;
    }
    if (!selectedRoomId && rooms.length > 0) {
      setSelectedRoomId(rooms[0].roomId);
      setSelectedSessionIds(rooms[0].participants.map((participant) => participant.sessionId));
    }
  }, [requestedRoomId, rooms, selectedRoomId]);

  useEffect(() => {
    if (!selectedRoomId && !selectedSessionIds.length && sessions.length > 0) {
      setSelectedSessionIds(sessions.map((session) => session.id));
    }
  }, [selectedRoomId, selectedSessionIds.length, sessions]);

  useEffect(() => {
    if (!selectedModeId && readyModes.length > 0) {
      setSelectedModeId(readyModes[0].id);
    }
  }, [readyModes, selectedModeId]);

  const selectedSessionSet = useMemo(() => new Set(selectedSessionIds), [selectedSessionIds]);

  const createRoomMutation = useMutation({
    mutationFn: async () =>
      fetchJson<ChatRoomDetail>("/api/chat-rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: roomTitle.trim(),
          participantSessionIds: selectedSessionIds,
          mode: runnableModeId,
        }),
      }),
    onSuccess: (room) => {
      setSelectedRoomId(room.roomId);
      setSelectedSessionIds(room.participants.map((participant) => participant.sessionId));
      setRoomTitle("");
      setRoomActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setRoomActionError(describeError(error, lang === "en" ? "Create room failed" : "创建群聊失败"));
    },
  });

  const updateRoomMutation = useMutation({
    mutationFn: async () =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeRoom?.roomId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          participantSessionIds: selectedSessionIds,
          mode: runnableModeId,
        }),
      }),
    onSuccess: (room) => {
      setSelectedRoomId(room.roomId);
      setRoomActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setRoomActionError(describeError(error, lang === "en" ? "Update room failed" : "更新群聊失败"));
    },
  });

  const deleteRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<{ deleted: boolean; roomId: string }>(`/api/chat-rooms/${roomId}`, {
        method: "DELETE",
      }),
    onSuccess: (_payload, variables) => {
      setSelectedRoomId("");
      setRoomActionError("");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setRoomActionError(describeError(error, lang === "en" ? "Delete room failed" : "删除群聊失败"));
    },
  });

  const startRoundMutation = useMutation({
    mutationFn: async () =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeRoom?.roomId}/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: topic.trim(),
          mode: runnableModeId,
        }),
      }),
    onSuccess: (room) => {
      setSelectedRoomId(room.roomId);
      setTopic("");
      setRoomActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setRoomActionError(describeError(error, lang === "en" ? "Run round failed" : "启动讨论失败"));
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: async () =>
      fetchJson<SessionDetail>("/api/sessions", {
        method: "POST",
      }),
    onSuccess: (session) => {
      setSelectedSessionIds((current) => (current.includes(session.id) ? current : [...current, session.id]));
      setSessionActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
    onError: (error) => {
      setSessionActionError(describeError(error, lang === "en" ? "Create session failed" : "创建会话失败"));
    },
  });

  const renameSessionMutation = useMutation({
    mutationFn: async ({ sessionId, title }: { sessionId: string; title: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => {
      setEditingSessionId("");
      setEditingSessionTitle("");
      setSessionActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      if (selectedRoomId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(selectedRoomId) });
      }
    },
    onError: (error) => {
      setSessionActionError(describeError(error, lang === "en" ? "Rename session failed" : "重命名会话失败"));
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: (_session, variables) => {
      setSelectedSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));
      setSessionActionError("");
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      if (selectedRoomId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(selectedRoomId) });
      }
    },
    onError: (error) => {
      setSessionActionError(describeError(error, lang === "en" ? "Delete session failed" : "删除会话失败"));
    },
  });

  const toggleSession = (sessionId: string) => {
    setSelectedSessionIds((current) => {
      if (current.includes(sessionId)) {
        return current.filter((item) => item !== sessionId);
      }
      return [...current, sessionId];
    });
  };

  const createDisabled = createRoomMutation.isPending || selectedSessionIds.length === 0 || !selectedModeReady;
  const updateDisabled = updateRoomMutation.isPending || !activeRoom || selectedSessionIds.length === 0 || !selectedModeReady;
  const roundDisabled = startRoundMutation.isPending || !activeRoom || !topic.trim() || activeRoom.status === "running" || !selectedModeReady;
  const selectedDiffersFromRoom = Boolean(
    activeRoom
    && (
      selectedSessionIds.length !== activeRoomSessionIds.size
      || selectedSessionIds.some((sessionId) => !activeRoomSessionIds.has(sessionId))
    ),
  );
  const createRoomLabel = createRoomMutation.isPending
    ? (lang === "en" ? "Creating" : "创建中")
    : (lang === "en" ? "Create room" : "创建群聊");
  const subtitle = lang === "en"
    ? "Pull existing session agents into one room, then run extensible discussion rounds."
    : "把现有会话 Agent 拉到同一个房间里，用可扩展调度跑一轮讨论。";

  return (
    <main className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>CHAT ROOM</p>
          <h1>{lang === "en" ? "Agent Rooms" : "Agent 群聊"}</h1>
          <p>{subtitle}</p>
        </div>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => {
            roomsQuery.refetch();
            if (selectedRoomId) {
              detailQuery.refetch();
            }
          }}
          title={lang === "en" ? "Refresh" : "刷新"}
          aria-label={lang === "en" ? "Refresh" : "刷新"}
        >
          <RefreshCw size={16} />
        </button>
      </header>

      <section className={styles.summaryGrid}>
        <div className={styles.summaryCard}>
          <span>{lang === "en" ? "Rooms" : "房间"}</span>
          <strong>{rooms.length}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span>{lang === "en" ? "Sessions" : "会话"}</span>
          <strong>{sessions.length}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span>{lang === "en" ? "Ready mode" : "当前模式"}</span>
          <strong>{selectedMode ? modeLabel(selectedMode, lang) : "-"}</strong>
        </div>
        <div className={styles.summaryCard}>
          <span>{lang === "en" ? "Status" : "状态"}</span>
          <strong>{activeRoom ? roomStatusLabel(activeRoom.status, lang) : "-"}</strong>
        </div>
      </section>

      <section className={styles.workspace}>
        <aside className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{lang === "en" ? "Rooms" : "群聊房间"}</p>
              <h2>{lang === "en" ? "Room list" : "房间列表"}</h2>
            </div>
            <MessageSquareText size={17} />
          </div>
          <div className={styles.roomList}>
            {rooms.map((room) => (
              <button
                key={room.roomId}
                type="button"
                className={room.roomId === activeRoom?.roomId ? `${styles.roomButton} ${styles.roomButtonActive}` : styles.roomButton}
                onClick={() => {
                  setSelectedRoomId(room.roomId);
                  setSelectedSessionIds(room.participants.map((participant) => participant.sessionId));
                }}
              >
                <strong>{room.title}</strong>
                <span>
                  {room.participants.length} {lang === "en" ? "agents" : "位 Agent"} · {roomStatusLabel(room.status, lang)}
                </span>
              </button>
            ))}
            {!rooms.length ? (
              <p className={styles.emptyText}>
                {lang === "en" ? "No rooms yet. Create one from the session list." : "还没有群聊房间。先从会话列表创建一个。"}
              </p>
            ) : null}
          </div>
        </aside>

        <section className={styles.discussion}>
          <div className={styles.discussionHeader}>
            <div>
              <p className={styles.panelEyebrow}>{activeRoom?.mode ?? "round_robin"}</p>
              <h2>{activeRoom?.title ?? (lang === "en" ? "No room selected" : "未选择房间")}</h2>
              <p>
                {currentRound?.summary
                  || (lang === "en" ? "Start a topic to collect participant replies." : "输入议题后启动一轮讨论，收集每位参与者发言。")}
              </p>
            </div>
            <div className={styles.discussionActions}>
              {currentRoundApiKeyError ? (
                <a className={styles.configLink} href="/config" title={lang === "en" ? "Configure API key" : "配置 API Key"}>
                  <KeyRound size={14} />
                  <span>{lang === "en" ? "API key" : "配置 API Key"}</span>
                </a>
              ) : null}
              {activeRoom ? (
                <button
                  type="button"
                  className={styles.iconButton}
                  disabled={deleteRoomMutation.isPending || activeRoom.status === "running"}
                  onClick={() => deleteRoomMutation.mutate({ roomId: activeRoom.roomId })}
                  title={lang === "en" ? "Delete room" : "删除群聊"}
                  aria-label={lang === "en" ? "Delete room" : "删除群聊"}
                >
                  <Trash2 size={15} />
                </button>
              ) : null}
              <span className={styles.statusPill}>{activeRoom ? roomStatusLabel(activeRoom.status, lang) : "-"}</span>
            </div>
          </div>
          {roomActionError ? <p className={styles.inlineError}>{roomActionError}</p> : null}
          {currentRoundApiKeyError ? (
            <div className={styles.configNotice}>
              <KeyRound size={16} />
              <span>
                {lang === "en"
                  ? "The discussion agent could not call the model because the global API key is not configured."
                  : "讨论 Agent 无法调用模型，因为全局 API Key 尚未配置。"}
              </span>
            </div>
          ) : null}

          <div className={styles.topicBar}>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder={lang === "en" ? "Topic for the next discussion round" : "下一轮讨论议题"}
            />
            <button type="button" className={styles.primaryButton} disabled={roundDisabled} onClick={() => startRoundMutation.mutate()}>
              <Play size={15} />
              <span>{startRoundMutation.isPending ? (lang === "en" ? "Running" : "讨论中") : (lang === "en" ? "Run round" : "启动讨论")}</span>
            </button>
          </div>

          <div className={styles.messageList}>
            {(currentRound?.messages ?? []).map((message) => (
              <article key={message.messageId} className={message.status === "failed" ? `${styles.messageCard} ${styles.messageCardFailed}` : styles.messageCard}>
                <header>
                  <strong>{message.speakerTitle}</strong>
                  <span>{message.status}</span>
                </header>
                <p>{message.content || message.summary}</p>
              </article>
            ))}
            {!currentRound?.messages?.length ? (
              <div className={styles.emptyState}>
                <UsersRound size={28} />
                <p>{lang === "en" ? "The room is ready for its first discussion round." : "房间已准备好，等待第一轮群聊发言。"}</p>
                {!activeRoom ? (
                  <button
                    type="button"
                    className={styles.emptyActionButton}
                    disabled={createDisabled}
                    onClick={() => createRoomMutation.mutate()}
                  >
                    <Plus size={15} />
                    <span>{createRoomLabel}</span>
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>

        <aside className={`${styles.panel} ${styles.participantPanel}`}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{lang === "en" ? "Participants" : "参与者"}</p>
              <h2>{lang === "en" ? "Session agents" : "会话 Agent"}</h2>
            </div>
            <UsersRound size={17} />
          </div>
          <div className={styles.createBox}>
            <div className={styles.createBoxHeader}>
              <strong>{lang === "en" ? "New room" : "新建群聊"}</strong>
              <span>
                {selectedSessionIds.length}/{sessions.length} {lang === "en" ? "selected" : "已选择"}
              </span>
            </div>
            <input
              value={roomTitle}
              onChange={(event) => setRoomTitle(event.target.value)}
              placeholder={lang === "en" ? "Room title" : "群聊名称"}
            />
            <button type="button" className={styles.createButton} disabled={createDisabled} onClick={() => createRoomMutation.mutate()}>
              <Plus size={15} />
              <span>{createRoomLabel}</span>
            </button>
            {createDisabled && !createRoomMutation.isPending ? (
              <p className={styles.actionHint}>
                {lang === "en" ? "Select at least one ready session and a ready mode." : "至少选择一个会话，并使用 ready 模式。"}
              </p>
            ) : null}
            {activeRoom ? (
              <button
                type="button"
                className={selectedDiffersFromRoom ? styles.applyButton : styles.secondaryButton}
                disabled={updateDisabled}
                onClick={() => updateRoomMutation.mutate()}
              >
                <Check size={15} />
                <span>
                  {updateRoomMutation.isPending
                    ? (lang === "en" ? "Applying" : "应用中")
                    : (lang === "en" ? "Apply to room" : "应用到当前群聊")}
                </span>
              </button>
            ) : null}
            {roomActionError ? <p className={styles.inlineError}>{roomActionError}</p> : null}
            {sessionActionError ? <p className={styles.inlineError}>{sessionActionError}</p> : null}
          </div>
          <div className={styles.sessionList}>
            <button
              type="button"
              className={styles.newAgentButton}
              disabled={createSessionMutation.isPending}
              onClick={() => createSessionMutation.mutate()}
            >
              <Plus size={15} />
              <span>{createSessionMutation.isPending ? (lang === "en" ? "Creating session" : "创建会话中") : (lang === "en" ? "New session agent" : "新建会话 Agent")}</span>
            </button>
            {sessions.map((session) => (
              <div key={session.id} className={styles.sessionItem}>
                <label className={styles.sessionSelectLine}>
                  <input
                    type="checkbox"
                    checked={selectedSessionSet.has(session.id)}
                    onChange={() => toggleSession(session.id)}
                  />
                  <span>
                    {editingSessionId === session.id ? (
                      <input
                        className={styles.sessionTitleInput}
                        value={editingSessionTitle}
                        autoFocus
                        maxLength={120}
                        onChange={(event) => setEditingSessionTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            renameSessionMutation.mutate({ sessionId: session.id, title: editingSessionTitle.trim() });
                          }
                          if (event.key === "Escape") {
                            setEditingSessionId("");
                            setEditingSessionTitle("");
                          }
                        }}
                      />
                    ) : (
                      <strong>{session.title}</strong>
                    )}
                    <small>{session.currentPhase || session.status}</small>
                  </span>
                </label>
                <div className={styles.sessionActions}>
                  {editingSessionId === session.id ? (
                    <>
                      <button
                        type="button"
                        className={styles.sessionIconButton}
                        disabled={renameSessionMutation.isPending || !editingSessionTitle.trim()}
                        onClick={() => renameSessionMutation.mutate({ sessionId: session.id, title: editingSessionTitle.trim() })}
                        title={lang === "en" ? "Save name" : "保存名称"}
                        aria-label={lang === "en" ? "Save name" : "保存名称"}
                      >
                        <Check size={14} />
                      </button>
                      <button
                        type="button"
                        className={styles.sessionIconButton}
                        disabled={renameSessionMutation.isPending}
                        onClick={() => {
                          setEditingSessionId("");
                          setEditingSessionTitle("");
                        }}
                        title={lang === "en" ? "Cancel" : "取消"}
                        aria-label={lang === "en" ? "Cancel" : "取消"}
                      >
                        <X size={14} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className={styles.sessionIconButton}
                        onClick={() => {
                          setEditingSessionId(session.id);
                          setEditingSessionTitle(session.title);
                        }}
                        title={lang === "en" ? "Rename session" : "重命名会话"}
                        aria-label={lang === "en" ? "Rename session" : "重命名会话"}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        className={styles.sessionDeleteButton}
                        disabled={deleteSessionMutation.isPending || session.currentPhase === "running" || session.currentPhase === "stopping"}
                        onClick={() => deleteSessionMutation.mutate({ sessionId: session.id })}
                        title={lang === "en" ? "Delete session" : "删除会话"}
                        aria-label={lang === "en" ? "Delete session" : "删除会话"}
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
            {!sessions.length ? (
              <p className={styles.emptyText}>{lang === "en" ? "No chat sessions available." : "当前没有可加入群聊的会话。"}</p>
            ) : null}
          </div>
          <div className={styles.modeList}>
            {modes.map((mode) => (
              <button
                key={mode.id}
                type="button"
                className={[
                  styles.modeButton,
                  mode.status === "ready" ? styles.modeReady : styles.modePlanned,
                  mode.id === selectedMode?.id ? styles.modeSelected : "",
                ].filter(Boolean).join(" ")}
                disabled={mode.status !== "ready"}
                onClick={() => setSelectedModeId(mode.id)}
                title={mode.status === "ready"
                  ? modeLabel(mode, lang)
                  : (lang === "en" ? "Planned mode" : "规划中的模式")}
              >
                {modeLabel(mode, lang)} · {mode.status}
              </button>
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}
