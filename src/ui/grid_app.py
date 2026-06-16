"""Self-contained HTML for the interactive 13x13 grid MCP App.

Rendered inline by the claude.ai connector via the MCP Apps extension. The page uses the
official ``@modelcontextprotocol/ext-apps`` View SDK (loaded from esm.sh) to receive the
``solve_spot`` tool's ``structuredContent`` and render a clickable, hoverable hand grid.
"""

from __future__ import annotations

GRID_APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0; padding: 12px;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: var(--background, #ffffff); color: var(--foreground, #111827);
  }
  #header { font-size: 13px; margin-bottom: 8px; line-height: 1.4; }
  #controls { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .seg { display: inline-flex; border: 1px solid #9ca3af55; border-radius: 8px; overflow: hidden; }
  .seg button {
    border: 0; padding: 4px 10px; font-size: 12px; cursor: pointer;
    background: transparent; color: inherit;
  }
  .seg button.active { background: #6366f1; color: #fff; }
  #grid { display: grid; grid-template-columns: repeat(13, 1fr); gap: 2px; max-width: 680px; }
  .cell {
    position: relative; aspect-ratio: 1 / 1; border-radius: 3px;
    display: flex; align-items: center; justify-content: center;
    font-size: 9px; font-weight: 600; text-align: center; line-height: 1.05;
    color: #111; background: #f3f4f6; user-select: none;
  }
  .cell.empty { opacity: 0.18; }
  #tip {
    position: fixed; pointer-events: none; z-index: 10; display: none;
    background: #111827; color: #f9fafb; padding: 6px 8px; border-radius: 6px;
    font-size: 11px; line-height: 1.35; box-shadow: 0 4px 14px #0006; max-width: 220px;
  }
  #status { font-size: 13px; opacity: 0.7; }
</style>
</head>
<body>
  <div id="status">Loading solve…</div>
  <div id="header"></div>
  <div id="controls"></div>
  <div id="grid"></div>
  <div id="tip"></div>
<script type="module">
  import { App, applyDocumentTheme } from "https://esm.sh/@modelcontextprotocol/ext-apps";

  const RANKS = "AKQJT98765432".split("");
  const METRICS = ["bet", "check", "fold", "blended"];
  const state = { data: null, player: "oop", metric: "bet" };

  const $ = (id) => document.getElementById(id);

  function gridClass(r, c) {
    const hi = RANKS[r], lo = RANKS[c];
    if (r === c) return hi + lo;
    if (c > r) return hi + lo + "s";
    return RANKS[c] + RANKS[r] + "o";
  }

  function cellColor(cell) {
    if (!cell) return null;
    const m = state.metric;
    if (m === "blended") {
      const r = Math.round(255 * cell.bet), g = Math.round(255 * cell.check), b = Math.round(255 * cell.fold);
      return `rgb(${r}, ${g}, ${b})`;
    }
    const base = { bet: [220, 38, 38], check: [22, 163, 74], fold: [37, 99, 235] }[m];
    const v = cell[m] ?? 0;
    const mix = (x) => Math.round(243 + (x - 243) * v);
    return `rgb(${mix(base[0])}, ${mix(base[1])}, ${mix(base[2])})`;
  }

  function showTip(evt, cls, cell) {
    const tip = $("tip");
    if (!cell) { tip.style.display = "none"; return; }
    const lines = Object.entries(cell.actions)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}: ${(v * 100).toFixed(1)}%`)
      .join("<br/>");
    tip.innerHTML = `<b>${cls}</b><br/>${lines}`;
    tip.style.display = "block";
    tip.style.left = Math.min(evt.clientX + 12, window.innerWidth - 230) + "px";
    tip.style.top = (evt.clientY + 12) + "px";
  }

  function renderControls() {
    const c = $("controls");
    const seg = (items, current, onpick) => {
      const wrap = document.createElement("div");
      wrap.className = "seg";
      for (const [val, label] of items) {
        const b = document.createElement("button");
        b.textContent = label;
        if (val === current) b.className = "active";
        b.onclick = () => { onpick(val); render(); };
        wrap.appendChild(b);
      }
      return wrap;
    };
    c.replaceChildren(
      seg([["oop", "OOP"], ["ip", "IP"]], state.player, (v) => state.player = v),
      seg(METRICS.map((m) => [m, m]), state.metric, (v) => state.metric = v),
    );
  }

  function render() {
    const d = state.data;
    if (!d) return;
    $("status").style.display = "none";
    const expl = d.exploitability_pct == null ? "n/a" : d.exploitability_pct.toFixed(2) + "% of pot";
    const who = state.player === "oop" ? "OOP (first to act)" : "IP (facing check)";
    $("header").innerHTML =
      `<b>${d.board}</b> &nbsp; pot ${d.pot} &nbsp; exploitability ${expl}<br/>` +
      `Showing <b>${who}</b> — <b>${state.metric}</b> frequency`;
    renderControls();

    const cells = d.players[state.player] || {};
    const grid = $("grid");
    grid.replaceChildren();
    for (let r = 0; r < 13; r++) {
      for (let col = 0; col < 13; col++) {
        const cls = gridClass(r, col);
        const cell = cells[cls];
        const el = document.createElement("div");
        el.className = "cell" + (cell ? "" : " empty");
        const color = cellColor(cell);
        if (color) el.style.background = color;
        const pct = cell ? Math.round((state.metric === "blended" ? cell.bet : cell[state.metric]) * 100) : "";
        el.innerHTML = cell ? `${cls}<br/>${pct}%` : cls;
        el.onmousemove = (e) => showTip(e, cls, cell);
        el.onmouseleave = () => { $("tip").style.display = "none"; };
        grid.appendChild(el);
      }
    }
  }

  const app = new App({ name: "poker-grid", version: "1.0.0" });
  app.onhostcontextchanged = (ctx) => { if (ctx && ctx.theme) applyDocumentTheme(ctx.theme); };
  app.ontoolresult = (result) => {
    const data = result && result.structuredContent;
    if (!data || !data.players) return;
    state.data = data;
    state.player = data.grid_for || "oop";
    state.metric = data.grid_metric || "bet";
    render();
  };
  app.connect().then(() => {
    const ctx = app.getHostContext();
    if (ctx && ctx.theme) applyDocumentTheme(ctx.theme);
  }).catch((e) => { $("status").textContent = "Bridge error: " + e.message; });
</script>
</body>
</html>
"""
