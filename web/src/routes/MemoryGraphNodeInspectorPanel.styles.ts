const styles = {
  detailHeader:
    "detailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  detailMeta:
    "detailMeta min-w-0 flex flex-wrap items-center gap-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  detailPanel:
    "detailPanel min-w-0 min-h-0 overflow-auto rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  emptyDetail:
    "emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  graphKnowledgeContent:
    "graphKnowledgeContent min-w-0 whitespace-pre-wrap break-words [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  graphKnowledgeItem:
    "graphKnowledgeItem min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 line-clamp-3",
  graphKnowledgeList:
    "graphKnowledgeList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  graphKnowledgePanel:
    "graphKnowledgePanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  graphRelationEmpty:
    "graphRelationEmpty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  graphRelationGroup:
    "graphRelationGroup min-w-0 [&_button]:w-full",
  graphRelationHeader:
    "graphRelationHeader min-w-0 flex flex-wrap items-center gap-1.5",
  graphRelationPanel:
    "graphRelationPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  graphResponsibilityPanel:
    "graphResponsibilityPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  rawPanel:
    "rawPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 [&_pre]:whitespace-pre-wrap [&_pre]:break-words",
  selectedConfigSummary:
    "selectedConfigSummary min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[var(--vui-surface-row)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] p-2 text-[var(--accent-cool)]",
} as const;

export default styles;
