import { forwardRef, useContext, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { FieldRowIdContext } from "./fieldRowContext";
import { vuiFormControlClass } from "./formClasses";

export type VNativeTextareaProps = ComponentPropsWithoutRef<"textarea"> & {
  density?: VuiDensity;
  minRows?: number;
  "data-vui"?: string;
};

export const VNativeTextarea = forwardRef<HTMLTextAreaElement, VNativeTextareaProps>(function VNativeTextarea(
  {
    density = "compact",
    className,
    minRows,
    rows,
    id,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  const fieldRowId = useContext(FieldRowIdContext);
  return (
    <textarea
      {...props}
      ref={ref}
      rows={rows ?? minRows}
      id={id ?? fieldRowId}
      data-vui={dataVui ?? "native-textarea"}
      data-density={density}
      className={[
        vuiFormControlClass(density),
        "min-h-20 resize-y py-1.5 leading-5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
});
