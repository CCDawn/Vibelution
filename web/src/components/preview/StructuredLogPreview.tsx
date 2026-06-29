import { AlertTriangle, Bot, Brain, MessageSquareText, MonitorCog, Rows3, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { VButton } from "../vui";
import { useAppI18n } from "../../i18n/useAppI18n";
import {
  filterStructuredLogEntries,
  type StructuredLogCategoryFilter,
  type StructuredLogPreviewModel,
} from "../../logs/structuredLogPreview";
import type { LogSeverityFilter } from "../../logs/logSeverity";
import styles from "./StructuredLogPreview.module.css";

type StructuredLogPreviewProps = {
  model: StructuredLogPreviewModel;
  severityFilter: LogSeverityFilter;
};

const categoryOptions: Array<{
  value: StructuredLogCategoryFilter;
  icon: typeof Rows3;
  zh: string;
  en: string;
}> = [
  { value: "all", icon: Rows3, zh: "全部", en: "All" },
  { value: "dialogue", icon: MessageSquareText, zh: "对话", en: "Dialogue" },
  { value: "thinking", icon: Brain, zh: "思考", en: "Thinking" },
  { value: "tool", icon: Wrench, zh: "工具", en: "Tools" },
  { value: "system", icon: MonitorCog, zh: "系统", en: "System" },
  { value: "problem", icon: AlertTriangle, zh: "问题", en: "Issues" },
];

function levelClassName(level: string) {
  if (level === "error") {
    return `${styles.levelPill} ${styles.levelError}`;
  }
  if (level === "warning") {
    return `${styles.levelPill} ${styles.levelWarning}`;
  }
  return styles.levelPill;
}

function categoryLabel(category: string, lang: "zh" | "en") {
  const option = categoryOptions.find((item) => item.value === category);
  return option ? (lang === "zh" ? option.zh : option.en) : category;
}

export function StructuredLogPreview({ model, severityFilter }: StructuredLogPreviewProps) {
  const { lang, t } = useAppI18n();
  const [categoryFilter, setCategoryFilter] = useState<StructuredLogCategoryFilter>("all");
  const visibleEntries = useMemo(
    () => filterStructuredLogEntries(model.entries, categoryFilter, severityFilter),
    [categoryFilter, model.entries, severityFilter],
  );
  const categoryCounts = useMemo(() => {
    const counts: Record<StructuredLogCategoryFilter, number> = {
      all: model.entries.length,
      dialogue: 0,
      thinking: 0,
      tool: 0,
      system: 0,
      problem: 0,
    };
    for (const entry of model.entries) {
      counts[entry.category] += 1;
    }
    return counts;
  }, [model.entries]);

  return (
    <section className={styles.surface}>
      <div className={styles.toolbar}>
        <div className={styles.summary}>
          <Bot size={16} />
          <span>{lang === "zh" ? "结构化日志" : "Structured log"}</span>
          <strong>
            {model.parseableLineCount}/{model.totalLineCount}
          </strong>
        </div>
        <div className={styles.filterGroup} role="group" aria-label={lang === "zh" ? "日志内容筛选" : "Log content filter"}>
          {categoryOptions.map((option) => {
            const Icon = option.icon;
            const active = categoryFilter === option.value;
            return (
              <VButton
                key={option.value}
                type="button"
                className={active ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                onPress={() => setCategoryFilter(option.value)}
                title={lang === "zh" ? option.zh : option.en}
                icon={<Icon size={14} />}
              >
                <span>{lang === "zh" ? option.zh : option.en}</span>
                <strong>{categoryCounts[option.value]}</strong>
              </VButton>
            );
          })}
        </div>
      </div>

      <div className={styles.list}>
        {visibleEntries.length === 0 ? (
          <div className={styles.empty}>{t("logSeverityEmpty")}</div>
        ) : (
          visibleEntries.map((entry) => (
            <article key={`${entry.lineNumber}-${entry.title}-${entry.timestamp}`} className={styles.entry}>
              <div className={styles.entryMeta}>
                <span>#{entry.lineNumber}</span>
                {entry.timestamp ? <time>{entry.timestamp}</time> : null}
                <span>{categoryLabel(entry.category, lang)}</span>
                {entry.actor ? <span>{entry.actor}</span> : null}
                <span className={levelClassName(entry.level)}>{entry.level}</span>
              </div>
              <div className={styles.entryBody}>
                <strong>{entry.title}</strong>
                <p>{entry.message}</p>
              </div>
              {entry.fields.length > 0 ? (
                <dl className={styles.fieldGrid}>
                  {entry.fields.map((field) => (
                    <div key={`${entry.lineNumber}-${field.key}`}>
                      <dt>{field.key}</dt>
                      <dd>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </article>
          ))
        )}
      </div>
    </section>
  );
}
