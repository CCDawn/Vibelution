import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { memoryGraphCosmosOverviewDistance } from "./memoryGraphCosmosCamera";

const direction = new Vector3(0.5, 0.28, 1).normalize();
const target = new Vector3(7, -3, 12);
const tangent = Math.tan(44 * Math.PI / 360);

describe("cosmos overview framing", () => {
  it.each([0.28, 0.65, 1, 2.4])("fits wide and deep real bounds at aspect %s in perspective and flat views", aspect => {
    const nodes = Array.from({ length: 500 }, (_, index) => ({
      x: target.x + Math.sin(index * 2.4) * 52,
      y: target.y + Math.cos(index * 1.3) * 27,
      z: target.z + Math.sin(index * 0.7) * 43,
    }));
    const preferredDistance = 65;
    const distance = memoryGraphCosmosOverviewDistance({ THREE: { Vector3 }, nodes, target, perspectiveDirection: direction, tangent, aspect, preferredDistance });
    expect(distance).toBeGreaterThan(preferredDistance);
    for (const viewDirection of [direction, new Vector3(0, 0, 1)]) {
      const camera = new PerspectiveCamera(44, aspect, 0.1, 5000);
      camera.position.copy(target).addScaledVector(viewDirection, distance);
      camera.lookAt(target);
      camera.updateMatrixWorld();
      for (const node of nodes) {
        const projected = new Vector3(node.x, node.y, node.z).project(camera);
        expect(Math.abs(projected.x)).toBeLessThan(1);
        expect(Math.abs(projected.y)).toBeLessThan(1);
        expect(projected.z).toBeGreaterThan(-1);
        expect(projected.z).toBeLessThan(1);
      }
    }
  });

  it("keeps the approved close framing for a small local graph when every node fits", () => {
    const nodes = [-1, 0, 1].map(x => ({ x: target.x + x, y: target.y, z: target.z }));
    expect(memoryGraphCosmosOverviewDistance({ THREE: { Vector3 }, nodes, target, perspectiveDirection: direction, tangent, aspect: 1.5, preferredDistance: 10.08 })).toBe(10.08);
  });
});
