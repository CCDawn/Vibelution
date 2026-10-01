const styles = {
  root: "flex h-full flex-col gap-1 border-r border-vui-border-subtle bg-vui-surface-workspace p-3 max-[700px]:flex-row max-[700px]:overflow-auto max-[700px]:border-b max-[700px]:border-r-0 max-[700px]:p-2",
  project: "mb-5 px-3 pt-2 max-[700px]:hidden",
  projectLabel: "m-0 text-vui-xs text-vui-fg-tertiary",
  projectName: "mb-0 mt-2 flex items-center gap-2 text-vui-sm font-semibold",
  runningCount: "mb-3 px-3 text-vui-xs text-vui-fg-tertiary max-[700px]:hidden",
  settingsItem: "mt-auto max-[700px]:mt-0",
  link: "flex min-h-10 w-full items-center gap-3 rounded-md px-3 text-vui-sm font-medium max-[700px]:min-h-11",
  selectedLink: "bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool)]",
  idleLink: "text-vui-fg-secondary hover:bg-vui-surface-row-hover",
} as const;

export default styles;
