import { type ButtonHTMLAttributes, forwardRef } from "react";

export type VNativeButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  "data-vui"?: string;
};

function classNameTokens(className: VNativeButtonProps["className"]): string[] {
  return typeof className === "string" ? className.trim().split(/\s+/).filter(Boolean) : [];
}

function hasExplicitRootDisplay(className: VNativeButtonProps["className"]): boolean {
  return classNameTokens(className).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?(?:block|inline-block|inline-flex|inline-grid|flex|grid)$/.test(token);
  });
}

function hasExplicitRootWidth(className: VNativeButtonProps["className"]): boolean {
  return classNameTokens(className).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?w-(?:auto|fit|full|max|min|\[|[0-9])/.test(token);
  });
}

function nativeButtonGeometryClass(className: VNativeButtonProps["className"]): string {
  const displayExplicit = hasExplicitRootDisplay(className);
  return [
    displayExplicit ? null : "inline-flex items-center justify-center gap-1.5",
    hasExplicitRootWidth(className) ? null : "max-w-full shrink-0 justify-self-start",
    // Multi-line grid/flex roots must keep normal whitespace (session cards, headers).
    displayExplicit ? null : "whitespace-nowrap",
  ]
    .filter(Boolean)
    .join(" ");
}

export const VNativeButton = forwardRef<HTMLButtonElement, VNativeButtonProps>(
  function VNativeButton({ className, type = "button", "data-vui": dataVui, ...props }, ref) {
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        data-vui={dataVui ?? "native-button"}
        className={[nativeButtonGeometryClass(className), className].filter(Boolean).join(" ")}
      />
    );
  },
);
