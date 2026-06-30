import { type ButtonHTMLAttributes, forwardRef } from "react";

export type VNativeButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  "data-vui"?: string;
};

export const VNativeButton = forwardRef<HTMLButtonElement, VNativeButtonProps>(
  function VNativeButton({ className, type = "button", "data-vui": dataVui, ...props }, ref) {
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        data-vui={dataVui ?? "native-button"}
        className={className}
      />
    );
  },
);
