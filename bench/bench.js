import * as THREE from "three";

const canvas = document.getElementById("c");
const listEl = document.getElementById("list");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1410);

const camera = new THREE.PerspectiveCamera(45, 1, 1, 20000);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x1a1410, 1);
renderer.autoClear = false;

scene.add(new THREE.AmbientLight(0xfff2dd, 0.55));
const sun = new THREE.DirectionalLight(0xffe6c0, 1.1);
sun.position.set(800, 1400, 600);
scene.add(sun);

const GRID_MM = 4000;
const GRID_DIVS = 40;
const GRID_CELL_MM = GRID_MM / GRID_DIVS;
const grid = new THREE.GridHelper(GRID_MM, GRID_DIVS, 0x6a5030, 0x3a2a18);
scene.add(grid);
const cellEl = document.getElementById("grid-cell");
const spanEl = document.getElementById("grid-span");
if (cellEl) cellEl.textContent = GRID_CELL_MM + " mm";
if (spanEl) spanEl.textContent = GRID_MM + " mm";

function axisLabel(text, color) {
  const c = document.createElement("canvas");
  c.width = 160;
  c.height = 160;
  const g = c.getContext("2d");
  g.fillStyle = color;
  g.font = "bold 112px sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, 80, 80);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false })
  );
  sprite.scale.set(140, 140, 1);
  return sprite;
}

function addAxes(len = 600) {
  // Scene JSON: x along, y across, z up → three.js x, z, y.
  const root = new THREE.Group();
  const line = (to, color) => {
    const geom = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, 0, 0),
      to,
    ]);
    return new THREE.Line(geom, new THREE.LineBasicMaterial({ color }));
  };
  root.add(line(new THREE.Vector3(len, 0, 0), 0xff5555));
  root.add(line(new THREE.Vector3(0, 0, len), 0x44cc55));
  root.add(line(new THREE.Vector3(0, len, 0), 0x5599ff));
  const x = axisLabel("X", "#ff6666");
  x.position.set(len + 90, 50, 0);
  const y = axisLabel("Y", "#55dd66");
  y.position.set(0, 50, len + 90);
  const z = axisLabel("Z", "#77aaff");
  z.position.set(50, len + 90, 0);
  root.add(x, y, z);
  scene.add(root);
}
addAxes();

const group = new THREE.Group();
scene.add(group);
const siteGroup = new THREE.Group();
scene.add(siteGroup);
const overlay = new THREE.Scene();
const gizmo = new THREE.Group();
gizmo.renderOrder = 1000;
overlay.add(gizmo);
const spinViz = new THREE.Group();
overlay.add(spinViz);

const WOOD = 0xb58a4a;
const WOOD_HOVER = 0xc9a56a;
const WOOD_SEL = 0xdbb57a;
const woodEdge = new THREE.LineBasicMaterial({ color: 0x5a3a18 });
const wallMat = new THREE.MeshLambertMaterial({
  color: 0x6a5848,
  transparent: true,
  opacity: 0.35,
});
const floorMat = new THREE.MeshLambertMaterial({
  color: 0x3a2a18,
  transparent: true,
  opacity: 0.35,
});

let parts = [];
let site = {};
let stock = [];
let check = {};
let az = 0.7, el = 0.45, dist = 2200;
const target = new THREE.Vector3(800, 0, 0);
let dragging = false, moved = false, lastX = 0, lastY = 0;
let dragMode = "orbit";
let cameraTouched = false;
let framedOnce = false;
let camRev = 0;
let camTimer = 0;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let pickables = [];
let hoverIdx = -1;
let selectedIds = [];
let selectDownIdx = -1;
let editId = "";
let faceHandles = [];
let faceHover = null;
let faceDrag = null;
let moveDrag = null;
let rotateMode = false;
let rotateHover = null;
let rotateDrag = null;
let undoStack = [];
let redoStack = [];
let clip = null;
let pasteN = 0;
let mutating = false;
const MIN_DIM = 1;
const FACE_COL = 0xf0c060;
const SNAP_DEG = 15;

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
  const look = document.getElementById("look-at");
  const dEl = document.getElementById("cam-dist");
  if (look) {
    look.textContent =
      Math.round(target.x) +
      ", " +
      Math.round(target.z) +
      ", " +
      Math.round(target.y);
  }
  if (dEl) dEl.textContent = Math.round(dist) + " mm";
}

function cameraState() {
  return {
    look_x_mm: target.x,
    look_y_mm: target.z,
    look_z_mm: target.y,
    az,
    el,
    dist_mm: dist,
  };
}

function applyCameraState(c) {
  if (!c) return;
  if (c.look_x_mm != null) target.x = Number(c.look_x_mm);
  if (c.look_y_mm != null) target.z = Number(c.look_y_mm);
  if (c.look_z_mm != null) target.y = Number(c.look_z_mm);
  if (c.az != null) az = Number(c.az);
  if (c.el != null) el = Number(c.el);
  if (c.dist_mm != null) dist = Number(c.dist_mm);
  el = Math.max(0.08, Math.min(1.2, el));
  dist = Math.max(200, Math.min(12000, dist));
}

function pushCamera() {
  cameraTouched = true;
  clearTimeout(camTimer);
  camTimer = setTimeout(postCamera, 280);
}

async function postCamera() {
  try {
    const resp = await fetch("/api/camera", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cameraState()),
    });
    const data = await resp.json();
    if (data.camera && data.camera.rev != null) camRev = data.camera.rev;
  } catch (_) {}
}

function panView(dxPix, dyPix) {
  camera.updateMatrixWorld();
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  const scale = (2 * dist * Math.tan((camera.fov * Math.PI) / 360)) / Math.max(1, canvas.clientHeight);
  target.addScaledVector(right, -dxPix * scale);
  target.addScaledVector(up, dyPix * scale);
}

function frameParts() {
  if (!parts.length) {
    target.set(800, 0, 0);
    dist = 2200;
    return;
  }
  const box = new THREE.Box3();
  group.updateMatrixWorld(true);
  box.setFromObject(group);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 400);
  target.copy(c);
  dist = Math.max(900, span * 1.6);
}

function wantsPan(e) {
  return (
    e.button === 1 ||
    e.button === 2 ||
    (e.buttons & 2) !== 0 ||
    (e.buttons & 4) !== 0
  );
}

function sceneBox(x, y, z, sx, sy, sz, mat) {
  const geom = new THREE.BoxGeometry(sx, sz, sy);
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.set(x + sx / 2, z + sz / 2, y + sy / 2);
  return mesh;
}

function rebuildSite() {
  while (siteGroup.children.length) {
    const ch = siteGroup.children[0];
    siteGroup.remove(ch);
    if (ch.geometry) ch.geometry.dispose();
  }
  const w = site.width_mm || 0;
  const L = site.length_mm || 0;
  if (w <= 0 || L <= 0) return;
  const wall = site.wall_height_mm || site.min_headroom_mm || 2000;
  const house = site.house_height_mm || wall * 2;
  siteGroup.add(sceneBox(0, 0, -4, L, w, 8, floorMat));
  siteGroup.add(sceneBox(0, -80, 0, L, 80, house, wallMat));
  siteGroup.add(sceneBox(0, w, 0, L, 80, wall, wallMat));
}

