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

const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_1fr] bg-[var(--surface-panel)]";
const toolbarClass = "flex items-center justify-between gap-3 border-b border-vui-border-soft px-3 py-2.5";
const summaryClass = "inline-flex min-w-max items-center gap-2 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const summaryCountClass = "font-[var(--font-mono)] text-vui-fg-primary";
const filterGroupClass = "flex flex-wrap justify-end gap-1.5";
const filterButtonClass = "min-h-7 border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_88%,transparent)] px-2 py-1 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const filterButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--surface-raised))] text-vui-fg-primary";
const filterCountClass = "font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const listClass = "min-h-0 overflow-auto p-2.5";
const entryClass = "mt-2 grid gap-2 border-b border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_92%,var(--surface-raised))] px-[11px] py-2.5 first:mt-0";
const entryMetaClass = "flex flex-wrap items-center gap-1.5 font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const levelPillClass = "inline-flex items-center rounded-full border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_78%,transparent)] px-1.5 py-0.5 text-vui-fg-tertiary";
const levelErrorClass = "border-[color-mix(in_srgb,var(--state-error)_28%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)] text-[var(--state-error)]";
const levelWarningClass = "border-[color-mix(in_srgb,var(--state-warning)_28%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]";
const entryBodyClass = "grid min-w-0 gap-1";
const entryTitleClass = "break-words font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-primary";
const entryMessageClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-vui-fg-secondary";
const fieldGridClass = "m-0 grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-1.5";
const fieldItemClass = "min-w-0 rounded-md border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-base)_62%,transparent)] px-[7px] py-1.5";
const fieldKeyClass = "font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const fieldValueClass = "m-0 mt-[3px] whitespace-pre-wrap break-words font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.42] text-vui-fg-secondary";
const emptyClass = "grid min-h-[180px] place-items-center rounded-lg border border-dashed border-vui-border-soft text-vui-fg-tertiary";

function levelClassName(level: string) {
  if (level === "error") {
    return `${levelPillClass} ${levelErrorClass}`;
  }
  if (level === "warning") {
    return `${levelPillClass} ${levelWarningClass}`;
  }
  return levelPillClass;
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
    <section className={surfaceClass}>
      <div className={toolbarClass}>
        <div className={summaryClass}>
          <Bot size={16} />
          <span>{lang === "zh" ? "结构化日志" : "Structured log"}</span>
          <strong className={summaryCountClass}>
            {model.parseableLineCount}/{model.totalLineCount}
          </strong>
        </div>
        <div className={filterGroupClass} role="group" aria-label={lang === "zh" ? "日志内容筛选" : "Log content filter"}>
          {categoryOptions.map((option) => {
            const Icon = option.icon;
            const active = categoryFilter === option.value;
            return (
              <VButton
                key={option.value}
                type="button"
                className={active ? `${filterButtonClass} ${filterButtonActiveClass}` : filterButtonClass}
                onPress={() => setCategoryFilter(option.value)}
                title={lang === "zh" ? option.zh : option.en}
                icon={<Icon size={14} />}
              >
                <span>{lang === "zh" ? option.zh : option.en}</span>
                <strong className={filterCountClass}>{categoryCounts[option.value]}</strong>
              </VButton>
            );
          })}
        </div>
      </div>

      <div className={listClass}>
        {visibleEntries.length === 0 ? (
          <div className={emptyClass}>{t("logSeverityEmpty")}</div>
        ) : (
          visibleEntries.map((entry) => (
            <article key={`${entry.lineNumber}-${entry.title}-${entry.timestamp}`} className={entryClass}>
              <div className={entryMetaClass}>
                <span>#{entry.lineNumber}</span>
                {entry.timestamp ? <time>{entry.timestamp}</time> : null}
                <span>{categoryLabel(entry.category, lang)}</span>
                {entry.actor ? <span>{entry.actor}</span> : null}
                <span className={levelClassName(entry.level)}>{entry.level}</span>
              </div>
              <div className={entryBodyClass}>
                <strong className={entryTitleClass}>{entry.title}</strong>
                <p className={entryMessageClass}>{entry.message}</p>
              </div>
              {entry.fields.length > 0 ? (
                <dl className={fieldGridClass}>
                  {entry.fields.map((field) => (
                    <div key={`${entry.lineNumber}-${field.key}`} className={fieldItemClass}>
                      <dt className={fieldKeyClass}>{field.key}</dt>
                      <dd className={fieldValueClass}>{field.value}</dd>
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
