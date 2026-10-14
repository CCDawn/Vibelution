const styles = {
  identityField:
    "identityField grid min-w-0 gap-1 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  identitySelect:
    "identitySelect min-w-0 w-full font-normal",
  notice:
    "notice grid min-w-0 content-start gap-3",
  noticeText:
    "noticeText m-0 min-w-0 whitespace-pre-wrap break-words [font-size:var(--vui-font-sm)] font-normal leading-relaxed text-[var(--fg-primary)]",
  readerList:
    "readerList flex min-w-0 flex-wrap gap-2",
} as const;

export default styles;
