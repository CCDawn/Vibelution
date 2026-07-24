import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VPage } from "./VPage";
import { VRouteHeader } from "./VRouteHeader";

export type VSettingsFormPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** Optional band between header and scroll body (tabs, status strip). */
  toolbar?: ReactNode;
  /** Optional banner / status inside the scroll body, above children. */
  banner?: ReactNode;
  /** Form sections and fields. */
  children: ReactNode;
  /** Sticky footer actions (save / reset). */
  footer?: ReactNode;
  /** Applied to the header band wrapping VRouteHeader. */
  headerClassName?: string;
  /** Applied to the settings body (default: scrollable). */
  bodyClassName?: string;
  /** Applied to the sticky footer band. */
  footerClassName?: string;
  className?: string;
};

/**
 * Page recipe: header + optional toolbar + scrollable settings body + sticky action footer.
 * Use for config / preference style surfaces instead of reinventing sticky save bars.
 */
export function VSettingsFormPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  toolbar,
  banner,
  children,
  footer,
  headerClassName,
  bodyClassName,
  footerClassName,
  className,
  ...props
}: VSettingsFormPageProps) {
  return (
    <VPage
      ariaLabel={ariaLabel}
      data-vui-recipe="settings-form-page"
      className={[
        "flex min-h-0 min-w-0 h-full flex-col gap-0 overflow-hidden",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      <div
        data-vui="settings-form-header"
        className={["min-w-0 shrink-0", headerClassName].filter(Boolean).join(" ")}
      >
        <VRouteHeader eyebrow={eyebrow} title={title} meta={meta} actions={actions} />
      </div>
      {toolbar ? (
        <div data-vui="settings-form-toolbar" className="min-w-0 shrink-0">
          {toolbar}
        </div>
      ) : null}
      <div
        data-vui="settings-form-body"
        className={[
          "grid min-h-0 min-w-0 flex-1 content-start gap-2 overflow-y-auto",
          bodyClassName,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {banner}
        {children}
      </div>
      {footer ? (
        <div
          data-vui="settings-form-footer"
          className={[
            "sticky bottom-0 z-[1] flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-1.5 border-t border-vui-border-subtle bg-[color-mix(in_srgb,var(--bg-canvas)_88%,transparent)] py-2 backdrop-blur-md",
            footerClassName,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {footer}
        </div>
      ) : null}
    </VPage>
  );
}
