import { type ComponentPropsWithoutRef } from "react";

import { vuiFormControlClass } from "./formClasses";

export type VNativeTextareaProps = ComponentPropsWithoutRef<"textarea"> & {
  density?: "compact" | "normal";
  minRows?: number;
  "data-vui"?: string;
};

export function VNativeTextarea({
  density = "compact",
  className,
  minRows,
  rows,
  "data-vui": dataVui,
  ...props
}: VNativeTextareaProps) {
  return (
    <textarea
      {...props}
      rows={rows ?? minRows}
      data-vui={dataVui ?? "native-textarea"}
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
