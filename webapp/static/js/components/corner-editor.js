// Drag the four page corners (or a whole edge) over the photo, with a magnifier loupe.
// Corners are normalised 0..1 and ordered TL, TR, BR, BL.

import { h } from '../lib/ui.js';

const FULL = [[0, 0], [1, 0], [1, 1], [0, 1]];
const HIT = 22;       // px radius for grabbing a handle
const LOUPE_ZOOM = 3;

export class CornerEditor {
  constructor({ src, corners, onChange }) {
    this.corners = (corners || FULL).map((p) => [...p]);
    this.onChange = onChange;
    this.drag = null;
    this.active = 0;
    this.img = h('img', { src, alt: 'Original photo', draggable: 'false' });
    this.canvas = h('canvas', { tabindex: 0, 'aria-label': 'Page corners. Tab selects the editor, 1-4 choose a corner, arrow keys move it.' });
    this.loupe = h('canvas', { class: 'loupe', width: 124, height: 124 });
    this.el = h('div', { class: 'ce' }, this.img, this.canvas, this.loupe);
    this.ctx = this.canvas.getContext('2d');

    this.img.addEventListener('load', () => this.layout());
    this.resizeObserver = new ResizeObserver(() => this.layout());
    this.resizeObserver.observe(this.el);
    this.canvas.addEventListener('pointerdown', (e) => this.onDown(e));
    this.canvas.addEventListener('pointermove', (e) => this.onMove(e));
    this.canvas.addEventListener('pointerup', (e) => this.onUp(e));
    this.canvas.addEventListener('pointercancel', (e) => this.onUp(e));
    this.canvas.addEventListener('keydown', (e) => this.onKey(e));
    this.canvas.addEventListener('focus', () => this.draw());
    this.canvas.addEventListener('blur', () => this.draw());
  }

  destroy() { this.resizeObserver.disconnect(); }

  setCorners(corners) {
    this.corners = (corners || FULL).map((p) => [...p]);
    this.draw();
  }

  getCorners() { return this.corners.map((p) => [...p]); }

  isFull() { return this.corners.every((p, i) => Math.abs(p[0] - FULL[i][0]) < 1e-3 && Math.abs(p[1] - FULL[i][1]) < 1e-3); }

