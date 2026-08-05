/**
 * SC presentation API context — reduces inject prop spray (R2-q).
 * Controller/surface layers may consume this instead of threading 100+ keys.
 */
import { createContext, useContext, type ReactNode } from "react";
import type { SourceCollectionPresentationApi } from "../useSourceCollectionPresentationCore";

const SourceCollectionPresentationContext = createContext<SourceCollectionPresentationApi | null>(null);

export function SourceCollectionPresentationProvider({
  value,
  children,
}: {
  value: SourceCollectionPresentationApi;
  children: ReactNode;
}) {
  return (
    <SourceCollectionPresentationContext.Provider value={value}>
      {children}
    </SourceCollectionPresentationContext.Provider>
  );
}

export function useSourceCollectionPresentationContext(): SourceCollectionPresentationApi {
  const value = useContext(SourceCollectionPresentationContext);
  if (!value) {
    throw new Error("useSourceCollectionPresentationContext requires SourceCollectionPresentationProvider");
  }
  return value;
}

export function useOptionalSourceCollectionPresentationContext(): SourceCollectionPresentationApi | null {
  return useContext(SourceCollectionPresentationContext);
}
