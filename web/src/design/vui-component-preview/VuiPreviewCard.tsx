import { type ReactNode } from "react";

import { VSurface } from "../../components/vui";

export type VuiPreviewCardProps = {
  name: string;
  children: ReactNode;
  className?: string;
};

export function VuiPreviewCard({ name, children, className }: VuiPreviewCardProps) {
  return (
    <VSurface
      ariaLabel={name}
      tone="card"
      elevation="panel"
      className={[
        "grid min-h-40 min-w-0 content-center justify-items-center gap-4 px-5 py-5 text-center",
        className,
      ].filter(Boolean).join(" ")}
    >
      <span className="font-mono text-[var(--vui-font-sm)] font-semibold tracking-[-0.01em] text-vui-fg-primary">
        {name}
      </span>
      <div className="flex w-full min-w-0 max-w-full flex-wrap items-center justify-center gap-2">
        {children}
      </div>
    </VSurface>
  );
}
