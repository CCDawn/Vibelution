const styles = {
  rail:
    "grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,_1fr)] [gap:0] [overflow:hidden]",
  railHeader:
    "grid min-w-0 [gap:2px] [padding:8px_10px] [border-b:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [background:color-mix(in_srgb,_var(--vui-surface-row)_42%,_transparent)] [&_p]:[margin:0] [&_p]:[color:var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[letter-spacing:0.06em] [&_p]:[text-transform:uppercase] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem]",
  railBody:
    "grid min-h-0 min-w-0 [align-content:start] [gap:0] [overflow:auto] [overscroll-behavior:contain] [&_>_*]:[border-radius:0] [&_>_*]:[border-left:0] [&_>_*]:[border-right:0] [&_>_*+[data-vui-product],_&>_*+section]:[border-top:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)]",
  emptyRail:
    "grid h-full min-h-0 place-content-center place-items-center [gap:8px] [padding:16px] [border:1px_dashed_color-mix(in_srgb,_var(--vui-border-subtle)_80%,_transparent)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-row)_40%,_transparent)] [color:var(--fg-tertiary)] [text-align:center] [&_strong]:[color:var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
} as const;

export default styles;
