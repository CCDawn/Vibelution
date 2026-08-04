import {
  forwardRef,
  type ButtonHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

import { cn } from "../../lib/cn";
import {
  vuiButtonDisabledClass,
  vuiButtonFocusClass,
  vuiButtonVariantClass,
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
  /** Mutation / async in flight — disables and exposes aria-busy. */
  isPending?: boolean;
  isIconOnly?: boolean;
  /** HeroUI-era compatibility: mapped to onClick. */
  onPress?: (event: MouseEvent<HTMLButtonElement>) => void;
  "data-vui"?: string;
  children?: ReactNode;
};

export const ShadcnButton = forwardRef<HTMLButtonElement, ShadcnButtonProps>(
  function ShadcnButton(
    {
      variant = "secondary",
      density = "compact",
      isDisabled = false,
      isPending = false,
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
    const blocked = Boolean(isDisabled || isPending);
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        disabled={blocked}
        data-vui={dataVui ?? "button"}
        data-variant={variant}
        data-density={density}
        data-icon-only={isIconOnly ? "true" : undefined}
        data-pending={isPending ? "true" : undefined}
        data-renderer="shadcn"
        aria-disabled={blocked || undefined}
        aria-busy={isPending || undefined}
        className={cn(
          "inline-flex max-w-full shrink-0 items-center justify-center justify-self-start",
          "rounded-[var(--radius-control)] px-2.5 [font-size:var(--vui-font-sm)] font-semibold leading-tight",
          "select-none",
          vuiButtonDensityClass(density),
          vuiButtonVariantClass(variant),
          // Focus is included for primary in variant slots; always apply ring base for secondary/ghost/danger.
          vuiButtonFocusClass,
          vuiButtonDisabledClass,
          isIconOnly ? "aspect-square px-0" : null,
          className,
        )}
        onClick={(event) => {
          if (blocked) {
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
