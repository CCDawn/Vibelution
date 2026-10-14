import { expect, it } from "vitest";
import * as THREE from "three";
import { nebulaMaterial } from "./NebulaField";

it("converts the integrated linear nebula color to the renderer output space without changing alpha", () => {
  const center = new THREE.Vector3(2, 4, -5);
  const material = nebulaMaterial(THREE, center, 3.7, 0x94aeca, 11.71, 0.9);
  try {
    expect(material.uniforms.tint.value).toEqual(new THREE.Color(0x94aeca));
    expect(material.uniforms.tint.value.r).toBeLessThan(0x94 / 255);
    const output = material.fragmentShader.slice(material.fragmentShader.indexOf("gl_FragColor ="));
    expect(output).toContain("vec4(rgb / max(alpha, 0.001), alpha)");
    expect(output).toContain("#include <colorspace_fragment>");
    expect(THREE.ShaderChunk.colorspace_fragment).toContain("linearToOutputTexel( gl_FragColor )");
    expect(material.transparent).toBe(true);
    expect(material.depthWrite).toBe(false);
    expect(material.uniforms.center.value).toEqual(center);
    expect(material.uniforms.center.value).not.toBe(center);
  } finally {
    material.dispose();
  }
});
