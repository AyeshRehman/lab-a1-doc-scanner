// Same idea as docscan/tracking.py: smooth corners over time and detect a steady hold.
// Corners are normalised (0..1), so thresholds do not depend on resolution.

export class CornerTracker {
  constructor({ alpha = 0.45, move = 0.02, hold = 6, stable = 15 } = {}) {
    Object.assign(this, { alpha, move, hold, stableFrames: stable });
    this.reset();
  }

  reset() { this.corners = null; this.stable = 0; this.missed = 0; }

  update(corners) {
    if (!corners) {
      this.missed += 1;
      if (this.missed > this.hold) { this.corners = null; this.stable = 0; }
      return this.corners;
    }
    this.missed = 0;
    if (!this.corners) {
      this.corners = corners;
      this.stable = 0;
      return this.corners;
    }
    let maxMove = 0;
    corners.forEach((p, i) => {
      maxMove = Math.max(maxMove, Math.abs(p[0] - this.corners[i][0]), Math.abs(p[1] - this.corners[i][1]));
    });
    if (maxMove < this.move) {
      this.corners = corners.map((p, i) => [
        this.alpha * p[0] + (1 - this.alpha) * this.corners[i][0],
        this.alpha * p[1] + (1 - this.alpha) * this.corners[i][1],
      ]);
      this.stable += 1;
    } else {
      this.corners = corners;
      this.stable = 0;
    }
    return this.corners;
  }

  get progress() { return this.corners ? Math.min(1, this.stable / this.stableFrames) : 0; }
  get isStable() { return this.progress >= 1; }
}

/** Draw the page outline over a stage. rect = where the image is shown inside the canvas. */
export function drawPageOverlay(ctx, rect, corners, { progress = 0, color } = {}) {
  const pts = corners.map(([x, y]) => [rect.x + x * rect.w, rect.y + y * rect.h]);
  const steady = progress >= 1;
  const stroke = color || (steady ? '#4ade80' : '#fbbf24');
  ctx.save();
  // dim everything outside the page
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.beginPath();
  ctx.rect(rect.x, rect.y, rect.w, rect.h);
  ctx.moveTo(...pts[0]);
  for (const p of pts.slice(1).reverse()) ctx.lineTo(...p);
  ctx.closePath();
  ctx.fill('evenodd');
  // outline
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3;
  ctx.strokeStyle = stroke;
  ctx.fillStyle = steady ? 'rgba(74,222,128,0.12)' : 'rgba(251,191,36,0.08)';
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // corner brackets
  ctx.lineWidth = 5;
  ctx.lineCap = 'round';
  pts.forEach((p, i) => {
    const prev = pts[(i + 3) % 4], next = pts[(i + 1) % 4];
    const seg = (q) => {
      const dx = q[0] - p[0], dy = q[1] - p[1], len = Math.hypot(dx, dy) || 1, l = Math.min(26, len * 0.25);
      return [p[0] + (dx / len) * l, p[1] + (dy / len) * l];
    };
    ctx.beginPath();
    ctx.moveTo(...seg(prev));
    ctx.lineTo(...p);
    ctx.lineTo(...seg(next));
    ctx.stroke();
  });
  ctx.restore();
}
