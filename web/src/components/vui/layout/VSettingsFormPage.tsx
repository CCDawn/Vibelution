import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VPage } from "./VPage";
import { VRouteHeader } from "./VRouteHeader";

export type VSettingsFormPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** Optional banner / status above the form body. */
  banner?: ReactNode;
  /** Form sections and fields. */
  children: ReactNode;
  /** Sticky footer actions (save / reset). */
  footer?: ReactNode;
  className?: string;
};

/**
 * Page recipe: header + scrollable settings body + sticky action footer.
 * Use for config / preference style surfaces instead of reinventing sticky save bars.
 */
export function VSettingsFormPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  banner,
  children,
  footer,
  className,
  ...props
}: VSettingsFormPageProps) {
  return (
    <VPage
      ariaLabel={ariaLabel}
      data-vui-recipe="settings-form-page"
      className={[
        "grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      <VRouteHeader eyebrow={eyebrow} title={title} meta={meta} actions={actions} />
      <div
        data-vui="settings-form-body"
        className="grid min-h-0 min-w-0 content-start gap-2 overflow-y-auto"
      >
        {banner}
        {children}
      </div>
      {footer ? (
        <div
          data-vui="settings-form-footer"
          className="sticky bottom-0 z-[1] flex min-w-0 flex-wrap items-center justify-end gap-1.5 border-t border-vui-border-subtle bg-[color-mix(in_srgb,var(--bg-canvas)_88%,transparent)] py-2 backdrop-blur-md"
        >
          {footer}
        </div>
      ) : null}
    </VPage>
  );
}
