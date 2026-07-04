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
  onToggle,
  children,
}: AgentResponseSectionViewProps) {
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
        onClick={onToggle}
        title={expanded ? expandedTitle : collapsedTitle}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{label}</span>
        {showSpinner ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
      </VButton>
      {expanded ? <div className={styles.responseBody}>{children}</div> : null}
    </section>
  );
}
