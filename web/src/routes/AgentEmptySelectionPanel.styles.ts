const styles = {
  emptyState:
    "grid h-full min-h-[min(100%,280px)] [place-content:center] [place-items:center] [justify-items:center] [gap:8px] [padding:24px_16px] [border:1px_dashed_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--vui-surface-row)_42%,transparent)] [color:var(--fg-secondary)] [text-align:center] [&_svg]:[width:22px] [&_svg]:[height:22px] [&_svg]:[color:var(--accent-cool)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_p]:[margin:0] [&_p]:[max-width:42ch] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.34] [&_p]:[overflow-wrap:anywhere]",
} as const;

export default styles;
