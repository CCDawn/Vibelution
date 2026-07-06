import { ChevronDown, ChevronRight, LoaderCircle } from "lucide-react";
import React, { ReactNode } from "react";

import { VButton } from "../vui";
import styles from "./AgentResponseSectionView.styles";

type AgentResponseSectionViewProps = {
  answerKey: string;
  answerContentSectionIds?: string;
  expanded: boolean;
  label: string;
  expandedTitle: string;
  collapsedTitle: string;
  showSpinner: boolean;
  forceBodyVisible?: boolean;
  onToggle: () => void;
  children: ReactNode;
};

export function AgentResponseSectionView({
  answerKey,
  answerContentSectionIds,
  expanded,
  label,
  expandedTitle,
  collapsedTitle,
  showSpinner,
  forceBodyVisible = false,
  onToggle,
  children,
}: AgentResponseSectionViewProps) {
  const bodyVisible = expanded || forceBodyVisible;
  const responseBodyId = `agent-response-${answerKey}`;
  const toggleLabel = bodyVisible ? expandedTitle : collapsedTitle;
  return (
    <section
      className={styles.responseSection}
      data-conversation-part-key={answerKey}
      data-agent-content-section-ids={answerContentSectionIds}
      data-agent-content-channel={answerContentSectionIds ? "answer" : undefined}
    >
      <VButton
        type="button"
        className={styles.responseToggle}
        aria-expanded={expanded}
        aria-controls={responseBodyId}
        aria-label={toggleLabel}
        onClick={onToggle}
        title={toggleLabel}
      >
        {bodyVisible ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
        <span>{label}</span>
        <span className={styles.responseToggleStatus}>
          {showSpinner ? <LoaderCircle className={styles.statusSpinner} size={14} aria-hidden="true" /> : null}
        </span>
      </VButton>
      {bodyVisible ? <div id={responseBodyId} className={styles.responseBody}>{children}</div> : null}
    </section>
  );
}
