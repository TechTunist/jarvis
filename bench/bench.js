import * as THREE from "three";

const canvas = document.getElementById("c");
const listEl = document.getElementById("list");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1410);

const camera = new THREE.PerspectiveCamera(45, 1, 1, 20000);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

scene.add(new THREE.AmbientLight(0xfff2dd, 0.55));
const sun = new THREE.DirectionalLight(0xffe6c0, 1.1);
sun.position.set(800, 1400, 600);
scene.add(sun);

const grid = new THREE.GridHelper(4000, 40, 0x6a5030, 0x3a2a18);
scene.add(grid);

const group = new THREE.Group();
scene.add(group);

const wood = new THREE.MeshLambertMaterial({ color: 0xb58a4a });
const woodEdge = new THREE.LineBasicMaterial({ color: 0x5a3a18 });

let parts = [];
let az = 0.7, el = 0.45, dist = 2200;
const target = new THREE.Vector3(800, 0, 0);
let dragging = false, lastX = 0, lastY = 0;

function resize() {
  const w = innerWidth, h = innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h, false);
}
addEventListener("resize", resize);
resize();

function placeCamera() {
  const x = target.x + dist * Math.cos(el) * Math.sin(az);
  const y = target.y + dist * Math.sin(el);
  const z = target.z + dist * Math.cos(el) * Math.cos(az);
  camera.position.set(x, y, z);
  camera.lookAt(target);
}

function rebuild() {
  while (group.children.length) {
    const ch = group.children[0];
    group.remove(ch);
    if (ch.geometry) ch.geometry.dispose();
  }
  let maxL = 400;
  for (const p of parts) {
    const L = p.length_mm || 100;
    const W = p.width_mm || 40;
    const T = p.thickness_mm || 15;
    const up = !!p.upright;
    const geom = up
      ? new THREE.BoxGeometry(T, L, W)
      : new THREE.BoxGeometry(L, T, W);
    const mesh = new THREE.Mesh(geom, wood);
    mesh.position.set(
      (p.x_mm || 0) + (up ? T : L) / 2,
      (p.z_mm || 0) + (up ? L : T) / 2,
      (p.y_mm || 0) + W / 2
    );
    group.add(mesh);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom), woodEdge);
    edges.position.copy(mesh.position);
    group.add(edges);
    maxL = Math.max(maxL, L, 400);
  }
  target.x = maxL / 2;
  dist = Math.max(900, maxL * 1.2);
  listEl.innerHTML = parts.length
    ? parts
        .map(
          (p) =>
            `<div class="part"><strong>${p.name || p.kind}</strong><div class="dim">${p.length_mm} × ${p.width_mm} × ${p.thickness_mm} mm · ${p.upright ? "vertical" : "flat"}</div></div>`
        )
        .join("")
    : "Empty.";
}

async function poll() {
  try {
    const s = await (await fetch("/api/scene", { cache: "no-store" })).json();
    const next = s.parts || [];
    if (JSON.stringify(next) !== JSON.stringify(parts)) {
      parts = next;
      rebuild();
    }
  } catch (_) {}
}
setInterval(poll, 400);
poll();

canvas.addEventListener("pointerdown", (e) => {
  dragging = true;
  lastX = e.clientX;
  lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointerup", () => {
  dragging = false;
});
canvas.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  az -= (e.clientX - lastX) * 0.005;
  el += (e.clientY - lastY) * 0.005;
  el = Math.max(0.08, Math.min(1.2, el));
  lastX = e.clientX;
  lastY = e.clientY;
});
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    dist *= e.deltaY > 0 ? 1.08 : 0.92;
    dist = Math.max(200, Math.min(12000, dist));
  },
  { passive: false }
);

function tick() {
  placeCamera();
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
tick();
