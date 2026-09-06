import { useState } from "react";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { summarizeErrorText, VEmptyState, VErrorSummary, VPanelHeader, VStringSelect, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { buildResearchTimelineGroups, filterResearchTimelineGroups, type ResearchTimelineFilter } from "./researchWorkflowTimelineModel";
import { ResearchWorkflowInsightsPanel } from "./ResearchWorkflowInsightsPanel";
import { ResearchCriticalPathPanel } from "./ResearchCriticalPathPanel";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { RUN_TIMELINE_TERM } from "./researchTerminology";
import styles from "./ResearchRunTimeline.styles";

export function ResearchRunTimeline(props: {
  run: WorkflowRunRecord | null;
  projection: WorkflowCanvasProjection | null;
  insights: ResearchWorkflowInsights;
  selectedNodeId?: string | null;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const [filter, setFilter] = useState<ResearchTimelineFilter>("attention");
  const allGroups = buildResearchTimelineGroups(
    (props.run?.events ?? []) as WorkflowEventEnvelope[],
    {
      nodeRuns: props.projection?.run.nodeRuns,
      blockedReason: props.projection?.run.blockedReason ?? props.run?.blockedReason,
    },
  );
  const effectiveFilter = filter === "selected" && !props.selectedNodeId ? "all" : filter;
  const groups = filterResearchTimelineGroups(allGroups, effectiveFilter, props.selectedNodeId);
  const filterOptions = [
    { value: "attention", label: isZh ? "仅异常与待处理" : "Errors and pending actions" },
    { value: "selected", label: isZh ? "所选节点" : "Selected node", disabled: !props.selectedNodeId },
    { value: "all", label: isZh ? "全部事件" : "All events" },
  ];
  return (
    <div className={styles.root}>
      <VSurface tone="panel" className={styles.surface}>
        <VPanelHeader title={isZh ? RUN_TIMELINE_TERM.zh : RUN_TIMELINE_TERM.en} headingLevel={3} />
        <VStringSelect
          ariaLabel={isZh ? "筛选运行事件" : "Filter run events"}
          className="max-w-max"
          value={effectiveFilter}
          options={filterOptions}
          onValueChange={(value) => setFilter(value as ResearchTimelineFilter)}
        />
        {groups.length ? (
          <ol className={styles.groups}>
            {groups.map((group) => (
              <li key={group.key}>
                <h4 className={styles.groupTitle}>{group.title}</h4>
                <ul className={styles.items}>
                  {group.items.map((item) => (
                    <li key={item.key} className={styles.item} data-event-tone={item.tone}>
                      {item.details ? (
                        <VErrorSummary
                          tone={item.tone}
                          label={isZh ? "事件详情" : "Event details"}
                          summary={summarizeErrorText(item.label, 48).summary}
                          details={`${item.label}\n\n${item.details}`}
                          openLabel={isZh ? "展开" : "Details"}
                          closeLabel={isZh ? "收起" : "Hide"}
                          defaultOpen={false}
                        />
                      ) : <span>{item.label}</span>}
                      {item.status ? <span className={styles.status}>{item.status}</span> : null}
                      <time className={styles.status} dateTime={item.occurredAt || undefined}>
                        {item.occurredAt ? new Date(item.occurredAt).toLocaleString(isZh ? "zh-CN" : "en-US", { hour12: false }) : (isZh ? "当前状态快照 · 无事件时间" : "Current snapshot · no event time")}
                      </time>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ) : (
          <VEmptyState title={allGroups.length
            ? (isZh ? "没有符合筛选条件的事件" : "No matching events")
            : (isZh ? "暂无运行事件" : "No run events yet")} className={styles.empty} />
        )}
      </VSurface>
      <ResearchCriticalPathPanel projection={props.projection} insights={props.insights} lang={lang} />
      <ResearchWorkflowInsightsPanel insights={props.insights} lang={lang} />
    </div>
  );
}
