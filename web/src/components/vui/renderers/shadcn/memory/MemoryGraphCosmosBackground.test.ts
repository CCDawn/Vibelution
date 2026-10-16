import { afterEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import { createMemoryGraphCosmosBackground } from "./MemoryGraphCosmosBackground";

afterEach(() => vi.unstubAllGlobals());

function setup(compact = false, pixelRatio = 2) {
  const scene = new THREE.Scene();
  const geometries: THREE.BufferGeometry[] = [], materials: THREE.Material[] = [];
  const background = createMemoryGraphCosmosBackground({
    THREE, scene, compact, pixelRatio,
    disposeGeometry: geometry => { geometries.push(geometry); return geometry; },
    disposeMaterial: material => { materials.push(material); return material; },
  });
  return { scene, geometries, materials, background, release() {
    background.dispose();
    geometries.forEach(geometry => geometry.dispose());
    materials.forEach(material => material.dispose());
  } };
}

describe("static memory graph cosmos", () => {
  it("registers every GPU resource, never picks or invents graph records, and only removes on dispose", () => {
    const requestFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    const fixture = setup();
    try {
      const root = fixture.scene.children[0];
      const objects: THREE.Object3D[] = [];
      root.traverse(object => objects.push(object));
      expect(root.name).toBe("memory-graph-cosmos-background");
      expect(root.children).toHaveLength(5);
      expect(fixture.geometries).toHaveLength(5);
      expect(fixture.materials).toHaveLength(2);
      expect(requestFrame).not.toHaveBeenCalled();
      for (const object of objects) {
        expect(object.userData.nodeId).toBeUndefined();
        expect(object.userData.edgeId).toBeUndefined();
        expect(object.userData.recordId).toBeUndefined();
        const intersections: THREE.Intersection[] = [];
        object.raycast(new THREE.Raycaster(), intersections);
        expect(intersections).toEqual([]);
        if (object instanceof THREE.Mesh || object instanceof THREE.Points) {
          expect(fixture.geometries).toContain(object.geometry);
          expect(fixture.materials).toContain(object.material);
        }
      }
      const disposal = [...fixture.geometries, ...fixture.materials].map(resource => vi.spyOn(resource, "dispose"));
      fixture.background.dispose();
      fixture.background.dispose();
      expect(fixture.scene.children).toHaveLength(0);
      expect(root.children).toHaveLength(0);
      expect(disposal.every(spy => spy.mock.calls.length === 0)).toBe(true);
    } finally { fixture.release(); }
  });

  it("keeps deterministic finite-depth star shells and caller-controlled pixel density", () => {
    const first = setup(), second = setup(), compact = setup(true, 1);
    try {
      const firstShells = first.scene.children[0].children.filter(object => object instanceof THREE.Points);
      const secondShells = second.scene.children[0].children.filter(object => object instanceof THREE.Points);
      expect(firstShells.map(shell => shell.geometry.getAttribute("position").count)).toEqual([4600, 1100, 240, 2100]);
      expect(compact.scene.children[0].children.filter(object => object instanceof THREE.Points).map(shell => shell.geometry.getAttribute("position").count)).toEqual([2800, 650, 140, 1250]);
      firstShells.forEach((shell, index) => {
        for (const attribute of ["position", "starColor", "starSize", "starStrength"]) {
          expect(shell.geometry.getAttribute(attribute).array).toEqual(secondShells[index].geometry.getAttribute(attribute).array);
        }
        const positions = shell.geometry.getAttribute("position");
        const bounds = [[150, 175], [116, 149], [90, 115], [156, 174]][index];
        for (let i = 0; i < positions.count; i++) {
          const radius = Math.hypot(positions.getX(i), positions.getY(i), positions.getZ(i));
          expect(radius).toBeGreaterThanOrEqual(bounds[0] - 0.001);
          expect(radius).toBeLessThanOrEqual(bounds[1] + 0.001);
        }
      });
      const stars = first.materials[1] as THREE.ShaderMaterial;
      expect(stars.uniforms.pixelRatio.value).toBe(1.75);
      expect((compact.materials[1] as THREE.ShaderMaterial).uniforms.pixelRatio.value).toBe(1);
      const sky = first.scene.children[0].children[0] as THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>;
      expect(sky.material.uniforms.galacticNormal.value.length()).toBeCloseTo(1);
      expect(sky.material.depthWrite).toBe(false);
    } finally { first.release(); second.release(); compact.release(); }
  });
});
