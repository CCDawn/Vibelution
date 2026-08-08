import { vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  // VSurface owns card chrome; keep layout hooks + neutralize shell double chrome.
  lifecycleProofCard:
    "vui-app-appshell lifecycleProofCard grid min-w-0 gap-2 !border-0 !bg-transparent !p-0 !shadow-none",
  lifecycleProofHeader:
    "vui-app-appshell lifecycleProofHeader min-w-0 [&_h4]:text-[var(--vui-font-sm)] [&_h4]:font-semibold",
  lifecycleProofItem: `vui-app-appshell lifecycleProofItem flex min-w-0 items-center justify-between gap-2 ${vuiOpaqueRowClass} p-2`,
  lifecycleProofList: "vui-app-appshell lifecycleProofList grid min-w-0 min-h-0 content-start gap-1.5 overflow-auto",
  lifecycleProofMeta: "vui-app-appshell lifecycleProofMeta min-w-0",
  lifecycleProofName:
    "vui-app-appshell lifecycleProofName min-w-0 truncate [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  statusGuideCard:
    "vui-app-appshell statusGuideCard grid min-w-0 gap-1.5 !border-0 !bg-transparent !p-0 !shadow-none",
  statusGuideCardHeader: "vui-app-appshell statusGuideCardHeader flex min-w-0 items-center gap-1.5",
  statusGuideGrid: "vui-app-appshell statusGuideGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  statusGuideHeader:
    "vui-app-appshell statusGuideHeader min-w-0 [&_h3]:text-[var(--vui-font-sm)] [&_h3]:font-semibold",
  statusGuideList: "vui-app-appshell statusGuideList grid min-w-0 min-h-0 content-start gap-1 overflow-auto",
  statusGuideListItem:
    "vui-app-appshell statusGuideListItem min-w-0 list-none rounded-[var(--radius-control)] p-0.5 data-[current=true]:ring-1 data-[current=true]:ring-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)]",
  statusGuidePanel:
    "vui-app-appshell statusGuidePanel grid min-w-0 gap-2.5 !border-0 !bg-transparent !p-0 !shadow-none",
  statusGuideStateChip: "vui-app-appshell statusGuideStateChip max-w-full truncate",
  codeFreshnessCard: `vui-app-appshell codeFreshnessCard grid min-w-0 gap-2 ${vuiOpaqueRowClass} p-2`,
  codeFreshnessMeta: "vui-app-appshell codeFreshnessMeta flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1",
  codeFreshnessCommit:
    "vui-app-appshell codeFreshnessCommit min-w-0 truncate font-mono text-[0.72rem] text-[var(--fg-secondary)]",
} as const;

export default styles;
