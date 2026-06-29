import { type ReactNode } from "react";

type VibelutionHeroProviderProps = {
  children: ReactNode;
};

export function VibelutionHeroProvider({ children }: VibelutionHeroProviderProps) {
  return (
    <div
      className="vui-heroui-provider"
      data-vui-provider="heroui"
      style={{ display: "contents" }}
    >
      {children}
    </div>
  );
}
