/**
 * Streaming live-tail render budget hints (StreamingLiveMarkdownBlocks). The
 * live tail re-renders every streaming frame — an unclosed fence holds its
 * whole block in the live tail — so oversized live blocks cap what they paint
 * and announce the inflow with a static, non-interactive line. Settled
 * messages switch to the full renderer with the details-expand budget.
 */
const styles = {
  liveCodeInflowHint:
    "vui-components-conversationview liveMarkdownCodeInflowHint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  liveTableInflowHint:
    "vui-components-conversationview liveMarkdownTableInflowHint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
