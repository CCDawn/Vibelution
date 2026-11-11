import { ChevronDown } from "lucide-react";
import React, { ReactNode, useLayoutEffect, useRef, useState } from "react";

import { useAppI18n } from "../../i18n/useAppI18n";
import { VNativeButton } from "../vui";
import { shouldCollapseAssistantMessage } from "./conversationAssistantMessageCollapse";
import styles from "./AgentAssistantContentSectionView.styles";

type AgentAssistantContentSectionViewProps = {
  children: ReactNode;
  /** Message identity, so an explicit expand/collapse survives remounts. */
  messageId?: string;
};

/**
 * Explicit user choices only. A message the reader never touched always opens
 * expanded, which is why the default is not written here.
 */
const assistantAnswerExpansion = new Map<string, boolean>();

function readAssistantAnswerExpansion(messageId?: string) {
  if (!messageId) {
    return true;
  }
  return assistantAnswerExpansion.get(messageId) ?? true;
}

/**
 * Assistant answer shell (markdown children pass-through).
 *
 * The answer is the content the reader asked for, so it opens expanded and only
 * clamps after an explicit collapse. The bound exists to keep virtualization
 * honest (an unclamped 20 KB answer measures thousands of pixels while the list
 * estimates a fixed row height), not to hide the answer: the threshold, the
 * bottom fade and the toggle are a viewport guard, and the user's own choice is
 * what decides the state afterwards.
 *
 * Measurement is still ResizeObserver-driven (async media growth counts) and the
 * clamp is only applied once the natural height is known to exceed the
 * threshold, so a short answer never paints clamped for a frame.
 */
export function AgentAssistantContentSectionView({
  children,
  messageId,
}: AgentAssistantContentSectionViewProps) {
  const { t } = useAppI18n({ domains: ["chat"] });
  const measuredContentRef = useRef<HTMLDivElement | null>(null);
  // Flips only when the natural content height crosses the threshold, so
  // per-frame ResizeObserver reports never re-render the answer.
  // `null` means "not measured yet", which stays collapsed: a tall answer
  // should not paint at full height and then snap shut.
  const [overflows, setOverflows] = useState<boolean | null>(null);
  const [expanded, setExpanded] = useState(() => readAssistantAnswerExpansion(messageId));
  // `overflows === null` is "not measured yet": stay expanded instead of
  // clamping on the first paint and snapping open a frame later.
  const collapsed = overflows === true && !expanded;

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
          onClick={() => {
            setExpanded((current) => {
              const next = !current;
              if (messageId) {
                assistantAnswerExpansion.set(messageId, next);
              }
              return next;
            });
          }}
        >
          <ChevronDown
            className={styles.assistantCollapseChevron}
            data-assistant-content-collapse-chevron={expanded ? "expanded" : "collapsed"}
            size={14}
            aria-hidden="true"
          />
          {expanded ? t("collapseAssistantMessage") : t("expandAssistantMessage")}
        </VNativeButton>
      ) : null}
    </div>
  );
}
