import type { Vector3 } from "three";

/** Internal framing for the approved close perspective and its flat view. */
export function memoryGraphCosmosOverviewDistance(options: {
  THREE: Pick<typeof import("three"), "Vector3">;
  nodes: readonly { x: number; y: number; z: number }[];
  target: Vector3;
  perspectiveDirection: Vector3;
  tangent: number;
  aspect: number;
  preferredDistance: number;
}) {
  const { nodes, target, perspectiveDirection, tangent, aspect, preferredDistance } = options;
  const { Vector3 } = options.THREE;
  let distance = preferredDistance;
  const relative = new Vector3();
  // The same overview distance also backs the existing flat-mode transition.
  for (const direction of [perspectiveDirection, new Vector3(0, 0, 1)]) {
    const right = new Vector3().crossVectors(new Vector3(0, 1, 0), direction).normalize();
    const up = new Vector3().crossVectors(direction, right).normalize();
    for (const node of nodes) {
      relative.set(node.x, node.y, node.z).sub(target);
      const horizontal = (Math.abs(relative.dot(right)) + 0.75) / (tangent * aspect);
      const vertical = (Math.abs(relative.dot(up)) + 0.75) / tangent;
      // Include depth along the actual view axis. A global distance multiplier
      // can crop deep or wide graphs even when their planar bounds fit.
      distance = Math.max(distance, relative.dot(direction) + Math.max(horizontal, vertical) * 1.1);
    }
  }
  return distance;
}
