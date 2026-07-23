import {
  forwardRef,
  type ButtonHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

import { cn } from "../../lib/cn";
import {
  vuiButtonBaseClass,
  vuiButtonDangerClass,
  vuiButtonDisabledClass,
  vuiButtonFocusClass,
  vuiButtonHoverClass,
  vuiButtonPrimaryClass,
} from "../shared/buttonSlots";
import {
  type VuiButtonVariant,
  type VuiDensity,
  vuiButtonDensityClass,
} from "../shared/buttonVariants";

/**
 * Shadcn-style native button renderer (Radix-free first cut).
 * Pages must not import this — only VUI primitives consume it.
 */
export type ShadcnButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> & {
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  isDisabled?: boolean;
  isIconOnly?: boolean;
  /** HeroUI-era compatibility: mapped to onClick. */
  onPress?: (event: MouseEvent<HTMLButtonElement>) => void;
  "data-vui"?: string;
  children?: ReactNode;
};

function variantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonPrimaryClass}`;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return `border border-transparent bg-transparent text-vui-fg-secondary shadow-none ${vuiButtonHoverClass}`;
  }
  return `${vuiButtonBaseClass} ${vuiButtonHoverClass}`;
}

export const ShadcnButton = forwardRef<HTMLButtonElement, ShadcnButtonProps>(
  function ShadcnButton(
    {
      variant = "secondary",
      density = "compact",
      isDisabled = false,
      isIconOnly = false,
      onPress,
      onClick,
      type = "button",
      className,
      children,
      "data-vui": dataVui,
      ...props
    },
    ref,
  ) {
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        disabled={isDisabled}
        data-vui={dataVui ?? "button"}
        data-variant={variant}
        data-density={density}
        data-icon-only={isIconOnly ? "true" : undefined}
        data-renderer="shadcn"
        aria-disabled={isDisabled || undefined}
        className={cn(
          "inline-flex max-w-full shrink-0 items-center justify-center justify-self-start",
          "rounded-[var(--radius-control)] px-2 [font-size:var(--vui-font-sm)] font-semibold leading-tight",
          vuiButtonDensityClass(density),
          variantClass(variant),
          vuiButtonFocusClass,
          vuiButtonDisabledClass,
          isIconOnly ? "aspect-square px-0" : null,
          className,
        )}
        onClick={(event) => {
          if (isDisabled) {
            event.preventDefault();
            return;
          }
          onClick?.(event);
          onPress?.(event);
        }}
      >
        {children}
      </button>
    );
  },
);
