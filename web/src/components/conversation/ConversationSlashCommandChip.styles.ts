const scope = "vui-components-conversationslashcommandchip";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  // Skill tone rides the accent-cool state-tint family already used by the
  // slash suggestion builtin badge (accent + border/surface tokens, never a
  // surface+transparent wash).
  chipSkill: cv(
    "chipSkill",
    "inline-flex max-w-full min-w-0 items-center gap-1 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_var(--vui-alpha-line),var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_var(--vui-alpha-wash),var(--vui-surface-row))] px-1.5 py-0.5 align-middle text-vui-xs font-semibold leading-tight text-[var(--accent-cool)]",
  ),
  // Unknown slash tokens stay neutral: same geometry, no accent claim.
  chipUnknown: cv(
    "chipUnknown",
    "inline-flex max-w-full min-w-0 items-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-0.5 align-middle text-vui-xs font-semibold leading-tight text-[var(--fg-secondary)]",
  ),
  chipIcon: cv("chipIcon", "size-3.5 shrink-0"),
  chipCommand: cv("chipCommand", "min-w-0 truncate font-mono"),
} as const;

export default styles;
