import { type ReactNode } from "react";

export type VuiProviderProps = {
  children: ReactNode;
};

/**
 * Root UI boundary for the workbench.
 * Implementation backend is VUI + shadcn/Radix renderers.
 */
export function VuiProvider({ children }: VuiProviderProps) {
  return (
    <div className="vui-provider contents" data-vui-provider="shadcn">
      {children}
    </div>
  );
}
