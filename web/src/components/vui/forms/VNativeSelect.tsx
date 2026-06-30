import { type ComponentPropsWithoutRef } from "react";

import { vuiFormControlClass } from "./formClasses";

export type VNativeSelectProps = ComponentPropsWithoutRef<"select"> & {
  density?: "compact" | "normal";
  "data-vui"?: string;
};

export function VNativeSelect({
  density = "compact",
  className,
  "data-vui": dataVui,
  ...props
}: VNativeSelectProps) {
  return (
    <select
      {...props}
      data-vui={dataVui ?? "native-select"}
      className={[vuiFormControlClass(density), className].filter(Boolean).join(" ")}
    />
  );
}
