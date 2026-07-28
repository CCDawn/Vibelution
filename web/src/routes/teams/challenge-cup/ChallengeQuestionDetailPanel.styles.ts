const styles: Record<string, string> = {
  workspace: "grid gap-4 text-[var(--fg-primary)]",
  header:
    "flex items-center justify-between gap-6 [&_h2]:m-0 [&_h2]:mt-1 [&_h2]:text-[22px] [&_h2]:leading-[1.3] [&_p]:m-0 [&_p]:text-[var(--fg-secondary)]",
  headerActions: "flex shrink-0 items-center gap-2",
  eyebrow: "text-xs font-[650] tracking-[0.02em] text-[var(--fg-secondary)]",
  anchorNav:
    "grid grid-cols-8 overflow-hidden rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] [&_a]:flex [&_a]:min-w-0 [&_a]:items-center [&_a]:gap-[7px] [&_a]:px-2.5 [&_a]:py-[9px] [&_a]:text-xs [&_a]:text-inherit [&_a]:no-underline [&_a+a]:border-l [&_a+a]:border-[var(--vui-border-subtle)] [&_span]:grid [&_span]:h-5 [&_span]:w-5 [&_span]:shrink-0 [&_span]:place-items-center [&_span]:rounded-full [&_span]:bg-[var(--vui-surface-inset)] [&_span]:text-[var(--fg-secondary)] max-[1320px]:grid-cols-4 max-[1320px]:[&_a:nth-child(5)]:border-l-0 max-[1320px]:[&_a:nth-child(n+5)]:border-t max-[1320px]:[&_a:nth-child(n+5)]:border-[var(--vui-border-subtle)]",
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  sectionHeading:
    "flex items-start gap-2.5 [&>span]:pt-[3px] [&>span]:text-xs [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_h3]:text-base [&_p]:mt-0.5 [&_p]:text-xs [&_p]:text-[var(--fg-secondary)]",
  factGrid:
    "grid grid-cols-4 gap-2 [&_section]:grid [&_section]:gap-1 [&_span]:text-xs [&_span]:font-[650] [&_span]:tracking-[0.02em] [&_span]:text-[var(--fg-secondary)]",
  warning:
    "flex items-start gap-[9px] rounded-[var(--vui-radius-panel-soft)] border border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-3 py-2.5 [&_svg]:shrink-0 [&_svg]:text-[var(--state-warning)] [&_p]:mt-0.5 [&_p]:text-xs [&_p]:text-[var(--fg-secondary)]",
  explanation:
    "grid gap-2.5 [&_dl]:m-0 [&_dl]:grid [&_dl]:grid-cols-3 [&_dl]:gap-2 [&_dl>div]:grid [&_dl>div]:gap-[3px] [&_dt]:text-xs [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0",
  cardList: "grid gap-[9px]",
  evidenceCard:
    "rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3",
  cardTopline: "flex items-center justify-between gap-3",
  metadata:
    "mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-[var(--fg-secondary)] [&_a]:inline-flex [&_a]:items-center [&_a]:gap-[3px] [&_a]:text-[var(--accent-cool)]",
  fact:
    "mt-2.5 border-l-[3px] border-[var(--accent-cool)] bg-[var(--vui-surface-inset)] px-2.5 py-[9px] [&>span]:text-xs [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:mt-[3px]",
  missing: "text-xs text-[var(--state-warning)]",
  missingLine: "mt-1.5 text-xs text-[var(--state-warning)]",
  compactList: "mt-[3px] mb-0 grid gap-[3px] pl-[18px]",
  twoColumn: "grid grid-cols-2 gap-2.5",
  hypothesisCard:
    "grid gap-2.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_h4]:text-[15px] [&_h4]:leading-[1.45] [&_dl]:m-0 [&_dl]:grid [&_dl]:gap-2 [&_dl>div]:grid [&_dl>div]:gap-[3px] [&_dt]:text-xs [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0",
  reviewGroups:
    "grid gap-[9px] [&>article]:grid [&>article]:gap-2 [&>article]:rounded-[var(--vui-radius-panel-soft)] [&>article]:border [&>article]:border-[var(--vui-border-subtle)] [&>article]:bg-[var(--vui-surface-card)] [&>article]:p-3",
  reviewGrid:
    "grid grid-cols-7 gap-1.5 max-[1320px]:grid-cols-4 [&>div]:grid [&>div]:min-w-0 [&>div]:content-start [&>div]:gap-1 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2 [&_span]:text-[11px] [&_span]:text-[var(--fg-secondary)] [&_small]:text-[11px] [&_small]:text-[var(--fg-secondary)] [&_p]:text-xs [&_p]:leading-[1.45]",
  selection:
    "grid grid-cols-2 gap-2.5 [&>div]:grid [&>div]:content-start [&>div]:gap-1.25 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2.5 [&>div>span]:text-xs [&>div>span]:font-[650] [&>div>span]:tracking-[0.02em] [&>div>span]:text-[var(--fg-secondary)]",
  plan: "grid gap-2.5",
  planGrid:
    "grid grid-cols-4 gap-2 [&>div]:grid [&>div]:content-start [&>div]:gap-1.25 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2.5",
  workPackage:
    "grid gap-1.25 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] p-2.5 [&_small]:text-[var(--fg-secondary)]",
  timeline:
    "grid gap-[9px] [&_article]:grid [&_article]:grid-cols-[76px_1fr] [&_article]:gap-3 [&_article]:rounded-[var(--vui-radius-panel-soft)] [&_article]:border [&_article]:border-[var(--vui-border-subtle)] [&_article]:bg-[var(--vui-surface-card)] [&_article]:p-3 [&_article>span]:font-bold [&_article>span]:text-[var(--accent-cool)] [&_small]:text-[var(--state-warning)]",
  artifact:
    "flex items-start gap-2.5 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-1.25 [&_code]:wrap-anywhere [&_code]:text-xs [&_code]:text-[var(--fg-secondary)]",
  state:
    "grid min-h-60 content-center justify-items-start gap-2.5 [&_span]:text-[var(--fg-secondary)] [&_code]:wrap-anywhere [&_code]:text-xs [&_code]:text-[var(--fg-secondary)]",
  secondaryButton:
    "min-h-8 cursor-pointer rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-control)] px-2.5 py-1.5 text-[var(--fg-primary)]",
};

export default styles;
