(function () {
 // Guillaume M. -- The Detection view is rebuilt for each forcing: initDetection(D) with that forcing's data.
 const H0 = {};
 function fresh(sel) {   // drop the listeners of a previous init by cloning the static controls
   document.querySelectorAll(sel).forEach(el => { const c = el.cloneNode(true); el.replaceWith(c); });
 }
 function initDetection(D) {
  ["#extent button", "#colour button", "#track button", "#mode button", "#level", "#storm"].forEach(fresh);
  document.getElementById("storm").innerHTML = ""; document.getElementById("vset").innerHTML = "";
  document.getElementById("maps").innerHTML = "";
  const NC = D.cells.lon.length, NS = D.storms.length, HC = (D.res || 1) / 2;
  const FKEY = D.forcing ? "-" + D.forcing : "";
  const b64 = s => { const bin = atob(s); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; };
  for (const f in D.grid) { D.grid[f].bitsA = b64(D.grid[f].bits); D.grid[f].faA = b64(D.grid[f].fa); }

  // Guillaume M. -- Every rule is set at the SAME onset rate L (onsets per cell and decade): one slider for all,
  // each rule's grid holds the parameter set that gives each level (build_storm_iso_onsets.py).
  const C = window.SDE_CONFIG;
  const RULES = C.rules.map(r => ({ id: r.id, name: r.name, fmt: r.fmt, opt: r.id })).filter(r => D.grid[r.id]);
  RULES.forEach(r => { r.keys = ["L"]; });
  const LEVELS = (D.iso && D.iso.levels) || D.grid[RULES[0].id].params.L;
  const VSETS = C.vsets;
  const esc = t => String(t).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
  const REF = 0.9, HI = 2.0;
  const faClass = f => f < REF ? "under" : f <= HI ? "ok" : "over";
  const faPill = f => `<span class="pill ${faClass(f)}" title="reference \u2248 0.9; plausible 0.9\u20132">${f.toFixed(2)}</span>`;
  const BUCKETS = ["1st", "2nd–3rd", "4th–10th", "11th–30th", "> 30th"];
  const near = (arr, v) => { let b = 0; arr.forEach((x, i) => { if (Math.abs(x - v) < Math.abs(arr[b] - v)) b = i; }); return b; };
  const lvIdx = rule => ({ L: near(D.grid[rule.id].params.L, S.L) });
  const setting = rule => { const g = D.grid[rule.id], i = lvIdx(rule).L, p = g.settings[i];
    return window.SDE_FMT(rule.fmt, p); };
  const reached = rule => Math.abs(D.grid[rule.id].params.L[lvIdx(rule).L] - S.L) < 0.051;

  const S = { storm: C.default_storm, vset: VSETS[0].id, extent: "storm", colour: "rank", track: "on", mode: "online", L: 1.0, idx: {} };
  try { const s = JSON.parse(localStorage.getItem("sde-state4" + FKEY) || "{}"); if (s && s.L) Object.assign(S, s); } catch (e) {}
  const syncIdx = () => RULES.forEach(r => { S.idx[r.id] = lvIdx(r); });
  syncIdx();
  if (!D.storms.some(s => s.id === S.storm)) S.storm = D.storms[D.storms.length - 1].id;
  if (!D.online) S.mode = "replay";
  document.querySelectorAll("#mode button").forEach(b => { b.disabled = !D.online && b.dataset.v === "online"; });
  const save = () => { try { localStorage.setItem("sde-state4" + FKEY, JSON.stringify(S)); } catch (e) {} };
  const ON = () => S.mode === "online" && !!D.online;
  const hasRun = rule => !!(D.online && D.online.runs[rule.id]);
  const ONr = rule => ON() && hasRun(rule);
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const storm = () => D.storms.find(s => s.id === S.storm) || D.storms[0];
  const sIndex = st => D.storms.indexOf(st);

  function combo(rule) {
    const g = D.grid[rule.id], ix = S.idx[rule.id]; let c = 0;
    rule.keys.forEach(k => { c = c * g.params[k].length + ix[k]; });
    return c;
  }
  // ORCHIDEE mode: storm states the bench runs actually produced (replay episodes confirmed by a model storm end)
  const det = (rule, c, si, k) => {
    if (ONr(rule)) return +D.storms[si].online[rule.id][k];
    const i = (c * NS + si) * NC + k; return (D.grid[rule.id].bitsA[i >> 3] >> (i & 7)) & 1; };
  const fa = (rule, c, k) => ONr(rule) ? D.online.fa[rule.id][k] : D.grid[rule.id].faA[c * NC + k] * 0.05;
  const rank = (rule, st, k) => (+st.codes[rule.opt][k]) >> 1;

  function metrics(rule, st, vs) {
    const v = st.val[vs]; if (!v) return null;
    const c = combo(rule), si = sIndex(st), obs = new Set(v.obs), assessed = v.assessed ? new Set(v.assessed) : null;
    let hit = 0, out = 0, f = 0, na = 0;
    for (let k = 0; k < NC; k++) {
      if (assessed && !assessed.has(k)) continue;
      const d = det(rule, c, si, k); f += fa(rule, c, k); na++;
      if (obs.has(k)) hit += d; else out += d;
    }
    return { n: obs.size, hit, out, fa: f / Math.max(na, 1) };
  }

  // ---- global controls
  const sel = document.getElementById("storm");
  D.storms.forEach(s => { const o = document.createElement("option"); o.value = s.id;
    o.textContent = `${s.label} — ${s.date}  [${Object.keys(s.val).filter(k => s.val[k].obs.length).join(", ")}]`; sel.appendChild(o); });
  sel.addEventListener("change", () => { S.storm = sel.value; fixVset(); render(); });
  const vbox = document.getElementById("vset");
  VSETS.forEach(v => { const b = document.createElement("button"); b.type = "button"; b.dataset.v = v.id; b.textContent = v.name;
    b.addEventListener("click", () => { S.vset = v.id; render(); }); vbox.appendChild(b); });
  for (const key of ["extent", "colour", "track", "mode"])
    document.querySelectorAll(`#${key} button`).forEach(b => b.addEventListener("click", () => { S[key] = b.dataset.v; render(); }));
  const lv = document.getElementById("level"), lvout = document.getElementById("levelout");
  lv.min = 0; lv.max = LEVELS.length - 1; lv.step = 1; lv.value = near(LEVELS, S.L);
  lv.addEventListener("input", () => { S.L = LEVELS[+lv.value]; syncIdx(); syncSliders(); render(); });
  function fixVset() {
    const st = storm();
    if (!st.val[S.vset] || !st.val[S.vset].obs.length) {
      const first = VSETS.find(v => st.val[v.id] && st.val[v.id].obs.length);
      if (first) S.vset = first.id;
    }
  }

  // ---- rule panels
  const tip = document.getElementById("tip");
  const maps = document.getElementById("maps");
  const panels = RULES.map(rule => {
    const d = document.createElement("div"); d.className = "map";
    d.innerHTML = `<div class="mhead"><h4>${rule.name}</h4></div>
      <div class="bench note" hidden></div><div class="params note"></div><div class="stats"></div><canvas role="img"></canvas>`;
    const cv = d.querySelector("canvas");
    cv.addEventListener("mousemove", hover); cv.addEventListener("mouseleave", () => tip.hidden = true);
    maps.appendChild(d);
    return { rule, d, cv, stats: d.querySelector(".stats"), pbox: d.querySelector(".params"), bench: d.querySelector(".bench") };
  });
  function syncSliders() {
    lvout.textContent = S.L.toFixed(1);
    panels.forEach(p => { p.pbox.innerHTML = reached(p.rule) ? `Setting at this rate: <code>${setting(p.rule)}</code>`
      : `<span class="warnbox">Rate ${S.L.toFixed(1)} out of reach on this forcing; nearest ${D.grid[p.rule.id].params.L[lvIdx(p.rule).L].toFixed(1)}: <code>${setting(p.rule)}</code></span>`; });
  }

  // ---- map
  function extentFor(st) {
    const [x0, x1, y0, y1] = D.box;
    if (S.extent === "europe") return [x0 - 0.5, x1 + 0.5, y0 - 0.5, y1 + 0.5];
    const v = st.val[S.vset]; const ks = v && v.obs.length ? v.obs : (v && v.assessed) || [];
    if (!ks.length) return [x0 - 0.5, x1 + 0.5, y0 - 0.5, y1 + 0.5];
    let a = 1e9, b = -1e9, c = 1e9, d = -1e9;
    ks.forEach(k => { a = Math.min(a, D.cells.lon[k]); b = Math.max(b, D.cells.lon[k]); c = Math.min(c, D.cells.lat[k]); d = Math.max(d, D.cells.lat[k]); });
    const cx = (a + b) / 2, cy = (c + d) / 2, w = Math.max(b - a + 9, 18), h = Math.max(d - c + 7, 12);
    return [cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2];
  }
  function draw(p, st, vs) {
    const canvas = p.cv, rule = p.rule, c = combo(rule), si = sIndex(st);
    const [x0, x1, y0, y1] = extentFor(st);
    const kx = Math.cos(((y0 + y1) / 2) * Math.PI / 180);
    const W = canvas.clientWidth || 500, H = Math.round(W * (y1 - y0) / ((x1 - x0) * kx));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.height = H + "px";
    const g = canvas.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const X = x => (x - x0) / (x1 - x0) * W, Y = y => (y1 - y) / (y1 - y0) * H;
    g.fillStyle = css("--sea"); g.fillRect(0, 0, W, H);
    g.fillStyle = css("--land");
    D.land.forEach(r => { g.beginPath(); r.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.closePath(); g.fill(); });
    const v = st.val[vs] || { obs: [] }, obs = new Set(v.obs), assessed = v.assessed ? new Set(v.assessed) : null;
    const rk = [css("--r1"), css("--r2"), css("--r3"), css("--r4"), css("--cell-none")];
    const geo = [];
    for (let k = 0; k < NC; k++) {
      const lo = D.cells.lon[k], la = D.cells.lat[k];
      if (lo < x0 - 1 || lo > x1 + 1 || la < y0 - 1 || la > y1 + 1) continue;
      let col;
      if (S.colour === "rank") col = rk[rank(rule, st, k)];
      else { const f = fa(rule, c, k); col = f <= 0 ? rk[4] : f < REF ? css("--under") : f <= HI ? css("--ok") : f <= 5 ? css("--over") : css("--over2"); }
      const px = X(lo - HC), py = Y(la + HC), pw = X(lo + HC) - px, ph = Y(la - HC) - py;
      g.globalAlpha = assessed && !assessed.has(k) ? 0.3 : 1;
      g.fillStyle = col; g.fillRect(px + 0.5, py + 0.5, pw - 1, ph - 1); g.globalAlpha = 1;
      geo.push([k, px, py, pw, ph, det(rule, c, si, k)]);
    }
    g.strokeStyle = css("--border"); g.lineWidth = 0.8;
    D.borders.forEach(r => { g.beginPath(); r.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke(); });
    g.strokeStyle = css("--obs"); g.lineWidth = 2;
    geo.forEach(([k, px, py, pw, ph]) => { if (obs.has(k)) g.strokeRect(px + 1, py + 1, pw - 2, ph - 2); });
    g.fillStyle = css("--dot");
    geo.forEach(([k, px, py, pw, ph, dd]) => { if (dd) { g.beginPath(); g.arc(px + pw / 2, py + ph / 2, Math.max(2, Math.min(pw, ph) * 0.16), 0, 7); g.fill(); } });
    if (S.track !== "off") drawTracks(g, st, X, Y);
    canvas._geo = geo; canvas._ctx = { st, rule, c, vs };
    canvas.setAttribute("aria-label", `${rule.name} map for ${st.label}`);
  }
  function drawTracks(g, st, X, Y) {
    const T = (window.STORMTRACKS || {})[st.id]; if (!T) return;
    const noon = st.date + " 12";
    const one = (pts, dashed) => {
      if (!pts || pts.length < 2) return;
      g.save(); g.lineJoin = "round"; g.lineCap = "round";
      for (const [col, wd] of [[css("--track-halo"), dashed ? 4 : 5], [css("--track"), dashed ? 1.6 : 2.4]]) {
        g.strokeStyle = col; g.lineWidth = wd; g.setLineDash(dashed ? [6, 4] : []);
        g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke();
      }
      g.setLineDash([]);
      pts.forEach(([x, y, t]) => {
        const big = t.slice(0, 13) === noon;
        g.beginPath(); g.arc(X(x), Y(y), big ? 4.5 : 2, 0, 7); g.fillStyle = css("--track"); g.fill();
        if (big) { g.lineWidth = 1.5; g.strokeStyle = css("--track-halo"); g.stroke(); }
      });
      if (!dashed || !T.xws) {
        g.font = "11px " + css("--f-data"); g.textBaseline = "bottom";
        pts.forEach(([x, y, t]) => { if (t.endsWith(" 00")) {
          const lab = t.slice(8, 10) + "/" + t.slice(5, 7);
          g.lineWidth = 3; g.strokeStyle = css("--track-halo"); g.strokeText(lab, X(x) + 5, Y(y) - 3);
          g.fillStyle = css("--track"); g.fillText(lab, X(x) + 5, Y(y) - 3); } });
      }
      const [xa, ya] = pts[pts.length - 2], [xb, yb] = pts[pts.length - 1];
      const ang = Math.atan2(Y(yb) - Y(ya), X(xb) - X(xa));
      g.beginPath(); g.moveTo(X(xb), Y(yb)); g.lineTo(X(xb) - 9 * Math.cos(ang - 0.45), Y(yb) - 9 * Math.sin(ang - 0.45));
      g.lineTo(X(xb) - 9 * Math.cos(ang + 0.45), Y(yb) - 9 * Math.sin(ang + 0.45)); g.closePath(); g.fillStyle = css("--track"); g.fill();
      g.restore();
    };
    if (T.xws && T.xws.length > 1) one(T.xws, false); else one(T.era5, true);
    if (T.xws2 && T.xws2.length > 1) one(T.xws2, false);
  }
  function hover(e) {
    const cv = e.currentTarget, r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const hit = (cv._geo || []).find(([k, px, py, pw, ph]) => x >= px && x < px + pw && y >= py && y < py + ph);
    if (!hit) { tip.hidden = true; return; }
    const [k, , , , , dd] = hit; const { st, rule, c, vs } = cv._ctx; const v = st.val[vs] || {};
    const lines = [`${D.cells.lon[k].toFixed(1)}°E ${D.cells.lat[k].toFixed(1)}°N · forest ${D.cells.forest_kha[k]} kha`,
      `${dd ? "DETECTED" : "not detected"} · rank ${BUCKETS[rank(rule, st, k)]}`,
      `${(v.obs || []).includes(k) ? "reported: struck" : "reported: no"}`,
      `background ${fa(rule, c, k).toFixed(2)} onsets/decade`];
    if (v.n) lines.push(`FORWIND ${v.n[k]} polygons, ${v.pct[k]} % of forest`);
    if (v.assessed && !v.assessed.includes(k)) lines.push("not assessed for this set");
    tip.innerHTML = lines.join("<br>"); tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (e.clientY + 14) + "px";
  }

  // ---- render
  let raf = 0;
  function render() { cancelAnimationFrame(raf); raf = requestAnimationFrame(renderNow); }
  function renderNow() {
    save();
    const st = storm(); sel.value = st.id;
    document.querySelectorAll("#vset button").forEach(b => {
      const ok = st.val[b.dataset.v] && st.val[b.dataset.v].obs.length;
      b.disabled = !ok; b.setAttribute("aria-pressed", String(b.dataset.v === S.vset)); });
    for (const key of ["extent", "colour", "track", "mode"])
      document.querySelectorAll(`#${key} button`).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === S[key])));
    document.getElementById("level").closest(".ctl").hidden = ON();
    const vs = S.vset, V = VSETS.find(v => v.id === vs), val = st.val[vs];
    document.getElementById("vnote").innerHTML = (vs === "efda" ? '<span class="warnbox">EFDA is annual and merges wind with bark beetle: storms of the same EFDA year share one footprint; storms from July on are looked up in the following year.</span> ' : "")
      + (val ? `${V.name}: ${val.obs.length} reported cells. ${val.note || ""}` : "No data for this storm.")
      + (val && val.reports && val.reports.length ? `<details class="reps"><summary>${val.reports.length} reports and sources</summary><ul>`
         + val.reports.map(r => `<li><b>${esc(r[0])}</b> ${esc(r[1])} · ${esc(r[2])} · ${esc(r[3])}: `
           + (/^https?:\/\//.test(r[5]) ? `<a href="${esc(r[5])}" target="_blank" rel="noopener">${esc(r[4])}</a>` : esc(r[4])) + `</li>`).join("")
         + `</ul></details>` : "");
    const M = panels.map(p => metrics(p.rule, st, vs));
    const best = Math.max(...M.map(m => m ? m.hit : -1)), nbest = M.filter(m => m && m.hit === best).length;
    panels.forEach((p, i) => {
      const m = M[i];
      p.pbox.hidden = ONr(p.rule); p.bench.hidden = !ON();
      if (ON()) p.bench.innerHTML = hasRun(p.rule) ? `ORCHIDEE run <code>${D.online.runs[p.rule.id]}</code>: ${esc(D.online.settings[p.rule.id])}`
        : "No ORCHIDEE run of this rule on this forcing: offline replay at the chosen rate.";
      p.d.classList.toggle("best", !!m && best > 0 && m.hit === best && nbest === 1);
      p.stats.innerHTML = m ? `<span class="rate">${m.n ? Math.round(100 * m.hit / m.n) : 0} %</span>
        <span>detected <b>${m.hit} / ${m.n}</b></span><span>${V.out} <b>${m.out}</b></span>
        <span>${ONr(p.rule) ? "storm ends" : "background"} ${faPill(m.fa)} ${ONr(p.rule) ? "per decade (ORCHIDEE)" : "onsets / decade"} <span class="note">(ref \u2248 0.9)</span></span>` : "";
      draw(p, st, vs);
    });
    const sw = S.colour === "rank"
      ? BUCKETS.map((b, i) => [b, ["--r1", "--r2", "--r3", "--r4", "--cell-none"][i]])
      : [["> 5 over", "--over2"], ["2\u20135 over", "--over"], ["0.9\u20132 plausible", "--ok"], ["< 0.9 under", "--under"], ["0", "--cell-none"]];
    document.getElementById("legend").innerHTML = `<span>${S.colour === "rank" ? `Storm rank in the cell, ${C.first_year}-${D.period[1]}:` : `Onsets per cell and decade, ${C.first_year}-${D.period[1]} (reference \u2248 0.9):`}</span>`
      + sw.map(([b, v]) => `<span><i class="sw" style="background:var(${v})"></i>${b}</span>`).join("")
      + `<span><i class="sw" style="background:transparent;box-shadow:inset 0 0 0 2px var(--obs)"></i>reported struck</span>
         <span><i class="sw" style="background:radial-gradient(circle, var(--dot) 30%, transparent 34%)"></i>${ON() ? "detected by ORCHIDEE (bench run)" : "detected (offline replay)"}</span>`
      + (S.track !== "off" ? ((window.STORMTRACKS || {})[st.id] && (window.STORMTRACKS[st.id].xws || []).length > 1
          ? `<span><i class="sw" style="height:3px;vertical-align:3px;background:var(--track)"></i>track: XWS (published)</span>`
          : `<span><i class="sw" style="height:0;vertical-align:4px;border-top:2px dashed var(--track)"></i>track: ERA5 pressure minimum (in-house)</span>`) : "");
    // all-storm table with the current sliders
    const rows = D.storms.filter(s => s.val[vs] && s.val[vs].obs.length);
    const pool = RULES.map(() => [0, 0]), faPool = RULES.map(() => 0);
    const body = rows.map(s => {
      const ms = RULES.map(r => metrics(r, s, vs));
      const b = Math.max(...ms.map(m => m.hit)), nb = ms.filter(m => m.hit === b).length;
      ms.forEach((m, i) => { pool[i][0] += m.hit; pool[i][1] += m.n; });
      return `<tr class="click${s.id === st.id ? " sel" : ""}" data-id="${s.id}"><td>${s.label}</td><td class="num">${s.date}</td>`
        + ms.map(m => `<td class="num${b > 0 && m.hit === b && nb === 1 ? " win" : ""}">${m.hit}/${m.n}</td>`).join("") + "</tr>";
    }).join("");
    RULES.forEach((r, i) => { const c = combo(r); let f = 0; for (let k = 0; k < NC; k++) f += fa(r, c, k); faPool[i] = f / NC; });
    document.getElementById("tab").innerHTML = `<thead><tr><th>Storm</th><th>Date</th>${RULES.map(r => `<th>${r.name}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody><tfoot><tr><td>Pooled detection</td><td></td>${pool.map(p => `<td class="num">${p[1] ? Math.round(100 * p[0] / p[1]) : 0} %</td>`).join("")}</tr>
      <tr><td>${ON() ? "Storm ends / cell / decade (ORCHIDEE)" : "Background onsets / cell / decade"}</td><td>${NC} cells, ref \u2248 0.9</td>${faPool.map(f => `<td class="num">${faPill(f)}</td>`).join("")}</tr></tfoot>`;
    document.querySelectorAll("#tab tr.click").forEach(tr => tr.addEventListener("click", () => { S.storm = tr.dataset.id; fixVset(); render(); }));
  }
  fixVset(); syncSliders(); renderNow();
  H0.render = render;
 }
 let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => H0.render && H0.render(), 150); });
 if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => H0.render && H0.render());

 // ---- forcing menu: the main forcing is in clear, the others are gzip + base64 strings in window.SDE_FORCINGS
 const C0 = window.SDE_CONFIG, MAIN = C0.main, B = window.SDE_BASEMAP;
 Object.assign(window.STORMDATA, { land: B.land, borders: B.borders });
 const cache = { [MAIN]: window.STORMDATA };
 window.SDE = { load: f => load(f) };
 const fsel = document.getElementById("forcing"), fnote = document.getElementById("forcingnote");
 const mainNote = () => (C0.forcings.find(x => x.id === MAIN) || {}).note || "";
 async function load(f) {
   if (cache[f]) return cache[f];
   const b64 = (window.SDE_FORCINGS || {})[f];
   if (!b64) throw new Error("not in this page");
   const bin = atob(b64), buf = new Uint8Array(bin.length);
   for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
   const txt = await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
   const d = JSON.parse(txt);
   d.land = B.land; d.borders = B.borders; d.box = d.box || window.STORMDATA.box;
   return (cache[f] = d);
 }
 async function choose(f) {
   fsel.disabled = true; fnote.textContent = "Loading " + fsel.options[fsel.selectedIndex].text + " …";
   try {
     const d = await load(f); initDetection(d);
     const P = d.protocol;
     fnote.innerHTML = f === MAIN ? mainNote()
       : `${d.label}: ${d.note}, ${d.period[0]}-${d.period[1]}; ${d.cells.lon.length} forest cells. Offline replay only (no ORCHIDEE run on this forcing). `
         + (P ? `Out-of-region Peirce skill score of each rule's best setting on this grid: ` + C0.rules.map(r => r.id).filter(k => P[k])
           .map(k => `${k} ${P[k].loro.toFixed(2)}`).join(" · ") + "." : "");
     try { localStorage.setItem("sde-forcing", f); } catch (e) {}
   } catch (e) { fnote.textContent = "Could not load this forcing: " + e.message; fsel.value = MAIN; initDetection(cache[MAIN]); }
   fsel.disabled = false;
 }
 let f0 = MAIN; try { f0 = localStorage.getItem("sde-forcing") || f0; } catch (e) {}
 if (![...fsel.options].some(o => o.value === f0)) f0 = MAIN;
 fsel.value = f0; fsel.addEventListener("change", () => choose(fsel.value));
 if (f0 === MAIN) { initDetection(cache[MAIN]); fnote.textContent = mainNote(); }
 else choose(f0);
})();
