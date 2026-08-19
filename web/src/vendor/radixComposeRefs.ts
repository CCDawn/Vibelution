import * as React from "react";

type PossibleRef<T> = React.Ref<T> | undefined | null;

function setRef<T>(ref: PossibleRef<T>, value: T): unknown {
  if (typeof ref === "function") {
    return ref(value);
  }
  if (ref != null) {
    (ref as React.MutableRefObject<T>).current = value;
  }
}

export function composeRefs<T>(...refs: PossibleRef<T>[]) {
  return (node: T) => {
    let hasCleanup = false;
    const cleanups = refs.map((ref) => {
      const cleanup = setRef(ref, node);
      if (!hasCleanup && typeof cleanup === "function") {
        hasCleanup = true;
      }
      return cleanup;
    });
    if (hasCleanup) {
      return () => {
        for (let i = 0; i < cleanups.length; i += 1) {
          const cleanup = cleanups[i];
          if (typeof cleanup === "function") {
            cleanup();
          } else {
            setRef(refs[i], null as T);
          }
        }
      };
    }
  };
}

/**
 * Upstream `useComposedRefs` is `useCallback(composeRefs(...refs), refs)`.
 * React 19 detaches a ref whenever the callback identity changes; composed
 * state-setters then toggle `null → node` and schedule another render.
 * Keep one stable callback and read the latest refs from a ref slot.
 *
 * See radix-ui/primitives#3963 / #3968.
 */
export function useComposedRefs<T>(...refs: PossibleRef<T>[]) {
  const refsRef = React.useRef(refs);
  refsRef.current = refs;
  return React.useCallback((node: T) => composeRefs(...refsRef.current)(node), []);
}
