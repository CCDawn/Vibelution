import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { ShadcnScrollRegion } from "../renderers/shadcn/ShadcnScrollRegion";

export type VScrollRegionProps = ComponentPropsWithoutRef<"div"> & {
  "data-vui"?: string;
};

/** Native scroll host with VUI's shared transient scrollbar presentation. */
export const VScrollRegion = forwardRef<HTMLDivElement, VScrollRegionProps>(function VScrollRegion(
  { "data-vui": dataVui = "scroll-region", ...props },
  ref,
) {
  return <ShadcnScrollRegion {...props} ref={ref} data-vui={dataVui} />;
});
