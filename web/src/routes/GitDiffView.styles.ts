const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const headerClass = "flex items-start justify-between gap-4 border-b border-vui-border-soft px-5 pb-3.5 pt-[18px]";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-1 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const fileNameClass = "m-0 font-[var(--font-display)] text-[1.28rem] text-vui-fg-primary";
const filePathClass = "m-0 mt-2 break-all leading-[1.4] text-vui-fg-secondary";
const summaryClass = "m-0 mt-2 break-all text-[var(--vui-font-xs)] leading-[1.4] text-vui-fg-tertiary";
const metaBlockClass = "flex flex-wrap justify-end gap-2";
const pillClass = "inline-flex min-h-7 items-center whitespace-nowrap rounded-full px-2.5 text-[var(--vui-font-xs)]";
const changedPillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]`;
const sourcePillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-vui-fg-secondary`;
const diffWrapClass = "min-h-0 overflow-auto bg-[var(--surface-code)]";
const diffTableClass = "w-max min-w-full py-2 font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.55]";
const diffRowClass = "grid min-w-full grid-cols-[54px_54px_24px_minmax(0,1fr)] pr-[18px]";
const columnHeaderClass = "sticky top-0 z-[2] border-b border-[var(--border-hairline,var(--border-soft))] bg-[var(--surface-panel-muted)] text-vui-fg-tertiary";
const lineNumberClass = "min-w-0 select-none py-px pr-2.5 text-right text-vui-fg-tertiary";
const lineMarkerClass = "min-w-0 select-none py-px text-center text-vui-fg-tertiary";
const lineContentClass = "block min-w-0 whitespace-pre py-px";
const footnoteClass = "m-0 border-t border-vui-border-soft px-5 pb-3.5 pt-2.5 text-[var(--vui-font-xs)] text-vui-fg-tertiary";

const styles = {
  surfaceClass,
  headerClass,
  headerCopyClass,
  eyebrowClass,
  fileNameClass,
  filePathClass,
  summaryClass,
  metaBlockClass,
  pillClass,
  changedPillClass,
  sourcePillClass,
  diffWrapClass,
  diffTableClass,
  diffRowClass,
  columnHeaderClass,
  lineNumberClass,
  lineMarkerClass,
  lineContentClass,
  footnoteClass,
} as const;

export default styles;
