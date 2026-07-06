import { ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";

import { VNativeButton } from "../components/vui";
import styles from "./ConversationIndexSection.styles";

type ConversationIndexSectionProps = {
  children: ReactNode;
  className?: string;
  count: number;
  expanded: boolean;
  label: string;
  onToggle: () => void;
};

export function ConversationIndexSection({
  children,
  className = "",
  count,
  expanded,
  label,
  onToggle,
}: ConversationIndexSectionProps) {
  const sectionId = useId();
  const headerId = `${sectionId}-header`;
  const listId = `${sectionId}-list`;
  const sectionClassName = className
    ? `${styles.conversationGroup} ${className}`
    : styles.conversationGroup;

  return (
    <section className={sectionClassName}>
      <VNativeButton
        type="button"
        className={styles.conversationGroupHeader}
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={listId}
      >
        <ChevronRight size={14} aria-hidden="true" />
        <span id={headerId}>{label}</span>
        <strong>{count}</strong>
      </VNativeButton>
      {expanded ? (
        <div
          id={listId}
          className={styles.conversationGroupList}
          role="group"
          aria-labelledby={headerId}
        >
          {children}
        </div>
      ) : null}
    </section>
  );
}
