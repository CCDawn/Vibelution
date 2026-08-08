import { forwardRef, useContext, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { FieldRowIdContext } from "./fieldRowContext";
import { vuiFormControlClass } from "./formClasses";

export type VNativeSelectProps = ComponentPropsWithoutRef<"select"> & {
  density?: VuiDensity;
  "data-vui"?: string;
};

export const VNativeSelect = forwardRef<HTMLSelectElement, VNativeSelectProps>(function VNativeSelect(
  {
    density = "compact",
    className,
    id,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  const fieldRowId = useContext(FieldRowIdContext);
  return (
    <select
      {...props}
      ref={ref}
      id={id ?? fieldRowId}
      data-vui={dataVui ?? "native-select"}
      data-density={density}
      className={[vuiFormControlClass(density), className].filter(Boolean).join(" ")}
    />
  );
});
