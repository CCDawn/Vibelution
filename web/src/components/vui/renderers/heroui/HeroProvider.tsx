import { cn } from "@heroui/react";
import { type ReactNode } from "react";

type VibelutionHeroProviderProps = {
  children: ReactNode;
};

export function VibelutionHeroProvider({ children }: VibelutionHeroProviderProps) {
  return (
    <div
      className={cn("vui-heroui-provider")}
      data-vui-provider="heroui"
      style={{ display: "contents" }}
    >
      {children}
    </div>
  );
}