function mark(ok) {
  return ok ? "yes" : "no";
}

function partLine(p) {
  return (
    (p.length_mm || 0) +
    " × " +
    (p.width_mm || 0) +
    " × " +
    (p.thickness_mm || 0) +
    " mm · " +
    (p.upright ? "vertical" : "flat")
  );
}

function partLoc(p) {
  return (
    "@ " +
    (p.x_mm || 0) +
    ", " +
    (p.y_mm || 0) +
    ", " +
    (p.z_mm || 0) +
    " mm"
  );
}

function partRot(p) {
  return (
    "rot " +
    (p.rx_deg || 0) +
    "°, " +
    (p.ry_deg || 0) +
    "°, " +
    (p.rz_deg || 0) +
    "°"
  );
}

function partKey(p) {
  return (p && (p.id || p.name)) || "";
}

function selectedIndex() {
  if (!selectedIds.length) return -1;
  const key = selectedIds[selectedIds.length - 1];
  return parts.findIndex((p) => partKey(p) === key);
}

function selectedIndices() {
  const keys = new Set(selectedIds);
  const out = [];
  parts.forEach((p, i) => {
    if (keys.has(partKey(p))) out.push(i);
  });
  return out;
}

function isSelectedIdx(idx) {
  const p = parts[idx];
  return !!(p && selectedIds.includes(partKey(p)));
}

function selectOnly(idx) {
  const p = parts[idx];
  selectedIds = p ? [partKey(p)] : [];
}

function toggleSelect(idx) {
  const p = parts[idx];
  if (!p) return;
  const k = partKey(p);
  const at = selectedIds.indexOf(k);
  if (at >= 0) selectedIds.splice(at, 1);
  else selectedIds.push(k);
}

function clearSelection() {
  selectedIds = [];
}

function pruneSelection() {
  const live = new Set(parts.map(partKey).filter(Boolean));
  selectedIds = selectedIds.filter((k) => live.has(k));
}

function tintMesh(mesh, mode) {
  const mat = mesh.material;
  if (mode === "sel") {
    mat.color.setHex(WOOD_SEL);
    mat.emissive.setHex(0x4a3010);
  } else if (mode === "hover") {
    mat.color.setHex(WOOD_HOVER);
    mat.emissive.setHex(0x2a1a08);
  } else {
    mat.color.setHex(WOOD);
    mat.emissive.setHex(0x000000);
  }
}

function applyTint() {
  for (const mesh of pickables) {
    const i = mesh.userData.idx;
    tintMesh(mesh, isSelectedIdx(i) ? "sel" : i === hoverIdx ? "hover" : "");
  }
  if (!listEl) return;
  for (const el of listEl.querySelectorAll(".part")) {
    const i = Number(el.dataset.idx);
    el.classList.toggle("selected", isSelectedIdx(i));
    el.classList.toggle("hover", i === hoverIdx && !isSelectedIdx(i));
  }
}

function nameInputEl() {
  return document.getElementById("inspect-name-input");
}

function typingInName() {
  const el = nameInputEl();
  return !!(el && document.activeElement === el);
}

function showInspect(idx) {
  const box = document.getElementById("inspect");
  const nameEl = document.getElementById("inspect-name");
  const nameIn = nameInputEl();
  const dimEl = document.getElementById("inspect-dim");
  const titleEl = document.getElementById("inspect-title");
  const hintEl = document.getElementById("inspect-hint");
  const locEl = document.getElementById("inspect-loc");
  const rotEl = document.getElementById("inspect-rot");
  if (!box || !nameEl || !dimEl) return;
  if (idx < 0 || !parts[idx]) {
    box.hidden = true;
    nameEl.textContent = "";
    nameEl.hidden = false;
    if (nameIn) {
      nameIn.hidden = true;
      nameIn.value = "";
    }
    dimEl.textContent = "";
    if (locEl) locEl.textContent = "";
    if (rotEl) rotEl.textContent = "";
    if (hintEl) hintEl.hidden = true;
    if (titleEl) titleEl.textContent = "PART";
    syncActions();
    return;
  }
  const p = parts[idx];
  const nSel = selectedIds.length;
  const editing = editId && (p.id || p.name) === editId && nSel === 1;
  const label = p.name || p.kind || "board";
  box.hidden = false;
  if (titleEl) {
    titleEl.textContent = rotateMode ? "ROTATE" : editing ? "EDIT" : nSel > 1 ? "PARTS" : "PART";
  }
  if (nSel > 1) {
    nameEl.hidden = false;
    nameEl.textContent = nSel + " selected";
    if (nameIn) nameIn.hidden = true;
    dimEl.textContent = "Transforms apply to all.";
    if (locEl) locEl.textContent = "";
    if (rotEl) rotEl.textContent = "";
  } else {
    dimEl.textContent = partLine(p);
    if (locEl) locEl.textContent = partLoc(p);
    if (rotEl) rotEl.textContent = partRot(p);
    if (editing && nameIn) {
      nameEl.hidden = true;
      nameIn.hidden = false;
      if (!typingInName()) nameIn.value = label;
    } else {
      nameEl.hidden = false;
      nameEl.textContent = label;
      if (nameIn) nameIn.hidden = true;
    }
  }
  if (hintEl) {
    if (rotateMode) {
      hintEl.hidden = false;
      hintEl.textContent =
        nSel > 1
          ? "Hover a face. Drag to rotate all selected. 15° snap, Shift free."
          : "Hover a face. Drag around the axis. 15° snap, Shift free.";
    } else if (editing) {
      hintEl.hidden = false;
      hintEl.textContent = "Rename here. Drag a face in or out.";
    } else {
      hintEl.hidden = false;
      hintEl.textContent =
        nSel > 1
          ? "Drag an axis to move all. Shift-drag free. R rotate."
          : "Drag an axis. Shift-drag free. R rotate. Shift-click add.";
    }
  }
  syncActions();
}

async function postRename(p) {
  if (!p) return;
  try {
    await fetch("/api/ops", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops: [{ op: "rename", id: p.id, to: p.name }] }),
    });
  } catch (_) {}
}

function commitNameEdit() {
  const el = nameInputEl();
  const idx = selectedIndex();
  if (!el || idx < 0 || !parts[idx]) return;
  const p = parts[idx];
  const prev = String(p.name || "");
  const next = el.value.trim();
  if (!next || next === prev) {
    el.value = prev || p.kind || "board";
    return;
  }
  pushUndo();
  p.name = next;
  postRename(p);
  const row = listEl && listEl.querySelector(`.part[data-idx="${idx}"] strong`);
  if (row) row.textContent = next;
  showInspect(idx);
}

function bindNameEdit() {
  const el = nameInputEl();
  if (!el || el.dataset.bound) return;
  el.dataset.bound = "1";
  el.addEventListener("change", commitNameEdit);
  el.addEventListener("blur", commitNameEdit);
  el.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      el.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      const idx = selectedIndex();
      el.value = idx >= 0 && parts[idx] ? parts[idx].name || "" : el.value;
      el.blur();
    }
  });
}
bindNameEdit();

