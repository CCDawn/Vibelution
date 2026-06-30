import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VStatusStripTone = "neutral" | "info" | "success" | "warning" | "danger";

export type VStatusStripItem = {
  label: ReactNode;
  value: ReactNode;
  tone?: VStatusStripTone;
};

export type VStatusStripProps = Omit<ComponentPropsWithoutRef<"div">, "children"> & {
  items: VStatusStripItem[];
};

function toneClass(tone: VStatusStripTone | undefined): string {
  if (tone === "info") {
    return "bg-[var(--vui-status-info-bg)] text-[var(--vui-status-info-fg)]";
  }
  if (tone === "success") {
    return "bg-[var(--vui-status-success-bg)] text-[var(--vui-status-success-fg)]";
  }
  if (tone === "warning") {
    return "bg-[var(--vui-status-warning-bg)] text-[var(--vui-status-warning-fg)]";
  }
  if (tone === "danger") {
    return "bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)]";
  }
  return "bg-vui-control-muted text-vui-fg-secondary";
}

export function VStatusStrip({ className, items, ...props }: VStatusStripProps) {
  return (
    <div
      {...props}
      data-vui="status-strip"
      className={["flex min-w-0 flex-wrap items-center gap-1.5", className]
        .filter(Boolean)
        .join(" ")}
    >
      {items.map((item, index) => (
        <span
          key={index}
          data-vui="status-strip-item"
          className={[
            "inline-grid min-h-7 grid-cols-[auto_auto] items-center gap-1 rounded-md",
            "border border-vui-border-subtle px-2 text-xs font-semibold",
            toneClass(item.tone),
          ].join(" ")}
        >
          <span className="text-vui-fg-tertiary">{item.label}</span>
          <span>{item.value}</span>
        </span>
      ))}
    </div>
  );
}
