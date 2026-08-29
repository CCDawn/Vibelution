const root = "shrink-0";
const trigger = "max-w-[15rem] gap-1.5";
const triggerState = "truncate text-[var(--fg-tertiary)]";
const panel = "grid w-[20rem] max-w-[calc(100vw-2rem)] gap-3 p-3";
const header = "grid min-w-0 gap-1";
const title = "m-0 text-sm font-semibold text-[var(--fg-primary)]";
const description = "m-0 text-xs leading-relaxed text-[var(--fg-tertiary)]";
const usage = "m-0 text-xs text-[var(--fg-secondary)]";
const presetList = "grid gap-1.5";
const presetButton = "w-full !justify-between px-2.5 py-2 text-left";
const presetCopy = "grid min-w-0 flex-1 gap-0.5 text-left";
const presetLabel = "text-sm font-semibold text-[var(--fg-primary)]";
const presetMeta = "text-xs font-normal text-[var(--fg-tertiary)]";
const presetCheck = "shrink-0 text-[var(--accent-cool)]";
const toggle = "border-t border-[var(--vui-border-subtle)] pt-2.5";
const feedback = "m-0 text-xs text-[var(--fg-secondary)]";

export default {
  root,
  trigger,
  triggerState,
  panel,
  header,
  title,
  description,
  usage,
  presetList,
  presetButton,
  presetCopy,
  presetLabel,
  presetMeta,
  presetCheck,
  toggle,
  feedback,
} as const;
