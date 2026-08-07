/**
 * P1-1 initial-fit lifecycle for the workflow canvas.
 *
 * Arms on the layout hook's `initialFitRevision` and fires the fit only when:
 *  - the layout hook still holds an un-acknowledged initial-fit revision;
 *  - the STRUCTURE has not changed since arming (a topology/run switch bumps
 *    `structureKey`, which cancels the pending fit; a size-calibration relayout
 *    keeps `structureKey` stable, so the pending first fit survives it);
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
  /** Structural identity; changes only on topology/run switches. */
  structureKey: string;
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
  structureKey,
  nodesInitialized,
  fit,
  acknowledgeInitialFit,
}: UseWorkflowInitialFitOptions): UseWorkflowInitialFitResult {
  const [pendingInitialFit, setPendingInitialFit] = useState(false);
  const handledRevisionRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const armedStructureKeyRef = useRef<string | null>(null);

  const fireRef = useRef({ fit, acknowledgeInitialFit, structureKey });
  fireRef.current = { fit, acknowledgeInitialFit, structureKey };

  // Arm: any un-acknowledged initial-fit revision may fit, even when
  // layoutRevision has advanced past it (size-calibration relayouts bump the
  // revision without meaning the initial fit should be cancelled). Stale runs
  // are dropped upstream via the layout token; the hook only guards against
  // re-firing the SAME armed revision twice and against topology switches.
  useEffect(() => {
    const armed =
      initialFitRevision !== null &&
      handledRevisionRef.current !== initialFitRevision;
    if (armed) {
      // Arm against the CURRENT structure. A topology switch changes the
      // structure key, so a pending fit scheduled for the old structure is
      // cancelled at frame time; the new topology then re-arms against its own
      // structure (same un-acknowledged initialFitRevision).
      if (armedStructureKeyRef.current === null || armedStructureKeyRef.current !== structureKey) {
        armedStructureKeyRef.current = structureKey;
      }
    } else {
      armedStructureKeyRef.current = null;
    }
    setPendingInitialFit(armed);
  }, [initialFitRevision, layoutRevision, structureKey]);

  // Fire: after nodes entered React Flow internals, schedule the fit on the
  // next frame and only then acknowledge — but only if the structure is still
  // the one that was armed (a topology switch before the frame cancels it).
  useEffect(() => {
    if (!pendingInitialFit || !nodesInitialized) {
      return;
    }
    const armedRevision = initialFitRevision;
    const raf = requestAnimationFrame(() => {
      rafRef.current = null;
      if (fireRef.current.structureKey !== armedStructureKeyRef.current) {
        // Topology switched between arming and the frame: do not fit the old
        // graph; the new topology will arm its own initial fit (if any).
        handledRevisionRef.current = armedRevision;
        setPendingInitialFit(false);
        return;
      }
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
  }, [pendingInitialFit, nodesInitialized, initialFitRevision, structureKey]);

  return { pendingInitialFit };
}