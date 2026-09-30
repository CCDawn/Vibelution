import type * as Three from "three";

/** A soft volumetric field integrated through a sphere, not a flat billboard. */
export function nebulaMaterial(
  THREE: typeof Three,
  center: Three.Vector3,
  radius: number,
  color: number,
  seed: number,
  strength: number,
): Three.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    depthTest: false,
    side: THREE.BackSide,
    uniforms: {
      center: { value: center.clone() },
      radius: { value: radius },
      tint: { value: new THREE.Color(color) },
      seed: { value: seed },
      strength: { value: strength },
    },
    vertexShader: `
      varying vec3 worldPoint;
      void main() {
        vec4 point = modelMatrix * vec4(position, 1.0);
        worldPoint = point.xyz;
        gl_Position = projectionMatrix * viewMatrix * point;
      }
    `,
    fragmentShader: `
      precision highp float;
      varying vec3 worldPoint;
      uniform vec3 center;
      uniform float radius;
      uniform vec3 tint;
      uniform float seed;
      uniform float strength;

      float hash(vec3 point) {
        return fract(sin(dot(point, vec3(127.1, 311.7, 74.7)) + seed) * 43758.5453);
      }

      float noise3(vec3 point) {
        vec3 cell = floor(point);
        vec3 fraction = fract(point);
        fraction = fraction * fraction * (3.0 - 2.0 * fraction);
        return mix(
          mix(
            mix(hash(cell), hash(cell + vec3(1.0, 0.0, 0.0)), fraction.x),
            mix(hash(cell + vec3(0.0, 1.0, 0.0)), hash(cell + vec3(1.0, 1.0, 0.0)), fraction.x),
            fraction.y
          ),
          mix(
            mix(hash(cell + vec3(0.0, 0.0, 1.0)), hash(cell + vec3(1.0, 0.0, 1.0)), fraction.x),
            mix(hash(cell + vec3(0.0, 1.0, 1.0)), hash(cell + vec3(1.0, 1.0, 1.0)), fraction.x),
            fraction.y
          ),
          fraction.z
        );
      }

      float fbm(vec3 point) {
        return noise3(point) * 0.58
          + noise3(point * 2.08 + 13.7) * 0.28
          + noise3(point * 4.13 - 8.4) * 0.14;
      }

      void main() {
        vec3 rayOrigin = (cameraPosition - center) / radius;
        vec3 rayDirection = normalize(worldPoint - cameraPosition);
        float b = dot(rayOrigin, rayDirection);
        float c = dot(rayOrigin, rayOrigin) - 1.0;
        float discriminant = b * b - c;
        if (discriminant < 0.0) discard;

        float start = max(0.0, -b - sqrt(discriminant));
        float end = -b + sqrt(discriminant);
        float stepSize = (end - start) / 24.0;
        vec3 rgb = vec3(0.0);
        float alpha = 0.0;
        for (int index = 0; index < 24; index++) {
          vec3 point = rayOrigin + rayDirection * (start + (float(index) + 0.5) * stepSize);
          float shell = pow(max(0.0, 1.0 - dot(point, point)), 1.8);
          float cloud = fbm(point * 3.4 + vec3(seed));
          float filament = smoothstep(0.31, 0.76, cloud);
          float density = shell * (0.18 + filament * 1.65);
          float sampleAlpha = 1.0 - exp(-density * stepSize * 0.66 * strength);
          vec3 glow = mix(tint * 0.42, tint * 1.35, filament);
          rgb += (1.0 - alpha) * sampleAlpha * glow;
          alpha += (1.0 - alpha) * sampleAlpha;
        }
        if (alpha < 0.008) discard;
        gl_FragColor = vec4(rgb / max(alpha, 0.001), alpha);
      }
    `,
  });
}
