/**
 * P1-1 initial-fit lifecycle for the workflow canvas.
 *
 * Arms on the layout hook's `initialFitRevision` and fires the fit only when:
 *  - the layout hook still holds an un-acknowledged initial-fit revision
 *    (layout revision may advance past it due to size calibration — P1-5 —
 *    without cancelling the pending fit, because layoutRevision only bumps on
 *    a successful commit and stale runs are already dropped upstream by the
 *    layout token);
 *  - the committed nodes have entered React Flow internals (`nodesInitialized`);
 *  - one animation frame has elapsed after that.
 *
 * `acknowledgeInitialFit` is called only after the fit has been scheduled in
 * the frame callback, so runtime-only updates (status/selection/run events) can
 * never re-trigger the initial fit.
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

  // Arm/cancel: any un-acknowledged initial-fit revision may fit, even when
  // layoutRevision has advanced past it (size-calibration relayouts bump the
  // revision without meaning the initial fit should be cancelled). Stale runs
  // are already dropped in useWorkflowAutoLayout via the layout token; the
  // hook only guards against re-firing the SAME armed revision twice.
  useEffect(() => {
    const armed =
      initialFitRevision !== null &&
      handledRevisionRef.current !== initialFitRevision;
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