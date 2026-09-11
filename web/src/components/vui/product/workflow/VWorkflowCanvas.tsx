/**
 * Product API: workflow canvas. Routes must import this, never the React Flow renderer.
 *
 * The renderer statically imports ``@xyflow/react`` and its stylesheet, so a static
 * re-export here pulled the whole canvas engine (xyflow + its d3 stack) into the eager
 * application entry chunk the moment anything imported the VUI barrel. The renderer is
 * therefore loaded on demand; the public surface and props stay identical for callers.
 */
import { lazy, Suspense } from "react";

import type { ShadcnWorkflowCanvasProps } from "../../renderers/shadcn/ShadcnWorkflowCanvas";

import styles from "./VWorkflowCanvas.styles";

export type VWorkflowCanvasProps = ShadcnWorkflowCanvasProps;

const LazyShadcnWorkflowCanvas = lazy(async () => {
  const renderer = await import("../../renderers/shadcn/ShadcnWorkflowCanvas");
  return { default: renderer.ShadcnWorkflowCanvas };
});

export function VWorkflowCanvas(props: VWorkflowCanvasProps) {
  return (
    <Suspense
      fallback={<div className={styles.fallback} style={{ height: props.height }} />}
    >
      <LazyShadcnWorkflowCanvas {...props} />
    </Suspense>
  );
}
