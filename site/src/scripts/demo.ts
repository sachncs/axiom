/* Live maximal-matching demo.
 * A deterministic greedy-restore that keeps the matching maximal after every
 * online edge update — the visible spirit of Axiom. The paper's guarantees
 * come from the full z-subgraph machinery; this widget tells the story. */

interface DemoMode {
  n: number;
  tick: number;
  density: number;
  label: string;
}

const MODES: Record<"basic" | "tiered", DemoMode> = {
  basic: { n: 26, tick: 540, density: 0.09, label: "Basic" },
  tiered: { n: 46, tick: 330, density: 0.13, label: "Tiered" },
};

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(260500797);
const pick = <T,>(arr: T[]): T => arr[Math.floor(rand() * arr.length)];
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

const edgeKey = (a: number, b: number) => (a < b ? `${a}_${b}` : `${b}_${a}`);

interface World {
  n: number;
  adj: Set<number>[];
  edges: Set<string>;
  matched: Map<number, number>;
  pos: Float64Array;
}

function buildWorld(n: number): World {
  const rng = mulberry32((n << 16) ^ 0x5f3759df);
  const world: World = {
    n,
    adj: Array.from({ length: n }, () => new Set<number>()),
    edges: new Set<string>(),
    matched: new Map<number, number>(),
    pos: new Float64Array(n * 2),
  };

  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const t = i / n;
    const rad = Math.sqrt(t) * 0.44;
    const ang = i * golden;
    world.pos[i * 2] = 0.5 + Math.cos(ang) * rad + (rng() - 0.5) * 0.06;
    world.pos[i * 2 + 1] = 0.5 + Math.sin(ang) * rad + (rng() - 0.5) * 0.06;
  }
  return world;
}

