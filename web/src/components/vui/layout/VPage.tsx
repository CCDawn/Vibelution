import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VPageProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

export function VPage({ ariaLabel, className, children, ...props }: VPageProps) {
  return (
    <section
      {...props}
      data-vui="page"
      aria-label={ariaLabel}
      className={[
        "grid min-h-0 min-w-0 content-start gap-[var(--vui-page-gap,8px)] text-vui-fg-primary",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </section>
  );
}