function syncActions() {
  const sel = selectedIds.length > 0;
  const cut = document.getElementById("act-cut");
  const copy = document.getElementById("act-copy");
  const paste = document.getElementById("act-paste");
  const del = document.getElementById("act-delete");
  if (cut) cut.disabled = !sel;
  if (copy) copy.disabled = !sel;
  if (del) del.disabled = !sel;
  if (paste) paste.disabled = !clip;
}

function clonePart(p) {
  return {
    kind: p.kind || "board",
    name: p.name || "",
    length_mm: p.length_mm,
    width_mm: p.width_mm,
    thickness_mm: p.thickness_mm,
    x_mm: p.x_mm || 0,
    y_mm: p.y_mm || 0,
    z_mm: p.z_mm || 0,
    rx_deg: p.rx_deg || 0,
    ry_deg: p.ry_deg || 0,
    rz_deg: p.rz_deg || 0,
    upright: !!p.upright,
    role: p.role || "",
  };
}

function applyScene(s) {
  if (!s) return;
  if (Array.isArray(s.parts)) parts = s.parts;
  if (s.site) site = s.site;
  if (s.stock) stock = s.stock;
  if (s.check) check = s.check;
  rebuild();
}

async function postOps(ops) {
  const resp = await fetch("/api/ops", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops }),
  });
  return await resp.json();
}

function copySelected() {
  const idxs = selectedIndices();
  if (!idxs.length) return;
  clip = idxs.map((i) => clonePart(parts[i]));
  pasteN = 0;
  syncActions();
}

async function deleteSelected() {
  const idxs = selectedIndices();
  if (!idxs.length) return;
  pushUndo();
  mutating = true;
  try {
    const ops = idxs.map((i) => ({
      op: "delete",
      id: parts[i].id,
      name: parts[i].name,
    }));
    const data = await postOps(ops);
    if (!data || data.error || !data.scene) {
      undoStack.pop();
      return;
    }
    clearSelection();
    editId = "";
    rotateMode = false;
    clearSpinViz();
    applyScene(data.scene);
  } catch (_) {
    undoStack.pop();
  } finally {
    mutating = false;
  }
}

async function cutSelected() {
  const idxs = selectedIndices();
  if (!idxs.length) return;
  clip = idxs.map((i) => clonePart(parts[i]));
  pasteN = 0;
  syncActions();
  await deleteSelected();
}

async function pasteClipboard() {
  if (!clip) return;
  const items = Array.isArray(clip) ? clip : [clip];
  if (!items.length) return;
  pasteN += 1;
  pushUndo();
  mutating = true;
  try {
    const before = new Set(parts.map((p) => p.id));
    const ops = items.map((spec) => {
      const s = clonePart(spec);
      s.y_mm = (Number(spec.y_mm) || 0) + pasteN * 100;
      return {
        op: "add",
        length_mm: s.length_mm,
        width_mm: s.width_mm,
        thickness_mm: s.thickness_mm,
        name: s.name,
        upright: s.upright,
        x_mm: s.x_mm,
        y_mm: s.y_mm,
        z_mm: s.z_mm,
        rx_deg: s.rx_deg,
        ry_deg: s.ry_deg,
        rz_deg: s.rz_deg,
        role: s.role,
      };
    });
    const data = await postOps(ops);
    if (!data || data.error || !data.scene) {
      undoStack.pop();
      pasteN -= 1;
      return;
    }
    selectedIds = (data.scene.parts || [])
      .filter((p) => p.id && !before.has(p.id))
      .map(partKey);
    editId = "";
    rotateMode = false;
    clearSpinViz();
    applyScene(data.scene);
  } catch (_) {
    undoStack.pop();
    pasteN -= 1;
  } finally {
    mutating = false;
  }
}

function pickAt(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(pickables, false);
  if (!hits.length) return -1;
  return hits[0].object.userData.idx;
}

function localSize(p) {
  const L = p.length_mm || 100;
  const W = p.width_mm || 40;
  const T = p.thickness_mm || 15;
  if (p.upright) return { sx: T, sy: L, sz: W };
  return { sx: L, sy: T, sz: W };
}

function writeLocalSize(p, sx, sy, sz) {
  const x = Math.max(MIN_DIM, sx);
  const y = Math.max(MIN_DIM, sy);
  const z = Math.max(MIN_DIM, sz);
  if (p.upright) {
    p.thickness_mm = round1(x);
    p.length_mm = round1(y);
    p.width_mm = round1(z);
  } else {
    p.length_mm = round1(x);
    p.thickness_mm = round1(y);
    p.width_mm = round1(z);
  }
}

function round1(n) {
  return Math.round(Number(n) * 10) / 10;
}

function editIndex() {
  if (!editId) return -1;
  return parts.findIndex((p) => (p.id || p.name) === editId);
}

function clearFaceHandles() {
  for (const f of faceHandles) {
    if (f.parent) f.parent.remove(f);
    if (f.geometry) f.geometry.dispose();
    if (f.material) f.material.dispose();
  }
  faceHandles = [];
  faceHover = null;
}

