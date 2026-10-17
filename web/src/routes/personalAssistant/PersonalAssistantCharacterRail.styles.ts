const styles = {
  root: "flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-[var(--vui-surface-panel)] text-[var(--fg-primary)]",
  header: "shrink-0 px-4 py-4 text-xs text-[var(--fg-secondary)]",
  portrait: "assistant-rail-character relative mt-3 h-[250px] min-h-0 shrink overflow-hidden",
  identity: "mt-2 text-center [&_h2]:text-base [&_h2]:font-medium",
  status: "mt-2 flex items-center justify-center gap-1.5 px-2 text-[11px] leading-5 text-[var(--fg-secondary)]",
  dot: "h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--vui-pet-accent)] [[data-tone=approval]_&]:bg-[var(--vui-pet-tone-approval)] [[data-tone=error]_&]:bg-[var(--vui-pet-tone-error)]",
  unread: "mx-2 mt-3 text-xs",
  line: "mx-auto mt-5 max-w-[130px] px-1 text-center text-[11px] leading-6 text-[var(--fg-secondary)]",
  actions: "mt-auto flex shrink-0 flex-col gap-1 px-3 pb-3 pt-4 [&_button]:text-xs",
  desktop: "w-full",
  settings: "flex flex-col items-start gap-4 py-2 text-sm",
} as const;
export default styles;
