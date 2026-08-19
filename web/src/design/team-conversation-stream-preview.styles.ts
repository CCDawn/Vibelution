import { vuiGlassPanelClass } from "./vuiSurfaceRecipes";

export const teamConversationStreamPreviewStyles = {
  page: "tcs-page",
  header: "tcs-header",
  eyebrow: "tcs-eyebrow",
  subtitle: "tcs-subtitle",
  scenes: "tcs-scenes",
  layout: "tcs-layout",
  column: "tcs-column",
  columnLabel: "tcs-column-label",
  frame: "tcs-frame",
  frameHeader: "tcs-frame-header",
  frameTitle: "tcs-frame-title",
  frameMeta: "tcs-frame-meta",
  timeline: "tcs-timeline",
  topic: "tcs-topic",
  topicAuthor: "tcs-topic-author",
  note: "tcs-note",
  roundHairline:
    "vui-design-team-conversation-stream roundHairline flex min-w-0 items-center gap-2 py-2 text-[10px] font-semibold tracking-wide text-[var(--fg-tertiary)] before:h-px before:flex-1 before:bg-[var(--vui-border-subtle)] after:h-px after:flex-1 after:bg-[var(--vui-border-subtle)]",
  streamList: "vui-design-team-conversation-stream streamList grid min-w-0 content-start gap-0",
  streamCluster: "vui-design-team-conversation-stream streamCluster grid min-w-0 content-start gap-1 pt-4 first:pt-0",
  streamRow:
    "vui-design-team-conversation-stream streamRow min-w-0 !grid grid-cols-[36px_minmax(0,1fr)] items-start gap-2.5 border-0 bg-transparent p-0 shadow-none",
  streamAvatar:
    "vui-design-team-conversation-stream streamAvatar inline-grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[11px] font-semibold text-[var(--fg-secondary)]",
  streamAvatarSpacer: "vui-design-team-conversation-stream streamAvatarSpacer h-9 w-9 shrink-0",
  streamCopy: "vui-design-team-conversation-stream streamCopy grid min-w-0 content-start gap-0.5",
  streamHeader: "vui-design-team-conversation-stream streamHeader flex min-w-0 flex-wrap items-baseline gap-1.5",
  streamName: "vui-design-team-conversation-stream streamName [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  streamRole: "vui-design-team-conversation-stream streamRole text-[10px] font-medium leading-tight text-[var(--fg-tertiary)]",
  streamTime: "vui-design-team-conversation-stream streamTime text-[10px] leading-tight text-[var(--fg-tertiary)]",
  streamBody:
    "vui-design-team-conversation-stream streamBody m-0 min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  streamBodyClamp:
    "vui-design-team-conversation-stream streamBodyClamp m-0 min-w-0 overflow-hidden [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere] [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:8]",
  streamToggle: "vui-design-team-conversation-stream streamToggle mt-0.5 !h-auto !min-h-0 !justify-start !border-0 !bg-transparent !p-0 !text-[11px] !font-semibold !text-[var(--accent-cool)] !shadow-none hover:!bg-transparent",
  processDisclosure:
    "vui-design-team-conversation-stream processDisclosure mt-1 min-w-0 text-[11px] leading-snug text-[var(--fg-tertiary)] [&_summary]:cursor-pointer [&_summary]:list-none [&_summary]:font-medium [&_summary::-webkit-details-marker]:hidden",
  processDetail: "vui-design-team-conversation-stream processDetail m-0 mt-1 text-[11px] leading-snug text-[var(--fg-tertiary)]",
  pendingLine: "vui-design-team-conversation-stream pendingLine m-0 text-[11px] text-[var(--fg-tertiary)]",
  digest: `vui-design-team-conversation-stream digest min-w-0 ${vuiGlassPanelClass} mt-3 grid gap-1.5 p-2`,
  digestTitle: "vui-design-team-conversation-stream digestTitle m-0 text-[11px] font-semibold text-[var(--fg-primary)]",
  digestList: "vui-design-team-conversation-stream digestList m-0 grid list-disc gap-1 pl-4 text-[12px] leading-snug text-[var(--fg-secondary)]",
} as const;