function addFaceHandles(holder, sx, sy, sz, idx) {
  const faces = [
    { axis: 0, sign: 1, pos: [sx, sy / 2, sz / 2], rot: [0, Math.PI / 2, 0], w: sz, h: sy },
    { axis: 0, sign: -1, pos: [0, sy / 2, sz / 2], rot: [0, -Math.PI / 2, 0], w: sz, h: sy },
    { axis: 1, sign: 1, pos: [sx / 2, sy, sz / 2], rot: [Math.PI / 2, 0, 0], w: sx, h: sz },
    { axis: 1, sign: -1, pos: [sx / 2, 0, sz / 2], rot: [-Math.PI / 2, 0, 0], w: sx, h: sz },
    { axis: 2, sign: 1, pos: [sx / 2, sy / 2, sz], rot: [0, 0, 0], w: sx, h: sy },
    { axis: 2, sign: -1, pos: [sx / 2, sy / 2, 0], rot: [0, Math.PI, 0], w: sx, h: sy },
  ];
  for (const f of faces) {
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(Math.max(1, f.w), Math.max(1, f.h)),
      new THREE.MeshBasicMaterial({
        color: FACE_COL,
        transparent: true,
        opacity: 0.14,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
    );
    const n = new THREE.Vector3();
    n.setComponent(f.axis, f.sign);
    mesh.position.set(f.pos[0] + n.x * 0.4, f.pos[1] + n.y * 0.4, f.pos[2] + n.z * 0.4);
    mesh.rotation.set(f.rot[0], f.rot[1], f.rot[2]);
    mesh.userData = { kind: "face", idx, axis: f.axis, sign: f.sign };
    holder.add(mesh);
    faceHandles.push(mesh);
  }
}

function pickFaceAt(clientX, clientY) {
  if (!faceHandles.length) return null;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(faceHandles, false);
  return hits.length ? hits[0].object : null;
}

function tintFaces(hover) {
  for (const f of faceHandles) {
    f.material.opacity = f === hover ? 0.38 : 0.14;
  }
}

function worldToCanvas(v) {
  const p = v.clone().project(camera);
  return {
    x: (p.x * 0.5 + 0.5) * canvas.clientWidth,
    y: (-p.y * 0.5 + 0.5) * canvas.clientHeight,
  };
}

function screenAlongAxis(dx, dy, origin, axisVec) {
  camera.updateMatrixWorld();
  const sample = 100;
  const p0 = worldToCanvas(origin);
  const p1 = worldToCanvas(origin.clone().addScaledVector(axisVec, sample));
  const vx = p1.x - p0.x;
  const vy = p1.y - p0.y;
  const lenSq = vx * vx + vy * vy;
  if (lenSq < 1e-6) return 0;
  return (sample * (dx * vx + dy * vy)) / lenSq;
}

function alongPixels(dx, dy, worldN) {
  const origin = faceDrag ? faceDrag.origin : target;
  return screenAlongAxis(dx, dy, origin, worldN);
}

function camFacingPlane(point) {
  camera.updateMatrixWorld();
  const n = new THREE.Vector3();
  camera.getWorldDirection(n);
  return new THREE.Plane().setFromNormalAndCoplanarPoint(n, point);
}

function dragDeltaWorld(clientX, clientY, origin, x0, y0) {
  const plane = camFacingPlane(origin);
  const a = planePoint(x0, y0, plane);
  const b = planePoint(clientX, clientY, plane);
  if (!a || !b) return new THREE.Vector3();
  return b.sub(a);
}

function distToSegment2D(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const lenSq = vx * vx + vy * vy;
  let t = lenSq < 1e-8 ? 0 : ((px - ax) * vx + (py - ay) * vy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + vx * t), py - (ay + vy * t));
}

function inferredAxis(origin, dx, dy) {
  let best = "x";
  let bestAbs = -1;
  const md = Math.hypot(dx, dy) || 1;
  for (const name of ["x", "y", "z"]) {
    const a = sceneAxis(name);
    const sample = 100;
    const p0 = worldToCanvas(origin);
    const p1 = worldToCanvas(origin.clone().addScaledVector(a, sample));
    const vx = p1.x - p0.x;
    const vy = p1.y - p0.y;
    const len = Math.hypot(vx, vy) || 1;
    const align = Math.abs((dx / md) * (vx / len) + (dy / md) * (vy / len));
    if (align > bestAbs) {
      bestAbs = align;
      best = name;
    }
  }
  return best;
}

function applyFaceDrag(e) {
  if (!faceDrag) return;
  const p = parts[faceDrag.idx];
  const holder = faceDrag.holder;
  if (!p || !holder) return;
  const dx = e.clientX - faceDrag.x0;
  const dy = e.clientY - faceDrag.y0;
  let along = alongPixels(dx, dy, faceDrag.worldN);
  const sizes = [faceDrag.sx0, faceDrag.sy0, faceDrag.sz0];
  let next = sizes[faceDrag.axis] + along;
  next = Math.max(MIN_DIM, Math.round(next));
  along = next - sizes[faceDrag.axis];
  sizes[faceDrag.axis] = next;
  writeLocalSize(p, sizes[0], sizes[1], sizes[2]);
  const origin = faceDrag.origin.clone();
  if (faceDrag.sign < 0) {
    origin.addScaledVector(faceDrag.worldN, along);
  }
  holder.position.copy(origin);
  p.x_mm = Math.round(origin.x);
  p.y_mm = Math.round(origin.z);
  p.z_mm = Math.round(origin.y);
  updateHolderBox(holder, sizes[0], sizes[1], sizes[2], faceDrag.idx);
  showInspect(faceDrag.idx);
  const row = listEl && listEl.querySelector(`.part[data-idx="${faceDrag.idx}"] .dim`);
  if (row) row.textContent = partLine(p);
}

function updateHolderBox(holder, sx, sy, sz, idx) {
  const mesh = holder.userData.mesh;
  const edges = holder.userData.edges;
  if (!mesh || !edges) return;
  mesh.geometry.dispose();
  mesh.geometry = new THREE.BoxGeometry(sx, sy, sz);
  mesh.position.set(sx / 2, sy / 2, sz / 2);
  edges.geometry.dispose();
  edges.geometry = new THREE.EdgesGeometry(mesh.geometry);
  edges.position.copy(mesh.position);
  clearFaceHandles();
  addFaceHandles(holder, sx, sy, sz, idx);
}

function poseOps(p) {
  return [
    {
      op: "resize",
      id: p.id,
      name: p.name,
      length_mm: p.length_mm,
      width_mm: p.width_mm,
      thickness_mm: p.thickness_mm,
    },
    {
      op: "move",
      id: p.id,
      name: p.name,
      x_mm: p.x_mm,
      y_mm: p.y_mm,
      z_mm: p.z_mm,
    },
    {
      op: "rotate",
      id: p.id,
      name: p.name,
      rx_deg: p.rx_deg || 0,
      ry_deg: p.ry_deg || 0,
      rz_deg: p.rz_deg || 0,
    },
  ];
}

async function postPart(idx) {
  return postParts([idx]);
}

async function postParts(idxs) {
  const ops = [];
  for (const idx of idxs) {
    const p = parts[idx];
    if (p) ops.push(...poseOps(p));
  }
  if (!ops.length) return;
  try {
    await fetch("/api/ops", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops }),
    });
  } catch (_) {}
}

function holderOf(idx) {
  const mesh = pickables.find((m) => m.userData.idx === idx);
  return mesh ? mesh.parent : null;
}

function writePose(p, holder) {
  p.x_mm = Math.round(holder.position.x);
  p.y_mm = Math.round(holder.position.z);
  p.z_mm = Math.round(holder.position.y);
  const e = new THREE.Euler().setFromQuaternion(holder.quaternion, "XYZ");
  p.rx_deg = round1(THREE.MathUtils.radToDeg(e.x));
  p.ry_deg = round1(THREE.MathUtils.radToDeg(e.y));
  p.rz_deg = round1(THREE.MathUtils.radToDeg(e.z));
}

function snapshotParts() {
  return JSON.stringify(parts);
}

function pushUndo() {
  undoStack.push(snapshotParts());
  if (undoStack.length > 40) undoStack.shift();
  redoStack.length = 0;
}

async function restoreParts(raw) {
  let next;
  try {
    next = JSON.parse(raw);
  } catch (_) {
    return;
  }
  if (!Array.isArray(next)) return;
  parts = next;
  try {
    await fetch("/api/ops", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops: [{ op: "set_parts", parts: next }] }),
    });
  } catch (_) {}
  rebuild();
}

function undo() {
  if (!undoStack.length) return;
  redoStack.push(snapshotParts());
  restoreParts(undoStack.pop());
}

function redo() {
  if (!redoStack.length) return;
  undoStack.push(snapshotParts());
  restoreParts(redoStack.pop());
}

