import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatRoomDetail, ChatRoomParticipant, ChatRoomRound, ConversationMessage } from "../../src/api/types";
import { ChatGroupCenterSurface } from "../../src/routes/chat/ChatGroupCenterSurface";
import { Plus } from "lucide-react";
import { VButton } from "../../src/components/vui";
import { ConversationView } from "../../src/components/conversation/ConversationView";

export type PreviewMember = { name: string; role: string; initials: string; note: string };
const timestamp = "2026-10-14T06:32:00Z";
const discussion = [
  "已梳理主页与对话页的差异。建议优先统一消息阅读区域和底部输入区，画布继续保留。",
  "核对了现有对话组件：团队讨论使用群聊消息流，成员独立对话使用单人对话流。身份、轮次和引用应继续由各自组件展示。",
  "我会验证团队切换、画布与发言切换，以及发送、停止和长内容滚动时的输入区位置。",
];
function round(roomId: string, id: string, topic: string, members: readonly PreviewMember[], running = false): ChatRoomRound {
  return { roundId: id, roomId, topic, mode: "round_robin", purpose: "discussion", config: {}, status: running ? "running" : "completed",
    speakerOrder: members.map((_, index) => "member-" + index), summary: "", startedAt: timestamp, updatedAt: timestamp, finishedAt: running ? "" : timestamp,
    messages: running ? [] : members.map((member, index) => ({ messageId: id + "-" + index, participantId: "member-" + index, agentId: "preview-" + index,
      sessionId: "", speakerTitle: member.name, status: "completed", content: discussion[index], summary: "", timestamp, messageKind: "team_discussion" })) };
}
export function TeamConversationPreview({ teamId, teamName, members, topic, running, onStart, onStop, onNotice, directMember }: {
  teamId: string; teamName: string; members: readonly PreviewMember[]; topic: string; running: boolean;
  onStart: (topic: string) => void; onStop: () => void; onNotice: (notice: string) => void; directMember: PreviewMember | null;
}) {
  const [draft, setDraft] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [directMessages, setDirectMessages] = useState<ConversationMessage[]>([]);
  const [streamText, setStreamText] = useState("");
  const [completedRounds, setCompletedRounds] = useState<ChatRoomRound[]>([]);
  const streamedText = useRef("");
  const wasRunning = useRef(false);
  useEffect(() => { setDraft(""); setDirectMessages([]); setExpanded([]); }, [teamId, directMember?.name]);
  useEffect(() => {
    if (!running) {
      if (wasRunning.current) { const stopped = round("preview-team-" + teamId, "stopped-" + completedRounds.length, topic, members); stopped.status = "stopped"; stopped.messages = [{ ...stopped.messages[0], content: streamedText.current || "本轮示例已停止。" }]; setCompletedRounds((items) => [...items, stopped]); }
      wasRunning.current = false; streamedText.current = ""; setStreamText(""); return;
    }
    wasRunning.current = true;
    const text = "正在核对消息阅读区域与输入区的位置。先检查桌面布局，再整理需要修正的间距。";
    let index = 0;
    const timer = window.setInterval(() => { index += 3; streamedText.current = text.slice(0, index); setStreamText(streamedText.current); if (index >= text.length) window.clearInterval(timer); }, 90);
    return () => window.clearInterval(timer);
  }, [running, topic, teamId]);
  const roomId = "preview-team-" + teamId;
  const participants: ChatRoomParticipant[] = useMemo(() => members.map((member, index) => ({ participantId: "member-" + index, kind: "agent", agentId: "preview-" + index,
    sessionId: "", title: member.name, teamRole: member.role, enabled: true, status: "ready" })), [members]);
  const room: ChatRoomDetail = useMemo(() => ({ roomId, title: teamName + "讨论", mode: "round_robin", purpose: "discussion", config: {}, participants,
    rounds: [round(roomId, "history", "核对团队对话页的布局与消息流", members), ...completedRounds, ...(running ? [round(roomId, "active", topic, members, true)] : [])],
    status: running ? "running" : "ready", activeRoundId: running ? "active" : "", createdAt: timestamp, updatedAt: timestamp, availableModes: [], availablePurposes: [] }), [roomId, teamName, participants, topic, members, running, completedRounds]);
  if (directMember) {
    const initial: ConversationMessage[] = [{ id: "initial-user", role: "user", timestamp, content: "请核对团队对话页的布局，重点看消息和输入区。" },
      { id: "initial-answer", role: "assistant", timestamp, turnId: "initial-turn", status: "completed", turnItems: [{ id: "initial-item", itemId: "initial-item", version: 3,
        sessionId: "preview-direct", turnId: "initial-turn", type: "agent_message", phase: "final_answer", text: "已核对。消息正文和底部输入区现在直接使用现有对话组件。\n\n" + directMember.note + "，我会保留成员身份与任务上下文。",
        status: "completed", terminal: true, revision: 1, sequence: 1 }] }];
    return <ConversationView sessionId="" title={directMember.name} phase="idle" messages={[...initial, ...directMessages]} defaultFileContext=""
      showHeader={false} showSessionOverview={false} showMentalSnapshots={false} composerVariant="codex" processDisplayMode="answer"
      assistantDisplayName={directMember.name} assistantAvatarFallback={directMember.initials} userDisplayName="我" promptSuggestionEnabled={false}
      composerValue={draft} composerPlaceholder={"发给 " + directMember.name + "（预览）"} composerDisabled={false} composerPending={false}
      composerActionDisabled={!draft.trim()} onComposerChange={setDraft} onSubmit={() => { if (!draft.trim()) return;
        setDirectMessages((items) => [...items, { id: "local-" + items.length, role: "user", timestamp, content: draft.trim() }]); setDraft(""); onNotice("消息已进入本地预览对话流，未发送给真实 Agent。"); }} />;
  }
  return <ChatGroupCenterSurface composerLeadingControl={<VButton isIconOnly variant="ghost" aria-label="添加附件" icon={<Plus size={17} />} onClick={() => onNotice("附件入口已保留；此预览不上传文件。")} />} lang="zh" projectBusActive={false} standardGroupRoomActive groupRoomInitialLoading={false}
    activeGroupRoom={room} activeGroupRoomId={roomId} availableGroupParticipantCount={members.length} visibleGroupParticipants={participants}
    activeGroupParticipantById={new Map(participants.map((participant) => [participant.participantId, participant]))}
    projectBusTimeline={null} projectBusEvents={[]} projectBusDraft="" projectBusInterruptTargets={false}
    groupTopicDraft={draft} groupRoomActionError="" groupRoundActive={running} groupRoundStopping={false} groupStopDisabled={false}
    expandedGroupMessageIds={expanded} chatMentionTargets={[]} userDisplayName="我" projectBusRefreshing={false} projectBusRefreshError=""
    projectBusSendPending={false} projectBusRevokePending={false} groupRoomRefreshing={false} groupRoomRefreshError="" groupStreamConnected
    groupSpeakerStreams={running ? { active: { "member-0": { roundId: "active", participantId: "member-0", seq: 1, content: streamText, sessionId: "", turnId: "preview-active", lastDeltaAtMs: Date.now() } } } : {}}
    groupSpeakerProgress={running ? { active: { "member-0": { participantId: "member-0", sessionId: "", state: "running", status: "", updatedAt: timestamp } } } : {}}
    startGroupRoundPending={false} stopGroupRoundPending={false} formatTime={() => "14:32"} statusLabel={(status) => ({ running: "运行中", completed: "已完成", stopped: "已停止", ready: "就绪" } as Record<string, string>)[status] || status}
    groupParticipantIdentity={(participant) => { const index = participants.findIndex((item) => item.participantId === participant?.participantId); const member = members[Math.max(0, index)];
      return { name: member.name, identityLabel: member.name + " · " + member.role, fullIdentityLabel: member.name + " · " + member.role, functionLabel: member.role }; }}
    renderAgentAvatar={(className, _imageUrl, initials) => <span className={className}>{initials}</span>}
    avatarInitials={(_code, name) => name?.slice(0, 1) || "团"}
    onProjectBusDraftChange={() => undefined} onProjectBusInterruptTargetsChange={() => undefined} onGroupTopicDraftChange={setDraft}
    onRefreshProjectBus={() => undefined} onRefreshGroupRoom={() => onNotice("示例讨论已刷新。")} onSendProjectBusMessage={() => undefined} onRevokeProjectBusMessage={() => undefined}
    onStartGroupRound={() => { if (!draft.trim()) return; onStart(draft.trim()); setDraft(""); }} onStopGroupRound={onStop} onOpenMentionTarget={() => undefined}
    onToggleExpandedGroupMessage={(id) => setExpanded((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id])} />;
}
