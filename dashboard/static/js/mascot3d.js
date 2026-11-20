// SafeAnchor — mascot 3D tương tác (trang của trẻ /kid/...).
//
// Ba nhân vật GỐC của dự án: Tíc-Tắc (đồng hồ báo thức), Khiên Xanh (chiếc khiên), Sao Nhỏ (ngôi sao đội mũ tốt
// nghiệp). Mô hình dựng hoàn toàn bằng hình khối của three.js (không tải tệp mô hình bên ngoài), tô kiểu hoạt hình
// (toon 3 bậc sáng) + viền nâu "inverted hull" để giống bản SVG 2D. Mascot thương hiệu (ảnh mascot.png) KHÔNG được
// dựng 3D ở đây.
//
// Tương tác: chạm => nhảy + đổi nét mặt + lời thoại theo số liệu thật của trẻ; kéo ngang => xoay 360°;
// kéo qua lại nhanh => "cù" (cười + tim); chạm 5 lần liên tiếp => cả nhóm nhảy múa; mắt dõi theo con trỏ.
// Bàn phím: mỗi nhân vật có một nút (ẩn, hiện khi được focus). Tôn trọng prefers-reduced-motion.
// Không WebGL / tắt JS => trang giữ nguyên mascot SVG (không mất nội dung).
import * as THREE from "./vendor/three.module.min.js";

const LINE = 0x4A3530, EYE = 0x3A2724, BLUSH = 0xFFB3C2, HATCH = 0xEE7591, CREAM = 0xFFF6EE;
export const NAMES = { tictac: "Tíc-Tắc", khien: "Khiên Xanh", sao: "Sao Nhỏ" };

