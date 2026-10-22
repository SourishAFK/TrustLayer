import * as THREE from 'three';

/**
 * The site's background: thousands of "claims" on a clock face. A sweeping hand checks them as
 * it passes — most light up cyan (supported), a few flare ember (caught mistakes) and stay lit
 * longer. Scrolling morphs the ring into a globe ("a trust grade for every AI").
 * No post-processing: the glow is additive soft points, so the canvas stays transparent.
 */
export type FieldState = {
  morph: number; opacity: number; x: number; y: number; scale: number; tilt: number; speed: number;
};

const VERT = /* glsl */ `
  attribute vec3 aRing;
  attribute vec3 aSphere;
  attribute float aAngle;
  attribute float aLon;
  attribute float aSeed;
  uniform float uTime, uSweep, uMorph, uSize, uPixelRatio, uOpacity;
  uniform vec3 uCalm, uOk, uBad;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float m = clamp(uMorph * 1.7 - aSeed * 0.7, 0.0, 1.0);
    m = m * m * (3.0 - 2.0 * m);
    vec3 p = mix(aRing, aSphere, m);
    p += 0.035 * vec3(sin(uTime * 0.7 + aSeed * 40.0), cos(uTime * 0.6 + aSeed * 31.0), sin(uTime * 0.5 + aSeed * 23.0));
    float ang = mix(aAngle, aLon, m);
    float d = mod(ang - uSweep, 6.2831853);
    float flash = exp(-d * 2.4);
    float bad = step(aSeed, 0.055);
    float memory = bad * 0.85 * exp(-d * 0.3);
    vColor = mix(uCalm, mix(uOk, uBad, bad), clamp(flash * 1.2 + memory, 0.0, 1.0));
    vAlpha = clamp(0.5 + flash * 1.2 + memory, 0.0, 1.0) * uOpacity;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * (0.55 + aSeed * 0.9) * (1.0 + flash * 1.8 + memory * 1.4) * uPixelRatio * (10.0 / -mv.z);
  }`;

const FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0;
    float glow = exp(-r * r * 7.0) + 0.22 * exp(-r * 3.2);
    gl_FragColor = vec4(vColor * glow * vAlpha, glow * vAlpha);
  }`;

const CONE_FRAG = /* glsl */ `
  uniform float uOpacity;
  uniform vec3 uColor;
  varying vec2 vPos;
  void main() {
    float t = 1.0 - clamp(atan(vPos.y, vPos.x) / 1.1, 0.0, 1.0);
    float r = length(vPos);
    float a = pow(t, 4.0) * smoothstep(3.7, 1.0, r) * smoothstep(0.2, 1.2, r) * 0.32 * uOpacity;
    gl_FragColor = vec4(uColor * a, a);
  }`;

const gauss = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;

export function createField(canvas: HTMLCanvasElement, { reduced, lite }: { reduced: boolean; lite: boolean }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setClearColor(0x000000, 0);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, lite ? 1.25 : 1.75);
  renderer.setPixelRatio(pixelRatio);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 120);
  camera.position.set(0, 0, 10);
  const world = new THREE.Group();
  const dial = new THREE.Group();
  world.add(dial);
  scene.add(world);

  // Claims on the clock face (ring) and on the globe (sphere).
  const count = lite ? 1600 : 3600;
  const ring = new Float32Array(count * 3), sphere = new Float32Array(count * 3);
  const angle = new Float32Array(count), lon = new Float32Array(count), seed = new Float32Array(count);
  const golden = Math.PI * (1 + Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2;
    const lane = Math.random();
    const radius = lane < 0.72 ? 2.6 + gauss() * 0.14 : lane < 0.88 ? 3.05 + gauss() * 0.03 : 2.05 + gauss() * 0.05;
    ring.set([Math.cos(a) * radius, Math.sin(a) * radius, gauss() * 0.09], i * 3);
    const phi = Math.acos(1 - (2 * (i + 0.5)) / count), theta = golden * i;
    const s = 2.35 + gauss() * 0.04;
    const x = Math.sin(phi) * Math.cos(theta) * s, y = Math.cos(phi) * s, z = Math.sin(phi) * Math.sin(theta) * s;
    sphere.set([x, y, z], i * 3);
    angle[i] = a;
    lon[i] = Math.atan2(z, x) + Math.PI;
    seed[i] = Math.random();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(ring, 3));
  geometry.setAttribute('aRing', new THREE.BufferAttribute(ring, 3));
  geometry.setAttribute('aSphere', new THREE.BufferAttribute(sphere, 3));
  geometry.setAttribute('aAngle', new THREE.BufferAttribute(angle, 1));
  geometry.setAttribute('aLon', new THREE.BufferAttribute(lon, 1));
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  const uniforms = {
    uTime: { value: 0 }, uSweep: { value: 0 }, uMorph: { value: 0 }, uSize: { value: lite ? 11 : 10 },
    uPixelRatio: { value: pixelRatio }, uOpacity: { value: 1 },
    uCalm: { value: new THREE.Color('#5a6fa8') }, uOk: { value: new THREE.Color('#38d6ff') }, uBad: { value: new THREE.Color('#ff5a36') },
  };
  const material = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, uniforms,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  world.add(points);

  // Watch-dial ticks, guide rings, the hand and its radar trail.
  const lineMaterial = (opacity: number, color = '#7b88a6') =>
    new THREE.LineBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
  const ticks: number[] = [];
  for (let i = 0; i < 120; i++) {
    const a = (i / 120) * Math.PI * 2, major = i % 10 === 0;
    const r0 = major ? 3.32 : 3.42, r1 = major ? 3.62 : 3.52;
    ticks.push(Math.cos(a) * r0, Math.sin(a) * r0, 0, Math.cos(a) * r1, Math.sin(a) * r1, 0);
  }
  const tickGeometry = new THREE.BufferGeometry();
  tickGeometry.setAttribute('position', new THREE.Float32BufferAttribute(ticks, 3));
  const tickLines = new THREE.LineSegments(tickGeometry, lineMaterial(0.5));
  const circle = (r: number, opacity: number) => {
    const pts = Array.from({ length: 257 }, (_, i) => {
      const a = (i / 256) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0);
    });
    return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMaterial(opacity));
  };
  const guides = [circle(3.75, 0.22), circle(2.3, 0.1), circle(1.2, 0.08)];
  const hand = new THREE.Group();
  const handLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0.25, 0, 0), new THREE.Vector3(3.7, 0, 0)]),
    lineMaterial(0.9, '#bff6ff'),
  );
  const coneUniforms = { uOpacity: { value: 1 }, uColor: { value: new THREE.Color('#38d6ff') } };
  const cone = new THREE.Mesh(
    new THREE.CircleGeometry(3.7, 64, 0, 1.1),
    new THREE.ShaderMaterial({
      vertexShader: 'varying vec2 vPos; void main(){ vPos = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: CONE_FRAG, uniforms: coneUniforms,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    }),
  );
  hand.add(cone, handLine);
  dial.add(tickLines, ...guides, hand);

  // Tilted orbits for depth, and a far starfield.
  const orbits = new THREE.Group();
  [[1.2, 0.3, 4.4], [-0.9, 0.8, 4.9], [0.4, -1.1, 5.4]].forEach(([rx, ry, r]) => {
    const o = circle(r, 0.07);
    o.rotation.set(rx, ry, 0);
    orbits.add(o);
  });
  world.add(orbits);
  const stars = new Float32Array(900 * 3);
  for (let i = 0; i < 900; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(18 + Math.random() * 30);
    stars.set([v.x, v.y, v.z - 10], i * 3);
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.BufferAttribute(stars, 3));
  const starField = new THREE.Points(starGeometry, new THREE.PointsMaterial({
    color: '#8fa3c7', size: 0.06, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  scene.add(starField);

  const state: FieldState = { morph: 0, opacity: 1, x: 0, y: 0, scale: 1, tilt: 0, speed: 1 };
  const shown = { ...state, opacity: 0 }; // fades in, and glides to its first look
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const onPointer = (e: PointerEvent) => {
    pointer.tx = (e.clientX / window.innerWidth - 0.5) * 2;
    pointer.ty = (e.clientY / window.innerHeight - 0.5) * 2;
  };
  window.addEventListener('pointermove', onPointer, { passive: true });

  const resize = () => {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  resize();
  window.addEventListener('resize', resize);

  let sweep = 0.6, last = performance.now(), frame = 0, running = true;
  const render = (now: number) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const k = reduced ? 1 : 1 - Math.pow(0.0015, dt);
    (Object.keys(state) as (keyof FieldState)[]).forEach(key => { shown[key] += (state[key] - shown[key]) * k; });
    pointer.x += (pointer.tx - pointer.x) * k * 0.6;
    pointer.y += (pointer.ty - pointer.y) * k * 0.6;
    if (!reduced) {
      sweep -= dt * 0.85 * shown.speed;
      uniforms.uTime.value += dt;
    }
    uniforms.uSweep.value = ((sweep % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    uniforms.uMorph.value = shown.morph;
    uniforms.uOpacity.value = shown.opacity;
    const dialOpacity = shown.opacity * Math.max(0, 1 - shown.morph * 1.8);
    hand.rotation.z = uniforms.uSweep.value;
    coneUniforms.uOpacity.value = dialOpacity;
    tickLines.material.opacity = 0.5 * dialOpacity;
    handLine.material.opacity = 0.9 * dialOpacity;
    guides.forEach((g, i) => { g.material.opacity = [0.22, 0.1, 0.08][i] * dialOpacity; });
    orbits.children.forEach(o => { (o as THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>).material.opacity = 0.07 * shown.opacity; });
    orbits.rotation.z = uniforms.uTime.value * 0.03;
    world.position.set(shown.x, shown.y, 0);
    world.scale.setScalar(shown.scale);
    world.rotation.set(shown.tilt + pointer.y * 0.12, pointer.x * 0.18 + uniforms.uTime.value * 0.12 * shown.morph, 0);
    starField.rotation.y = uniforms.uTime.value * 0.01;
    starField.position.set(-pointer.x * 0.4, pointer.y * 0.3, 0);
    (starField.material as THREE.PointsMaterial).opacity = 0.55 * Math.min(1, shown.opacity + 0.4);
    renderer.render(scene, camera);
  };
  const loop = (now: number) => {
    if (!running) return;
    frame = requestAnimationFrame(loop);
    if (!document.hidden) render(now);
  };
  if (reduced) {
    render(performance.now());
  } else {
    frame = requestAnimationFrame(loop);
  }

  return {
    state,
    /** Reduced motion has no loop: draw once after a state change. */
    refresh: () => reduced && render(performance.now()),
    dispose() {
      running = false;
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onPointer);
      window.removeEventListener('resize', resize);
      renderer.dispose();
      scene.traverse(obj => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose();
        (mesh.material as THREE.Material | undefined)?.dispose();
      });
    },
  };
}

export type Field = ReturnType<typeof createField>;
