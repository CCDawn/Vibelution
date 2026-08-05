const styles = {
  statusDot:
    "vui-app-appshell statusDot block h-2 w-2 shrink-0 grow-0 self-center rounded-full border-0 bg-current p-0 leading-none",
  status_idle:
    "vui-app-appshell status_idle text-[color-mix(in_srgb,var(--fg-tertiary)_74%,transparent)]",
  topClock:
    "vui-app-appshell topClock min-w-0 flex shrink-0 items-center gap-1.5 whitespace-nowrap [font-size:var(--vui-font-xs)] leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
