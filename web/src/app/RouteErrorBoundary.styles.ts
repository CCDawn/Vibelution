const surfaceClass = [
  "grid min-h-screen place-items-center bg-[image:var(--vui-gradient-route-soft)] p-8 text-vui-fg-primary",
  "max-[640px]:p-[18px]",
].join(" ");
const panelClass = [
  "w-[min(560px,100%)] rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass p-5 shadow-none backdrop-blur-[14px]",
  "max-[640px]:p-[18px]",
].join(" ");
const kickerClass = "mb-2 mt-0 text-[var(--vui-font-sm)] font-bold text-vui-accent-cool";
const titleClass = "m-0 text-[1.28rem] leading-[1.25] max-[640px]:text-xl";
const detailClass = "mb-0 mt-3 text-[var(--vui-font-chat)] leading-[1.55] text-vui-fg-secondary";
const actionsClass = "mt-[18px] flex flex-wrap gap-2";
const actionButtonClass = "min-w-24";
const technicalClass = "mt-[18px] border-t border-vui-border-subtle pt-[14px]";
const technicalSummaryClass = "cursor-pointer text-[var(--vui-font-sm)] font-bold text-vui-fg-tertiary";
const technicalPreClass = "mt-2.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-[var(--radius-card)] border border-vui-border-subtle bg-[var(--surface-code)] p-3 text-[var(--vui-font-xs)] leading-[1.5] text-vui-fg-primary";

const styles = {
  surfaceClass,
  panelClass,
  kickerClass,
  titleClass,
  detailClass,
  actionsClass,
  actionButtonClass,
  technicalClass,
  technicalSummaryClass,
  technicalPreClass,
} as const;

export default styles;
