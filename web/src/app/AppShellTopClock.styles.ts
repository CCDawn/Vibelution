const styles = {
  statusDot:
    "vui-app-appshell statusDot inline-block h-2 w-2 shrink-0 rounded-full border border-[color-mix(in_srgb,currentColor_38%,transparent)] bg-current p-0 align-middle",
  status_idle:
    "vui-app-appshell status_idle text-[color-mix(in_srgb,var(--fg-tertiary)_74%,transparent)]",
  topClock:
    "vui-app-appshell topClock min-w-0 flex shrink-0 items-center gap-1.5 whitespace-nowrap [font-size:var(--vui-font-xs)] leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
