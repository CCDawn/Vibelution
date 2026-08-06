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
    return "text-[var(--vui-status-info-fg)]";
  }
  if (tone === "success") {
    return "text-[var(--vui-status-success-fg)]";
  }
  if (tone === "warning") {
    return "text-[var(--vui-status-warning-fg)]";
  }
  if (tone === "danger") {
    return "text-[var(--vui-status-danger-fg)]";
  }
  return "text-vui-fg-secondary";
}

export function VStatusStrip({ className, items, ...props }: VStatusStripProps) {
  return (
    <div
      {...props}
      data-vui="status-strip"
      className={[
        "inline-flex max-w-full min-w-0 flex-wrap items-center gap-0.5 rounded-[var(--radius-control)]",
        "border border-vui-border-subtle bg-[var(--vui-surface-row)] p-0.5 shadow-[var(--vui-elevation-1)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {items.map((item, index) => (
        <span
          key={index}
          data-vui="status-strip-item"
          data-tone={item.tone ?? "neutral"}
          className={[
            "inline-flex min-h-7 items-center gap-1 rounded-[calc(var(--radius-control)-2px)] px-2",
            "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)]",
          ].join(" ")}
        >
          <span className="text-vui-fg-tertiary">{item.label}</span>
          <strong className={["font-[760]", toneClass(item.tone)].join(" ")}>
            {item.value}
          </strong>
        </span>
      ))}
    </div>
  );
}
