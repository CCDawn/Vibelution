import {
  vuiFlatPanelClass,
} from "../../../../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionStageAgentHeader:
    "sourceCollectionStageAgentHeader mb-1.5 flex min-w-0 items-center [&>strong]:text-[var(--fg-primary)]",
  sourceCollectionStageAgentConfigLink:
    "shrink-0 text-[length:var(--vui-font-xs)] font-semibold text-[var(--accent-cool)] hover:underline",
  sourceCollectionStageAgentModel:
    "w-[44%] text-[var(--fg-secondary)]",
  sourceCollectionStageAgentModelContent:
    "flex min-w-0 items-center gap-1.5",
  sourceCollectionStageAgentModelValue:
    "min-w-0 flex-1 truncate",
  sourceCollectionStageAgentPanel:
    `sourceCollectionStageAgentPanel min-w-0 ${vuiFlatPanelClass} p-2 text-[var(--fg-primary)]`,
  sourceCollectionStageAgentRole:
    "w-[34%] font-semibold text-[var(--fg-primary)]",
  sourceCollectionStageAgentStatus:
    "w-[22%] whitespace-nowrap [&_[data-vui=status-chip]]:max-w-full",
  sourceCollectionStageAgentTable:
    "sourceCollectionStageAgentTable bg-transparent [&_tbody_tr]:h-11",
} as const;

export default styles;
