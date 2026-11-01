import { useEffect, type ReactNode } from "react";
import { UsersRound } from "lucide-react";
import type { ProjectAgentBusEvent, ProjectAgentBusTimeline } from "../../api/types";
import { AgentMessageDetail } from "../../components/agent-messages";
import { VButton, VNativeInput } from "../../components/vui";
import type { ChatMentionTarget } from "../chatMentionTokens";
import { selectAgentMessage, useAgentMessageSelection } from "./agentMessageSelectionStore";
import { useAgentMessageRecords } from "./useAgentMessageRecords";
import styles from "./ChatProjectBusSurface.styles";

export type ChatProjectBusSurfaceProps = {
  lang: "zh" | "en";
  projectBusTimeline: ProjectAgentBusTimeline | null | undefined;
  projectBusEvents: ProjectAgentBusEvent[];
  projectBusDraft: string;
  projectBusInterruptTargets: boolean;
  projectBusRefreshing: boolean;
  projectBusRefreshError: string;
  projectBusSendPending: boolean;
  projectBusRevokePending: boolean;
  projectBusInitialLoading: boolean;
  groupRoomActionError: string;
  userDisplayName: string;
  chatMentionTargets: ChatMentionTarget[];
  composerLeadingControl?: ReactNode;
  formatTime: (value: string) => string;
  onProjectBusDraftChange: (value: string) => void;
  onProjectBusInterruptTargetsChange: (value: boolean) => void;
  onRefreshProjectBus: () => void;
  onSendProjectBusMessage: () => void;
  onRevokeProjectBusMessage: (eventId: string) => void;
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
};

/** The existing message-center route shares records/selection with the left rail. */
export function ChatProjectBusSurface(props: ChatProjectBusSurfaceProps) {
  const { lang, projectBusEvents, projectBusDraft, projectBusInterruptTargets, projectBusSendPending,
    projectBusRevokePending, groupRoomActionError, onProjectBusDraftChange, onProjectBusInterruptTargetsChange,
    onSendProjectBusMessage, onRevokeProjectBusMessage, composerLeadingControl } = props;
  const model = useAgentMessageRecords();
  const selectedId = useAgentMessageSelection();
  const selected = model.records.find((record) => record.id === selectedId || record.aliases?.includes(selectedId || ""));
  const canonicalId = selected?.id || selectedId;
  const revocable = selected && projectBusEvents.find((event) => event.createdBy === "user" && event.status !== "revoked"
    && (event.eventId === selected.sourceEventId || selected.aliases?.includes(event.eventId)));
  useEffect(() => {
    if (!selectedId && model.records.length) selectAgentMessage(model.records[0].id);
  }, [selectedId, model.records]);
  return <div className={`${styles.groupConversationFrame} !flex !flex-col`} data-testid="agent-message-center">
    {groupRoomActionError ? <div className={styles.inlineNotice} role="alert">{groupRoomActionError}</div> : null}
    <div className="min-h-0 flex-1 overflow-hidden">
      <AgentMessageDetail records={model.records} selectedId={canonicalId} onSelect={selectAgentMessage} lang={lang} />
    </div>
    {revocable ? <div className="shrink-0 px-5 pb-2"><VButton isDisabled={projectBusRevokePending} onPress={() => onRevokeProjectBusMessage(revocable.eventId)}>{lang === "zh" ? "撤回这条广播" : "Recall this broadcast"}</VButton></div> : null}
    <div className={styles.groupComposerBar}>
      {composerLeadingControl}
      <VNativeInput value={projectBusDraft} onChange={(event) => onProjectBusDraftChange(event.target.value)} disabled={projectBusSendPending}
        aria-label={lang === "zh" ? "发送项目广播" : "Send a project broadcast"}
        placeholder={lang === "zh" ? "输入广播；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Write a broadcast; @AgentCode targets one"}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSendProjectBusMessage(); } }} />
      <label className={styles.projectBusInterruptToggle}><VNativeInput type="checkbox" checked={projectBusInterruptTargets} onChange={(event) => onProjectBusInterruptTargetsChange(event.target.checked)} /><span>{lang === "zh" ? "打断目标助手" : "Interrupt targets"}</span></label>
      <VButton onPress={onSendProjectBusMessage} isDisabled={!projectBusDraft.trim() || projectBusSendPending} icon={<UsersRound size={15} />}>
        {projectBusSendPending ? (lang === "zh" ? "发送中" : "Sending") : (lang === "zh" ? "发送广播" : "Send broadcast")}
      </VButton>
    </div>
  </div>;
}
