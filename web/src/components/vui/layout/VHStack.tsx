import { type ComponentPropsWithoutRef } from "react";

export type VHStackProps = ComponentPropsWithoutRef<"div">;

export function VHStack({ className, ...props }: VHStackProps) {
  return (
    <div
      {...props}
      data-vui="hstack"
      className={["flex min-w-0 items-center gap-1.5", className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
