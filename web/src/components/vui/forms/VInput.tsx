import { Input, type InputProps } from "@heroui/react";

import { type VuiDensity } from "../renderers/heroui/heroVariants";
import { vuiFormControlClass } from "./formClasses";

export type VInputProps = Omit<InputProps, "variant"> & {
  density?: VuiDensity;
  "data-vui"?: string;
};

export function VInput({
  density = "compact",
  className,
  "data-vui": dataVui,
  ...props
}: VInputProps) {
  return (
    <Input
      {...props}
      data-vui={dataVui ?? "input"}
      variant="secondary"
      className={[vuiFormControlClass(density), className].filter(Boolean).join(" ")}
    />
  );
}