function sceneAxis(name) {
  if (name === "x") return new THREE.Vector3(1, 0, 0);
  if (name === "y") return new THREE.Vector3(0, 0, 1);
  return new THREE.Vector3(0, 1, 0);
}

const GIZMO_SHAFT = 150;
const GIZMO_HEAD = 42;
const GIZMO_LOCAL_LEN = GIZMO_SHAFT + GIZMO_HEAD;

function axisMaterial(color) {
  const mat = new THREE.MeshBasicMaterial({
    color,
    depthTest: false,
    depthWrite: false,
    transparent: true,
    opacity: 0.95,
    toneMapped: false,
  });
  return mat;
}

function buildGizmo() {
  while (gizmo.children.length) {
    const ch = gizmo.children[0];
    gizmo.remove(ch);
    ch.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material && o.material.dispose) o.material.dispose();
    });
  }
  const axes = [
    { name: "x", dir: new THREE.Vector3(1, 0, 0), color: 0xff5555 },
    { name: "y", dir: new THREE.Vector3(0, 0, 1), color: 0x44cc55 },
    { name: "z", dir: new THREE.Vector3(0, 1, 0), color: 0x5599ff },
  ];
  const yUp = new THREE.Vector3(0, 1, 0);
  for (const a of axes) {
    const mat = axisMaterial(a.color);
    const pickMat = new THREE.MeshBasicMaterial({
      color: a.color,
      depthTest: false,
      depthWrite: false,
      transparent: true,
      opacity: 0,
      toneMapped: false,
    });
    for (const sign of [1, -1]) {
      const arm = new THREE.Group();
      arm.userData = { kind: "gizmo", axis: a.name };
      arm.quaternion.setFromUnitVectors(yUp, a.dir.clone().multiplyScalar(sign));
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(8, 8, GIZMO_SHAFT, 12), mat);
      shaft.position.y = GIZMO_SHAFT / 2;
      shaft.renderOrder = 1000;
      shaft.userData = { kind: "gizmo", axis: a.name };
      const head = new THREE.Mesh(new THREE.ConeGeometry(18, GIZMO_HEAD, 14), mat);
      head.position.y = GIZMO_SHAFT + GIZMO_HEAD / 2;
      head.renderOrder = 1000;
      head.userData = { kind: "gizmo", axis: a.name };
      const pick = new THREE.Mesh(
        new THREE.CylinderGeometry(14, 14, GIZMO_LOCAL_LEN, 8),
        pickMat
      );
      pick.position.y = GIZMO_LOCAL_LEN / 2;
      pick.renderOrder = 999;
      pick.userData = { kind: "gizmo", axis: a.name, pick: true };
      arm.add(shaft, head, pick);
      gizmo.add(arm);
    }
  }
}
buildGizmo();

function placeGizmo() {
  const idxs = selectedIndices();
  if (!idxs.length || rotateMode || editId || !pickables.length) {
    gizmo.visible = false;
    return;
  }
  const center = new THREE.Vector3();
  let n = 0;
  let radius = 120;
  for (const i of idxs) {
    const mesh = pickables.find((m) => m.userData.idx === i);
    if (!mesh) continue;
    mesh.updateWorldMatrix(true, false);
    const pos = new THREE.Vector3();
    mesh.getWorldPosition(pos);
    center.add(pos);
    n += 1;
    if (!mesh.geometry.boundingSphere) mesh.geometry.computeBoundingSphere();
    const r = mesh.geometry.boundingSphere ? mesh.geometry.boundingSphere.radius : 120;
    radius = Math.max(radius, r);
  }
  if (!n) {
    gizmo.visible = false;
    return;
  }
  center.multiplyScalar(1 / n);
  gizmo.position.copy(center);
  camera.updateMatrixWorld();
  const distToCam = Math.max(1, camera.position.distanceTo(gizmo.position));
  const worldPerPix =
    (2 * distToCam * Math.tan((camera.fov * Math.PI) / 360)) /
    Math.max(1, canvas.clientHeight);
  const worldLen = Math.max(worldPerPix * 90, radius * 0.6, 90);
  gizmo.scale.setScalar(worldLen / GIZMO_LOCAL_LEN);
  gizmo.visible = true;
}

function tintGizmo(axis) {
  gizmo.traverse((o) => {
    if (!o.material || o.userData.kind !== "gizmo" || o.userData.pick) return;
    o.material.opacity = !axis || o.userData.axis === axis ? 0.98 : 0.28;
  });
}

function pickGizmoAt(clientX, clientY) {
  if (!gizmo.visible) return null;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(gizmo.children, true);
  if (hits.length) {
    let obj = hits[0].object;
    while (obj && obj.userData.kind !== "gizmo") obj = obj.parent;
    if (obj && obj.userData.kind === "gizmo") return obj.userData.axis;
  }
  const mx = clientX - rect.left;
  const my = clientY - rect.top;
  const origin = gizmo.position;
  const reach = GIZMO_LOCAL_LEN * gizmo.scale.x;
  let best = null;
  let bestD = 18;
  for (const name of ["x", "y", "z"]) {
    const a = sceneAxis(name);
    const p0 = worldToCanvas(origin.clone().addScaledVector(a, -reach));
    const p1 = worldToCanvas(origin.clone().addScaledVector(a, reach));
    const d = distToSegment2D(mx, my, p0.x, p0.y, p1.x, p1.y);
    if (d < bestD) {
      bestD = d;
      best = name;
    }
  }
  return best;
}

function clearSpinViz() {
  while (spinViz.children.length) {
    const ch = spinViz.children[0];
    spinViz.remove(ch);
    ch.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material && o.material.dispose) o.material.dispose();
    });
  }
  spinViz.visible = false;
}

function showProtractor(pivot, worldN) {
  clearSpinViz();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), worldN.clone().normalize());
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(90, 120, 64),
    new THREE.MeshBasicMaterial({
      color: 0xf0c060,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.45,
      depthTest: false,
    })
  );
  ring.quaternion.copy(q);
  ring.position.copy(pivot);
  spinViz.add(ring);
  const ticks = new THREE.Group();
  ticks.quaternion.copy(q);
  ticks.position.copy(pivot);
  const tickMat = new THREE.LineBasicMaterial({ color: 0xf0c060, depthTest: false });
  for (let d = 0; d < 360; d += SNAP_DEG) {
    const a = (d * Math.PI) / 180;
    const inner = d % 90 === 0 ? 70 : 100;
    const p0 = new THREE.Vector3(Math.cos(a) * inner, Math.sin(a) * inner, 0);
    const p1 = new THREE.Vector3(Math.cos(a) * 120, Math.sin(a) * 120, 0);
    ticks.add(
      new THREE.Line(new THREE.BufferGeometry().setFromPoints([p0, p1]), tickMat)
    );
  }
  spinViz.add(ticks);
  const axisLen = 220;
  const axisGeom = new THREE.BufferGeometry().setFromPoints([
    pivot.clone().addScaledVector(worldN, -axisLen),
    pivot.clone().addScaledVector(worldN, axisLen),
  ]);
  spinViz.add(new THREE.Line(axisGeom, new THREE.LineBasicMaterial({ color: 0xffeeaa, depthTest: false })));
  spinViz.visible = true;
}

