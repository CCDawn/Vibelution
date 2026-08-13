import { type ReactNode } from "react";

export type VuiPreviewSectionProps = {
  title: string;
  children: ReactNode;
};

export function VuiPreviewSection({ title, children }: VuiPreviewSectionProps) {
  return (
    <section className="grid min-w-0 gap-3" aria-label={title}>
      <h2 className="m-0 font-mono [font-size:var(--vui-font-sm)] font-semibold tracking-[0.04em] text-vui-fg-secondary">
        {title}
      </h2>
      <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(15rem,1fr))] gap-3">
        {children}
      </div>
    </section>
  );
}
