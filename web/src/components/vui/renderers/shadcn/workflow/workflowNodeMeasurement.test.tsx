/**
 * P1-5 node-measurement contracts (M level, happy-dom).
 *
 * Renders the measurement wrapper and asserts it reports the rendered DOM
 * size back to the auto-layout hook:
 *  - nonzero offset size is reported once per mount with the measure key;
 *  - zero sizes (unmeasured/SSR) are skipped so calibration stays clean;
 *  - the wrapped node renders through (children passthrough).
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NodeProps } from "@xyflow/react";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { NodeMeasureReporter, wrapNodeForMeasurement } from "./ShadcnWorkflowCanvas";

function StubNode(props: NodeProps) {
  return (
    <div style={{ width: 212, height: 88 }} data-stub-node={props.id}>
      {String(props.data.label ?? "")}
    </div>
  );
}

async function mountReporter(onMeasure: ReturnType<typeof vi.fn>) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const Wrapped = wrapNodeForMeasurement(StubNode, onMeasure);
  await act(async () => {
    root.render(<Wrapped id="n1" data={{ label: "x" }} />);
  });
  return { container, root };
}

describe("NodeMeasureReporter (P1-5)", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      value: 212,
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      value: 88,
    });
  });

  it("reports nonzero rendered size with the node id", async () => {
    const onMeasure = vi.fn();
    const { root, container } = await mountReporter(onMeasure);
    expect(onMeasure).toHaveBeenCalledTimes(1);
    expect(onMeasure).toHaveBeenCalledWith("n1", { width: 212, height: 88 });
    expect(container.querySelector('[data-node-measure="n1"]')).toBeTruthy();
    expect(container.querySelector('[data-stub-node="n1"]')).toBeTruthy();
    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("skips zero sizes so calibration never feeds garbage", async () => {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      value: 0,
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      value: 0,
    });
    const onMeasure = vi.fn();
    const { root, container } = await mountReporter(onMeasure);
    expect(onMeasure).not.toHaveBeenCalled();
    await act(async () => {
      root.unmount();
      container.remove();
    });
  });
});
