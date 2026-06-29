import { type ComponentPropsWithoutRef } from "react";

export type VStackProps = ComponentPropsWithoutRef<"div">;

export function VStack({ className, ...props }: VStackProps) {
  return (
    <div
      {...props}
      data-vui="vstack"
      className={["grid min-w-0 gap-1.5", className].filter(Boolean).join(" ")}
    />
  );
}