  // ---------------------------------------------------------------- geometry
  layout() {
    const r = this.img.getBoundingClientRect();
    const host = this.el.getBoundingClientRect();
    if (!r.width) return;
    const dpr = window.devicePixelRatio || 1;
    this.box = { x: r.left - host.left, y: r.top - host.top, w: r.width, h: r.height };
    // a small margin lets handles at the very edge still be grabbed
    this.pad = 14;
    Object.assign(this.canvas.style, {
      left: `${this.box.x - this.pad}px`, top: `${this.box.y - this.pad}px`,
      width: `${this.box.w + 2 * this.pad}px`, height: `${this.box.h + 2 * this.pad}px`,
    });
    this.canvas.width = (this.box.w + 2 * this.pad) * dpr;
    this.canvas.height = (this.box.h + 2 * this.pad) * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  toPx([x, y]) { return [this.pad + x * this.box.w, this.pad + y * this.box.h]; }
  toNorm(px, py) {
    return [Math.min(1, Math.max(0, (px - this.pad) / this.box.w)), Math.min(1, Math.max(0, (py - this.pad) / this.box.h))];
  }
  local(e) { const r = this.canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }

  hitTest(px, py) {
    const pts = this.corners.map((p) => this.toPx(p));
    let best = null, bestD = HIT;
    pts.forEach((p, i) => { const d = Math.hypot(p[0] - px, p[1] - py); if (d < bestD) { best = { type: 'corner', i }; bestD = d; } });
    if (best) return best;
    pts.forEach((p, i) => {
      const q = pts[(i + 1) % 4];
      const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
      const d = Math.hypot(m[0] - px, m[1] - py);
      if (d < bestD) { best = { type: 'edge', i }; bestD = d; }
    });
    return best;
  }

  // ---------------------------------------------------------------- pointer
  onDown(e) {
    if (!this.box) return;
    const [px, py] = this.local(e);
    const hit = this.hitTest(px, py);
    if (!hit) return;
    e.preventDefault();
    this.canvas.setPointerCapture(e.pointerId);
    this.drag = { ...hit, start: this.toNorm(px, py), orig: this.getCorners() };
    if (hit.type === 'corner') this.active = hit.i;
    this.canvas.classList.add('grabbing');
    this.onMove(e);
  }

  onMove(e) {
    if (!this.box) return;
    const [px, py] = this.local(e);
    if (!this.drag) {
      this.canvas.classList.toggle('grab', !!this.hitTest(px, py));
      return;
    }
    const [nx, ny] = this.toNorm(px, py);
    if (this.drag.type === 'corner') {
      this.corners[this.drag.i] = [nx, ny];
      this.showLoupe(nx, ny);
    } else {
      const dx = nx - this.drag.start[0], dy = ny - this.drag.start[1];
      for (const j of [this.drag.i, (this.drag.i + 1) % 4]) {
        const o = this.drag.orig[j];
        this.corners[j] = [Math.min(1, Math.max(0, o[0] + dx)), Math.min(1, Math.max(0, o[1] + dy))];
      }
    }
    this.draw();
  }

  onUp() {
    if (!this.drag) return;
    const changed = JSON.stringify(this.drag.orig) !== JSON.stringify(this.corners);
    this.drag = null;
    this.canvas.classList.remove('grabbing');
    this.loupe.style.display = 'none';
    this.draw();
    if (changed) this.onChange?.(this.getCorners());
  }

  onKey(e) {
    if (['1', '2', '3', '4'].includes(e.key)) { this.active = Number(e.key) - 1; this.draw(); return; }
    const step = e.shiftKey ? 0.01 : 0.002;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (!d) return;
    e.preventDefault();
    const p = this.corners[this.active];
    this.corners[this.active] = [Math.min(1, Math.max(0, p[0] + d[0])), Math.min(1, Math.max(0, p[1] + d[1]))];
    this.draw();
    clearTimeout(this.keyTimer);
    this.keyTimer = setTimeout(() => this.onChange?.(this.getCorners()), 350);
  }

  // ---------------------------------------------------------------- drawing
  showLoupe(nx, ny) {
    const L = this.loupe, lctx = L.getContext('2d');
    const nw = this.img.naturalWidth, nh = this.img.naturalHeight;
    const size = 124, src = (size / LOUPE_ZOOM) * (nw / this.box.w);
    lctx.fillStyle = '#000';
    lctx.fillRect(0, 0, size, size);
    lctx.drawImage(this.img, nx * nw - src / 2, ny * nh - src / 2, src, src, 0, 0, size, size);
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    lctx.strokeStyle = accent;
    lctx.lineWidth = 1.5;
    lctx.beginPath();
    lctx.moveTo(size / 2, 0); lctx.lineTo(size / 2, size);
    lctx.moveTo(0, size / 2); lctx.lineTo(size, size / 2);
    lctx.stroke();
    // keep the loupe away from the finger/cursor
    const [px, py] = this.toPx([nx, ny]);
    const left = this.box.x - this.pad + px + (nx > 0.5 ? -150 : 26);
    const top = this.box.y - this.pad + py + (ny > 0.5 ? -150 : 26);
    Object.assign(L.style, { display: 'block', left: `${left}px`, top: `${top}px` });
  }

  draw() {
    if (!this.box) return;
    const ctx = this.ctx;
    const W = this.box.w + 2 * this.pad, H = this.box.h + 2 * this.pad;
    const style = getComputedStyle(document.documentElement);
    const accent = style.getPropertyValue('--accent').trim() || '#4f46e5';
    ctx.clearRect(0, 0, W, H);
    const pts = this.corners.map((p) => this.toPx(p));

    // dim outside the page
    ctx.fillStyle = 'rgba(10,10,14,0.45)';
    ctx.beginPath();
    ctx.rect(this.pad, this.pad, this.box.w, this.box.h);
    pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
    ctx.closePath();
    ctx.fill('evenodd');

    // outline
    ctx.lineWidth = 2;
    ctx.strokeStyle = accent;
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
    ctx.closePath();
    ctx.stroke();

    // edge handles (pills at mid-points)
    pts.forEach((p, i) => {
      const q = pts[(i + 1) % 4];
      const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
      const ang = Math.atan2(q[1] - p[1], q[0] - p[0]);
      ctx.save();
      ctx.translate(...m);
      ctx.rotate(ang);
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.roundRect(-11, -4, 22, 8, 4);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    });

    // corner handles
    pts.forEach((p, i) => {
      const activeDrag = this.drag?.type === 'corner' && this.drag.i === i;
      ctx.beginPath();
      ctx.arc(p[0], p[1], activeDrag ? 11 : 9, 0, Math.PI * 2);
      ctx.fillStyle = activeDrag ? accent : '#fff';
      ctx.fill();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = accent;
      ctx.stroke();
      if (document.activeElement === this.canvas && this.active === i) {
        ctx.beginPath();
        ctx.arc(p[0], p[1], 15, 0, Math.PI * 2);
        ctx.lineWidth = 2;
        ctx.strokeStyle = accent;
        ctx.stroke();
      }
    });
  }
}
