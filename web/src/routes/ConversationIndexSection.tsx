import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { VButton } from "../components/vui";
import styles from "./ChatCodingRoute.styles";

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
      <VButton
        type="button"
        className={styles.conversationGroupHeader}
        onPress={onToggle}
        aria-expanded={expanded}
      >
        <ChevronRight size={14} aria-hidden="true" />
        <span>{label}</span>
        <strong>{count}</strong>
      </VButton>
      {expanded ? (
        <div className={styles.conversationGroupList}>
          {children}
        </div>
      ) : null}
    </section>
  );
}
