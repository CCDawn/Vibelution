/**
 * Chat center tab strip: return chip, session/file tabs, responsive overlay toggles.
 */
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Suspense } from "react";

import { VButton } from "../../components/vui";

export type ChatCenterTabStripProps = {
  /** Route style map (ChatCodingRoute.styles is Record<string, string>). */
  styles: Record<string, string>;
  lang: "zh" | "en";
  agentSessionLabel: string;
  chatReturnTarget: string | null;
  chatReturnLabel: string;
  groupPanelActive: boolean;
  projectBusActive: boolean;
  showSessionTabs: boolean;
  showAgentFallbackTab: boolean;
  workspaceActiveTab: string;
  sessionTabs: ReactNode;
  fileTabs: ReactNode;
  companionActions?: ReactNode;
  leftOverlayVisible: boolean;
  rightOverlayVisible: boolean;
  conversationIndexOverlayOpen: boolean;
  statusRailOverlayOpen: boolean;
  onActivateAgentFallbackTab: () => void;
  onToggleLeftOverlay: () => void;
  onToggleRightOverlay: () => void;
};

export function ChatCenterTabStrip({
  styles,
  lang,
  agentSessionLabel,
  chatReturnTarget,
  chatReturnLabel,
  groupPanelActive,
  projectBusActive,
  showSessionTabs,
  showAgentFallbackTab,
  workspaceActiveTab,
  sessionTabs,
  fileTabs,
  companionActions,
  leftOverlayVisible,
  rightOverlayVisible,
  conversationIndexOverlayOpen,
  statusRailOverlayOpen,
  onActivateAgentFallbackTab,
  onToggleLeftOverlay,
  onToggleRightOverlay,
}: ChatCenterTabStripProps) {
  return (
    <div className={styles.tabStrip}>
      {chatReturnTarget ? (
        <Link
          className={styles.chatReturnLink}
          to={chatReturnTarget}
          title={chatReturnLabel}
          aria-label={chatReturnLabel}
        >
          <ArrowLeft size={14} className={styles.chatReturnLinkIcon} aria-hidden="true" />
          <span>{lang === "zh" ? "返回" : "Back"}</span>
        </Link>
      ) : null}
      <div className={styles.tabStripSessions}>
        {groupPanelActive ? (
          <VButton
            type="button"
            className={`${styles.tab} ${styles.tabActive}`}
            onClick={() => undefined}
          >
            {projectBusActive ? (lang === "zh" ? "通知流" : "Notice stream") : (lang === "zh" ? "群聊" : "Group")}
          </VButton>
        ) : showSessionTabs ? (
          sessionTabs
        ) : showAgentFallbackTab ? (
          <VButton
            type="button"
            className={workspaceActiveTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={onActivateAgentFallbackTab}
          >
            {agentSessionLabel}
          </VButton>
        ) : null}
        <Suspense fallback={null}>{fileTabs}</Suspense>
      </div>
      {companionActions}
      {!leftOverlayVisible || !rightOverlayVisible ? (
        <div className={styles.overlayPaneControls}>
          {!leftOverlayVisible ? (
            <VButton
              id="chat-conversation-index-toggle"
              type="button"
              className={styles.overlayPaneToggle}
              aria-expanded={conversationIndexOverlayOpen}
              aria-controls="chat-conversation-index-pane"
              onClick={onToggleLeftOverlay}
            >
              {lang === "zh" ? "会话" : "Chats"}
            </VButton>
          ) : null}
          {!rightOverlayVisible ? (
            <VButton
              id="chat-status-toggle"
              type="button"
              className={styles.overlayPaneToggle}
              aria-expanded={statusRailOverlayOpen}
              aria-controls="chat-status-pane"
              onClick={onToggleRightOverlay}
            >
              {lang === "zh" ? "状态" : "Status"}
            </VButton>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
