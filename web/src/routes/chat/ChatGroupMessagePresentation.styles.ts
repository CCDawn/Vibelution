import {
  vuiStateCoolInfoClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  agentMention:
    `vui-routes-chatcodingroute agentMention min-w-0 ${vuiStateCoolInfoClass}`,
  groupBubbleBody:
    "vui-routes-chatcodingroute groupBubbleBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  groupBubbleBodyCollapsed:
    "vui-routes-chatcodingroute groupBubbleBodyCollapsed min-w-0 overflow-hidden [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere] [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:8]",
  groupBubbleToggle: "vui-routes-chatcodingroute groupBubbleToggle min-w-0",
  structuredMessage:
    "vui-routes-chatcodingroute structuredMessage grid min-w-0 gap-3 border-0 bg-transparent p-0 shadow-none",
  structuredConclusion:
    "vui-routes-chatcodingroute structuredConclusion m-0 min-w-0 [font-size:var(--vui-font-md)] font-semibold leading-[var(--vui-line-readable)] text-[var(--fg-primary)] [overflow-wrap:anywhere]",
  structuredSections: "vui-routes-chatcodingroute structuredSections grid min-w-0 gap-2.5",
  structuredSection: "vui-routes-chatcodingroute structuredSection grid min-w-0 gap-1.5",
  structuredSectionTitle:
    "vui-routes-chatcodingroute structuredSectionTitle m-0 min-w-0 [font-size:var(--vui-font-sm)] font-semibold leading-[var(--vui-line-readable)] text-[var(--fg-primary)] [overflow-wrap:anywhere]",
  structuredList:
    "vui-routes-chatcodingroute structuredList m-0 grid min-w-0 gap-1 pl-5 [font-size:var(--vui-font-md)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_li]:min-w-0 [&_li]:[overflow-wrap:anywhere]",
  protocolGrid: "vui-routes-chatcodingroute protocolGrid grid min-w-0 gap-2 xl:grid-cols-2",
  protocolCard:
    "vui-routes-chatcodingroute protocolCard grid min-w-0 content-start gap-2 border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)]",
  protocolCardTitle:
    "vui-routes-chatcodingroute protocolCardTitle m-0 min-w-0 [font-size:var(--vui-font-sm)] font-semibold leading-[var(--vui-line-readable)] text-[var(--fg-primary)]",
  protocolCardList:
    "vui-routes-chatcodingroute protocolCardList m-0 grid min-w-0 gap-1.5 pl-5 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_li]:min-w-0 [&_li]:[overflow-wrap:anywhere]",
  disagreementList: "vui-routes-chatcodingroute disagreementList grid min-w-0 gap-2",
  disagreementItem:
    "vui-routes-chatcodingroute disagreementItem grid min-w-0 gap-1 border-l-2 border-[var(--state-warning)] pl-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  disagreementIssue:
    "vui-routes-chatcodingroute disagreementIssue min-w-0 font-semibold text-[var(--fg-primary)] [overflow-wrap:anywhere]",
  evidenceList: "vui-routes-chatcodingroute evidenceList grid min-w-0 gap-2",
  evidenceItem:
    "vui-routes-chatcodingroute evidenceItem grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  evidenceRationale:
    "vui-routes-chatcodingroute evidenceRationale m-0 min-w-0 [font-size:var(--vui-font-md)] font-semibold leading-[var(--vui-line-readable)] text-[var(--fg-primary)] [overflow-wrap:anywhere]",
  evidenceFields:
    "vui-routes-chatcodingroute evidenceFields m-0 grid min-w-0 gap-1 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)]",
  evidenceField:
    "vui-routes-chatcodingroute evidenceField grid min-w-0 grid-cols-[6.5rem_minmax(0,1fr)] gap-2 max-[760px]:grid-cols-1 max-[760px]:gap-0.5",
  evidenceLabel: "vui-routes-chatcodingroute evidenceLabel font-semibold text-[var(--fg-tertiary)]",
  evidenceValue:
    "vui-routes-chatcodingroute evidenceValue m-0 min-w-0 text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  protocolDisclosure: "vui-routes-chatcodingroute protocolDisclosure grid min-w-0 justify-items-start gap-1.5",
  rawProtocol:
    "vui-routes-chatcodingroute rawProtocol m-0 max-h-72 w-full min-w-0 overflow-auto whitespace-pre-wrap rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] p-2 font-[family-name:var(--font-mono)] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
} as const;

export default styles;
