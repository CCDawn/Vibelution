import { describe, expect, it } from "vitest";
import type { Node, NodeChange } from "@xyflow/react";

import { resolveWorkflowNodeChangeOutcome } from "./workflowNodeChanges";

const task: Node = {
  id: "protocol_design",
  type: "agentTask",
  position: { x: 40, y: 80 },
  data: {},
  width: 300,
  height: 72,
  selectable: true,
  selected: false,
};

const stage: Node = {
  id: "stage:experiment",
  type: "stageRegion",
  position: { x: 0, y: 0 },
  data: {},
  selectable: false,
};

describe("resolveWorkflowNodeChangeOutcome", () => {
  it("drops add, remove, and replace so the library cannot edit topology", () => {
    const changes: NodeChange[] = [
      { type: "add", item: { id: "extra", position: { x: 0, y: 0 }, data: {} } },
      { type: "remove", id: "protocol_design" },
      { type: "replace", id: "protocol_design", item: { ...task, id: "replaced" } },
    ];
    expect(resolveWorkflowNodeChangeOutcome(changes, [task], true)).toBeNull();
  });

  it("records measured size without taking over the layout box", () => {
    const outcome = resolveWorkflowNodeChangeOutcome(
      [{
        type: "dimensions",
        id: "protocol_design",
        dimensions: { width: 10, height: 12 },
        setAttributes: true,
      }],
      [task],
      false,
    );
    expect(outcome?.measured).toEqual({ protocol_design: { width: 10, height: 12 } });
    expect(outcome?.positions).toEqual({});
  });

  it("turns select changes into one selected id and can clear it", () => {
    const selected = resolveWorkflowNodeChangeOutcome(
      [
        { type: "select", id: "protocol_design", selected: true },
        { type: "select", id: "stage:experiment", selected: true },
      ],
      [task, stage],
      false,
    );
    expect(selected?.selectedId).toBe("protocol_design");

    const cleared = resolveWorkflowNodeChangeOutcome(
      [{ type: "select", id: "protocol_design", selected: false }],
      [{ ...task, selected: true }, stage],
      false,
    );
    expect(cleared?.selectedId).toBeNull();
  });

  it("keeps a resting unlocked position and ignores locked or in-progress drags", () => {
    const resting = resolveWorkflowNodeChangeOutcome(
      [{ type: "position", id: "protocol_design", position: { x: 120, y: 200 }, dragging: false }],
      [task, stage],
      true,
    );
    expect(resting?.positions).toEqual({ protocol_design: { x: 120, y: 200 } });
    expect(resting?.dragging).toBe(false);

    const stageMove = resolveWorkflowNodeChangeOutcome(
      [{ type: "position", id: "stage:experiment", position: { x: 8, y: 8 }, dragging: false }],
      [task, stage],
      true,
    );
    expect(stageMove?.positions).toEqual({});

    const locked = resolveWorkflowNodeChangeOutcome(
      [{ type: "position", id: "protocol_design", position: { x: 8, y: 8 }, dragging: false }],
      [task],
      false,
    );
    expect(locked).toBeNull();

    const dragging = resolveWorkflowNodeChangeOutcome(
      [{ type: "position", id: "protocol_design", position: { x: 8, y: 8 }, dragging: true }],
      [task],
      true,
    );
    expect(dragging?.positions).toEqual({});
    expect(dragging?.dragging).toBe(true);
  });
});
