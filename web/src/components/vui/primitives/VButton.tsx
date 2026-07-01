import { Button, type ButtonProps } from "@heroui/react";
import { type ReactNode } from "react";

import {
  vuiButtonBaseClass,
  vuiButtonDangerClass,
  vuiButtonPrimaryClass,
} from "../renderers/heroui/heroSlots";
import {
  type VuiButtonVariant,
  type VuiDensity,
  vuiControlHeight,
} from "../renderers/heroui/heroVariants";

export type VButtonProps = Omit<
  ButtonProps,
  "variant" | "color" | "size" | "startContent" | "endContent"
> & {
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  children?: ReactNode;
  "data-vui"?: string;
  role?: string;
  title?: string;
};

function variantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    return `${vuiButtonBaseClass} ${vuiButtonPrimaryClass}`;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return "border border-transparent bg-transparent text-vui-fg-secondary shadow-none";
  }
  return vuiButtonBaseClass;
}

export function VButton({
  variant = "secondary",
  density = "compact",
  icon,
  trailingIcon,
  className,
  children,
  "data-vui": dataVui,
  title,
  ...props
}: VButtonProps) {
  const titleProps = title ? ({ title } as Record<string, string>) : undefined;
  const isIconOnly = Boolean(props.isIconOnly);

  return (
    <Button
      {...props}
      {...titleProps}
      data-vui={dataVui ?? "button"}
      size={vuiControlHeight(density)}
      className={[variantClass(variant), "min-w-0 px-2 text-[var(--vui-font-sm)] font-semibold", className]
        .filter(Boolean)
        .join(" ")}
    >
      <span
        data-slot="vui-button-content"
        title={title}
        className="inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
      >
        {icon ? (
          <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
            {icon}
          </span>
        ) : null}
        {isIconOnly && children ? (
          <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
            {children}
          </span>
        ) : children ? (
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
    </Button>
  );
}
