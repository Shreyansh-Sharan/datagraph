// Graph rendering on a <canvas> with a small force layout. No external dependency, works offline.
// Nodes: {id, label, color, size}. Edges: {source, target, label}.
export function renderGraph(container, { nodes, edges, onSelect, selected }) {
  container.replaceChildren();
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `Graph with ${nodes.length} nodes and ${edges.length} edges`);
  container.append(canvas);
  const dpr = window.devicePixelRatio || 1;
  const W = container.clientWidth || 800, H = container.clientHeight || 520;
  canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const byId = new Map(nodes.map((n, i) => [n.id, { ...n, x: W / 2 + Math.cos(i) * 120 + (Math.random() - .5) * 40, y: H / 2 + Math.sin(i) * 120 + (Math.random() - .5) * 40, vx: 0, vy: 0 }]));
  const N = [...byId.values()];
  const E = edges.filter(e => byId.has(e.source) && byId.has(e.target)).map(e => ({ ...e, s: byId.get(e.source), t: byId.get(e.target) }));
  let zoom = 1, ox = 0, oy = 0, drag = null, hover = null, sel = selected || null;
  const styles = getComputedStyle(document.documentElement);
  const colText = styles.getPropertyValue("--text").trim(), colMuted = styles.getPropertyValue("--muted").trim(), colBorder = styles.getPropertyValue("--border-strong").trim();

  function step(iter) {
    const k = 60;
    for (const a of N) { a.fx = 0; a.fy = 0; }
    for (let i = 0; i < N.length; i++) for (let j = i + 1; j < N.length; j++) {
      const a = N[i], b = N[j]; let dx = a.x - b.x, dy = a.y - b.y; let d2 = dx * dx + dy * dy || 1; const f = (k * k) / d2 * 4;
      dx *= f; dy *= f; a.fx += dx; a.fy += dy; b.fx -= dx; b.fy -= dy;
    }
    for (const e of E) { const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - k * 1.6) / d * 0.08; e.s.fx += dx * f; e.s.fy += dy * f; e.t.fx -= dx * f; e.t.fy -= dy * f; }
    for (const a of N) { a.fx += (W / 2 - a.x) * 0.005; a.fy += (H / 2 - a.y) * 0.005; }
    const damp = Math.max(0.1, 1 - iter / 300);
    for (const a of N) { if (a === drag) continue; a.vx = (a.vx + a.fx) * 0.5 * damp; a.vy = (a.vy + a.fy) * 0.5 * damp; a.x += a.vx; a.y += a.vy; }
  }
  function draw() {
    ctx.clearRect(0, 0, W, H); ctx.save(); ctx.translate(ox, oy); ctx.scale(zoom, zoom);
    ctx.lineWidth = 1 / zoom; ctx.strokeStyle = colBorder;
    for (const e of E) {
      ctx.beginPath(); ctx.moveTo(e.s.x, e.s.y); ctx.lineTo(e.t.x, e.t.y); ctx.stroke();
      const ang = Math.atan2(e.t.y - e.s.y, e.t.x - e.s.x), r = (e.t.size || 6) + 2, tx = e.t.x - Math.cos(ang) * r, ty = e.t.y - Math.sin(ang) * r;
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx - Math.cos(ang - .4) * 6, ty - Math.sin(ang - .4) * 6); ctx.lineTo(tx - Math.cos(ang + .4) * 6, ty - Math.sin(ang + .4) * 6); ctx.closePath(); ctx.fillStyle = colBorder; ctx.fill();
      if (e.label && zoom > 0.8) { ctx.fillStyle = colMuted; ctx.font = `${10 / zoom}px system-ui`; ctx.fillText(e.label, (e.s.x + e.t.x) / 2 + 4, (e.s.y + e.t.y) / 2 - 4); }
    }
    for (const n of N) {
      ctx.beginPath(); ctx.arc(n.x, n.y, n.size || 6, 0, Math.PI * 2); ctx.fillStyle = n.color || "#0b6e4f"; ctx.fill();
      if (n.id === sel || n === hover) { ctx.lineWidth = 3 / zoom; ctx.strokeStyle = colText; ctx.stroke(); }
      ctx.fillStyle = colText; ctx.font = `${12 / zoom}px system-ui`; ctx.fillText(n.label || n.id, n.x + (n.size || 6) + 3, n.y + 4);
    }
    ctx.restore();
  }
  let iter = 0, raf;
  const loop = () => { if (iter < 250) { step(iter++); draw(); raf = requestAnimationFrame(loop); } else draw(); };
  loop();
  const at = (ev) => { const r = canvas.getBoundingClientRect(); const x = (ev.clientX - r.left - ox) / zoom, y = (ev.clientY - r.top - oy) / zoom; return N.find(n => (n.x - x) ** 2 + (n.y - y) ** 2 <= ((n.size || 6) + 4) ** 2); };
  canvas.addEventListener("mousedown", ev => { drag = at(ev); if (!drag) drag = { pan: true, x: ev.clientX, y: ev.clientY }; });
  window.addEventListener("mousemove", ev => {
    if (drag?.pan) { ox += ev.clientX - drag.x; oy += ev.clientY - drag.y; drag.x = ev.clientX; drag.y = ev.clientY; draw(); return; }
    if (drag) { const r = canvas.getBoundingClientRect(); drag.x = (ev.clientX - r.left - ox) / zoom; drag.y = (ev.clientY - r.top - oy) / zoom; if (iter >= 250) draw(); return; }
    const hv = at(ev); if (hv !== hover) { hover = hv; canvas.style.cursor = hv ? "pointer" : "grab"; if (iter >= 250) draw(); }
  });
  window.addEventListener("mouseup", ev => { if (drag && !drag.pan) { const n = at(ev); if (n && n === drag) { sel = n.id; onSelect?.(n); draw(); } } drag = null; });
  canvas.addEventListener("wheel", ev => { ev.preventDefault(); const f = ev.deltaY < 0 ? 1.1 : 0.9; const r = canvas.getBoundingClientRect(); const mx = ev.clientX - r.left, my = ev.clientY - r.top; ox = mx - (mx - ox) * f; oy = my - (my - oy) * f; zoom *= f; draw(); }, { passive: false });
  canvas.tabIndex = 0;
  canvas.addEventListener("keydown", ev => { const idx = N.findIndex(n => n.id === sel); if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { const n = N[(idx + 1) % N.length]; sel = n.id; onSelect?.(n); draw(); } if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { const n = N[(idx - 1 + N.length) % N.length]; sel = n.id; onSelect?.(n); draw(); } });
  return { destroy: () => cancelAnimationFrame(raf), select: (id) => { sel = id; draw(); } };
}

export function palette(keys) {
  const colors = ["#0b6e4f", "#175cd3", "#b54708", "#7a1fa2", "#b42318", "#0e7490", "#4d7c0f", "#a21caf", "#9a3412", "#1d4ed8"];
  const m = new Map();
  [...new Set(keys)].forEach((k, i) => m.set(k, colors[i % colors.length]));
  return m;
}
