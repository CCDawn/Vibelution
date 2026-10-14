import { forwardRef, useContext, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { FieldRowIdContext } from "./fieldRowContext";
import { vuiFormControlClass } from "./formClasses";
import { ShadcnRange } from "../renderers/shadcn/ShadcnRange";

export type VNativeInputProps = ComponentPropsWithoutRef<"input"> & {
  density?: VuiDensity;
  "data-vui"?: string;
  rangeVariant?: "capsule";
  rangeTickCount?: number;
};

export const VNativeInput = forwardRef<HTMLInputElement, VNativeInputProps>(function VNativeInput(
  {
    density = "compact",
    className,
    type,
    id,
    "data-vui": dataVui,
    rangeVariant,
    rangeTickCount,
    ...props
  },
  ref,
) {
  const fieldRowId = useContext(FieldRowIdContext);
  const inputType = type ?? "text";
  if (inputType === "range" && rangeVariant === "capsule") {
    return (
      <ShadcnRange
        {...props}
        ref={ref}
        id={id ?? fieldRowId}
        className={className}
        tickCount={rangeTickCount}
        data-vui={dataVui ?? "native-input"}
        data-density={density}
      />
    );
  }
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
      id={id ?? fieldRowId}
      data-vui={dataVui ?? "native-input"}
      data-density={density}
      className={[controlClass, className].filter(Boolean).join(" ")}
    />
  );
});
