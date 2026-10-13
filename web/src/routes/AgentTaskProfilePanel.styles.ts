const styles = {
  advancedBody: "grid min-w-0 gap-4 pt-4",
  advancedDetails: "min-w-0 border-t border-vui-border-subtle pt-3 [&>summary]:cursor-pointer [&>summary]:text-sm [&>summary]:text-vui-fg-secondary [&>summary]:select-none",
  fieldSection: "grid min-w-0 gap-4 [&>h3]:m-0 [&>h3]:text-[15px] [&>h3]:font-semibold",
  pendingStatus: "text-sm text-[var(--accent-warm-2)]",
  savedStatus: "text-sm text-vui-fg-secondary",
  textarea: "!h-auto !min-h-24 !py-2.5 !leading-6 max-sm:!h-auto max-sm:!min-h-24",
} as const;

export default styles;