function pickRotateFace(clientX, clientY) {
  const idxs = selectedIndices();
  if (!idxs.length) return null;
  const meshes = idxs
    .map((i) => pickables.find((m) => m.userData.idx === i))
    .filter(Boolean);
  if (!meshes.length) return null;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(meshes, false);
  if (!hits.length) return null;
  const hit = hits[0];
  const mesh = hit.object;
  const idx = mesh.userData.idx;
  const n = hit.face.normal.clone();
  const ax =
    Math.abs(n.x) >= Math.abs(n.y) && Math.abs(n.x) >= Math.abs(n.z)
      ? 0
      : Math.abs(n.y) >= Math.abs(n.z)
        ? 1
        : 2;
  const sign = n.getComponent(ax) >= 0 ? 1 : -1;
  const holder = mesh.parent;
  const p = parts[idx];
  const { sx, sy, sz } = localSize(p);
  const local = new THREE.Vector3(sx / 2, sy / 2, sz / 2);
  const half = [sx / 2, sy / 2, sz / 2][ax];
  local.setComponent(ax, sign > 0 ? 2 * half : 0);
  holder.updateMatrixWorld();
  const pivot = holder.localToWorld(local);
  const worldN = new THREE.Vector3();
  worldN.setComponent(ax, sign);
  worldN.transformDirection(holder.matrixWorld).normalize();
  return { idx, holder, pivot, worldN, axis: ax, sign };
}

function planePoint(clientX, clientY, plane) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const pt = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(plane, pt)) return null;
  return pt;
}

function snapshotMoveItems() {
  return selectedIndices()
    .map((idx) => {
      const holder = holderOf(idx);
      return {
        idx,
        holder,
        origin: holder ? holder.position.clone() : new THREE.Vector3(),
      };
    })
    .filter((it) => it.holder);
}

function snapshotRotateItems() {
  return selectedIndices()
    .map((idx) => {
      const holder = holderOf(idx);
      return {
        idx,
        holder,
        pos0: holder ? holder.position.clone() : new THREE.Vector3(),
        quat0: holder ? holder.quaternion.clone() : new THREE.Quaternion(),
      };
    })
    .filter((it) => it.holder);
}

function itemsCenter(items, key) {
  const c = new THREE.Vector3();
  if (!items.length) return c;
  for (const it of items) c.add(it[key]);
  return c.multiplyScalar(1 / items.length);
}

function beginMoveDrag(axis, e, opts) {
  const items = snapshotMoveItems();
  if (!items.length) return false;
  dragMode = "move";
  pushUndo();
  moveDrag = {
    items,
    idx: items[0].idx,
    holder: items[0].holder,
    origin: itemsCenter(items, "origin"),
    axis: axis || null,
    free: !!(opts && opts.free),
    x0: lastX,
    y0: lastY,
  };
  canvas.setPointerCapture(e.pointerId);
  return true;
}

function applyMoveDrag(e) {
  if (!moveDrag || !moveDrag.items) return;
  const dx = e.clientX - moveDrag.x0;
  const dy = e.clientY - moveDrag.y0;
  const free = e.shiftKey || moveDrag.free;
  const delta = new THREE.Vector3();
  if (free) {
    delta.copy(
      dragDeltaWorld(e.clientX, e.clientY, moveDrag.origin, moveDrag.x0, moveDrag.y0)
    );
  } else {
    let axis = moveDrag.axis;
    if (!axis && Math.hypot(dx, dy) > 6) {
      axis = inferredAxis(moveDrag.origin, dx, dy);
      moveDrag.axis = axis;
    }
    if (axis) {
      const a = sceneAxis(axis);
      delta.addScaledVector(a, screenAlongAxis(dx, dy, moveDrag.origin, a));
    }
  }
  for (const it of moveDrag.items) {
    if (!it.holder || !parts[it.idx]) continue;
    it.holder.position.copy(it.origin).add(delta);
    writePose(parts[it.idx], it.holder);
  }
  showInspect(selectedIndex());
}

function applyRotateDrag(e) {
  if (!rotateDrag) return;
  const pt = planePoint(e.clientX, e.clientY, rotateDrag.plane);
  if (!pt) return;
  const v = pt.clone().sub(rotateDrag.pivot);
  v.projectOnPlane(rotateDrag.worldN);
  if (v.lengthSq() < 1) return;
  let angle = rotateDrag.startVec.angleTo(v);
  const cross = new THREE.Vector3().crossVectors(rotateDrag.startVec, v);
  if (cross.dot(rotateDrag.worldN) < 0) angle = -angle;
  if (!e.shiftKey) {
    const step = (SNAP_DEG * Math.PI) / 180;
    angle = Math.round(angle / step) * step;
  }
  const q = new THREE.Quaternion().setFromAxisAngle(rotateDrag.worldN, angle);
  const items = rotateDrag.items || [
    {
      idx: rotateDrag.idx,
      holder: rotateDrag.holder,
      pos0: rotateDrag.pos0,
      quat0: rotateDrag.quat0,
    },
  ];
  for (const it of items) {
    if (!it.holder || !parts[it.idx]) continue;
    const pos = it.pos0.clone().sub(rotateDrag.pivot).applyQuaternion(q).add(rotateDrag.pivot);
    it.holder.position.copy(pos);
    it.holder.quaternion.copy(it.quat0).premultiply(q);
    writePose(parts[it.idx], it.holder);
  }
  showInspect(selectedIndex());
}

function setEdit(idx) {
  rotateMode = false;
  clearSpinViz();
  if (idx < 0 || !parts[idx]) {
    editId = "";
  } else {
    const p = parts[idx];
    editId = p.id || p.name || "";
    selectedIds = [partKey(p)];
  }
  rebuild();
}

