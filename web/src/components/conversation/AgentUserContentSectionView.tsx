import React, { ReactNode, useLayoutEffect, useRef, useState } from "react";

import { useAppI18n } from "../../i18n/useAppI18n";
import { VNativeButton } from "../vui";
import { shouldCollapseUserMessage } from "./conversationUserMessageCollapse";
import styles from "./AgentUserContentSectionView.styles";

type AgentUserContentSectionViewProps = {
  userContentSectionIds?: string;
  children: ReactNode;
};

/**
 * User message bubble shell (markdown children pass-through). ZCode-aligned
 * long-message handling: when the rendered body grows past the collapse
 * threshold the content clamps behind a bottom fade with a small ghost
 * expand/collapse toggle. Collapsed state is measurement-driven
 * (ResizeObserver natural height, including async media growth) and
 * never persisted — every mount starts collapsed again. The inline editor
 * replaces this component entirely while editing, so edit mode is unaffected.
 */
export function AgentUserContentSectionView({
  userContentSectionIds,
  children,
}: AgentUserContentSectionViewProps) {
  const { t } = useAppI18n({ domains: ["chat"] });
  const measuredContentRef = useRef<HTMLDivElement | null>(null);
  // Flips only when the natural content height crosses the threshold, so
  // per-frame ResizeObserver reports never re-render the bubble.
  // Keep the default height bounded until the browser's initial observer
  // delivery, without forcing a document layout during the React commit.
  const [overflows, setOverflows] = useState<boolean | null>(null);
  const [expanded, setExpanded] = useState(false);
  const collapsed = overflows !== false && !expanded;

  useLayoutEffect(() => {
    const element = measuredContentRef.current;
    if (!element) {
      return;
    }
    const updateHeight = (height: number) => {
      const next = shouldCollapseUserMessage(height);
      setOverflows((current) => (current === next ? current : next));
    };
    // Content is markdown that can grow after first paint (images, streaming);
    // observe the natural-height node (the wrapper clips, the node does not).
    if (typeof ResizeObserver === "undefined") {
      updateHeight(element.scrollHeight);
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries.find((item) => item.target === element);
      if (entry) updateHeight(entry.contentRect.height);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className={styles.userMessageBody}
      data-agent-content-section-ids={userContentSectionIds}
      data-agent-content-channel={userContentSectionIds ? "user" : undefined}
    >
      <div className={collapsed ? styles.userMessageBodyClamped : styles.userMessageBodyWrap}>
        <div ref={measuredContentRef} data-testid="user-message-measured-content">
          {children}
        </div>
        {collapsed && overflows ? <div className={styles.userMessageCollapseFade} aria-hidden="true" /> : null}
      </div>
      {overflows ? (
        <VNativeButton
          className={styles.userMessageCollapseToggle}
          aria-expanded={expanded}
          data-testid="user-message-collapse-toggle"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? t("collapseUserMessage") : t("expandUserMessage")}
        </VNativeButton>
      ) : null}
    </div>
  );
}