// ------------------------------------------------------------------ vật liệu dùng chung
let GRADIENT = null;
function gradientMap() {
  if (!GRADIENT) {
    GRADIENT = new THREE.DataTexture(new Uint8Array([105, 175, 235, 255]), 4, 1, THREE.RedFormat);
    GRADIENT.minFilter = GRADIENT.magFilter = THREE.NearestFilter;
    GRADIENT.needsUpdate = true;
  }
  return GRADIENT;
}
const MATS = new Map();
function toon(color) {
  const k = "t" + color;
  if (!MATS.has(k)) MATS.set(k, new THREE.MeshToonMaterial({ color, gradientMap: gradientMap() }));
  return MATS.get(k);
}
function flat(color, opacity = 1) {
  const k = "b" + color + ":" + opacity;
  if (!MATS.has(k)) MATS.set(k, new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 }));
  return MATS.get(k);
}
function outlineMat(width) {
  const k = "o" + width;
  if (!MATS.has(k)) {
    MATS.set(k, new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(LINE) }, uW: { value: width } },
      vertexShader: `attribute vec3 onormal; uniform float uW;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          mv.xyz += normalize(normalMatrix * onormal) * uW;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `uniform vec3 uColor;
        void main() {
          gl_FragColor = vec4(uColor, 1.0);
          #include <colorspace_fragment>
        }`,
      side: THREE.BackSide,
    }));
  }
  return MATS.get(k);
}
// Pháp tuyến "trung bình theo vị trí" cho viền: khối đùn (ExtrudeGeometry) có cạnh sắc => nếu đẩy theo pháp tuyến
// gốc thì viền bị nứt ở mép; gộp các đỉnh trùng vị trí rồi lấy trung bình => viền liền.
function addOutlineNormals(geo) {
  if (geo.attributes.onormal) return;
  const pos = geo.attributes.position, nor = geo.attributes.normal, acc = new Map();
  const key = (i) => `${pos.getX(i).toFixed(3)},${pos.getY(i).toFixed(3)},${pos.getZ(i).toFixed(3)}`;
  for (let i = 0; i < pos.count; i++) {
    const k = key(i); let a = acc.get(k);
    if (!a) acc.set(k, (a = [0, 0, 0]));
    a[0] += nor.getX(i); a[1] += nor.getY(i); a[2] += nor.getZ(i);
  }
  const out = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const a = acc.get(key(i)), l = Math.hypot(a[0], a[1], a[2]) || 1;
    out[i * 3] = a[0] / l; out[i * 3 + 1] = a[1] / l; out[i * 3 + 2] = a[2] / l;
  }
  geo.setAttribute("onormal", new THREE.BufferAttribute(out, 3));
}
function part(geo, color, outline = 0.03) {
  const m = new THREE.Mesh(geo, toon(color));
  if (outline) {
    addOutlineNormals(geo);
    m.add(new THREE.Mesh(geo, outlineMat(outline)));
  }
  return m;
}
function tube(points, radius, color) {
  const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(p[0], p[1], p[2] || 0)));
  return new THREE.Mesh(new THREE.TubeGeometry(curve, 24, radius, 8, false), flat(color));
}

// ------------------------------------------------------------------ hình 2D để đùn khối
function roundedPoly(pts, frac) {
  const s = new THREE.Shape(), n = pts.length;
  for (let i = 0; i < n; i++) {
    const p = pts[i], a = p.clone().lerp(pts[(i - 1 + n) % n], frac(i)), b = p.clone().lerp(pts[(i + 1) % n], frac(i));
    if (i === 0) s.moveTo(a.x, a.y); else s.lineTo(a.x, a.y);
    s.quadraticCurveTo(p.x, p.y, b.x, b.y);
  }
  s.closePath();
  return s;
}
function starShape(R, r, tip = 0.28, inner = 0.16) {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r : R;
    pts.push(new THREE.Vector2(Math.cos(a) * rr, Math.sin(a) * rr));
  }
  return roundedPoly(pts, (i) => (i % 2 ? inner : tip));
}
function shieldShape(k = 1, dy = 0) {
  const s = new THREE.Shape(), P = (x, y) => [x * k, y * k + dy];
  s.moveTo(...P(0, 0.99));
  s.bezierCurveTo(...P(0.3, 0.99), ...P(0.58, 0.97), ...P(0.78, 0.95));
  s.quadraticCurveTo(...P(0.9, 0.94), ...P(0.9, 0.8));
  s.bezierCurveTo(...P(0.9, 0.12), ...P(0.72, -0.56), ...P(0.1, -1.0));
  s.quadraticCurveTo(...P(0, -1.07), ...P(-0.1, -1.0));
  s.bezierCurveTo(...P(-0.72, -0.56), ...P(-0.9, 0.12), ...P(-0.9, 0.8));
  s.quadraticCurveTo(...P(-0.9, 0.94), ...P(-0.78, 0.95));
  s.bezierCurveTo(...P(-0.58, 0.97), ...P(-0.3, 0.99), ...P(0, 0.99));
  return s;
}
function heartShape(k = 1) {
  const s = new THREE.Shape();
  s.moveTo(0, -0.9 * k);
  s.bezierCurveTo(-0.5 * k, -0.45 * k, -1.05 * k, 0, -0.95 * k, 0.45 * k);
  s.bezierCurveTo(-0.85 * k, 0.95 * k, -0.2 * k, 1.0 * k, 0, 0.55 * k);
  s.bezierCurveTo(0.2 * k, 1.0 * k, 0.85 * k, 0.95 * k, 0.95 * k, 0.45 * k);
  s.bezierCurveTo(1.05 * k, 0, 0.5 * k, -0.45 * k, 0, -0.9 * k);
  return s;
}
function extrude(shape, depth, bevel, bevelSize, segs = 5, curve = 24) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: bevel, bevelSize,
                                               bevelSegments: segs, curveSegments: curve, steps: 1 });
  g.translate(0, 0, -depth / 2);
  return g;
}

// ------------------------------------------------------------------ khuôn mặt chibi (mắt to có đốm sáng, má hồng, miệng ω)
const EYE_GEO = new THREE.SphereGeometry(1, 24, 16);
const HL_GEO = new THREE.SphereGeometry(1, 12, 8);
function makeFace(o) {
  const s = o.s || 1, surf = o.surf || (() => 0), face = new THREE.Group();
  const er = 0.105 * s;
  const eyes = [-1, 1].map((side) => {
    const x = side * o.eyeDx, y = o.eyeY, g = new THREE.Group();
    g.position.set(x, y, surf(x, y) + 0.012);
    const open = new THREE.Group();
    const ball = new THREE.Mesh(EYE_GEO, flat(EYE)); ball.scale.set(er * 0.86, er * 1.12, er * 0.42); open.add(ball);
    const h1 = new THREE.Mesh(HL_GEO, flat(0xffffff)); h1.scale.setScalar(er * 0.36); h1.position.set(er * 0.28, er * 0.4, er * 0.4);
    const h2 = new THREE.Mesh(HL_GEO, flat(0xffffff)); h2.scale.setScalar(er * 0.17); h2.position.set(-er * 0.3, -er * 0.42, er * 0.4);
    open.add(h1, h2);
    const up = tube([[-er, -er * 0.25], [0, er * 0.6], [er, -er * 0.25]], 0.022 * s, EYE);         // ^ vui
    const down = tube([[-er, er * 0.2], [0, -er * 0.45], [er, er * 0.2]], 0.022 * s, EYE);         // ︶ buồn ngủ
    const line = tube([[-er, 0], [0, -er * 0.12], [er, 0]], 0.02 * s, EYE);                        // nhắm (chớp mắt)
    g.add(open, up, down, line);
    face.add(g);
    return { g, open, up, down, line, base: new THREE.Vector3(x, y, g.position.z) };
  });
  const my = o.mouthY, mz = surf(0, my) + 0.014, w = 0.085 * s;
  const mouth = {
    w: tube([[-w, 0.025 * s], [-w * 0.5, -0.03 * s], [0, 0.004 * s], [w * 0.5, -0.03 * s], [w, 0.025 * s]], 0.017 * s, EYE),
    small: tube([[-w * 0.5, 0], [0, -0.022 * s], [w * 0.5, 0]], 0.016 * s, EYE),
    open: new THREE.Group(),
    o: new THREE.Mesh(new THREE.TorusGeometry(0.04 * s, 0.015 * s, 8, 24), flat(EYE)),
  };
  const lip = new THREE.Mesh(new THREE.CircleGeometry(0.1 * s, 28, Math.PI, Math.PI), flat(0x7A2E35));
  const tongue = new THREE.Mesh(new THREE.CircleGeometry(0.05 * s, 20, Math.PI, Math.PI), flat(0xFF8FA3));
  tongue.position.set(0, -0.042 * s, 0.002);
  mouth.open.add(lip, tongue);
  for (const m of Object.values(mouth)) { m.position.set(0, my, mz); face.add(m); }
  const cheeks = [-1, 1].map((side) => {
    const x = side * o.cheekDx, y = o.cheekY, c = new THREE.Group();
    c.position.set(x, y, surf(x, y) + 0.008);
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.105 * s, 24), flat(BLUSH, 0.92));
    disc.scale.set(1.35, 0.82, 1);
    c.add(disc);
    for (const dx of [-0.045, 0.0, 0.045]) {
      const h = new THREE.Mesh(new THREE.PlaneGeometry(0.012 * s, 0.06 * s), flat(HATCH));
      h.position.set(dx * s, 0, 0.002); h.rotation.z = -0.5; c.add(h);
    }
    face.add(c);
    return c;
  });
  let expr = "";
  const api = {
    group: face, eyes, cheeks,
    set(e) {
      if (e === expr) return;
      expr = e;
      const eyeMode = { happy: "open", wow: "open", joy: "up", love: "up", sleepy: "down", blink: "line" }[e] || "open";
      for (const ey of eyes) for (const k of ["open", "up", "down", "line"]) ey[k].visible = k === eyeMode;
      const mouthMode = { happy: "w", joy: "open", love: "w", wow: "o", sleepy: "small", blink: "w" }[e] || "w";
      for (const k of Object.keys(mouth)) mouth[k].visible = k === mouthMode;
      for (const c of cheeks) c.scale.setScalar(e === "love" ? 1.3 : 1);
    },
    look(x, y) {  // x, y trong [-1, 1]
      for (const ey of eyes) ey.g.position.set(ey.base.x + x * 0.03 * s, ey.base.y + y * 0.022 * s, ey.base.z);
    },
    get expr() { return expr; },
  };
  api.set("happy");
  return api;
}

// ------------------------------------------------------------------ 3 nhân vật
function arm(color, side, len = 0.34) {
  const pivot = new THREE.Group();
  const a = part(new THREE.CapsuleGeometry(0.095, len, 6, 14), color, 0.025);
  a.position.y = -len / 2 - 0.02;
  pivot.add(a);
  pivot.userData.side = side;
  return pivot;
}
function foot(color, x) {
  const f = part(new THREE.SphereGeometry(0.2, 24, 14), color, 0.025);
  f.scale.set(1.15, 0.62, 1.05);
  f.position.set(x, 0.11, 0.04);
  return f;
}

function buildTictac() {
  const g = new THREE.Group(), body = new THREE.Group(), CORAL = 0xFF7D5E, DEEP = 0xFF6B6B;
  body.position.y = 1.18;
  g.add(body);
  // Thân "trống" bo tròn mép (LatheGeometry), trục quay hướng về phía trước
  const R = 1, h = 0.36, r = 0.28, prof = [new THREE.Vector2(0.001, -h)];
  for (let i = 0; i <= 8; i++) { const a = -Math.PI / 2 + (i / 8) * (Math.PI / 2); prof.push(new THREE.Vector2(R - r + Math.cos(a) * r, -h + r + Math.sin(a) * r)); }
  for (let i = 0; i <= 8; i++) { const a = (i / 8) * (Math.PI / 2); prof.push(new THREE.Vector2(R - r + Math.cos(a) * r, h - r + Math.sin(a) * r)); }
  prof.push(new THREE.Vector2(0.001, h));
  const drum = new THREE.LatheGeometry(prof, 64);
  drum.rotateX(Math.PI / 2);
  body.add(part(drum, CORAL, 0.035));
  // Mặt đồng hồ hơi vồng
  const FR = 0.76, DR = 2.4, base = Math.sqrt(DR * DR - FR * FR), peak = h + (DR - base);
  const dome = new THREE.SphereGeometry(DR, 64, 12, 0, Math.PI * 2, 0, Math.asin(FR / DR));
  dome.rotateX(Math.PI / 2);
  dome.translate(0, 0, h - base);
  body.add(part(dome, CREAM, 0.022));
  const surf = (x, y) => Math.sqrt(Math.max(0, DR * DR - x * x - y * y)) - base + h - peak;
  // Vạch giờ 12-3-6-9
  for (let i = 0; i < 4; i++) {
    const a = (i * Math.PI) / 2, x = Math.sin(a) * 0.6, y = Math.cos(a) * 0.6;
    const t = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.11, 0.02), flat(0xD9CBC3));
    t.position.set(x, y, peak + surf(x, y) + 0.005); t.rotation.z = -a;
    body.add(t);
  }
  // Kim giờ + kim phút chạy theo GIỜ THẬT, đặt trên "trán"
  const hands = new THREE.Group();
  hands.position.set(0, 0.36, peak + surf(0, 0.36) + 0.02);
  const mkHand = (len, wdt) => { const geo = new THREE.BoxGeometry(wdt, len, 0.015); geo.translate(0, len / 2, 0); return new THREE.Mesh(geo, flat(EYE)); };
  const hourHand = mkHand(0.13, 0.032), minHand = mkHand(0.19, 0.024);
  const pin = new THREE.Mesh(new THREE.CircleGeometry(0.03, 16), flat(0xFF8E53)); pin.position.z = 0.012;
  hands.add(hourHand, minHand, pin);
  body.add(hands);
  // Mặt
  const face = makeFace({ eyeDx: 0.28, eyeY: -0.02, mouthY: -0.2, cheekDx: 0.47, cheekY: -0.16, surf: (x, y) => surf(x, y) });
  face.group.position.z = peak;
  body.add(face.group);
  // Hai chuông + núm trên đỉnh
  const bells = [-1, 1].map((side) => {
    const piv = new THREE.Group(), ang = side * 0.62;
    piv.position.set(Math.sin(ang) * 0.95, Math.cos(ang) * 0.95, -0.05);
    piv.rotation.z = -ang;
    const bell = part(new THREE.SphereGeometry(0.36, 32, 14, 0, Math.PI * 2, 0, Math.PI / 2), CORAL, 0.03);
    bell.scale.set(1, 0.85, 0.9);
    const lid = new THREE.Mesh(new THREE.CircleGeometry(0.36, 32), toon(DEEP)); lid.rotation.x = Math.PI / 2; lid.scale.set(1, 0.9, 1);
    const knob = part(new THREE.SphereGeometry(0.07, 14, 10), DEEP, 0.02); knob.position.y = 0.33;
    piv.add(bell, lid, knob);
    body.add(piv);
    return piv;
  });
  const stem = part(new THREE.CylinderGeometry(0.035, 0.035, 0.22, 10), DEEP, 0.02); stem.position.set(0, 1.08, -0.05);
  const top = part(new THREE.SphereGeometry(0.085, 16, 10), CORAL, 0.022); top.position.set(0, 1.21, -0.05);
  body.add(stem, top);
  // Tay + chân
  const armL = arm(CORAL, -1), armR = arm(CORAL, 1);
  armL.position.set(-0.96, 0.02, 0); armR.position.set(0.96, 0.02, 0);
  body.add(armL, armR);
  g.add(foot(DEEP, -0.42), foot(DEEP, 0.42));
  return { g, body, face, armL, armR, bells, hands: { hourHand, minHand }, headY: 2.45, width: 1.25 };
}

function buildKhien() {
  const g = new THREE.Group(), body = new THREE.Group(), BLUE = 0x3B7FF2, DEEP = 0x2563EB;
  body.position.y = 1.22;
  g.add(body);
  body.add(part(extrude(shieldShape(), 0.3, 0.14, 0.09, 5, 40), BLUE, 0.035));
  const inner = part(extrude(shieldShape(0.76, 0.03), 0.02, 0.03, 0.03, 3, 40), CREAM, 0.02);
  inner.position.z = 0.28;
  body.add(inner);
  // Vệt sáng trên viền (như bản SVG)
  const shine = tube([[-0.84, 0.5, 0.3], [-0.8, 0.78, 0.3], [-0.6, 0.93, 0.3]], 0.03, 0xffffff);
  shine.material = flat(0xffffff, 0.6);
  body.add(shine);
  // Ngôi sao vàng trên đỉnh
  const star = new THREE.Group();
  star.position.set(0, 1.12, 0);
  star.add(part(extrude(starShape(0.19, 0.09, 0.2, 0.12), 0.05, 0.035, 0.02, 3, 8), 0xFFD54A, 0.02));
  body.add(star);
  const face = makeFace({ eyeDx: 0.25, eyeY: 0.12, mouthY: -0.08, cheekDx: 0.42, cheekY: -0.05 });
  face.group.position.z = 0.335;
  body.add(face.group);
  const armL = arm(BLUE, -1), armR = arm(BLUE, 1);
  armL.position.set(-0.93, 0.3, 0); armR.position.set(0.93, 0.3, 0);
  body.add(armL, armR);
  g.add(foot(DEEP, -0.33), foot(DEEP, 0.33));
  return { g, body, face, armL, armR, star, headY: 2.5, width: 1.2 };
}

function buildSao() {
  const g = new THREE.Group(), body = new THREE.Group(), LAV = 0xC9B8FF, MINT = 0x2FD39A;
  body.position.y = 1.12;
  g.add(body);
  body.add(part(extrude(starShape(1.08, 0.56), 0.26, 0.2, 0.12, 6, 20), LAV, 0.035));
  const face = makeFace({ eyeDx: 0.2, eyeY: 0.0, mouthY: -0.15, cheekDx: 0.35, cheekY: -0.11, s: 0.95 });
  face.group.position.z = 0.33;
  body.add(face.group);
  // Mũ tốt nghiệp mint + tua vàng
  const hat = new THREE.Group();
  hat.position.set(0.04, 1.02, 0.02);
  hat.rotation.z = -0.16;
  const cap = part(new THREE.CylinderGeometry(0.27, 0.31, 0.2, 28), MINT, 0.022);
  const board = part(new THREE.BoxGeometry(0.74, 0.07, 0.74), MINT, 0.022);
  board.position.y = 0.13; board.rotation.y = Math.PI / 4;
  const btn = part(new THREE.SphereGeometry(0.05, 12, 8), 0xFFC23A, 0.015); btn.position.y = 0.18;
  const tassel = new THREE.Group(); tassel.position.set(0.02, 0.17, 0);
  const cord = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.42, 6), flat(0xFFC23A));
  cord.geometry.translate(0, -0.21, 0);
  cord.position.x = 0.54;   // treo ngoài góc tấm mũ (tấm xoay 45° => góc nằm trên trục x, cách tâm 0.52)
  const tip = part(new THREE.SphereGeometry(0.055, 12, 8), 0xFFC23A, 0.015); tip.position.set(0.54, -0.42, 0);
  const across = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.54, 6), flat(0xFFC23A));
  across.rotation.z = Math.PI / 2; across.position.set(0.27, 0.0, 0);
  tassel.add(cord, tip, across);
  hat.add(cap, board, btn, tassel);
  body.add(hat);
  return { g, body, face, hat, tassel, headY: 2.6, width: 1.25 };
}

const BUILDERS = { tictac: buildTictac, khien: buildKhien, sao: buildSao };

// ------------------------------------------------------------------ một nhân vật + chuyển động
export class Mascot {
  constructor(kind, { x = 0, z = 0, scale = 1, yaw = 0, phase = 0, reduced = false } = {}) {
    Object.assign(this, BUILDERS[kind]());
    this.kind = kind; this.reduced = reduced; this.phase = phase;
    this.root = new THREE.Group();
    this.root.position.set(x, 0, z);
    this.root.scale.setScalar(scale);
    this.root.add(this.g);
    this.root.userData.mascot = this;
    this.baseYaw = yaw; this.yaw = yaw; this.yawV = 0;
    this.sq = 0; this.sqV = 0;          // co giãn (lò xo)
    this.jumpT = -1; this.jumpDur = 0.55; this.jumpH = 0;
    this.spinT = -1; this.waveT = -1; this.ringT = -1; this.hatT = -1; this.wiggleT = -1;
    this.lookX = 0; this.lookY = 0; this.tLookX = 0; this.tLookY = 0;
    this.nextBlink = 2 + Math.random() * 3; this.blinkT = -1;
    this.mood = "happy"; this.exprUntil = 0; this.timers = [];
    this.tasselA = 0; this.tasselV = 0;
    this.dragging = false; this.releasedAt = -10;
    this.shadow = null;
  }
  after(sec, fn) { this.timers.push({ at: this.clock + sec, fn }); }
  express(e, sec) { this.face.set(e); this.exprUntil = this.clock + sec; }
  jump(height = 0.55) {
    if (this.reduced) height = 0;
    this.sqV = -2.4;
    this.after(0.07, () => { this.jumpT = 0; this.jumpH = height; this.sqV = 2.6; });
  }
  spin() { if (!this.reduced) this.spinT = 0; }
  wave(sec = 1.6) { this.waveT = 0; this.waveDur = sec; }
  ring() { this.ringT = 0; }
  tossHat() { if (!this.reduced) this.hatT = 0; this.tasselV += 6; }
  wiggle() { this.wiggleT = 0; }
  // Tư thế tĩnh (dùng khi render sẵn ảnh sprite cho Tray — tools/render_mascot_sprites.py)
  pose(yaw = 0, expr = "happy") {
    this.g.rotation.set(0, yaw, 0); this.g.scale.set(1, 1, 1); this.g.position.y = 0;
    this.face.set(expr); this.face.look(0, 0);
    if (this.armL) { this.armL.rotation.z = -0.35; this.armR.rotation.z = 0.35; }
    if (this.bells) {
      this.bells.forEach((b, i) => { b.rotation.z = -(i ? 1 : -1) * 0.62; });
      this.hands.minHand.rotation.z = -(10 / 60) * Math.PI * 2;          // 10:10 — tư thế "đẹp" kinh điển của đồng hồ
      this.hands.hourHand.rotation.z = -((10 + 10 / 60) / 12) * Math.PI * 2;
    }
    if (this.hat) { this.hat.position.y = 1.02; this.hat.rotation.y = 0; this.tassel.rotation.z = 0; }
    if (this.star) this.star.scale.setScalar(1);
  }

  update(dt, clock) {
    this.clock = clock;
    const t = clock + this.phase;
    for (const tm of this.timers.splice(0)) (tm.at <= clock ? tm.fn() : this.timers.push(tm));
    // nhảy
    let y = 0;
    if (this.jumpT >= 0) {
      this.jumpT += dt;
      const u = this.jumpT / this.jumpDur;
      if (u >= 1) { this.jumpT = -1; if (this.jumpH > 0) this.sqV -= 3.0; }
      else y = 4 * this.jumpH * u * (1 - u);
    }
    // lò xo co giãn: v += a*dt rồi x += v*dt (ổn định với dt <= 1/30)
    this.sqV += (-170 * this.sq - 11 * this.sqV) * dt;
    this.sq += this.sqV * dt;
    const breath = this.reduced ? 0 : Math.sin(t * 2.3) * 0.018;
    const sy = 1 + this.sq * 0.22 + breath, sxz = 1 - this.sq * 0.12 - breath * 0.5;
    this.g.scale.set(sxz, sy, sxz);
    this.g.position.y = y;
    // xoay: kéo tay / quay tròn khi chạm / lò xo về hướng mặc định
    let spinExtra = 0;
    if (this.spinT >= 0) {
      this.spinT += dt;
      const u = Math.min(1, this.spinT / 0.75);
      spinExtra = (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2) * Math.PI * 2;
      if (u >= 1) this.spinT = -1;
    }
    if (!this.dragging) {
      const target = this.baseYaw + this.lookX * 0.32;
      const k = clock - this.releasedAt < 1.0 ? 4 : 30;   // vừa thả tay: để quán tính chạy một chút rồi mới về
      this.yawV += ((target - this.yaw) * k - this.yawV * (k < 10 ? 1.2 : 9)) * dt;
      this.yaw += this.yawV * dt;
    }
    this.g.rotation.y = this.yaw + spinExtra;
    const sway = this.reduced ? 0 : Math.sin(t * 1.25) * 0.035;
    let wig = 0;
    if (this.wiggleT >= 0) { this.wiggleT += dt; wig = Math.sin(this.wiggleT * 28) * 0.12 * Math.max(0, 1 - this.wiggleT / 0.9); if (this.wiggleT > 0.9) this.wiggleT = -1; }
    this.g.rotation.z = sway + wig;
    this.g.rotation.x = -this.lookY * 0.12;
    // mắt dõi theo
    this.lookX += (this.tLookX - this.lookX) * Math.min(1, dt * 6);
    this.lookY += (this.tLookY - this.lookY) * Math.min(1, dt * 6);
    this.face.look(this.lookX, this.lookY);
    // tay
    if (this.armL) {
      const idle = this.reduced ? 0 : Math.sin(t * 2.1) * 0.06;
      this.armL.rotation.z = -0.35 - idle;
      let r = 0.35 + idle;
      if (this.waveT >= 0) {
        this.waveT += dt;
        r = 2.3 + Math.sin(this.waveT * 13) * 0.45;
        if (this.waveT > this.waveDur) this.waveT = -1;
      }
      this.armR.rotation.z += (r - this.armR.rotation.z) * Math.min(1, dt * 14);
    }
    // chuông reo
    if (this.bells) {
      let a = 0;
      if (this.ringT >= 0) { this.ringT += dt; a = Math.sin(this.ringT * 46) * 0.32 * Math.max(0, 1 - this.ringT / 1.0); if (this.ringT > 1) this.ringT = -1; }
      this.bells.forEach((b, i) => { b.rotation.z = -(i ? 1 : -1) * 0.62 + a * (i ? 1 : -1); });
      const now = new Date(), mins = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
      const fast = this.ringT >= 0 ? this.ringT * 14 : 0;
      this.hands.minHand.rotation.z = -((mins % 60) / 60) * Math.PI * 2 - fast;
      this.hands.hourHand.rotation.z = -(((mins / 60) % 12) / 12) * Math.PI * 2 - fast / 12;
    }
    // ngôi sao trên khiên nảy
    if (this.star) this.star.scale.setScalar(1 + Math.max(0, this.sq) * 0.6);
    // mũ bay + tua đung đưa
    if (this.hat) {
      let hy = 1.02, hr = 0;
      if (this.hatT >= 0) {
        this.hatT += dt;
        const u = this.hatT / 0.9;
        if (u >= 1) { this.hatT = -1; this.tasselV += 5; }
        else { hy += 4 * 0.75 * u * (1 - u); hr = u * Math.PI * 2; }
      }
      this.hat.position.y = hy; this.hat.rotation.y = hr;
      this.tasselV += (-60 * this.tasselA - 3 * this.tasselV - this.sqV * 2) * dt;
      this.tasselA += this.tasselV * dt;
      this.tassel.rotation.z = Math.max(-0.7, Math.min(0.7, this.tasselA * 0.25));
    }
    // chớp mắt + trở về nét mặt theo tâm trạng
    if (clock > this.exprUntil) {
      if (this.blinkT >= 0) {
        this.blinkT += dt;
        if (this.blinkT > 0.13) { this.blinkT = -1; this.face.set(this.mood); }
      } else if (clock > this.nextBlink && (this.mood === "happy" || this.mood === "wow")) {
        this.blinkT = 0; this.face.set("blink"); this.nextBlink = clock + 2.5 + Math.random() * 3.5;
      } else if (this.face.expr !== this.mood) {
        this.face.set(this.mood);
      }
    }
    if (this.shadow) {
      const k = 1 - Math.min(0.45, y * 0.5);
      this.shadow.scale.set(this.width * 1.25 * k, this.width * 0.42 * k, 1);
      this.shadow.material.opacity = 0.2 * k;
    }
  }
}

// ------------------------------------------------------------------ hạt (tim, sao, nốt nhạc, giấy màu)
const PALETTE = [0xFFC23A, 0x26B685, 0x47AEF5, 0xFF74A0, 0x9A7BFF, 0xFF8A1F];
class Particles {
  constructor(scene) {
    this.scene = scene; this.live = [];
    this.geos = {
      heart: new THREE.ShapeGeometry(heartShape(0.09)),
      star: new THREE.ShapeGeometry(starShape(0.1, 0.045, 0.2, 0.1)),
      bit: new THREE.PlaneGeometry(0.07, 0.12),
    };
  }
  burst(at, kind, n, camera) {
    for (let i = 0; i < n; i++) {
      const color = kind === "heart" ? [0xFF5C8A, 0xFF8FB0, 0xFF6B6B][i % 3] : PALETTE[(Math.random() * PALETTE.length) | 0];
      const m = new THREE.Mesh(this.geos[kind], new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
      m.position.copy(at);
      const a = Math.random() * Math.PI * 2, sp = 1.2 + Math.random() * 1.6;
      m.userData = { v: new THREE.Vector3(Math.cos(a) * sp, 2.2 + Math.random() * 2.2, (Math.random() - 0.3) * 0.8),
                     spin: (Math.random() - 0.5) * 8, life: 0, max: 1.1 + Math.random() * 0.6, kind, face: camera };
      m.scale.setScalar(0.8 + Math.random() * 0.7);
      this.scene.add(m); this.live.push(m);
    }
  }
  update(dt) {
    this.live = this.live.filter((m) => {
      const d = m.userData;
      d.life += dt;
      if (d.life > d.max) { this.scene.remove(m); m.material.dispose(); return false; }
      d.v.y -= (d.kind === "bit" ? 3.2 : 4.2) * dt;
      d.v.multiplyScalar(1 - 0.9 * dt);
      m.position.addScaledVector(d.v, dt);
      m.quaternion.copy(d.face.quaternion);
      m.rotateZ(d.spin * d.life);
      if (d.kind === "bit") m.rotateX(d.life * 9);
      m.material.opacity = Math.min(1, (d.max - d.life) * 2.5);
      return true;
    });
  }
}

function shadowTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const x = c.getContext("2d"), gr = x.createRadialGradient(64, 64, 4, 64, 64, 62);
  gr.addColorStop(0, "rgba(67,56,202,0.9)"); gr.addColorStop(1, "rgba(67,56,202,0)");
  x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ------------------------------------------------------------------ dựng cảnh
export function createScene({ kinds, reduced = false, layout = "trio" }) {
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xD9D2FF, 1.35));
  const sun = new THREE.DirectionalLight(0xffffff, 2.1); sun.position.set(-2.5, 5, 6); scene.add(sun);
  const shadowTex = shadowTexture();
  const spots = layout === "solo" ? [{ x: 0, z: 0, scale: 1, yaw: 0 }]
    : [{ x: 0, z: 0.3, scale: 1.05, yaw: 0 }, { x: -1.92, z: -0.55, scale: 0.8, yaw: 0.34 }, { x: 1.92, z: -0.55, scale: 0.8, yaw: -0.34 }];
  const mascots = kinds.map((kind, i) => {
    const m = new Mascot(kind, { ...spots[i], phase: i * 1.7, reduced });
    const sh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false, opacity: 0.2 }));
    sh.rotation.x = -Math.PI / 2; sh.position.y = 0.005;
    m.root.add(sh); m.shadow = sh;
    scene.add(m.root);
    return m;
  });
  return { scene, mascots };
}

// ------------------------------------------------------------------ lời thoại theo số liệu thật của trẻ
function lines(d) {
  const { name, me, guardian, left, streak, study } = d;
  const now = new Date(), hh = String(now.getHours()).padStart(2, "0"), mm = String(now.getMinutes()).padStart(2, "0");
  const time = left <= 0 ? [`Hôm nay hết giờ rồi, mai mình chơi tiếp nha ${name}!`, `Ngủ ngon nha, Tíc-Tắc canh giờ cho ${me} rồi.`]
    : left <= 10 ? [`Còn ${left} phút thôi, ${me} lưu bài trước nhé!`, `Reng reng! Sắp hết giờ rồi đó ${name}.`]
    : [`Reng reng! Hôm nay ${me} còn ${left} phút nữa đó.`, `Bây giờ là ${hh}:${mm} nè!`, `Cứ 30 phút mình nghỉ mắt một chút nha ${name}!`];
  return {
    tictac: time,
    khien: [`Khiên Xanh luôn che chắn cho ${name} khi lên mạng!`, `Gặp trang lạ thì hỏi ${guardian} nha.`,
            `${cap(me)} thấy rõ mọi quy tắc — không có gì bí mật đâu!`, `Đừng cho người lạ biết mật khẩu nha ${name}!`],
    sao: [streak > 1 ? `${name} đúng giờ ${streak} ngày liền rồi! Giỏi ghê!` : `Mình cùng giữ đúng giờ để được huy hiệu nha!`,
          study > 0 ? `Hôm nay ${me} học ${study} phút rồi đó, tuyệt quá!` : `Học một chút là có thêm ngôi sao nè!`,
          `Sao Nhỏ tin ${name} làm được mà!`],
    tickle: ["Hihi, nhột quá!", "Á á, đừng cù nữa mà!", "Hihihi!"],
    party: [`Cả nhà cùng nhảy với ${name} nào!`],
    hint: `Chạm vào tớ thử xem, ${name}!`,
  };
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// ------------------------------------------------------------------ gắn vào trang của trẻ
export function mountStage(stage) {
  const d = {
    name: stage.dataset.name || "bạn", me: stage.dataset.me || "con", guardian: stage.dataset.guardian || "ba mẹ",
    left: +stage.dataset.left || 0, streak: +stage.dataset.streak || 0, study: +stage.dataset.study || 0,
  };
  const main = BUILDERS[stage.dataset.avatar] ? stage.dataset.avatar : "tictac";
  const kinds = [main, ...["khien", "sao", "tictac"].filter((k) => k !== main)].slice(0, 3);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch (e) {
    return null;   // không có WebGL => giữ mascot SVG
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.className = "m3d-canvas";
  canvas.setAttribute("aria-hidden", "true");
  stage.appendChild(canvas);
  stage.classList.add("is-3d");

  const { scene, mascots } = createScene({ kinds, reduced });
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 60);
  camera.position.set(0, 1.75, 9.9);
  camera.lookAt(0, 1.2, 0);
  const particles = new Particles(scene);
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();

  // Bong bóng thoại (đọc cho trình đọc màn hình qua aria-live) + nút bàn phím
  const bubble = document.createElement("div");
  bubble.className = "m3d-bubble"; bubble.setAttribute("role", "status"); bubble.setAttribute("aria-live", "polite");
  stage.appendChild(bubble);
  const keys = document.createElement("div");
  keys.className = "m3d-keys";
  mascots.forEach((m) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = `Chạm vào ${NAMES[m.kind]}`;
    b.addEventListener("click", () => poke(m));
    keys.appendChild(b);
  });
  stage.appendChild(keys);
  const hint = document.createElement("p");
  hint.className = "m3d-hint";
  hint.textContent = "Chạm để chơi · kéo ngang để xoay · kéo qua lại để cù";
  stage.appendChild(hint);

  const L = lines(d);
  const pick = (arr) => arr[(Math.random() * arr.length) | 0];
  const lastLine = {};
  function sayFrom(m, key) {
    const pool = L[key];
    let s = pick(pool);
    if (pool.length > 1) while (s === lastLine[key]) s = pick(pool);
    lastLine[key] = s;
    say(m, s);
  }
  let bubbleFor = null, bubbleUntil = 0;
  function say(m, text) {
    activeUntil = clock + 4;
    bubble.textContent = text;
    bubble.classList.add("on");
    bubbleFor = m; bubbleUntil = clock + 3.4;
    placeBubble();
  }
  const v3 = new THREE.Vector3();
  function placeBubble() {
    if (!bubbleFor) return;
    v3.set(0, bubbleFor.headY, 0).applyMatrix4(bubbleFor.root.matrixWorld).project(camera);
    const w = stage.clientWidth, h = stage.clientHeight;
    const bw = bubble.offsetWidth, x = Math.max(bw / 2 + 4, Math.min(w - bw / 2 - 4, (v3.x * 0.5 + 0.5) * w));
    const y = Math.max(bubble.offsetHeight + 4, (-v3.y * 0.5 + 0.5) * h);
    bubble.style.transform = `translate(${Math.round(x - bw / 2)}px, ${Math.round(y - bubble.offsetHeight)}px)`;
  }

  // Phản ứng khi chạm
  // Sự kiện "m3d:react" trên sân khấu (chỉ báo loại phản ứng, không mang dữ liệu) — để kiểm thử tự động
  const emit = (type, m) => stage.dispatchEvent(new CustomEvent("m3d:react", { detail: { type, kind: m ? m.kind : null } }));
  let tapLog = [];
  function poke(m) {
    interacted = true;
    hint.classList.add("seen");
    tapLog = tapLog.filter((t) => clock - t < 2.6);
    tapLog.push(clock);
    if (tapLog.length >= 5) { tapLog = []; return party(); }
    emit("poke", m);
    const head = new THREE.Vector3(0, m.headY * 0.82, 0.4).applyMatrix4(m.root.matrixWorld);
    m.jump(); m.express("joy", 1.5);
    if (m.kind === "tictac") { m.ring(); particles.burst(head, "star", reduced ? 3 : 7, camera); }
    if (m.kind === "khien") { m.spin(); particles.burst(head, "star", reduced ? 3 : 7, camera); }
    if (m.kind === "sao") { m.tossHat(); particles.burst(head, "star", reduced ? 4 : 10, camera); }
    sayFrom(m, m.kind);
  }
  function tickle(m) {
    const head = new THREE.Vector3(0, m.headY * 0.75, 0.4).applyMatrix4(m.root.matrixWorld);
    emit("tickle", m);
    m.wiggle(); m.express("love", 1.8);
    particles.burst(head, "heart", reduced ? 3 : 8, camera);
    sayFrom(m, "tickle");
  }
  function party() {
    emit("party", null);
    mascots.forEach((m, i) => m.after(i * 0.16, () => { m.jump(0.7); m.express("joy", 2.2); if (m.armL) m.wave(1.8); if (m.kind === "khien") m.spin(); if (m.kind === "sao") m.tossHat(); if (m.kind === "tictac") m.ring(); }));
    particles.burst(new THREE.Vector3(0, 3.4, 0), "bit", reduced ? 8 : 34, camera);
    say(mascots[0], L.party[0]);
  }

  // Con trỏ: chạm / kéo xoay / cù / mắt dõi theo
  let drag = null, interacted = false;
  function hit(ev) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hits = ray.intersectObjects(mascots.map((m) => m.root), true);
    for (const h of hits) { let o = h.object; while (o && !o.userData.mascot) o = o.parent; if (o) return o.userData.mascot; }
    let best = null, bd = Infinity;
    for (const m of mascots) {
      v3.set(0, m.headY * 0.5, 0).applyMatrix4(m.root.matrixWorld).project(camera);
      const dd = Math.hypot(ev.clientX - (r.left + (v3.x * 0.5 + 0.5) * r.width), (ev.clientY - (r.top + (-v3.y * 0.5 + 0.5) * r.height)) * 0.7);
      if (dd < bd) { bd = dd; best = m; }
    }
    return bd < r.width * 0.17 ? best : null;
  }
  function lookAt(ev) {
    const r = canvas.getBoundingClientRect();
    for (const m of mascots) {
      v3.set(0, m.headY * 0.6, 0).applyMatrix4(m.root.matrixWorld).project(camera);
      const sx = r.left + (v3.x * 0.5 + 0.5) * r.width, sy = r.top + (-v3.y * 0.5 + 0.5) * r.height;
      m.tLookX = Math.max(-1, Math.min(1, (ev.clientX - sx) / (r.width * 0.45)));
      m.tLookY = Math.max(-1, Math.min(1, -(ev.clientY - sy) / (r.height * 0.6)));
    }
    lookUntil = clock + 2.5;
  }
  let lookUntil = 0;
  canvas.addEventListener("pointerdown", (ev) => {
    const m = hit(ev);
    if (!m) return;
    drag = { m, x0: ev.clientX, x: ev.clientX, t0: clock, dir: 0, flips: 0, moved: 0, lastV: 0, tickled: false };
    m.dragging = true; m.yawV = 0;
    canvas.setPointerCapture(ev.pointerId);
  });
  canvas.addEventListener("pointermove", (ev) => {
    lookAt(ev);
    canvas.style.cursor = drag ? "grabbing" : hit(ev) ? "pointer" : "";
    if (!drag) return;
    const dx = ev.clientX - drag.x;
    drag.x = ev.clientX; drag.moved += Math.abs(dx);
    if (Math.abs(dx) > 2) {
      const dir = Math.sign(dx);
      if (drag.dir && dir !== drag.dir) drag.flips++;
      drag.dir = dir;
    }
    if (!reduced) drag.m.yaw += dx * 0.013;
    drag.lastV = dx * 0.013 * 60;
    if (drag.flips >= 4 && !drag.tickled) { drag.tickled = true; tickle(drag.m); }
  });
  const end = (ev) => {
    if (!drag) return;
    const m = drag.m;
    m.dragging = false; m.releasedAt = clock; m.yawV = reduced ? 0 : drag.lastV;
    if (drag.moved < 8 && clock - drag.t0 < 0.5) poke(m);
    else interacted = true;
    drag = null;
    try { canvas.releasePointerCapture(ev.pointerId); } catch (e) { /* đã nhả */ }
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("pointerleave", () => { if (!drag) canvas.style.cursor = ""; });

  // Kích thước + chỉ vẽ khi đang nhìn thấy (tiết kiệm pin/CPU)
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // màn hẹp: lùi camera để cả 3 nhân vật vẫn lọt khung
    camera.position.z = 9.9 * Math.max(1, 1.12 / camera.aspect);
    camera.lookAt(0, 1.2, 0);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(stage);
  resize();
  let visible = true;
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible) kick(true); }).observe(stage);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(true); });

  // Tâm trạng theo thời gian còn lại
  const tic = mascots.find((m) => m.kind === "tictac");
  if (d.left <= 0) mascots.forEach((m) => (m.mood = m === tic ? "sleepy" : "happy"));
  else if (d.left <= 10 && tic) tic.mood = "wow";

  let clock = 0, last = 0, running = false, hinted = false, slow = 0, frameNo = 0, activeUntil = 0, pr = renderer.getPixelRatio();
  const markActive = () => { activeUntil = clock + 6; };
  canvas.addEventListener("pointermove", markActive);
  canvas.addEventListener("pointerdown", markActive);
  function frame(now) {
    running = false;
    if (!visible || document.hidden) return;
    const elapsed = last ? Math.min(0.25, Math.max(0, (now - last) / 1000)) : 1 / 60;
    last = now; frameNo++;
    if (frameNo > 30) {
      slow = slow * 0.95 + (elapsed > 0.05 ? 0.05 : 0);
      if (slow > 0.6 && pr > 0.6) { pr = Math.max(0.6, pr * 0.75); renderer.setPixelRatio(pr); resize(); slow = 0; }
    }
    for (let left = elapsed; left > 1e-4;) {
      const dt = Math.min(1 / 30, left);
      left -= dt; clock += dt;
      if (clock > lookUntil) for (const m of mascots) { m.tLookX *= 0.96; m.tLookY *= 0.96; }
      for (const m of mascots) m.update(dt, clock);
      particles.update(dt);
    }
    if (clock > activeUntil && !particles.live.length && !bubbleFor && frameNo % 2) { kick(); return; }
    if (!interacted && !hinted && clock > 6) {
      hinted = true;
      const m = mascots[0];
      if (m.armL) m.wave(2.2); else m.jump(0.3);
      say(m, L.hint);
    }
    if (bubbleFor) { if (clock > bubbleUntil) { bubble.classList.remove("on"); bubbleFor = null; } else placeBubble(); }
    renderer.render(scene, camera);
    kick();
  }
  function kick(resume) { if (resume) last = 0; if (!running) { running = true; requestAnimationFrame(frame); } }
  kick();
  return { renderer, scene, camera, mascots };
}

// Tự gắn vào mọi [data-m3d] trên trang (trang tạo ảnh sprite cho Tray import module này mà không có phần tử đó).
for (const el of document.querySelectorAll("[data-m3d]")) mountStage(el);
