import { useEffect, useRef } from "react";

import { isElectronDesktopShell } from "./projectCloseGuard";

/**
 * Bind `beforeunload` once for the component lifetime.
 *
 * Do not put polled status into the effect deps: re-binding tears down the
 * listener while the browser dialog is open (Edge flashes "重新加载应用?" and
 * dismisses before the user can click).
 */
export function useStableBeforeUnload(
  handler: (event: BeforeUnloadEvent) => void,
  options?: {
    /** Default true: desktop shell uses native close flows, not browser prompt. */
    skipElectronDesktopShell?: boolean;
  },
) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const skipElectronDesktopShell = options?.skipElectronDesktopShell !== false;

  useEffect(() => {
    if (skipElectronDesktopShell && isElectronDesktopShell()) {
      return;
    }

    function onBeforeUnload(event: BeforeUnloadEvent) {
      handlerRef.current(event);
    }

    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [skipElectronDesktopShell]);
}
