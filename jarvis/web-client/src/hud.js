// ZEMARK HUD — a J.A.R.V.I.S.-style arc-reactor visualizer.
//
// Pure canvas, no dependencies. It renders a glowing reactor core wrapped in
// rotating rings, tick marks, targeting brackets, and a circular waveform that
// reacts to live audio. Colour + energy shift with the assistant's state:
//
//   idle       dim cyan, slow breathing
//   listening  bright cyan, outer ring reacts to your microphone
//   thinking   amber, fast spinner sweep
//   speaking   gold, core pulses with the agent's voice
//
// Usage:
//   const hud = new ZemarkHUD(canvas);
//   hud.start();
//   hud.setState('listening');
//   hud.setAnalyser('mic', micAnalyser);     // Web Audio AnalyserNode
//   hud.setAnalyser('agent', agentAnalyser);

const STATE_COLORS = {
  idle:      { r: 90,  g: 200, b: 255 },
  listening: { r: 60,  g: 220, b: 255 },
  thinking:  { r: 255, g: 190, b: 70  },
  speaking:  { r: 255, g: 210, b: 120 },
};

export class ZemarkHUD {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.state = 'idle';
    this.analysers = { mic: null, agent: null };
    this._raf = null;
    this._t = 0;
    this._level = 0;       // smoothed current amplitude 0..1
    this._color = { ...STATE_COLORS.idle };
    this._resize = this._resize.bind(this);
    this._loop = this._loop.bind(this);
    this._wave = new Uint8Array(256);
  }

  setState(state) {
    if (STATE_COLORS[state]) this.state = state;
  }

  setAnalyser(kind, analyser) {
    if (kind in this.analysers) this.analysers[kind] = analyser;
  }

  start() {
    window.addEventListener('resize', this._resize);
    this._resize();
    if (!this._raf) this._raf = requestAnimationFrame(this._loop);
  }

  stop() {
    window.removeEventListener('resize', this._resize);
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._w = rect.width;
    this._h = rect.height;
  }

  // Pick which analyser drives the waveform/energy for the current state.
  _activeAnalyser() {
    if (this.state === 'speaking') return this.analysers.agent || this.analysers.mic;
    return this.analysers.mic || this.analysers.agent;
  }

  _readLevel() {
    const an = this._activeAnalyser();
    if (!an) return 0;
    try {
      an.getByteTimeDomainData(this._wave);
    } catch {
      return 0;
    }
    let sum = 0;
    for (let i = 0; i < this._wave.length; i++) {
      const v = (this._wave[i] - 128) / 128;
      sum += v * v;
    }
    return Math.min(1, Math.sqrt(sum / this._wave.length) * 3.2);
  }

  _loop() {
    this._t += 0.016;
    // smooth colour transition toward the target state colour
    const target = STATE_COLORS[this.state];
    const c = this._color;
    c.r += (target.r - c.r) * 0.08;
    c.g += (target.g - c.g) * 0.08;
    c.b += (target.b - c.b) * 0.08;

    const raw = this._readLevel();
    // breathing baseline when idle so it never looks dead
    const base = this.state === 'idle' ? 0.06 + 0.04 * Math.sin(this._t * 1.6) : 0.04;
    this._level += (Math.max(base, raw) - this._level) * 0.25;

    this._render();
    this._raf = requestAnimationFrame(this._loop);
  }

  _render() {
    const ctx = this.ctx;
    const w = this._w, h = this._h;
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * 0.34;
    const c = this._color;
    const rgb = (a) => `rgba(${c.r | 0},${c.g | 0},${c.b | 0},${a})`;
    const lvl = this._level;

    ctx.clearRect(0, 0, w, h);

    // faint radial backdrop glow
    const bg = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 2.2);
    bg.addColorStop(0, rgb(0.10 + lvl * 0.12));
    bg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    // outer rotating tick ring
    this._ticks(cx, cy, R * 1.42, 90, this._t * 0.15, rgb(0.35), 6);
    // inner counter-rotating fine ticks
    this._ticks(cx, cy, R * 1.18, 160, -this._t * 0.25, rgb(0.18), 3);

    // targeting brackets (four rotating arcs)
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(this._t * (this.state === 'thinking' ? 1.4 : 0.3));
    ctx.strokeStyle = rgb(0.5);
    ctx.lineWidth = 2;
    for (let k = 0; k < 4; k++) {
      ctx.beginPath();
      const a0 = (k * Math.PI) / 2 + 0.2;
      ctx.arc(0, 0, R * 1.55, a0, a0 + 0.6);
      ctx.stroke();
    }
    ctx.restore();

    // mic/agent reactive EQ ring — segmented bars around the core
    this._eqRing(cx, cy, R * 0.98, rgb);

    // circular waveform
    this._waveform(cx, cy, R * 0.72, rgb(0.85));

    // dashed rotating ring
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-this._t * 0.6);
    ctx.setLineDash([4, 10]);
    ctx.strokeStyle = rgb(0.4);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.86, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // the reactor core
    this._core(cx, cy, R * 0.5, lvl, rgb, c);
  }

  _ticks(cx, cy, radius, count, rot, color, len) {
    const ctx = this.ctx;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rot);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2;
      const big = i % 10 === 0;
      const l = big ? len * 2 : len;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * radius, Math.sin(a) * radius);
      ctx.lineTo(Math.cos(a) * (radius - l), Math.sin(a) * (radius - l));
      ctx.stroke();
    }
    ctx.restore();
  }

  _eqRing(cx, cy, radius, rgb) {
    const ctx = this.ctx;
    const bars = 72;
    ctx.save();
    ctx.translate(cx, cy);
    for (let i = 0; i < bars; i++) {
      const idx = Math.floor((i / bars) * this._wave.length);
      const amp = Math.abs((this._wave[idx] || 128) - 128) / 128;
      const len = 4 + amp * radius * 0.5;
      const a = (i / bars) * Math.PI * 2 + this._t * 0.1;
      const x0 = Math.cos(a) * radius, y0 = Math.sin(a) * radius;
      const x1 = Math.cos(a) * (radius + len), y1 = Math.sin(a) * (radius + len);
      ctx.strokeStyle = rgb(0.35 + amp * 0.6);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }
    ctx.restore();
  }

  _waveform(cx, cy, radius, color) {
    const ctx = this.ctx;
    const n = this._wave.length;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const idx = i % n;
      const amp = ((this._wave[idx] || 128) - 128) / 128;
      const a = (i / n) * Math.PI * 2;
      const rr = radius + amp * radius * 0.35;
      const x = Math.cos(a) * rr, y = Math.sin(a) * rr;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  _core(cx, cy, radius, lvl, rgb, c) {
    const ctx = this.ctx;
    const r = radius * (0.72 + lvl * 0.5);
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 1.6);
    glow.addColorStop(0, `rgba(255,255,255,${0.85})`);
    glow.addColorStop(0.25, rgb(0.9));
    glow.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.6, 0, Math.PI * 2);
    ctx.fill();

    // arc-reactor coils: nine segments
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(this._t * 0.4);
    ctx.strokeStyle = `rgba(10,20,30,0.85)`;
    ctx.lineWidth = Math.max(3, r * 0.14);
    for (let i = 0; i < 9; i++) {
      const a = (i / 9) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r * 0.35, Math.sin(a) * r * 0.35);
      ctx.lineTo(Math.cos(a) * r * 0.92, Math.sin(a) * r * 0.92);
      ctx.stroke();
    }
    ctx.restore();

    // bright inner disc
    ctx.fillStyle = `rgba(${240},${250},${255},${0.95})`;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 0.34, 0, Math.PI * 2);
    ctx.fill();

    // rim
    ctx.strokeStyle = rgb(0.9);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
  }
}
