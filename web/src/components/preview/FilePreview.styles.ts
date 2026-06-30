const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_1fr_auto]";
const headerClass = "flex items-start justify-between gap-4 border-b border-vui-border-soft px-5 pb-3.5 pt-[18px]";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-1 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const fileNameClass = "m-0 font-[var(--font-body)] text-[1.02rem] font-bold text-vui-fg-primary";
const filePathClass = "m-0 mt-2 break-all text-vui-fg-secondary";
const metaBlockClass = "flex flex-wrap justify-end gap-2";
const pillClass = "inline-flex items-center rounded-[var(--radius-control)] px-2.5 py-1.5 text-[var(--vui-font-xs)]";
const changedPillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]`;
const sourcePillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-vui-fg-secondary`;
const previewModeGroupClass = "inline-flex items-center gap-1 rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_72%,transparent)] p-[3px]";
const previewModeButtonClass = "min-h-[26px] border-0 bg-transparent px-2 py-[3px] text-[var(--vui-font-xs)] font-[inherit] text-vui-fg-secondary shadow-none";
const previewModeButtonActiveClass = "bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--surface-panel))] text-vui-fg-primary";
const editorWrapClass = [
  "grid min-h-0 overflow-hidden",
  "[&_.cm-theme]:h-full [&_.cm-theme]:min-h-0",
  "[&_.cm-editor]:h-full [&_.cm-editor]:min-h-0",
  "[&_.cm-scroller]:overflow-auto",
  "[&_.cm-content]:min-h-full [&_.cm-gutter]:min-h-full",
].join(" ");
const plainFallbackClass = "m-0 h-full min-h-0 overflow-auto whitespace-pre-wrap break-words bg-[var(--surface-panel)] px-4 py-3.5 font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.55] text-vui-fg-primary";
const footnoteClass = "m-0 border-t border-vui-border-soft px-5 pb-3.5 pt-2.5 text-[var(--vui-font-xs)] text-vui-fg-tertiary";

const styles = {
  surfaceClass,
  headerClass,
  headerCopyClass,
  eyebrowClass,
  fileNameClass,
  filePathClass,
  metaBlockClass,
  pillClass,
  changedPillClass,
  sourcePillClass,
  previewModeGroupClass,
  previewModeButtonClass,
  previewModeButtonActiveClass,
  editorWrapClass,
  plainFallbackClass,
  footnoteClass,
} as const;

export default styles;
