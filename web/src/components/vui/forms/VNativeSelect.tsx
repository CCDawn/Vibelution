import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { vuiFormControlClass } from "./formClasses";

export type VNativeSelectProps = ComponentPropsWithoutRef<"select"> & {
  density?: "compact" | "normal";
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
      className={[vuiFormControlClass(density), className].filter(Boolean).join(" ")}
    />
  );
});
