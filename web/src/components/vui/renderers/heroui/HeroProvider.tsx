import { type ReactNode } from "react";

type VibelutionHeroProviderProps = {
  children: ReactNode;
};

export function VibelutionHeroProvider({ children }: VibelutionHeroProviderProps) {
  // HeroUI 3.2.1 does not expose a root provider. Keep this renderer boundary
  // explicit so app code does not learn package-level assumptions.
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
