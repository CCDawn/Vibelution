import { useRef } from "react";

import { VListDetailPage } from "../vui";
import { AgentMessageDetail } from "./AgentMessageDetail";
import { AgentMessageSidebar, type AgentMessageSidebarHandle, type AgentMessageSidebarProps } from "./AgentMessageSidebar";
import { messageText } from "./agentMessagePresentation";
import styles from "./AgentMessages.styles";

export type AgentMessageCenterProps = AgentMessageSidebarProps;

/** Shared presentation only; the host owns fetching, scope and selected identity. */
export function AgentMessageCenter({ className, ...props }: AgentMessageCenterProps) {
  const sidebarRef = useRef<AgentMessageSidebarHandle>(null);
  const select = (id: string) => {
    props.onSelect(id);
    sidebarRef.current?.locate(id);
  };
  return <VListDetailPage title={messageText(props.lang, "跨 Agent 消息", "Agent messages")} hideHeader ariaLabel={messageText(props.lang, "跨 Agent 消息中心", "Agent message center")} className={[styles.page, className].filter(Boolean).join(" ")} workspaceClassName={styles.workspace} columnsClassName=""
    list={<AgentMessageSidebar ref={sidebarRef} {...props} onSelect={select} />}
    detail={<AgentMessageDetail records={props.records} selectedId={props.selectedId} onSelect={select} lang={props.lang} />}
  />;
}
