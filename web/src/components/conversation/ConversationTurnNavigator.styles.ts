const styles = {
  turnNavigatorRail:
    "vui-components-conversationview turnNavigatorRail absolute left-3 top-1/2 z-10 hidden h-[70%] max-h-[360px] w-9 -translate-y-1/2 @min-[864px]/conversation:block",
  turnNavigatorScroll:
    "h-full overflow-y-auto overflow-x-hidden overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
  turnNavigatorDot:
    "vui-components-conversationview turnNavigatorDot flex h-[18px] w-9 items-center justify-start rounded-sm border-0 bg-transparent p-0 text-[var(--fg-tertiary)] shadow-none focus-visible:ring-inset",
  turnNavigatorDotActive:
    "vui-components-conversationview turnNavigatorDotActive text-[var(--fg-primary)]",
  turnNavigatorDotMark:
    "vui-components-conversationview turnNavigatorDotMark pointer-events-none block h-0.5 w-3 origin-left rounded-full bg-current transition-[transform,opacity] duration-150 motion-reduce:transition-none",
  turnNavigatorHoverBody:
    "vui-components-conversationview turnNavigatorHoverBody grid w-[276px] min-w-0 max-w-full gap-1.5",
  turnNavigatorHoverUser:
    "vui-components-conversationview turnNavigatorHoverUser m-0 min-w-0 text-vui-xs font-medium leading-[var(--vui-line-readable)] text-[var(--fg-primary)] line-clamp-2",
  turnNavigatorHoverAssistant:
    "vui-components-conversationview turnNavigatorHoverAssistant m-0 min-w-0 text-vui-xs leading-[var(--vui-line-readable)] text-[var(--fg-tertiary)] line-clamp-3",
} as const;
export default styles;
