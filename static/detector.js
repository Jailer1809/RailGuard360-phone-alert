// Push / fall detector (same logic as detector.py). Units: frame-heights, torso-lengths/sec.
export class FallPushAnalyzer {
  constructor(o = {}) {
    this.fallVy = o.fallVy ?? 1.4; this.pushVx = o.pushVx ?? 1.6;
    this.lyingTilt = o.lyingTilt ?? 55; this.lyingTime = o.lyingTime ?? 0.30;
    this.stumbleTilt = o.stumbleTilt ?? 35; this.cooldown = o.cooldown ?? 10;
    this.h = []; this.lastEventT = -1e9; this.tilt = 0;
  }
  static tilt(sx, sy, hx, hy) { return Math.atan2(Math.abs(sx - hx), Math.abs(sy - hy) + 1e-9) * 180 / Math.PI; }
  update(t, [sx, sy], [hx, hy]) {
    const L = Math.max(Math.hypot(sx - hx, sy - hy), 1e-3);
    this.tilt = FallPushAnalyzer.tilt(sx, sy, hx, hy);
    this.h.push({ t, hx, hy, tilt: this.tilt, L });
    while (this.h.length && t - this.h[0].t > 1.5) this.h.shift();
    const H = this.h;
    if (H.length < 6 || t - this.lastEventT < this.cooldown) return null;
    const Ls = H.map(e => e.L).sort((a, b) => a - b), Lref = Ls[Math.floor(Ls.length / 2)];
    let pvy = 0, pvx = 0;
    for (let i = 0; i < H.length; i++) {
      for (let j = i - 1; j >= 0; j--) {
        const dt = H[i].t - H[j].t;
        if (dt >= 0.12) {
          if (dt <= 0.3) { pvy = Math.max(pvy, (H[i].hy - H[j].hy) / dt / Lref); pvx = Math.max(pvx, Math.abs(H[i].hx - H[j].hx) / dt / Lref); }
          break;
        }
      }
    }
    const recent = H.filter(e => t - e.t <= this.lyingTime);
    const lying = recent.length >= 3 && recent[recent.length - 1].t - recent[0].t >= this.lyingTime * 0.8 &&
      recent.every(e => e.tilt >= this.lyingTilt);
    const baseTilt = Math.min(...H.map(e => e.tilt));
    let ev = null;
    if (lying && (pvy >= this.fallVy || pvx >= this.pushVx))
      ev = { type: pvx >= this.pushVx ? "PUSH" : "FALL", confidence: Math.min(0.99, 0.6 + 0.1 * Math.max(pvx, pvy)) };
    else if (pvx >= this.pushVx * 1.4 && this.tilt - baseTilt >= this.stumbleTilt) ev = { type: "PUSH", confidence: 0.65 };
    if (ev) { this.lastEventT = t; Object.assign(ev, { t, peakVx: +pvx.toFixed(2), peakVy: +pvy.toFixed(2), tilt: +this.tilt.toFixed(1) }); }
    return ev;
  }
}
