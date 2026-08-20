export default {
  root: "grid gap-1",
  note: "[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  details: "grid gap-2 rounded border border-[var(--vui-border-subtle)] px-2 py-1.5 [font-size:var(--vui-font-2xs)]",
  stages: "m-0 list-none space-y-1 p-0 text-[var(--fg-secondary)]",
  anomaly: "rounded border border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] px-2 py-1.5 [font-size:var(--vui-font-2xs)] text-[var(--state-warning)]",
} as const;
