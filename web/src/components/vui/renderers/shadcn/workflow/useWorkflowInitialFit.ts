/**
 * P1-1 initial-fit lifecycle for the workflow canvas.
 *
 * Arms on the layout hook's `initialFitRevision` and fires the fit only when:
 *  - the committed layout revision matches the armed revision (a newer run
 *    superseding the armed one cancels the pending fit);
 *  - the committed nodes have entered React Flow internals (`nodesInitialized`);
 *  - one animation frame has elapsed after that.
 *
 * `acknowledgeInitialFit` is called only after the fit has been scheduled in
 * the frame callback, so runtime-only updates (status/selection/run events) can
 * never re-trigger the initial fit, and a stale run cannot fit the canvas.
 */
import { useEffect, useRef, useState } from "react";

export type UseWorkflowInitialFitOptions = {
  /** Armed initial-fit revision from the layout hook (null once acknowledged). */
  initialFitRevision: number | null;
  /** Current committed layout revision (monotonic per committed ELK run). */
  layoutRevision: number;
  /** True once React Flow has initialized the committed nodes' internals. */
  nodesInitialized: boolean;
  /** Executes the actual canvas fit. */
  fit: () => void;
  /** Consumed by the layout hook after the fit is scheduled. */
  acknowledgeInitialFit: () => void;
};

export type UseWorkflowInitialFitResult = {
  /** True while an initial fit is armed but not yet fired. */
  pendingInitialFit: boolean;
};

export function useWorkflowInitialFit({
  initialFitRevision,
  layoutRevision,
  nodesInitialized,
  fit,
  acknowledgeInitialFit,
}: UseWorkflowInitialFitOptions): UseWorkflowInitialFitResult {
  const [pendingInitialFit, setPendingInitialFit] = useState(false);
  const handledRevisionRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  const fireRef = useRef({ fit, acknowledgeInitialFit });
  fireRef.current = { fit, acknowledgeInitialFit };

  // Arm/cancel: only the layout revision that matches the armed initial-fit
  // revision may fit. A run switch (layoutRevision !== armed) cancels any
  // pending fit so a stale run can never touch the viewport.
  useEffect(() => {
    const armed =
      initialFitRevision !== null &&
      handledRevisionRef.current !== initialFitRevision &&
      layoutRevision === initialFitRevision;
    setPendingInitialFit(armed);
  }, [initialFitRevision, layoutRevision]);

  // Fire: after nodes entered React Flow internals, schedule the fit on the
  // next frame and only then acknowledge.
  useEffect(() => {
    if (!pendingInitialFit || !nodesInitialized) {
      return;
    }
    const armedRevision = initialFitRevision;
    const raf = requestAnimationFrame(() => {
      rafRef.current = null;
      handledRevisionRef.current = armedRevision;
      setPendingInitialFit(false);
      fireRef.current.fit();
      fireRef.current.acknowledgeInitialFit();
    });
    rafRef.current = raf;
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [pendingInitialFit, nodesInitialized, initialFitRevision]);

  return { pendingInitialFit };
}