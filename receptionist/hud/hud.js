import * as THREE from "./vendor/three.module.min.js";

const canvas = document.getElementById("c");
const elState = document.getElementById("state");
const elLine = document.getElementById("line");
const elHint = document.getElementById("hint");

const hud = { state: "idle", level: 0, line: "", name: "J.A.R.V.I.S." };

const PALETTE = {
  idle: new THREE.Color(0x00a0c8),
  listening: new THREE.Color(0xffb020),
  thinking: new THREE.Color(0x50dcff),
  speaking: new THREE.Color(0x00e5ff),
};

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  powerPreference: "high-performance",
});
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.setClearColor(0x01040a, 1);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x01040a, 0.085);

const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 80);
camera.position.set(0, 0.12, 5.4);

const group = new THREE.Group();
scene.add(group);

scene.add(new THREE.AmbientLight(0x071018, 1.2));
const coreLight = new THREE.PointLight(0x00e5ff, 12, 16);
scene.add(coreLight);
const rim = new THREE.PointLight(0x004466, 4, 20);
rim.position.set(-3, 2, 4);
scene.add(rim);

function addGlow(geo, color, opacity) {
  return new THREE.Mesh(
    geo,
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );
}

const core = addGlow(new THREE.IcosahedronGeometry(0.32, 2), 0x7eeeff, 0.22);
const coreWire = new THREE.Mesh(
  new THREE.IcosahedronGeometry(0.34, 1),
  new THREE.MeshBasicMaterial({
    color: 0x00e5ff,
    wireframe: true,
    transparent: true,
    opacity: 0.55,
  })
);
group.add(core, coreWire);

const rings = [];
const ringSpecs = [
  [0.85, 0.012, 0.9, 0.4, 0.2],
  [1.25, 0.01, 1.2, -0.55, 0.35],
  [1.72, 0.014, 0.7, 0.8, -0.15],
  [2.18, 0.008, 1.6, -0.3, 0.55],
  [2.65, 0.018, 0.45, 0.15, -0.4],
];
for (const [r, tube, speed, tiltX, tiltZ] of ringSpecs) {
  const mesh = addGlow(new THREE.TorusGeometry(r, tube, 12, 128), 0x00c8e8, 0.8);
  mesh.rotation.x = Math.PI / 2 + tiltX;
  mesh.rotation.z = tiltZ;
  mesh.userData = { speed, tiltX, tiltZ };
  group.add(mesh);
  rings.push(mesh);
}

const disc = addGlow(new THREE.RingGeometry(0.55, 2.9, 96), 0x003344, 0.18);
disc.rotation.x = -Math.PI / 2;
disc.position.y = -0.02;
group.add(disc);

const COUNT = 1200;
const positions = new Float32Array(COUNT * 3);
for (let i = 0; i < COUNT; i++) {
  const r = 3.2 + Math.random() * 7;
  const th = Math.random() * Math.PI * 2;
  const ph = Math.acos(2 * Math.random() - 1);
  positions[i * 3] = r * Math.sin(ph) * Math.cos(th);
  positions[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th) * 0.55;
  positions[i * 3 + 2] = r * Math.cos(ph);
}
const pgeo = new THREE.BufferGeometry();
pgeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
const points = new THREE.Points(
  pgeo,
  new THREE.PointsMaterial({
    color: 0x3ad7ff,
    size: 0.025,
    transparent: true,
    opacity: 0.65,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
);
scene.add(points);

function resize() {
  const w = innerWidth;
  const h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();

addEventListener("keydown", (e) => {
  if (e.key !== "f" && e.key !== "F") return;
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
});

async function poll() {
  try {
    const r = await fetch("/state", { cache: "no-store" });
    Object.assign(hud, await r.json());
  } catch (_) {}
}
setInterval(poll, 80);
poll();

const color = new THREE.Color();
const target = new THREE.Color();
let t0 = performance.now();

function hintFor(state) {
  if (state === "listening") return "LISTENING";
  if (state === "thinking") return "PROCESSING";
  if (state === "speaking") return hud.line || "SPEAKING";
  return "HOLD HOME TO SPEAK    ·    F FULLSCREEN";
}

function draw(now) {
  const t = (now - t0) / 1000;
  const state = hud.state || "idle";
  document.body.className = state;
  elState.textContent = state.toUpperCase();
  elLine.textContent = state === "speaking" ? hud.line || "" : "";
  elHint.textContent = hintFor(state);

  target.copy(PALETTE[state] || PALETTE.idle);
  color.lerp(target, 0.08);
  const hex = color.getHex();
  coreLight.color.copy(color);
  coreLight.intensity = state === "speaking" ? 16 : state === "listening" ? 14 : 10;
  core.material.color.copy(color);
  coreWire.material.color.copy(color);
  points.material.color.copy(color);
  disc.material.color.copy(color);

  const pulse =
    state === "idle"
      ? 0.08 * Math.sin(t * 1.5)
      : state === "listening"
        ? 0.16 * Math.sin(t * 7)
        : state === "thinking"
          ? 0.12 * Math.sin(t * 11)
          : 0.2 * Math.sin(t * 16);
  const s = 1 + pulse;
  core.scale.setScalar(s);
  coreWire.scale.setScalar(s * 1.04);
  core.rotation.y = t * 0.35;
  coreWire.rotation.y = -t * 0.55;
  coreWire.rotation.x = t * 0.2;

  const spin = state === "thinking" ? 1.8 : state === "listening" ? -1.1 : state === "speaking" ? 2.4 : 0.28;
  rings.forEach((ring, i) => {
    ring.material.color.setHex(hex);
    ring.material.opacity = 0.55 + 0.25 * Math.sin(t * 2 + i);
    ring.rotation.z += ring.userData.speed * spin * 0.008;
    ring.rotation.x = Math.PI / 2 + ring.userData.tiltX + 0.08 * Math.sin(t * 0.6 + i);
  });

  points.rotation.y = t * 0.04;
  points.rotation.x = 0.08 * Math.sin(t * 0.3);
  camera.position.x = Math.sin(t * 0.12) * 0.35;
  camera.position.y = 0.12 + Math.sin(t * 0.17) * 0.08;
  camera.lookAt(0, 0, 0);

  renderer.render(scene, camera);
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
