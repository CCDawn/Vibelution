import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { vuiFormControlClass } from "./formClasses";

export type VNativeInputProps = ComponentPropsWithoutRef<"input"> & {
  density?: VuiDensity;
  "data-vui"?: string;
};

export const VNativeInput = forwardRef<HTMLInputElement, VNativeInputProps>(function VNativeInput(
  {
    density = "compact",
    className,
    type,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  const inputType = type ?? "text";
  const isBox = inputType === "checkbox" || inputType === "radio";
  const controlClass = isBox
    ? [
        "h-4 w-4 min-w-4 rounded border border-vui-border-subtle",
        "bg-vui-control-muted text-vui-accent-cool shadow-none",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-vui-accent-cool",
        "disabled:cursor-not-allowed disabled:opacity-55",
      ].join(" ")
    : vuiFormControlClass(density);

  return (
    <input
      {...props}
      ref={ref}
      type={inputType}
      data-vui={dataVui ?? "native-input"}
      data-density={density}
      className={[controlClass, className].filter(Boolean).join(" ")}
    />
  );
});
