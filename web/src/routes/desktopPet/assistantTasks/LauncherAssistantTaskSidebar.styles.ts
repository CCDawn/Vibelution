const styles={
 root:"flex h-full min-h-0 min-w-0 flex-col gap-2",
 tabs:"min-w-0 !gap-0",
 tabList:"!flex w-full !flex-nowrap !gap-0 !p-0.5",
 tab:"min-w-0 flex-1 !px-0.5 !text-[12px] whitespace-nowrap",
 list:"grid min-h-0 min-w-0 flex-1 content-start gap-0.5 overflow-y-auto overscroll-contain pb-3 pr-0.5",
 emptyList:"hidden",
 row:"flex min-w-0 items-center gap-0.5 [&>button:first-child]:min-w-0 [&>button:first-child]:flex-1",
 remove:"shrink-0",
 empty:"px-2 py-3 text-center text-[12px] text-vui-fg-tertiary",
 notice:"grid min-w-0 gap-1 px-2 text-[12px] leading-relaxed text-vui-fg-secondary",
};export default styles;
