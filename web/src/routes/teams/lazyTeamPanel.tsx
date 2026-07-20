import {
  lazy,
  Suspense,
  type ComponentProps,
  type ComponentType,
  type ReactNode,
} from "react";

/**
 * Shared secondary-lazy helper for Teams UI panels.
 * All named loaders that point at the same module share one async chunk.
 */
export function createLazyNamedTeamPanel<
  TModule extends Record<string, ComponentType<any>>,
  TName extends keyof TModule & string,
>(
  loader: () => Promise<TModule>,
  exportName: TName,
  fallback: ReactNode = null,
): TModule[TName] {
  const LazyComponent = lazy(async () => {
    const module = await loader();
    const Component = module[exportName];
    if (!Component) {
      throw new Error(`Teams secondary panel missing export: ${exportName}`);
    }
    return { default: Component };
  });

  function LazyTeamPanel(props: ComponentProps<TModule[TName]>) {
    return (
      <Suspense fallback={fallback}>
        <LazyComponent {...props} />
      </Suspense>
    );
  }

  Object.defineProperty(LazyTeamPanel, "name", {
    value: `Lazy${exportName}`,
    configurable: true,
  });

  return LazyTeamPanel as TModule[TName];
}
