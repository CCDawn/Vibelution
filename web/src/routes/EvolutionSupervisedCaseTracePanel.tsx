import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Play,
  Sparkles,
  TriangleAlert,
  Wrench,
} from "lucide-react";

import { VButton } from "../components/vui";
import type { SupervisedCaseTraceItem, SupervisedCaseTraceTone } from "./supervisedCaseTrace";
import styles from "./EvolutionRoute.styles";

const CASE_TRACE_TURN_CLASS: Record<SupervisedCaseTraceTone, string> = {
  input: styles.caseTraceTurn_input,
  thought: styles.caseTraceTurn_thought,
  tool: styles.caseTraceTurn_tool,
  assistant: styles.caseTraceTurn_assistant,
  error: styles.caseTraceTurn_error,
};

export type EvolutionSupervisedCaseTracePanelProps = {
  items: SupervisedCaseTraceItem[];
  statusLabel: (status: string) => string;
  formatTimestamp: (value: string) => string;
};

function caseTraceIcon(item: SupervisedCaseTraceItem) {
  if (item.tone === "tool") {
    return <Wrench size={15} />;
  }
  if (item.tone === "assistant") {
    return <Sparkles size={15} />;
  }
  if (item.tone === "error") {
    return <TriangleAlert size={15} />;
  }
  if (item.tone === "input") {
    return <Play size={14} />;
  }
  return <Activity size={15} />;
}

function renderCaseTraceSection(
  section: SupervisedCaseTraceItem["sections"][number],
  index: number,
) {
  if (section.kind === "state") {
    return (
      <div key={`${section.label}-${index}`} className={styles.caseTraceStateGrid}>
        {section.rows.map((row) => (
          <dl key={`${section.label}-${row.label}`} className={styles.caseTraceStateRow}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </dl>
        ))}
      </div>
    );
  }
  return (
    <div
      key={`${section.label}-${index}`}
      className={
        section.kind === "json"
          ? `${styles.caseTraceSection} ${styles.caseTraceSectionJson}`
          : styles.caseTraceSection
      }
    >
      <span>{section.label}</span>
      <pre>{section.content}</pre>
    </div>
  );
}

/**
 * Expandable case-trace timeline for supervised live conversation evidence.
 */
export function EvolutionSupervisedCaseTracePanel({
  items,
  statusLabel,
  formatTimestamp,
}: EvolutionSupervisedCaseTracePanelProps) {
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const latestKey = items.at(-1)?.key ?? "";

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline || items.length === 0) {
      return;
    }
    timeline.scrollTop = timeline.scrollHeight;
  }, [latestKey, items.length]);

  if (items.length === 0) {
    return null;
  }

  return (
    <div className={styles.supervisedConversationTrace} data-vui-region="evolution-supervised-case-trace">
      <div ref={timelineRef} className={styles.caseTraceTimeline}>
        <div className={styles.caseTraceStack}>
          {items.map((entry) => {
            const expanded = expandedItems[entry.key] ?? entry.defaultOpen;
            return (
              <article
                key={entry.key}
                className={`${styles.caseTraceTurn} ${CASE_TRACE_TURN_CLASS[entry.tone]}`}
              >
                <VButton
                  type="button"
                  contentLayout="plain"
                  className={styles.caseTraceSummary}
                  aria-expanded={expanded}
                  onClick={() => {
                    setExpandedItems((current) => ({
                      ...current,
                      [entry.key]: !(current[entry.key] ?? entry.defaultOpen),
                    }));
                  }}
                >
                  <span className={styles.caseTraceIcon}>{caseTraceIcon(entry)}</span>
                  <span className={styles.caseTraceMessage}>
                    <span className={styles.caseTraceTitle}>{entry.title}</span>
                    <span className={styles.caseTracePreview}>{entry.preview}</span>
                  </span>
                  <span className={styles.caseTraceMeta}>
                    {entry.status ? (
                      <span className={styles.caseTraceStatus}>{statusLabel(entry.status)}</span>
                    ) : null}
                    {entry.timestamp ? (
                      <span className={styles.caseTraceTime}>{formatTimestamp(entry.timestamp)}</span>
                    ) : null}
                  </span>
                  <span className={styles.caseTraceChevron}>
                    {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </span>
                </VButton>
                {expanded ? (
                  <div className={styles.caseTraceBody}>
                    {entry.sections.map((section, sectionIndex) => renderCaseTraceSection(section, sectionIndex))}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
