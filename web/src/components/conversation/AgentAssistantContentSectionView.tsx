import React, { ReactNode, useLayoutEffect, useRef, useState } from "react";

import { useAppI18n } from "../../i18n/useAppI18n";
import { VNativeButton } from "../vui";
import { shouldCollapseAssistantMessage } from "./conversationAssistantMessageCollapse";
import styles from "./AgentAssistantContentSectionView.styles";

type AgentAssistantContentSectionViewProps = {
  children: ReactNode;
};

/**
 * Assistant answer shell (markdown children pass-through). Mirrors the
 * ZCode-aligned long-message handling that the user bubble already has, so both
 * halves of the transcript keep a bounded row height: past the collapse
 * threshold the body clamps behind a bottom fade with a small ghost
 * expand/collapse toggle. Collapsed state is measurement-driven (ResizeObserver
 * natural height, including async media growth) and never persisted — every
 * mount starts collapsed again.
 *
 * A bounded answer is also what keeps virtualization honest. An unclamped 20 KB
 * answer measures thousands of pixels while the list estimates the row at a
 * fixed size; that gap is what stacks rows on top of each other for a frame
 * after a session switch.
 */
export function AgentAssistantContentSectionView({
  children,
}: AgentAssistantContentSectionViewProps) {
  const { t } = useAppI18n({ domains: ["chat"] });
  const measuredContentRef = useRef<HTMLDivElement | null>(null);
  // Flips only when the natural content height crosses the threshold, so
  // per-frame ResizeObserver reports never re-render the answer.
  // `null` means "not measured yet", which stays collapsed: a tall answer
  // should not paint at full height and then snap shut.
  const [overflows, setOverflows] = useState<boolean | null>(null);
  const [expanded, setExpanded] = useState(false);
  const collapsed = overflows !== false && !expanded;

  useLayoutEffect(() => {
    const element = measuredContentRef.current;
    if (!element) {
      return;
    }
    const updateHeight = (height: number) => {
      const next = shouldCollapseAssistantMessage(height);
      setOverflows((current) => (current === next ? current : next));
    };
    // Content is markdown that can grow after first paint (images, late
    // highlight pass); observe the natural-height node (the wrapper clips, the
    // node does not).
    if (typeof ResizeObserver === "undefined") {
      updateHeight(element.scrollHeight);
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries.find((item) => item.target === element);
      if (entry) {
        updateHeight(entry.contentRect.height);
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={styles.assistantBody} data-assistant-content-collapse="1">
      <div
        className={collapsed ? styles.assistantBodyClamped : styles.assistantBodyWrap}
        data-assistant-content-collapsed={collapsed ? "1" : undefined}
      >
        <div ref={measuredContentRef} data-testid="assistant-message-measured-content">
          {children}
        </div>
        {collapsed && overflows ? (
          <div className={styles.assistantCollapseFade} aria-hidden="true" />
        ) : null}
      </div>
      {overflows ? (
        <VNativeButton
          className={styles.assistantCollapseToggle}
          aria-expanded={expanded}
          data-testid="assistant-message-collapse-toggle"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? t("collapseAssistantMessage") : t("expandAssistantMessage")}
        </VNativeButton>
      ) : null}
    </div>
  );
}
