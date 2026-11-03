const styles = {
  root:
    "min-h-0 min-w-0 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable] " +
    "[--vui-scrollbar-thumb:transparent] " +
    "data-[scroll-active=true]:[--vui-scrollbar-thumb:color-mix(in_srgb,var(--fg-secondary)_28%,transparent)] " +
    // Important overrides the unlayered native scrollbar reset in base.css.
    "[&::-webkit-scrollbar]:!w-[6px] [&::-webkit-scrollbar-track]:!bg-transparent " +
    "[&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:!bg-[var(--vui-scrollbar-thumb)] " +
    // Native Chromium thumb drags can bypass DOM pointer events entirely.
    "[&::-webkit-scrollbar-thumb:active]:!bg-[color-mix(in_srgb,var(--fg-secondary)_28%,transparent)] " +
    "[&::-webkit-scrollbar-thumb]:transition-colors [&::-webkit-scrollbar-thumb]:duration-150 " +
    "[&::-webkit-scrollbar-button]:!hidden [&::-webkit-scrollbar-button]:!h-0 [&::-webkit-scrollbar-button]:!w-0 " +
    "[&::-webkit-scrollbar-corner]:!bg-transparent " +
    // Chromium's standard scrollbar-width would bypass the 6px WebKit styling.
    "[@supports_not_selector(::-webkit-scrollbar)]:[scrollbar-width:thin] " +
    "[@supports_not_selector(::-webkit-scrollbar)]:[scrollbar-color:var(--vui-scrollbar-thumb)_transparent] " +
    "motion-reduce:[&::-webkit-scrollbar-thumb]:transition-none",
} as const;

export default styles;
