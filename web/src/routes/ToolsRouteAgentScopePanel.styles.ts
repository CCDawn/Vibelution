const styles = {
  agentScopeBar: "flex shrink-0 min-w-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-vui-border-subtle bg-transparent px-5 py-3 max-[640px]:px-4",
  scopeSelect: "flex min-w-0 items-center gap-2 text-vui-2xs text-vui-fg-tertiary [&>span:first-child]:shrink-0 [&>span:first-child]:whitespace-nowrap [&_[data-vui=select-shell]]:!w-[250px] [&_[data-vui=select-shell]]:shrink-0 max-[640px]:[&_[data-vui=select-shell]]:!w-[230px] [&:nth-child(2)_[data-vui=select-shell]]:!w-[128px] max-[760px]:[&_[data-vui=select]]:min-h-11",
  scopeStats: "shrink-0",
  scopeHintContent: "grid gap-2",
  deepLinkNotice: "m-0 basis-full min-w-0 break-words text-vui-2xs leading-relaxed text-vui-fg-secondary",
} as const;
export default styles;
