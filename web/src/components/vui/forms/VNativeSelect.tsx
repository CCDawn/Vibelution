import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { vuiFormControlClass } from "./formClasses";

export type VNativeSelectProps = ComponentPropsWithoutRef<"select"> & {
  density?: VuiDensity;
  "data-vui"?: string;
};

export const VNativeSelect = forwardRef<HTMLSelectElement, VNativeSelectProps>(function VNativeSelect(
  {
    density = "compact",
    className,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  return (
    <select
      {...props}
      ref={ref}
      data-vui={dataVui ?? "native-select"}
      data-density={density}
      className={[vuiFormControlClass(density), className].filter(Boolean).join(" ")}
    />
  );
});