function rebuild() {
  while (group.children.length) {
    const ch = group.children[0];
    group.remove(ch);
    ch.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material && obj.material !== woodEdge) obj.material.dispose();
    });
  }
  pickables = [];
  clearFaceHandles();
  rebuildSite();
  let maxL = 400;
  parts.forEach((p, idx) => {
    const L = p.length_mm || 100;
    const W = p.width_mm || 40;
    const T = p.thickness_mm || 15;
    const up = !!p.upright;
    const sx = up ? T : L;
    const sy = up ? L : T;
    const sz = W;
    const geom = new THREE.BoxGeometry(sx, sy, sz);
    const holder = new THREE.Group();
    holder.position.set(p.x_mm || 0, p.z_mm || 0, p.y_mm || 0);
    holder.rotation.set(
      THREE.MathUtils.degToRad(p.rx_deg || 0),
      THREE.MathUtils.degToRad(p.ry_deg || 0),
      THREE.MathUtils.degToRad(p.rz_deg || 0)
    );
    const mesh = new THREE.Mesh(
      geom,
      new THREE.MeshLambertMaterial({ color: WOOD, emissive: 0x000000 })
    );
    mesh.position.set(sx / 2, sy / 2, sz / 2);
    mesh.userData.idx = idx;
    holder.add(mesh);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom), woodEdge);
    edges.position.copy(mesh.position);
    holder.add(edges);
    holder.userData.mesh = mesh;
    holder.userData.edges = edges;
    holder.userData.idx = idx;
    if (editId && (p.id || p.name) === editId) {
      addFaceHandles(holder, sx, sy, sz, idx);
    }
    group.add(holder);
    pickables.push(mesh);
    maxL = Math.max(maxL, L + (p.x_mm || 0), 400);
  });
  const alleyW = site.width_mm || 0;
  const alleyL = site.length_mm || 0;
  if (alleyL) maxL = Math.max(maxL, alleyL);
  if (!framedOnce && !cameraTouched && parts.length) {
    frameParts();
    framedOnce = true;
  }
  const alleyEl = document.getElementById("alley-span");
  if (alleyEl) {
    alleyEl.textContent = alleyW ? alleyW + " × " + alleyL + " mm" : "—";
  }
  const siteBlock = document.getElementById("site-block");
  const siteDim = document.getElementById("site-dim");
  if (siteBlock && siteDim) {
    if (alleyW) {
      siteBlock.hidden = false;
      const head = site.min_headroom_mm ? site.min_headroom_mm + " mm headroom" : "";
      siteDim.textContent =
        alleyW +
        " mm across × " +
        alleyL +
        " mm along" +
        (head ? " · " + head : "");
    } else siteBlock.hidden = true;
  }
  const stockBlock = document.getElementById("stock-block");
  const stockDim = document.getElementById("stock-dim");
  if (stockBlock && stockDim) {
    if (stock.length) {
      stockBlock.hidden = false;
      stockDim.textContent = stock
        .map(
          (s) =>
            s.qty +
            " × " +
            s.length_mm +
            "×" +
            s.width_mm +
            "×" +
            s.thickness_mm
        )
        .join(" · ");
    } else stockBlock.hidden = true;
  }
  const checkBlock = document.getElementById("check-block");
  const checkDim = document.getElementById("check-dim");
  if (checkBlock && checkDim && (check.span_mm || check.mid_underside_mm)) {
    checkBlock.hidden = false;
    checkDim.textContent =
      "span " +
      mark(check.span_ok) +
      " " +
      (check.span_mm || 0) +
      " mm · length " +
      mark(check.length_ok) +
      " " +
      (check.length_mm || 0) +
      " mm · mid " +
      mark(check.headroom_ok) +
      " " +
      (check.mid_underside_mm || 0) +
      " mm";
  } else if (checkBlock) checkBlock.hidden = true;
  listEl.innerHTML = parts.length
    ? parts
        .map(
          (p, i) =>
            `<div class="part" data-idx="${i}"><strong>${p.name || p.kind}</strong><div class="dim">${partLine(p)}</div><div class="dim">${partLoc(p)} · ${partRot(p)}</div></div>`
        )
        .join("")
    : "Empty.";
  pruneSelection();
  applyTint();
  showInspect(selectedIndex());
}

async function poll() {
  if (faceDrag || moveDrag || rotateDrag || mutating) return;
  try {
    const s = await (await fetch("/api/scene", { cache: "no-store" })).json();
    const next = {
      parts: s.parts || [],
      site: s.site || {},
      stock: s.stock || [],
      check: s.check || {},
    };
    const prev = { parts, site, stock, check };
    if (JSON.stringify(next) !== JSON.stringify(prev)) {
      parts = next.parts;
      site = next.site;
      stock = next.stock;
      check = next.check;
      rebuild();
    }
    const cam = s.camera;
    if (cam && cam.rev != null && cam.rev > camRev) {
      applyCameraState(cam);
      camRev = cam.rev;
      cameraTouched = true;
    }
  } catch (_) {}
}
setInterval(poll, 400);
poll();

