const styles = {
  sectionSurface: "vui-routes-configproviderregistrypanel sectionSurface grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)] gap-3 overflow-hidden !border-0 !rounded-none !bg-transparent !shadow-none [&:has(>_.savePrompt)]:grid-rows-[auto_minmax(0,1fr)]",
  savePrompt:
    "vui-routes-configproviderregistrypanel savePrompt relative z-10 grid min-w-0 shrink-0 items-center gap-3 rounded-lg border border-[color-mix(in_srgb,var(--state-warning)_45%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_12%,var(--vui-surface-panel))] px-3 py-2.5 shadow-sm max-[720px]:grid-cols-1 [grid-template-columns:minmax(0,1fr)_auto]",
  savePromptCopy:
    "vui-routes-configproviderregistrypanel savePromptCopy grid min-w-0 gap-0.5 [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:text-[var(--state-warning)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-snug [&_span]:text-vui-fg-secondary [&_span]:[overflow-wrap:anywhere]",
  providerListSection:
    "vui-routes-configproviderregistrypanel providerListSection grid min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,1fr)] gap-1.5",
  providerListHeading:
    "vui-routes-configproviderregistrypanel providerListHeading m-0 px-0.5 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-wide text-vui-fg-tertiary",
  abnormalSection:
    "vui-routes-configproviderregistrypanel abnormalSection grid min-w-0 gap-1.5 border-t border-vui-border-hairline pt-2",
  abnormalToggle:
    "vui-routes-configproviderregistrypanel abnormalToggle !flex !h-auto !min-h-9 !w-full !items-center !justify-between gap-2 px-2 py-1.5 text-left [&_span]:grid [&_span]:min-w-0 [&_span]:gap-0.5 [&_small]:[font-size:10px] [&_small]:font-normal [&_small]:text-vui-fg-tertiary",
  registryWorkspace:
    "vui-routes-configproviderregistrypanel registryWorkspace h-full min-h-0 min-w-0 [--vui-workspace-sidebar:clamp(18rem,24vw,22rem)] [--vui-workspace-aside:clamp(18rem,24vw,22rem)] gap-2 overflow-hidden",
  providerRail: "vui-routes-configproviderregistrypanel providerRail grid h-full min-h-0 min-w-0 content-start gap-4 overflow-y-auto border-r border-vui-border-subtle pr-3",
  providerList: "vui-routes-configproviderregistrypanel providerList min-h-0 min-w-0 overflow-y-auto !border-0 !bg-transparent !backdrop-blur-none !p-0 [&>[data-vui=entity-list-item]]:!px-1 [&>[data-vui=entity-list-item]]:!py-0.5",
  providerRow:
    "vui-routes-configproviderregistrypanel providerRow min-w-0",
  providerButton:
    "vui-routes-configproviderregistrypanel providerButton !flex !h-auto !min-h-16 !w-full min-w-0 !flex-col !items-stretch !justify-center gap-2 !border-0 !bg-transparent !shadow-none px-2 py-2 text-left",
  providerIdentity: "vui-routes-configproviderregistrypanel providerIdentity grid min-w-0 gap-0.5",
  providerLabel:
    "vui-routes-configproviderregistrypanel providerLabel min-w-0 whitespace-normal break-words text-sm font-semibold leading-snug text-vui-fg-primary",
  providerMeta:
    "vui-routes-configproviderregistrypanel providerMeta min-w-0 whitespace-normal break-all [overflow-wrap:anywhere] [font-size:var(--vui-font-xs)] leading-snug text-vui-fg-tertiary",
  providerStatusRow:
    "vui-routes-configproviderregistrypanel providerStatusRow flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1",
  ellipsis: "vui-routes-configproviderregistrypanel ellipsis min-w-0 truncate",
  modelsColumn:
    "vui-routes-configproviderregistrypanel modelsColumn grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden [&:has(>_[data-feedback-phase])]:grid-rows-[auto_auto_minmax(0,1fr)]",
  inspectorPanel:
    "vui-routes-configproviderregistrypanel inspectorPanel grid min-h-0 min-w-0 max-h-[72vh] overflow-hidden",
  inspectorBody:
    "vui-routes-configproviderregistrypanel inspectorBody relative isolate z-0 grid min-h-0 min-w-0 content-start gap-3 overflow-y-auto overflow-x-hidden pr-0.5",
  inspectorAdvanced:
    "vui-routes-configproviderregistrypanel inspectorAdvanced relative isolate z-0 grid min-w-0 content-start gap-2 rounded-lg border border-vui-border-subtle bg-vui-surface-panel p-2",
  detailSurface: "vui-routes-configproviderregistrypanel detailSurface grid h-full min-h-0 min-w-0 [grid-template-rows:auto_auto_auto_auto_minmax(0,1fr)_auto_auto] gap-2 overflow-y-auto overflow-x-hidden pr-1",
  detailHeader:
    "vui-routes-configproviderregistrypanel detailHeader flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-vui-border-subtle pb-4",
  detailIdentity: "vui-routes-configproviderregistrypanel detailIdentity grid min-w-0 gap-0.5",
  setupChecklist:
    "vui-routes-configproviderregistrypanel setupChecklist relative isolate z-0 grid min-w-0 gap-1.5 rounded-md border border-vui-border-subtle !bg-vui-surface-panel px-2.5 py-2",
  setupChecklistItems:
    "vui-routes-configproviderregistrypanel setupChecklistItems flex min-w-0 flex-wrap items-center gap-2",
  setupChecklistItem:
    "vui-routes-configproviderregistrypanel setupChecklistItem inline-flex min-w-0 max-w-full items-center gap-1.5",
  setupChecklistNext:
    "vui-routes-configproviderregistrypanel setupChecklistNext m-0 min-w-0 [font-size:var(--vui-font-sm)] font-medium leading-snug text-vui-fg-primary [overflow-wrap:anywhere]",
  tabs: "vui-routes-configproviderregistrypanel tabs flex min-w-0 flex-wrap items-center gap-1",
  tabButton: "vui-routes-configproviderregistrypanel tabButton",
  detailBody:
    "vui-routes-configproviderregistrypanel detailBody min-h-0 min-w-0 overflow-hidden [&>_*]:h-full",
  tabSurface: "vui-routes-configproviderregistrypanel tabSurface grid h-full min-h-0 min-w-0 content-start gap-2 overflow-auto",
  connectionWorkspace:
    "vui-routes-configproviderregistrypanel connectionWorkspace relative isolate z-[1] grid min-h-0 min-w-0 content-start gap-3",
  connectionCard:
    "vui-routes-configproviderregistrypanel connectionCard grid min-w-0 gap-3 border-b border-vui-border-subtle py-4",
  connectionCardHeader:
    "vui-routes-configproviderregistrypanel connectionCardHeader flex min-w-0 flex-wrap items-start justify-between gap-2",
  connectionCardEyebrow:
    "vui-routes-configproviderregistrypanel connectionCardEyebrow m-0 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-wide text-vui-fg-tertiary",
  connectionCardTitle:
    "vui-routes-configproviderregistrypanel connectionCardTitle m-0 [font-size:var(--vui-font-sm)] font-bold text-vui-fg-primary",
  connectionCardBody:
    "vui-routes-configproviderregistrypanel connectionCardBody grid min-w-0 gap-2 justify-items-start [&>label]:w-full",
  inlineCredential:
    "vui-routes-configproviderregistrypanel inlineCredential grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-row/70 px-2.5 py-2",
  inlineCredentialField:
    "vui-routes-configproviderregistrypanel inlineCredentialField grid min-w-0 gap-1 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:font-semibold [&_span]:text-vui-fg-secondary",
  detailGrid:
    "vui-routes-configproviderregistrypanel detailGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  fact: "vui-routes-configproviderregistrypanel fact grid min-w-0 gap-0.5 rounded-md border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  factLabel: "vui-routes-configproviderregistrypanel factLabel [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary",
  factValue: "vui-routes-configproviderregistrypanel factValue min-w-0 truncate [font-size:var(--vui-font-sm)] font-semibold text-vui-fg-primary",
  deployment:
    "vui-routes-configproviderregistrypanel deployment grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-glass p-2",
  modelsWorkspace: "vui-routes-configproviderregistrypanel modelsWorkspace grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,1fr)] gap-2 overflow-hidden",
  modelChrome: "vui-routes-configproviderregistrypanel modelChrome grid min-w-0 gap-2",
  modelToolbar:
    "vui-routes-configproviderregistrypanel modelToolbar flex min-w-0 flex-wrap items-center justify-between gap-3",
  modelSearch: "vui-routes-configproviderregistrypanel modelSearch min-w-0 w-full max-w-80 flex-[1_1_14rem]",
  modelFilters: "vui-routes-configproviderregistrypanel modelFilters flex min-w-0 flex-wrap items-center justify-end gap-1",
  pinBanner:
    "vui-routes-configproviderregistrypanel pinBanner flex min-w-0 flex-wrap items-center justify-end gap-1.5",
  pinBannerActions:
    "vui-routes-configproviderregistrypanel pinBannerActions flex min-w-0 flex-wrap items-center justify-end gap-1.5",
  tableScroll:
    "vui-routes-configproviderregistrypanel tableScroll min-h-0 min-w-0 overflow-auto",
  table:
    "vui-routes-configproviderregistrypanel table w-full min-w-0 !border-0 !rounded-none [&_table]:w-full [&_table]:table-fixed [&_td]:whitespace-normal [&_td]:break-words [&_td]:!align-top [&_td]:!py-4 !overflow-visible [&_thead]:sticky [&_thead]:top-0 [&_thead]:z-10",
  verification: "grid min-w-0 gap-1 justify-items-start",
  verificationError: "text-xs text-[var(--state-error)]",
  verificationDetails: "cursor-pointer text-sm font-medium text-vui-fg-secondary",
  verificationMessage: "mt-2 max-w-full whitespace-pre-wrap break-words text-xs text-vui-fg-secondary [overflow-wrap:anywhere]",
  connectionAddress: "text-sm text-vui-fg-secondary break-words [overflow-wrap:anywhere]",
  modelName: "min-w-0 break-words [overflow-wrap:anywhere]",
  compactModelActions: "flex min-w-0 flex-wrap items-center gap-1",
  modelDetails: "grid min-w-0 gap-4",
  modelDetailSection: "grid min-w-0 gap-2 [&_h3]:font-semibold [&_h3]:text-vui-fg-secondary [&_strong]:whitespace-normal [&_strong]:break-all [&_span]:max-w-full [&_.ellipsis]:whitespace-normal [&_.ellipsis]:break-all",
  modelIdentity: "vui-routes-configproviderregistrypanel modelIdentity grid min-w-0 gap-0.5",
  modelActionState:
    "vui-routes-configproviderregistrypanel modelActionState inline-flex min-h-6 items-center rounded-full border border-vui-border-subtle bg-vui-surface-row/70 px-2 [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary",
  capabilityList: "vui-routes-configproviderregistrypanel capabilityList flex min-w-0 flex-wrap gap-1",
  capabilityHover: "vui-routes-configproviderregistrypanel capabilityHover inline-flex max-w-full",
  capabilityUnknown: "vui-routes-configproviderregistrypanel capabilityUnknown [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  actions: "vui-routes-configproviderregistrypanel actions flex min-w-0 flex-wrap items-center gap-1.5",
  actionFeedback:
    "vui-routes-configproviderregistrypanel actionFeedback sticky top-0 z-20 min-w-0 rounded-md border border-vui-border-subtle bg-vui-surface-panel px-2.5 py-2 [font-size:var(--vui-font-sm)] font-semibold text-vui-fg-primary [overflow-wrap:anywhere] shadow-sm",
  actionFeedbackSuccess:
    "vui-routes-configproviderregistrypanel actionFeedbackSuccess sticky top-0 z-20 min-w-0 rounded-md border border-[color-mix(in_srgb,var(--state-success)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_10%,var(--vui-surface-panel))] px-2.5 py-2 [font-size:var(--vui-font-sm)] font-semibold text-[var(--state-success)] [overflow-wrap:anywhere] shadow-sm",
  actionFeedbackError:
    "vui-routes-configproviderregistrypanel actionFeedbackError sticky top-0 z-20 min-w-0 rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-panel))] px-2.5 py-2 [font-size:var(--vui-font-sm)] font-semibold text-[var(--state-error)] [overflow-wrap:anywhere] shadow-sm",
  mergeSection:
    "vui-routes-configproviderregistrypanel mergeSection min-w-0 rounded-lg border border-vui-border-subtle bg-vui-surface-row/40 p-2",
  mergeContent: "vui-routes-configproviderregistrypanel mergeContent grid min-w-0 gap-2",
  mergeFacts:
    "vui-routes-configproviderregistrypanel mergeFacts flex min-w-0 flex-wrap items-center gap-2 [font-size:var(--vui-font-xs)] text-vui-fg-secondary",
  mergeConfirmation:
    "vui-routes-configproviderregistrypanel mergeConfirmation flex min-w-0 items-start gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-panel px-2 py-1.5 [font-size:var(--vui-font-sm)] text-vui-fg-secondary [&_input]:mt-0.5",
  dangerZone:
    "vui-routes-configproviderregistrypanel dangerZone flex min-w-0 items-center justify-between gap-3 border-t border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] pt-2",
  critical:
    "vui-routes-configproviderregistrypanel critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  muted: "vui-routes-configproviderregistrypanel muted [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
};

export default styles;