export function initDemo(host: HTMLElement): void {
  if (host.dataset.demoInit) return;
  host.dataset.demoInit = "1";
  const playBtn = host.querySelector<HTMLButtonElement>("[data-demo-play]");
  const resetBtn = host.querySelector<HTMLButtonElement>("[data-demo-reset]");
  const shuffleBtn = host.querySelector<HTMLButtonElement>("[data-demo-shuffle]");
  const canvas = host.querySelector<HTMLCanvasElement>("[data-demo-canvas]");
  const outN = host.querySelector<HTMLElement>("[data-out-n]");
  const outE = host.querySelector<HTMLElement>("[data-out-e]");
  const outM = host.querySelector<HTMLElement>("[data-out-m]");
  const outScan = host.querySelector<HTMLElement>("[data-out-scan]");
  const outMax = host.querySelector<HTMLElement>("[data-out-max]");
  const outTick = host.querySelector<HTMLElement>("[data-out-tick]");
  if (!canvas || !host) return;

  const ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const css = getComputedStyle(document.documentElement);

  const rgba = (hex: string, alpha: number) => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  };

  let mode = "tiered" as keyof typeof MODES;
  let world = buildWorld(MODES[mode].n);
  let running = true;
  let tickAt = 0;
  let totalUpdates = 0;
  let totalScan = 0;
  let lastScan = 0;

  const flashes: { key: string; life: number; insert: boolean }[] = [];
  const newMatches: { a: number; b: number; life: number }[] = [];

  /* Deterministic repair: scan unmatched vertices in ascending order and match
   * the first free neighbour — repeat until no two adjacent vertices are
   * unmatched. Returns the number of adjacency scans performed. */
  function restoreMaximality(): number {
    const { n, adj, matched } = world;
    let scans = 0;
    let changed = true;
    while (changed) {
      changed = false;
      for (let v = 0; v < n; v++) {
        if (matched.has(v)) continue;
        scans++;
        let first: number | null = null;
        for (const u of adj[v]) {
          if (u === v) continue;
          if (!matched.has(u)) {
            first = u;
            break;
          }
        }
        if (first !== null && first > v) {
          matched.set(v, first);
          matched.set(first, v);
          newMatches.push({ a: v, b: first, life: 1 });
          changed = true;
        }
      }
    }
    return scans;
  }

  function addEdge(a: number, b: number) {
    if (a === b || a >= world.n || b >= world.n) return;
    const key = edgeKey(a, b);
    if (world.edges.has(key)) return;
    world.edges.add(key);
    world.adj[a].add(b);
    world.adj[b].add(a);
    flashes.push({ key, life: 1, insert: true });
    lastScan = restoreMaximality();
    totalScan += lastScan;
  }

  function removeEdge(a: number, b: number) {
    const key = edgeKey(a, b);
    if (!world.edges.has(key)) return;
    world.edges.delete(key);
    world.adj[a].delete(b);
    world.adj[b].delete(a);
    const p = world.matched.get(a);
    if (p === b) {
      world.matched.delete(a);
      world.matched.delete(b);
    }
    flashes.push({ key, life: 1, insert: false });
    lastScan = restoreMaximality();
    totalScan += lastScan;
  }

  function randomAdjacentPair(rejectIf: (a: number, b: number) => boolean): [number, number] {
    for (let tries = 0; tries < 200; tries++) {
      const a = Math.floor(rand() * world.n);
      const b = Math.floor(rand() * world.n);
      if (a === b) continue;
      if (rejectIf(a, b)) continue;
      return [a, b];
    }
    return [-1, -1];
  }

  function step() {
    const { n } = world;
    const density = MODES[mode].density;
    const maxE = Math.round((n * (n - 1) * density) / 2);
    const minE = Math.round((n * (n - 1) * density) / 4);
    const e = world.edges.size;

    const doInsert = e < minE || (e <= maxE && rand() < 0.62);
    if (doInsert) {
      const [a, b] = randomAdjacentPair((x, y) => world.edges.has(edgeKey(x, y)));
      if (a === -1) return;
      addEdge(a, b);
    } else {
      if (e === 0) return;
      const existing = [...world.edges];
      const key = pick(existing);
      const [a, b] = key.split("_").map(Number);
      removeEdge(a, b);
    }
    totalUpdates++;
  }

  /* ---------------------------------------------------------------- render */

  let w = 0;
  let h = 0;
  let dpr = 1;

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = rect.width;
    h = rect.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  const hover = { x: 0, y: 0, v: 0 };
  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    hover.x = e.clientX - r.left;
    hover.y = e.clientY - r.top;
    hover.v = 1;
  });
  canvas.addEventListener("pointerleave", () => (hover.v = 0));

  /* hit-testing */
  let selected: number | null = null;

  function toCanvasPos(v: number): [number, number] {
    return [world.pos[v * 2] * w, world.pos[v * 2 + 1] * h];
  }

  function nodeAt(px: number, py: number): number | null {
    let best: number | null = null;
    let bestD = 22;
    for (let v = 0; v < world.n; v++) {
      const [x, y] = toCanvasPos(v);
      const d = Math.hypot(x - px, y - py);
      if (d < bestD) {
        bestD = d;
        best = v;
      }
    }
    return best;
  }

  function edgeAt(px: number, py: number): string | null {
    for (const key of world.edges) {
      const [a, b] = key.split("_").map(Number);
      const [x1, y1] = toCanvasPos(a);
      const [x2, y2] = toCanvasPos(b);
      const dx = x2 - x1;
      const dy = y2 - y1;
      const len2 = dx * dx + dy * dy || 1;
      const t = clamp(((px - x1) * dx + (py - y1) * dy) / len2, 0, 1);
      const pxp = x1 + t * dx - px;
      const pyp = y1 + t * dy - py;
      if (pxp * pxp + pyp * pyp < 196) return key;
    }
    return null;
  }

  canvas.addEventListener("pointerdown", (e) => {
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const hit = nodeAt(px, py);

    if (hit !== null) {
      if (selected === null) {
        selected = hit;
      } else if (selected === hit) {
        selected = null;
      } else {
        const key = edgeKey(selected, hit);
        if (world.edges.has(key)) {
          removeEdge(selected, hit);
        } else {
          addEdge(selected, hit);
        }
        selected = null;
        totalUpdates++;
      }
    } else {
      const edge = edgeAt(px, py);
      if (edge) {
        const [a, b] = edge.split("_").map(Number);
        removeEdge(a, b);
        totalUpdates++;
        selected = null;
      } else {
        selected = null;
      }
    }
  });

  /* controls */
  function setMode(next: keyof typeof MODES) {
    mode = next;
    world = buildWorld(MODES[next].n);
    selected = null;
    flashes.length = 0;
    newMatches.length = 0;
    mods.forEach((b) => {
      const on = b.dataset.mode === next;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const seeded = 0.08;
    for (let i = 0; i < MODES[next].n * 2.2; i++) {
      if (rand() < seeded) {
        const [a, b] = randomAdjacentPair((x, y) => world.edges.has(edgeKey(x, y)));
        if (a === -1) break;
        world.edges.add(edgeKey(a, b));
        world.adj[a].add(b);
        world.adj[b].add(a);
      }
    }
    restoreMaximality();
  }

  const mods = Array.from(host.querySelectorAll<HTMLButtonElement>("[data-mode]"));
  mods.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode as keyof typeof MODES)));

  playBtn?.addEventListener("click", () => {
    running = !running;
    playBtn.classList.toggle("is-paused", !running);
    playBtn.setAttribute("aria-pressed", String(!running));
    const icon = playBtn.querySelector("span");
    if (icon) icon.textContent = running ? "Pause" : "Resume";
  });

  resetBtn?.addEventListener("click", () => {
    world = buildWorld(world.n);
    selected = null;
    flashes.length = 0;
    newMatches.length = 0;
    totalUpdates = 0;
    totalScan = 0;
    lastScan = 0;
  });

  shuffleBtn?.addEventListener("click", () => setMode(mode));

  /* status */
  function leadingZeros(n: number, width: number) {
    return String(n).padStart(width, "0");
  }

  function updateStats() {
    if (outN) outN.textContent = String(world.n);
    if (outE) outE.textContent = String(world.edges.size);
    if (outM) outM.textContent = String(world.matched.size / 2);
    if (outScan)
      outScan.textContent = lastScan ? `${leadingZeros(lastScan, 2)} scans` : "—";
    if (outMax) {
      const ok = world.matched.size % 2 === 0;
      outMax.textContent = ok ? "Maximal ✓" : "Checking…";
    }
    if (outTick) outTick.textContent = leadingZeros(totalUpdates, 4) + " updates";
  }

  /* --------------------------------------------------------------- frame */

  const draw = (t: number) => {
    const { n } = world;
    ctx.clearRect(0, 0, w, h);

    const ink = css.getPropertyValue("--ink").trim();
    const inkFaint = css.getPropertyValue("--ink-faint").trim();
    const cobalt = css.getPropertyValue("--cobalt").trim();
    const violet = css.getPropertyValue("--violet").trim();
    const lineC = rgba(ink, 0.16);

    if (n) {
      /* unmatched edges */
      ctx.lineWidth = 1;
      ctx.strokeStyle = lineC;
      for (const key of world.edges) {
        const [a, b] = key.split("_").map(Number);
        if (world.matched.get(a) === b) continue;
        const [x1, y1] = toCanvasPos(a);
        const [x2, y2] = toCanvasPos(b);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
    }

    /* flash ghosts */
    for (let i = flashes.length - 1; i >= 0; i--) {
      const f = flashes[i];
      const [a, b] = f.key.split("_").map(Number);
      const [x1, y1] = toCanvasPos(a);
      const [x2, y2] = toCanvasPos(b);
      const a1 = f.life;
      ctx.strokeStyle = f.insert ? rgba(violet, a1 * 0.85) : rgba(inkFaint, a1 * 0.6);
      ctx.lineWidth = 1.6 + a1 * 1.4;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      f.life -= 0.04;
      if (f.life <= 0) flashes.splice(i, 1);
    }

    /* matched edges — flowing gradient energy */
    for (const [a, b] of world.matched) {
      if (a >= b) continue;
      const [x1, y1] = toCanvasPos(a);
      const [x2, y2] = toCanvasPos(b);
      const grad = ctx.createLinearGradient(x1, y1, x2, y2);
      grad.addColorStop(0, cobalt);
      grad.addColorStop(1, violet);
      ctx.strokeStyle = grad;
      ctx.lineWidth = 2.4;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      if (!reduceMotion) {
        ctx.setLineDash([7, 9]);
        ctx.lineDashOffset = -t * 0.05;
        ctx.strokeStyle = rgba("#ffffff", 0.35);
        ctx.lineWidth = 1.1;
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    /* matched-edge pulse on new matches */
    for (let i = newMatches.length - 1; i >= 0; i--) {
      const m = newMatches[i];
      const [x1, y1] = toCanvasPos(m.a);
      const [x2, y2] = toCanvasPos(m.b);
      const r = 6 + (1 - m.life) * 14;
      ctx.strokeStyle = rgba(violet, m.life * 0.5);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc((x1 + x2) / 2, (y1 + y2) / 2, r, 0, Math.PI * 2);
      ctx.stroke();
      m.life -= 0.03;
      if (m.life <= 0) newMatches.splice(i, 1);
    }

    /* nodes */
    for (let v = 0; v < n; v++) {
      const [x, y] = toCanvasPos(v);
      const isMatched = world.matched.has(v);
      const isSel = selected === v;
      const pulse = 1 + Math.sin(t * 0.002 + v * 0.9) * 0.06;

      if (isMatched) {
        const grad = ctx.createRadialGradient(x, y, 0, x, y, 9 * pulse);
        grad.addColorStop(0, rgba(cobalt, 0.95));
        grad.addColorStop(1, rgba(cobalt, 0));
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(x, y, 9 * pulse, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = rgba(ink, 0.98);
        ctx.beginPath();
        ctx.arc(x, y, 4.1 * pulse, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.strokeStyle = rgba(ink, 0.55);
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(x, y, 4.4 * pulse, 0, Math.PI * 2);
        ctx.stroke();
      }

      if (isSel) {
        ctx.strokeStyle = rgba("#ffffff", 0.85);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, 11, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    /* hover cursor */
    const c = canvas.style.cursor;
    if (hover.v > 0.01) {
      const hitNode = nodeAt(hover.x, hover.y);
      const hitEdge = hitNode === null ? edgeAt(hover.x, hover.y) : null;
      canvas.style.cursor = hitNode !== null || hitEdge !== null ? "pointer" : c;
      hover.v *= 0.9;
    }

    if (running && t - tickAt > MODES[mode].tick) {
      tickAt = t;
      step();
      updateStats();
    }
    updateStats();
    requestAnimationFrame(draw);
  }

  for (let i = 0; i < world.n * 2.2; i++) {
    if (rand() < 0.09) {
      const [a, b] = randomAdjacentPair((x, y) => world.edges.has(edgeKey(x, y)));
      if (a === -1) break;
      world.edges.add(edgeKey(a, b));
      world.adj[a].add(b);
      world.adj[b].add(a);
    }
  }
  restoreMaximality();
  updateStats();
  requestAnimationFrame(draw);
}