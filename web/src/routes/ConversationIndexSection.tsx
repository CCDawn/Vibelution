import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./ChatCodingRoute.module.css";

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
  const sectionClassName = className
    ? `${styles.conversationGroup} ${className}`
    : styles.conversationGroup;

  return (
    <section className={sectionClassName}>
      <button
        type="button"
        className={styles.conversationGroupHeader}
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <ChevronRight size={14} aria-hidden="true" />
        <span>{label}</span>
        <strong>{count}</strong>
      </button>
      {expanded ? (
        <div className={styles.conversationGroupList}>
          {children}
        </div>
      ) : null}
    </section>
  );
}
