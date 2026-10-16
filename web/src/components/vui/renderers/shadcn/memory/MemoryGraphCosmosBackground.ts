import type * as Three from "three";

type MemoryGraphCosmosOptions = {
  THREE: typeof Three;
  scene: Three.Scene;
  compact: boolean;
  pixelRatio: number;
  disposeGeometry: <T extends Three.BufferGeometry>(geometry: T) => T;
  disposeMaterial: <T extends Three.Material>(material: T) => T;
};

/** Static celestial scenery. Only the existing scene camera makes it move. */
export function createMemoryGraphCosmosBackground({
  THREE, scene, compact, pixelRatio, disposeGeometry, disposeMaterial,
}: MemoryGraphCosmosOptions): { dispose(): void } {
  const root = new THREE.Group();
  root.name = "memory-graph-cosmos-background";
  root.userData.memoryGraphBackground = true;
  root.userData.decorative = true;
  root.raycast = () => {};

  // One inexpensive sky surface; no volume integration, textures or timers.
  // The infinitely distant sky follows camera translation, but its orientation
  // stays in world space. The finite star shells below supply real parallax.
  const galacticNormal = new THREE.Vector3(0.46, 0.85, -0.24).normalize();
  const skyGeometry = disposeGeometry(new THREE.SphereGeometry(188, 48, 32));
  const skyMaterial = disposeMaterial(new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthTest: false,
    depthWrite: false,
    fog: false,
    toneMapped: false,
    uniforms: { galacticNormal: { value: galacticNormal } },
    vertexShader: `
      varying vec3 skyDirection;
      void main() {
        skyDirection = position;
        vec4 clip = projectionMatrix * viewMatrix * vec4(position + cameraPosition, 1.0);
        // Remain behind geometry even at the far end of the orbit zoom range.
        gl_Position = vec4(clip.xy, clip.w * 0.999999, clip.w);
      }
    `,
    fragmentShader: `
      precision highp float;
      varying vec3 skyDirection;
      uniform vec3 galacticNormal;

      float hash3(vec3 p) {
        p = fract(p * 0.1031);
        p += dot(p, p.yzx + 33.33);
        return fract((p.x + p.y) * p.z);
      }
      float noise3(vec3 p) {
        vec3 cell = floor(p);
        vec3 f = fract(p);
        f = f * f * (3.0 - 2.0 * f);
        return mix(
          mix(mix(hash3(cell), hash3(cell + vec3(1,0,0)), f.x),
              mix(hash3(cell + vec3(0,1,0)), hash3(cell + vec3(1,1,0)), f.x), f.y),
          mix(mix(hash3(cell + vec3(0,0,1)), hash3(cell + vec3(1,0,1)), f.x),
              mix(hash3(cell + vec3(0,1,1)), hash3(cell + vec3(1,1,1)), f.x), f.y), f.z);
      }
      void main() {
        vec3 direction = normalize(skyDirection);
        float latitude = dot(direction, galacticNormal);
        vec3 rgb = vec3(0.0017, 0.0034, 0.0080);
        // The band is broad, broken and asymmetric, with an actual dark lane.
        // Keep all fine detail in the band; empty sky needs no extra octaves.
        if (abs(latitude) < 0.48) {
          float broad = noise3(direction * 4.1 + vec3(7.3, 1.7, 4.8));
          float medium = noise3(direction * 12.8 + vec3(18.1, 6.5, 2.4));
          float fine = noise3(direction * 37.0 + vec3(2.7, 13.1, 9.6));
          float warped = latitude + (broad - 0.5) * 0.105;
          float band = exp(-pow(warped / 0.145, 2.0));
          float veil = exp(-pow(warped / 0.30, 2.0));
          float clouds = smoothstep(0.23, 0.80, broad * 0.55 + medium * 0.32 + fine * 0.13);
          float laneCenter = warped + 0.022 + (medium - 0.5) * 0.052;
          float dust = exp(-pow(laneCenter / 0.027, 2.0));
          float longitude = dot(direction, vec3(0.57, -0.08, 0.82));
          float arm = 0.46 + 0.54 * smoothstep(-0.7, 0.85, longitude);
          float light = band * clouds * arm * (1.0 - dust * 0.79);
          rgb += vec3(0.0025, 0.0037, 0.0065) * veil * clouds;
          rgb += vec3(0.0120, 0.0170, 0.0270) * light;
          rgb *= 1.0 - dust * band * 0.19;
        }
        gl_FragColor = vec4(rgb, 1.0);
        #include <colorspace_fragment>
      }
    `,
  }));
  const sky = new THREE.Mesh(skyGeometry, skyMaterial);
  sky.name = "cosmos-distant-galactic-sky";
  sky.renderOrder = -1000;
  sky.frustumCulled = false;
  sky.raycast = () => {};
  sky.userData.decorative = true;
  root.add(sky);

  // A fixed seed prevents a new constellation after selection/theme updates.
  let state = 0x524c554d;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const gaussian = () => Math.sqrt(-2 * Math.log(Math.max(0.00001, random())))
    * Math.cos(2 * Math.PI * random());
  const bandAxis = new THREE.Vector3(0, 1, 0).cross(galacticNormal).normalize();
  const bandTangent = galacticNormal.clone().cross(bandAxis).normalize();
  const point = new THREE.Vector3();
  const coldWhite = new THREE.Color(0xd4dfee);
  const neutralWhite = new THREE.Color(0xf0f2ed);
  const warmWhite = new THREE.Color(0xf4e5d1);

  const starsMaterial = disposeMaterial(new THREE.ShaderMaterial({
    transparent: true,
    depthTest: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    fog: false,
    toneMapped: false,
    uniforms: { maxPointSize: { value: compact ? 3.0 : 3.6 }, pixelRatio: { value: Math.min(Number.isFinite(pixelRatio) && pixelRatio > 0 ? pixelRatio : 1, 1.75) } },
    vertexShader: `
      attribute vec3 starColor;
      attribute float starSize;
      attribute float starStrength;
      uniform float maxPointSize;
      uniform float pixelRatio;
      varying vec3 tint;
      varying float strength;
      void main() {
        vec4 viewPoint = modelViewMatrix * vec4(position, 1.0);
        tint = starColor;
        // Passing a shell never turns a background star into a giant orb.
        strength = starStrength * smoothstep(18.0, 44.0, length(viewPoint.xyz));
        gl_Position = projectionMatrix * viewPoint;
        gl_PointSize = clamp(starSize * 235.0 / max(1.0, -viewPoint.z), 1.8, maxPointSize) * pixelRatio;
      }
    `,
    fragmentShader: `
      varying vec3 tint;
      varying float strength;
      void main() {
        float radius = length(gl_PointCoord - vec2(0.5)) * 2.0;
        if (radius >= 1.0) discard;
        float core = exp(-radius * radius * 4.5);
        float rim = 1.0 - smoothstep(0.3, 1.0, radius);
        gl_FragColor = vec4(tint, strength * (core * 0.78 + rim * 0.22));
        #include <colorspace_fragment>
      }
    `,
  }));

  const addStarShell = (
    name: string, count: number, inner: number, outer: number,
    luminosity: number, galactic: boolean,
  ) => {
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const strengths = new Float32Array(count);
    for (let index = 0; index < count; index++) {
      if (galactic) {
        const longitude = random() * Math.PI * 2;
        const latitude = Math.max(-0.34, Math.min(0.34, gaussian() * 0.072));
        point.copy(bandAxis).multiplyScalar(Math.cos(longitude) * Math.cos(latitude))
          .addScaledVector(bandTangent, Math.sin(longitude) * Math.cos(latitude))
          .addScaledVector(galacticNormal, Math.sin(latitude));
      } else {
        const vertical = random() * 2 - 1;
        const longitude = random() * Math.PI * 2;
        const circle = Math.sqrt(1 - vertical * vertical);
        point.set(circle * Math.cos(longitude), vertical, circle * Math.sin(longitude));
      }
      point.multiplyScalar(inner + (outer - inner) * random());
      point.toArray(positions, index * 3);
      const temperature = random();
      const color = temperature > 0.975 ? warmWhite : temperature > 0.74 ? neutralWhite : coldWhite;
      color.toArray(colors, index * 3);
      // Most stars stay fine and dim. There are no oversized hero-star flares.
      const prominence = Math.pow(random(), 4);
      sizes[index] = (galactic ? 0.72 : 0.95) + prominence * 1.15;
      strengths[index] = luminosity * (0.55 + prominence * 0.45);
    }
    const geometry = disposeGeometry(new THREE.BufferGeometry());
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("starColor", new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute("starSize", new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute("starStrength", new THREE.BufferAttribute(strengths, 1));
    const stars = new THREE.Points(geometry, starsMaterial);
    stars.name = name;
    stars.renderOrder = -990;
    stars.frustumCulled = false;
    stars.raycast = () => {};
    stars.userData.decorative = true;
    stars.userData.memoryGraphBackground = true;
    root.add(stars);
  };

  addStarShell("cosmos-far-stars", compact ? 2800 : 4600, 150, 175, 0.63, false);
  addStarShell("cosmos-mid-stars", compact ? 650 : 1100, 116, 149, 0.72, false);
  addStarShell("cosmos-near-stars", compact ? 140 : 240, 90, 115, 0.85, false);
  addStarShell("cosmos-galactic-stars", compact ? 1250 : 2100, 156, 174, 0.40, true);
  scene.add(root);

  return {
    dispose() {
      root.removeFromParent();
      root.clear();
      // The engine owns GPU disposal through its supplied resource registry.
      // Do not dispose shared star material here or release resources twice.
    },
  };
}
