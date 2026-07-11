const styles = {
  surface: "grid min-h-[min(520px,calc(100dvh_-_96px))] place-items-center p-6",
  panel: [
    "w-[min(360px,100%)] rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass",
    "px-[18px] py-4 text-vui-fg-primary shadow-none backdrop-blur-md",
  ].join(" "),
  title: "block text-[var(--vui-font-chat)] font-bold leading-[1.35]",
  meta: "mt-1.5 block text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary",
} as const;

export default styles;
