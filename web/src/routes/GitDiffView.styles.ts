const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-panel/82";
const headerClass = "flex items-start justify-between gap-3 border-b border-vui-border-hairline px-3.5 pb-2.5 pt-3 max-[640px]:flex-wrap";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-1 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const fileNameClass = "m-0 truncate font-[var(--font-display)] text-[1.02rem] leading-tight text-vui-fg-primary";
const filePathClass = "m-0 mt-1 break-all [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const summaryClass = "m-0 mt-1 break-all [font-size:var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary";
const metaBlockClass = "flex flex-wrap justify-end gap-1.5 max-[640px]:justify-start";
const pillClass = "inline-flex min-h-6 items-center whitespace-nowrap rounded-full px-2 [font-size:var(--vui-font-xs)]";
const changedPillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]`;
const sourcePillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-vui-fg-secondary`;
const diffWrapClass = "min-h-0 overflow-auto bg-[var(--surface-code)]";
const diffTableClass = "w-max min-w-full py-1.5 font-[var(--font-mono)] [font-size:var(--vui-font-xs)] leading-[1.42]";
const diffRowClass = "grid min-w-full grid-cols-[46px_46px_20px_minmax(0,1fr)] pr-3";
const columnHeaderClass = "sticky top-0 z-[2] border-b border-vui-border-hairline bg-vui-surface-toolbar text-vui-fg-tertiary";
const lineNumberClass = "min-w-0 select-none py-px pr-2 text-right text-vui-fg-tertiary";
const lineMarkerClass = "min-w-0 select-none py-px text-center text-vui-fg-tertiary";
const lineContentClass = "block min-w-0 whitespace-pre py-px";
const footnoteClass = "m-0 border-t border-vui-border-hairline px-3.5 pb-2.5 pt-2 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary";

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
