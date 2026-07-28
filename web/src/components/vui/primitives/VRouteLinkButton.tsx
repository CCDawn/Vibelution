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

export type VRouteLinkButtonProps = Omit<LinkProps, "children"> & {
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  children?: ReactNode;
  "data-vui"?: string;
};

/**
 * Internal SPA navigation rendered with the same stable visual contract as
 * VButton. This keeps link semantics (including open-in-new-tab behavior)
 * without route-owned button chrome.
 */
export const VRouteLinkButton = forwardRef<HTMLAnchorElement, VRouteLinkButtonProps>(
  function VRouteLinkButton(
    {
      variant = "secondary",
      density = "compact",
      icon,
      trailingIcon,
      className,
      children,
      "data-vui": dataVui,
      ...props
    },
    ref,
  ) {
    return (
      <Link
        {...props}
        ref={ref}
        data-vui={dataVui ?? "route-link-button"}
        data-variant={variant}
        data-density={density}
        data-renderer="shadcn"
        className={cn(
          "inline-flex max-w-full shrink-0 items-center justify-center justify-self-start",
          "rounded-[var(--radius-control)] px-2 [font-size:var(--vui-font-sm)] font-semibold leading-tight",
          vuiButtonDensityClass(density),
          vuiButtonVariantClass(variant),
          vuiButtonFocusClass,
          vuiButtonGeometryClass(className, "label"),
          "min-w-0 no-underline",
          className,
        )}
      >
        <span
          data-slot="vui-button-content"
          className="inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
        >
          {icon ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {icon}
            </span>
          ) : null}
          {children ? (
            <span data-slot="vui-button-label" className="min-w-0 truncate whitespace-nowrap">
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