canvas.addEventListener("pointerdown", (e) => {
  dragging = true;
  moved = false;
  lastX = e.clientX;
  lastY = e.clientY;
  selectDownIdx = -1;
  const hit = e.button === 0 ? pickAt(e.clientX, e.clientY) : -1;
  if (!wantsPan(e) && e.button === 0 && rotateMode) {
    const face = pickRotateFace(e.clientX, e.clientY);
    if (face) {
      dragMode = "rotate";
      pushUndo();
      const startPt = planePoint(
        e.clientX,
        e.clientY,
        new THREE.Plane().setFromNormalAndCoplanarPoint(face.worldN, face.pivot)
      );
      const startVec = startPt
        ? startPt.clone().sub(face.pivot).projectOnPlane(face.worldN)
        : new THREE.Vector3(1, 0, 0);
      if (startVec.lengthSq() < 1) startVec.set(1, 0, 0).projectOnPlane(face.worldN);
      const items = snapshotRotateItems();
      rotateDrag = {
        idx: face.idx,
        holder: face.holder,
        items,
        pivot: face.pivot.clone(),
        worldN: face.worldN.clone(),
        plane: new THREE.Plane().setFromNormalAndCoplanarPoint(face.worldN, face.pivot),
        startVec: startVec.normalize(),
        quat0: face.holder.quaternion.clone(),
        pos0: face.holder.position.clone(),
      };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
  }
  if (!wantsPan(e) && e.button === 0 && editId) {
    const face = pickFaceAt(e.clientX, e.clientY);
    if (face) {
      dragMode = "face";
      pushUndo();
      const holder = face.parent;
      const p = parts[face.userData.idx];
      const size = localSize(p);
      const worldN = new THREE.Vector3();
      worldN.setComponent(face.userData.axis, face.userData.sign);
      holder.updateMatrixWorld();
      worldN.transformDirection(holder.matrixWorld);
      faceDrag = {
        idx: face.userData.idx,
        axis: face.userData.axis,
        sign: face.userData.sign,
        holder,
        worldN,
        sx0: size.sx,
        sy0: size.sy,
        sz0: size.sz,
        origin: holder.position.clone(),
        x0: e.clientX,
        y0: e.clientY,
      };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
  }
  if (!wantsPan(e) && e.button === 0 && selectedIds.length && !editId && !rotateMode) {
    const axis = pickGizmoAt(e.clientX, e.clientY);
    if (axis) {
      beginMoveDrag(axis, e, { free: false });
      return;
    }
    if (hit >= 0 && isSelectedIdx(hit) && !e.shiftKey) {
      beginMoveDrag(null, e, { free: false });
      return;
    }
  }
  if (e.button === 0 && e.shiftKey && hit >= 0 && !editId && !rotateMode) {
    dragMode = "select";
    selectDownIdx = hit;
    canvas.setPointerCapture(e.pointerId);
    return;
  }
  dragMode = wantsPan(e) || (e.shiftKey && e.button === 0) ? "pan" : "orbit";
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointerup", (e) => {
  const wasDrag = moved;
  const mode = dragMode;
  dragging = false;
  moved = false;
  dragMode = "orbit";
  if (mode === "face") {
    const idx = faceDrag ? faceDrag.idx : -1;
    faceDrag = null;
    if (idx >= 0) postPart(idx);
    canvas.style.cursor = "pointer";
    return;
  }
  if (mode === "move") {
    const idxs = moveDrag && moveDrag.items ? moveDrag.items.map((it) => it.idx) : [];
    moveDrag = null;
    if (idxs.length) postParts(idxs);
    return;
  }
  if (mode === "rotate") {
    const idxs =
      rotateDrag && rotateDrag.items
        ? rotateDrag.items.map((it) => it.idx)
        : rotateDrag
          ? [rotateDrag.idx]
          : [];
    rotateDrag = null;
    if (idxs.length) postParts(idxs);
    return;
  }
  if (mode === "select") {
    if (!wasDrag && selectDownIdx >= 0) {
      toggleSelect(selectDownIdx);
      if (editId && !selectedIds.includes(editId)) setEdit(-1);
      else {
        applyTint();
        showInspect(selectedIndex());
      }
    }
    selectDownIdx = -1;
    return;
  }
  if (wasDrag) {
    if (mode === "pan" || mode === "orbit") pushCamera();
    return;
  }
  if (mode === "pan" || e.button === 2) return;
  const idx = pickAt(e.clientX, e.clientY);
  if (idx < 0) {
    if (rotateMode) {
      rotateMode = false;
      clearSpinViz();
      showInspect(selectedIndex());
      return;
    }
    clearSelection();
    if (editId) setEdit(-1);
    else {
      applyTint();
      showInspect(-1);
    }
    return;
  }
  selectOnly(idx);
  if (editId && !selectedIds.includes(editId)) setEdit(-1);
  applyTint();
  showInspect(selectedIndex());
});
canvas.addEventListener("pointermove", (e) => {
  if (dragging && dragMode === "face") {
    if (Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY) > 2) moved = true;
    applyFaceDrag(e);
    canvas.style.cursor = "ns-resize";
    return;
  }
  if (dragging && dragMode === "select") {
    if (Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY) > 4) moved = true;
    if (moved && selectDownIdx >= 0 && isSelectedIdx(selectDownIdx) && !editId && !rotateMode) {
      beginMoveDrag(null, e, { free: true });
      applyMoveDrag(e);
      canvas.style.cursor = "move";
    } else if (moved) {
      dragMode = "pan";
    }
    return;
  }
  if (dragging && dragMode === "move") {
    if (Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY) > 2) moved = true;
    applyMoveDrag(e);
    canvas.style.cursor = moveDrag && (moveDrag.free || e.shiftKey) ? "move" : "grabbing";
    return;
  }
  if (dragging && dragMode === "rotate") {
    if (Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY) > 2) moved = true;
    applyRotateDrag(e);
    canvas.style.cursor = "crosshair";
    return;
  }
  if (dragging) {
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    if (moved) {
      if (dragMode === "pan") {
        panView(dx, dy);
        canvas.style.cursor = "move";
      } else {
        az -= dx * 0.005;
        el += dy * 0.005;
        el = Math.max(0.08, Math.min(1.2, el));
      }
      lastX = e.clientX;
      lastY = e.clientY;
    }
    return;
  }
  if (rotateMode) {
    const face = pickRotateFace(e.clientX, e.clientY);
    canvas.style.cursor = face ? "crosshair" : "grab";
    if (face) {
      const key = face.idx + ":" + face.axis + ":" + face.sign;
      if (!rotateHover || rotateHover.key !== key) {
        rotateHover = { key };
        showProtractor(face.pivot, face.worldN);
      }
    } else if (!rotateDrag) {
      rotateHover = null;
      clearSpinViz();
    }
    return;
  }
  if (editId) {
    const face = pickFaceAt(e.clientX, e.clientY);
    canvas.style.cursor = face ? "ns-resize" : pickAt(e.clientX, e.clientY) >= 0 ? "pointer" : "grab";
    if (face !== faceHover) {
      faceHover = face;
      tintFaces(face);
    }
    return;
  }
  const axisHover = pickGizmoAt(e.clientX, e.clientY);
  tintGizmo(axisHover);
  if (axisHover) {
    canvas.style.cursor = "grab";
    return;
  }
  const idx = pickAt(e.clientX, e.clientY);
  canvas.style.cursor = idx >= 0 ? "pointer" : "grab";
  if (idx === hoverIdx) return;
  hoverIdx = idx;
  applyTint();
});
canvas.addEventListener("pointerleave", () => {
  tintGizmo(null);
  if (hoverIdx < 0) return;
  hoverIdx = -1;
  canvas.style.cursor = "grab";
  applyTint();
});
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
canvas.addEventListener("dblclick", (e) => {
  e.preventDefault();
  if (rotateMode) return;
  const idx = pickAt(e.clientX, e.clientY);
  setEdit(idx);
});
addEventListener("keydown", (e) => {
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (e.shiftKey) redo();
    else undo();
    return;
  }
  if (mod && e.key.toLowerCase() === "y") {
    e.preventDefault();
    redo();
    return;
  }
  if (mod && e.key.toLowerCase() === "x") {
    e.preventDefault();
    cutSelected();
    return;
  }
  if (mod && e.key.toLowerCase() === "c") {
    e.preventDefault();
    copySelected();
    return;
  }
  if (mod && e.key.toLowerCase() === "v") {
    e.preventDefault();
    pasteClipboard();
    return;
  }
  if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
    e.preventDefault();
    deleteSelected();
    return;
  }
  if (e.key === "Escape") {
    if (rotateMode) {
      rotateMode = false;
      clearSpinViz();
      showInspect(selectedIndex());
      return;
    }
    if (editId) setEdit(-1);
    return;
  }
  if (e.key.toLowerCase() === "r" && !mod && selectedIndex() >= 0) {
    e.preventDefault();
    rotateMode = !rotateMode;
    rotateHover = null;
    if (rotateMode) {
      if (editId) {
        editId = "";
        rebuild();
      }
      clearSpinViz();
    } else clearSpinViz();
    showInspect(selectedIndex());
  }
});
const actionsEl = document.getElementById("actions");
if (actionsEl) {
  actionsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn || btn.disabled) return;
    const act = btn.dataset.act;
    if (act === "cut") cutSelected();
    else if (act === "copy") copySelected();
    else if (act === "paste") pasteClipboard();
    else if (act === "delete") deleteSelected();
  });
}
syncActions();
if (listEl) {
  listEl.addEventListener("click", (e) => {
    const row = e.target.closest(".part");
    if (!row || row.dataset.idx == null) return;
    const idx = Number(row.dataset.idx);
    if (e.shiftKey) toggleSelect(idx);
    else selectOnly(idx);
    applyTint();
    showInspect(selectedIndex());
  });
}
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    dist *= e.deltaY > 0 ? 1.08 : 0.92;
    dist = Math.max(200, Math.min(12000, dist));
    pushCamera();
  },
  { passive: false }
);

function tick() {
  placeCamera();
  placeGizmo();
  renderer.clear();
  renderer.render(scene, camera);
  renderer.clearDepth();
  renderer.render(overlay, camera);
  requestAnimationFrame(tick);
}
tick();
