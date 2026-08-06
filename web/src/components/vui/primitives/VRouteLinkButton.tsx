import {
  forwardRef,
  type ReactNode,
} from "react";
import {
  Link,
  type LinkProps,
} from "react-router-dom";

import { cn } from "../lib/cn";
import {
  vuiButtonFocusClass,
  vuiButtonGeometryClass,
  vuiButtonVariantClass,
} from "../renderers/shared/buttonSlots";
import {
  type VuiButtonVariant,
  type VuiDensity,
  vuiButtonDensityClass,
} from "../renderers/shared/buttonVariants";

/**
 * `button` — same visual contract as VButton (default).
 * `shell-nav` — no button fill/height chrome; consumer owns surface classes
 * (AppShell primary/mobile nav, underline section subnavs).
 */
export type VRouteLinkButtonChrome = "button" | "shell-nav";

export type VRouteLinkButtonProps = Omit<LinkProps, "children"> & {
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  chrome?: VRouteLinkButtonChrome;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  children?: ReactNode;
  "data-vui"?: string;
};

/**
 * Internal SPA navigation rendered with the same stable visual contract as
 * VButton (default chrome). Use `chrome="shell-nav"` when domain CSS owns the
 * nav surface so button fill/density does not fight shell styles.
 */
export const VRouteLinkButton = forwardRef<HTMLAnchorElement, VRouteLinkButtonProps>(
  function VRouteLinkButton(
    {
      variant = "secondary",
      density = "compact",
      chrome = "button",
      icon,
      trailingIcon,
      className,
      children,
      "data-vui": dataVui,
      ...props
    },
    ref,
  ) {
    const shellNav = chrome === "shell-nav";

    return (
      <Link
        {...props}
        ref={ref}
        data-vui={dataVui ?? "route-link-button"}
        data-chrome={chrome}
        data-variant={shellNav ? undefined : variant}
        data-density={shellNav ? undefined : density}
        data-renderer="shadcn"
        className={cn(
          shellNav
            ? [
                // Geometry + paint live on consumer classes (navLink / subnavLink / …).
                "min-w-0 no-underline",
                // Keep keyboard focus ring even when domain CSS owns idle/hover paint.
                vuiButtonFocusClass,
              ]
            : [
                "inline-flex max-w-full shrink-0 items-center justify-center justify-self-start",
                "rounded-[var(--radius-control)] px-2 [font-size:var(--vui-font-sm)] font-semibold leading-tight",
                vuiButtonDensityClass(density),
                vuiButtonVariantClass(variant),
                vuiButtonFocusClass,
                vuiButtonGeometryClass(className, "label"),
                "min-w-0 no-underline",
              ],
          className,
        )}
      >
        <span
          data-slot="vui-button-content"
          className={
            shellNav
              ? "inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
              : "inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
          }
        >
          {icon ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {icon}
            </span>
          ) : null}
          {children ? (
            <span
              data-slot="vui-button-label"
              className={shellNav ? "min-w-0 whitespace-nowrap" : "min-w-0 truncate whitespace-nowrap"}
            >
              {children}
            </span>
          ) : null}
          {trailingIcon ? (
            <span data-slot="vui-button-trailing-icon" className="inline-grid shrink-0 place-items-center">
              {trailingIcon}
            </span>
          ) : null}
        </span>
      </Link>
    );
  },
);
