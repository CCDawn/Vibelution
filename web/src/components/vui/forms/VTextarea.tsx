import { TextArea, type TextAreaProps } from "@heroui/react";

import { type VuiDensity } from "../renderers/heroui/heroVariants";
import { vuiFormControlClass } from "./formClasses";

export type VTextareaProps = Omit<TextAreaProps, "variant" | "rows"> & {
  density?: VuiDensity;
  minRows?: number;
  rows?: number;
  "data-vui"?: string;
};

export function VTextarea({
  density = "compact",
  className,
  minRows,
  rows,
  "data-vui": dataVui,
  ...props
}: VTextareaProps) {
  return (
    <TextArea
      {...props}
      data-vui={dataVui ?? "textarea"}
      rows={rows ?? minRows}
      variant="secondary"
      className={[
        vuiFormControlClass(density),
        "min-h-20 resize-y py-1.5 leading-5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
