/**
 * Compact status legend — mirrors the four-bucket node status grammar.
 */
export function WorkflowCanvasLegend() {
  const items: Array<{ label: string; className: string }> = [
    { label: "运行中", className: "bg-[var(--accent-cool)]" },
    { label: "等待人工", className: "bg-[var(--state-warning)]" },
    { label: "阻塞/失败", className: "bg-[var(--state-error)]" },
    { label: "已完成", className: "bg-[var(--state-success)]" },
    { label: "待运行", className: "bg-[var(--vui-border-subtle)]" },
  ];
  return (
    <div
      className="pointer-events-none absolute right-3 top-3 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_92%,transparent)] px-2.5 py-1.5 text-[10px] text-[var(--fg-secondary)] shadow-sm backdrop-blur"
      data-vui="workflow-canvas-legend"
      aria-hidden
    >
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1">
          <span className={`h-2 w-2 rounded-full ${item.className}`} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
