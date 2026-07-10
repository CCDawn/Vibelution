import { LoaderCircle } from "lucide-react";
import { type ComponentPropsWithoutRef } from "react";

export type VLoadingValueProps = Omit<ComponentPropsWithoutRef<"span">, "children"> & {
  label: string;
};

export function VLoadingValue({ className, label, ...props }: VLoadingValueProps) {
  return (
    <span
      {...props}
      data-vui="loading-value"
      role="status"
      aria-label={label}
      className={[
        "inline-flex h-[1em] min-w-[1.25em] items-center justify-center align-middle",
        className,
      ].filter(Boolean).join(" ")}
    >
      <LoaderCircle
        aria-hidden="true"
        className="size-[0.9em] animate-spin motion-reduce:animate-none"
      />
    </span>
  );
}
