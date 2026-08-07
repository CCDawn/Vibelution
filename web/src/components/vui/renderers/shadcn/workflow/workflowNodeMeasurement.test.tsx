/**
 * P1-5 node-measurement contracts (M level, happy-dom).
 *
 * Renders the measurement wrapper and asserts it reports the CONTENT's
 * natural size back to the auto-layout hook:
 *  - baseline: offset size reported once per mount with the measure key;
 *  - content growth: when the content's scroll extent exceeds the
 *    ELK-committed box (offset), the reported size reflects the content;
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

function stubSize(offset: { w: number; h: number }, scroll: { w: number; h: number }) {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: offset.w });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: offset.h });
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", { configurable: true, value: scroll.w });
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, value: scroll.h });
}

describe("NodeMeasureReporter (P1-5)", () => {
  beforeEach(() => {
    stubSize({ w: 212, h: 88 }, { w: 212, h: 88 });
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

  it("reports the CONTENT size when it grows beyond the ELK-committed box (P1-5)", async () => {
    // The ELK box is 212x88; a longer label makes the content 300x120.
    stubSize({ w: 212, h: 88 }, { w: 300, h: 120 });
    const onMeasure = vi.fn();
    const { root, container } = await mountReporter(onMeasure);
    expect(onMeasure).toHaveBeenCalledWith("n1", { width: 300, height: 120 });
    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("never reports below the committed box (calibration cannot shrink a node)", async () => {
    stubSize({ w: 212, h: 88 }, { w: 120, h: 40 });
    const onMeasure = vi.fn();
    const { root, container } = await mountReporter(onMeasure);
    expect(onMeasure).toHaveBeenCalledWith("n1", { width: 212, height: 88 });
    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("skips zero sizes so calibration never feeds garbage", async () => {
    stubSize({ w: 0, h: 0 }, { w: 0, h: 0 });
    const onMeasure = vi.fn();
    const { root, container } = await mountReporter(onMeasure);
    expect(onMeasure).not.toHaveBeenCalled();
    await act(async () => {
      root.unmount();
      container.remove();
    });
  });
});
