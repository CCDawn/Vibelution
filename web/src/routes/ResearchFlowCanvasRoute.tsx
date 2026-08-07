/**
 * Task 9: ResearchFlowCanvasRoute retired — organization/flow hybrid page removed.
 * Router uses ResearchFlowCanvasRedirect; this module remains a thin redirect for residual imports.
 */
import { Navigate } from "react-router-dom";

export function ResearchFlowCanvasRoute() {
  return <Navigate to="/teams?researchView=workflow&panel=agents" replace />;
}

/** Retained export names for residual pure-logic tests that will be retired with Task 9 contracts. */
export function validateResearchFlowCanvasContract(_canvas: unknown): { valid: boolean } {
  return { valid: false };
}
