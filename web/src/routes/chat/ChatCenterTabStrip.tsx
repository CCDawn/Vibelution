/**
 * Chat center tab strip: return chip, session/file tabs, responsive overlay toggles.
 */
import { ArrowLeft, PanelRightClose, PanelRightOpen } from "lucide-react";
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
  companionHeader?: ReactNode;
  conversationIndexControl?: ReactNode;
  leftOverlayVisible: boolean;
  rightOverlayVisible: boolean;
  /** Companion status can be opened from a narrow window. */
  statusRailAvailable: boolean;
  /**
   * Ordinary chat keeps this labeled control in the tab strip on every width,
   * including when the column is still empty. Companion omits it.
   */
  rightRailLabel?: string;
  /** Whether the right column is currently open (docked or overlay). */
  rightRailOpen?: boolean;
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
  companionHeader,
  conversationIndexControl,
  leftOverlayVisible,
  rightOverlayVisible,
  statusRailAvailable,
  rightRailLabel,
  rightRailOpen,
  conversationIndexOverlayOpen,
  statusRailOverlayOpen,
  onActivateAgentFallbackTab,
  onToggleLeftOverlay,
  onToggleRightOverlay,
}: ChatCenterTabStripProps) {
  const railOpen = rightRailOpen ?? statusRailOverlayOpen;
  // Ordinary chat (rightRailLabel) keeps the control on wide windows too.
  // Companion still uses the narrow-window status button only.
  const showRightToggle = Boolean(rightRailLabel) || (statusRailAvailable && !rightOverlayVisible);
  return (
    <div className={styles.tabStrip}>
      {conversationIndexControl}
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
        {companionHeader ?? (groupPanelActive ? (
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
        ) : null)}
        {companionHeader ? null : <Suspense fallback={null}>{fileTabs}</Suspense>}
      </div>
      {!leftOverlayVisible || showRightToggle ? (
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
          {showRightToggle ? (
            <VButton
              id="chat-status-toggle"
              type="button"
              className={railOpen ? `${styles.overlayPaneToggle} ${styles.tabActive}` : styles.overlayPaneToggle}
              aria-expanded={railOpen}
              aria-controls="chat-status-pane"
              icon={rightRailLabel ? (railOpen
                ? <PanelRightClose size={14} aria-hidden="true" />
                : <PanelRightOpen size={14} aria-hidden="true" />) : undefined}
              onClick={onToggleRightOverlay}
            >
              {rightRailLabel ?? (lang === "zh" ? "状态" : "Status")}
            </VButton>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
