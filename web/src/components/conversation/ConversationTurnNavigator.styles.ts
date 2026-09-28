const styles = {
  // Right-edge vertical rail inside the timeline area. It sits in the
  // timeline's existing right padding band (pr-[clamp(3rem,3vw,3.5rem)]), so
  // no layout change is needed; z-10 keeps it under the back-to-bottom button
  // (z-20) and the selection menu (z-30).
  turnNavigatorRail:
    "vui-components-conversationview turnNavigatorRail absolute right-1 top-1/2 z-10 flex max-h-[70%] w-10 min-w-10 -translate-y-1/2 flex-col items-center justify-center gap-0.5 overflow-visible",
  turnNavigatorDot:
    "vui-components-conversationview turnNavigatorDot !flex !h-4 !min-h-4 !w-4 !min-w-4 shrink-0 !items-center !justify-center !rounded-full !border-0 !bg-transparent !p-0 !shadow-none text-[var(--fg-tertiary)] transition-colors duration-150 hover:!bg-transparent hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_var(--vui-alpha-line),transparent)]",
  turnNavigatorDotActive:
    "vui-components-conversationview turnNavigatorDotActive !text-[var(--accent-cool)]",
  turnNavigatorDotMark:
    "vui-components-conversationview turnNavigatorDotMark block size-1.5 rounded-full bg-current opacity-60",
} as const;

export default styles;
