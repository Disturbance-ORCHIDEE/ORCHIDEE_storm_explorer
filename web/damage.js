(function () {
  const D = window.STORMDATA, G = window.STORMDAMAGE, C = window.SDE_CONFIG;
  if (!G) return;
  const NC = D.cells.lon.length;
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  // Guillaume M. -- The runs shown come with the data (build_storm_damage_tab.py).
  const RULES = G.rules;
  const Mm3 = v => v / 1e6;
  const fmtM = v => { const m = Mm3(v); return m === 0 ? "0" : m < 0.01 ? "< 0.01" : m < 10 ? m.toFixed(2) : m.toFixed(1); };

  // ---- state
  const S = { storm: C.default_storm, colour: "pct", extent: "storm", country: "France", scale: "log", agent: "wind" };
  const REF = C.damage.reference, Y0 = G.period[0], Y1 = G.period[1];
  const AGENTS = { wind: { name: "Wind", model: "WIND_DAMAGE_WOODVOL, all storm events", dfde: C.damage.agent_labels.wind[1] },
    beetle: { name: "Bark beetle", model: "Beetle_damage_woodvol (computed once a year)", dfde: C.damage.agent_labels.beetle[1] },
    fire: { name: "Fire", model: "wood of the burnt stands, upper bound (all trees killed)", dfde: C.damage.agent_labels.fire[1] } };
  try { Object.assign(S, JSON.parse(localStorage.getItem("sde-damage") || "{}")); } catch (e) {}
  const save = () => { try { localStorage.setItem("sde-damage", JSON.stringify(S)); } catch (e) {} };
  if (!G.storms[S.storm]) { const f = D.storms.filter(s => G.storms[s.id]).pop(); if (f) S.storm = f.id; }
  const stormOf = id => D.storms.find(s => s.id === id) || D.storms[0];
  const repCells = st => new Set((st.val.rep && st.val.rep.obs) || []);

  // ---- controls
  const sel = document.getElementById("dstorm");
  D.storms.forEach(s => { const o = document.createElement("option"); o.value = s.id;
    o.textContent = `${s.label} (${s.date})${G.storms[s.id] ? "" : " · not yet simulated"}`; sel.appendChild(o); });
  sel.addEventListener("change", () => { S.storm = sel.value; render(); });
  for (const [id, key] of [["dcolour", "colour"], ["dextent", "extent"], ["dscale", "scale"], ["dagent", "agent"]])
    document.querySelectorAll(`#${id} button`).forEach(b => b.addEventListener("click", () => { S[key] = b.dataset.v; render(); }));
  // Guillaume M. -- Europe = sum over the countries DFDE covers, so model and DFDE share the same footprint.
  const EU = C.damage.europe_label;
  (() => {
    const agg = {};
    (G.agents || ["wind"]).forEach(ag => {
      const A = { model: {}, dfde: {} };
      Object.entries(G.countries).forEach(([n, C]) => {
        const X = C[ag]; if (!X || !Object.keys(X.dfde || {}).length) return;
        Object.entries(X.dfde).forEach(([y, v]) => { A.dfde[y] = (A.dfde[y] || 0) + v; });
        A.status = A.status || {};
        Object.entries(X.status || {}).forEach(([y, c]) => {
          const rank = { g: 3, e: 2, r: 1, z: 0 }, cur = A.status[y];
          if (cur === undefined || rank[c] > rank[cur]) A.status[y] = c; });
        Object.entries(X.model || {}).forEach(([r, ys]) => {
          A.model[r] = A.model[r] || {};
          Object.entries(ys).forEach(([y, v]) => { A.model[r][y] = (A.model[r][y] || 0) + v; });
        });
      });
      agg[ag] = A;
    });
    G.countries[EU] = agg;
  })();
  const csel = document.getElementById("dcountry");
  const ctot = c => Object.values(((G.countries[c] || {}).wind || {}).dfde || {}).reduce((a, b) => a + b, 0);
  [EU, ...Object.keys(G.countries).filter(c => c !== EU).sort((a, b) => ctot(b) - ctot(a))].forEach(c => {
    const o = document.createElement("option"); o.value = c; o.textContent = c; csel.appendChild(o); });
  if (!G.countries[S.country]) S.country = csel.options[0] ? csel.options[0].value : "";
  csel.addEventListener("change", () => { S.country = csel.value; render(); });

  // ---- maps
  const tip = document.getElementById("tip");
  const box = document.getElementById("dmaps");
  const panels = RULES.map(rule => {
    const d = document.createElement("div"); d.className = "map";
    d.innerHTML = `<div class="mhead"><h4>${rule.name}</h4><span class="set note">${esc(G.settings[rule.id] || "")}</span></div>
      <div class="stats"></div><canvas role="img"></canvas>`;
    const cv = d.querySelector("canvas");
    cv.addEventListener("mousemove", hover); cv.addEventListener("mouseleave", () => { tip.hidden = true; });
    box.appendChild(d);
    return { rule, d, cv, stats: d.querySelector(".stats") };
  });
  const recOf = (sid, rid) => ((G.storms[sid] || {})[rid]) || null;
  function cellValues(rec) {
    const v = new Map(), k = new Set();
    if (rec) rec.cells.forEach((c, i) => { v.set(c, rec.vol[i]); if (rec.kill[i]) k.add(c); });
    return { v, k };
  }
  const BINS = {
    pct: { edges: [5, 1, 0.1, 0], labels: ["> 5 %", "1–5 %", "0.1–1 %", "< 0.1 %"] },
    ha: { edges: [20, 5, 1, 0], labels: ["> 20 m³/ha", "5–20", "1–5", "< 1"] },
  };
  const metric = (c, vol) => S.colour === "pct"
    ? (G.standing_m3[c] > 0 ? 100 * vol / G.standing_m3[c] : 0)
    : (D.cells.forest_kha[c] > 0 ? vol / (D.cells.forest_kha[c] * 1000) : 0);
  const binOf = m => { const e = BINS[S.colour].edges; for (let i = 0; i < e.length; i++) if (m > e[i]) return i; return -1; };

  function extent(st) {
    const [x0, x1, y0, y1] = D.box;
    if (S.extent === "europe") return [x0 - 0.5, x1 + 0.5, y0 - 0.5, y1 + 0.5];
    const ks = new Set(repCells(st));
    RULES.forEach(r => { const rec = recOf(st.id, r.id); if (rec) rec.cells.forEach((c, i) => { if (rec.kill[i]) ks.add(c); }); });
    if (!ks.size) return [x0 - 0.5, x1 + 0.5, y0 - 0.5, y1 + 0.5];
    let a = 1e9, b = -1e9, c = 1e9, d = -1e9;
    ks.forEach(k => { a = Math.min(a, D.cells.lon[k]); b = Math.max(b, D.cells.lon[k]); c = Math.min(c, D.cells.lat[k]); d = Math.max(d, D.cells.lat[k]); });
    const cx = (a + b) / 2, cy = (c + d) / 2, w = Math.max(b - a + 6, 18), h = Math.max(d - c + 5, 12);
    return [cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2];
  }
  function draw(p, st) {
    const canvas = p.cv, [x0, x1, y0, y1] = extent(st);
    const kx = Math.cos(((y0 + y1) / 2) * Math.PI / 180);
    const W = canvas.clientWidth || 500, H = Math.round(W * (y1 - y0) / ((x1 - x0) * kx));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.height = H + "px";
    const g = canvas.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const X = x => (x - x0) / (x1 - x0) * W, Y = y => (y1 - y) / (y1 - y0) * H;
    g.fillStyle = css("--sea"); g.fillRect(0, 0, W, H);
    g.fillStyle = css("--land");
    D.land.forEach(r => { g.beginPath(); r.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.closePath(); g.fill(); });
    const rec = recOf(st.id, p.rule.id), { v, k } = cellValues(rec), rep = repCells(st);
    const cols = [css("--d1"), css("--d2"), css("--d3"), css("--d4")], none = css("--cell-none");
    const geo = [];
    for (let c = 0; c < NC; c++) {
      const lo = D.cells.lon[c], la = D.cells.lat[c];
      if (lo < x0 - 1 || lo > x1 + 1 || la < y0 - 1 || la > y1 + 1) continue;
      const vol = v.get(c) || 0, b = vol > 0 ? binOf(metric(c, vol)) : -1;
      const px = X(lo - 0.5), py = Y(la + 0.5), pw = X(lo + 0.5) - px, ph = Y(la - 0.5) - py;
      g.fillStyle = b < 0 ? none : cols[3 - b]; g.fillRect(px + 0.5, py + 0.5, pw - 1, ph - 1);
      geo.push([c, px, py, pw, ph]);
    }
    g.strokeStyle = css("--border"); g.lineWidth = 0.8;
    D.borders.forEach(r => { g.beginPath(); r.forEach(([x, y], i) => i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke(); });
    g.strokeStyle = css("--obs"); g.lineWidth = 2;
    geo.forEach(([c, px, py, pw, ph]) => { if (rep.has(c)) g.strokeRect(px + 1, py + 1, pw - 2, ph - 2); });
    g.fillStyle = css("--dot");
    geo.forEach(([c, px, py, pw, ph]) => { if (k.has(c)) { g.beginPath(); g.arc(px + pw / 2, py + ph / 2, Math.max(2, Math.min(pw, ph) * 0.16), 0, 7); g.fill(); } });
    if (!rec) {
      g.fillStyle = css("--muted"); g.font = `500 14px ${css("--f-ui")}`; g.textAlign = "center";
      g.fillText("Not simulated yet", W / 2, H / 2);
    }
    canvas._geo = geo; canvas._ctx = { st, rule: p.rule, v, k, rep };
    canvas.setAttribute("aria-label", `${p.rule.name}: felled volume for ${st.label}`);
  }
  function hover(e) {
    const cv = e.currentTarget, r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const hit = (cv._geo || []).find(([c, px, py, pw, ph]) => x >= px && x < px + pw && y >= py && y < py + ph);
    if (!hit) { tip.hidden = true; return; }
    const c = hit[0], { v, k, rep } = cv._ctx, vol = v.get(c) || 0;
    const pct = G.standing_m3[c] > 0 ? 100 * vol / G.standing_m3[c] : 0;
    tip.innerHTML = [`${D.cells.lon[c].toFixed(1)}°E ${D.cells.lat[c].toFixed(1)}°N · ${esc((G.cell_country || [])[c] || "")}`,
      `felled ${Math.round(vol).toLocaleString("en")} m³ · ${pct.toFixed(2)} % of standing volume`,
      `${k.has(c) ? "storm ended here (effective detection)" : "no storm ended here"}`,
      `${rep.has(c) ? "reported: struck" : "reported: no"}`].join("<br>");
    tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (e.clientY + 14) + "px";
  }

  // ---- DFDE reference for one storm: national wind volume of its calendar year, countries with reported damage
  function dfdeFor(st) {
    const y = st.date.slice(0, 4), cs = new Set();
    repCells(st).forEach(c => { const n = (G.cell_country || [])[c]; if (n) cs.add(n); });
    let s = 0; cs.forEach(n => { s += (((G.countries[n] || {}).wind || {}).dfde || {})[y] || 0; });
    return { v: s, countries: [...cs] };
  }

  // ---- country chart
  function chart() {
    const cv = document.getElementById("dchart"), C = (G.countries[S.country] || {})[S.agent];
    const W = cv.clientWidth || 700, H = Math.max(220, Math.round(W * 0.32)), dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    if (!C) return;
    const years = []; for (let y = Y0; y <= Y1; y++) years.push(y);
    const L = 54, R = 10, T = 10, B = 50, pw = W - L - R, ph = H - T - B;
    const vals = [];
    years.forEach(y => { vals.push((C.dfde || {})[y] || 0); RULES.forEach(r => vals.push(((C.model || {})[r.id] || {})[y] || 0)); });
    const vmax = Math.max(1, ...vals) / 1e6;
    const log = S.scale === "log", lo = 0.01;
    const hi = log ? Math.pow(10, Math.ceil(Math.log10(Math.max(vmax, 0.1)))) : niceMax(vmax);
    const yv = m => log ? T + ph * (1 - (Math.log10(Math.max(m, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) : T + ph * (1 - m / hi);
    const xv = y => L + (y - Y0 + 0.5) / years.length * pw;
    g.font = `12px ${css("--f-data")}`; g.fillStyle = css("--muted"); g.strokeStyle = css("--line"); g.lineWidth = 1;
    const ticks = log ? (() => { const t = []; for (let e = Math.log10(lo); e <= Math.log10(hi) + 1e-9; e++) t.push(Math.pow(10, e)); return t; })()
      : [0, hi / 4, hi / 2, 3 * hi / 4, hi];
    g.textAlign = "right"; g.textBaseline = "middle";
    ticks.forEach(t => { const yy = yv(t); g.beginPath(); g.moveTo(L, yy); g.lineTo(W - R, yy); g.stroke();
      g.fillText(t >= 1 ? String(+t.toFixed(0)) : String(t), L - 6, yy); });
    g.save(); g.translate(12, T + ph / 2); g.rotate(-Math.PI / 2); g.textAlign = "center"; g.fillText("million m³", 0, 0); g.restore();
    g.textAlign = "center"; g.textBaseline = "top";
    years.forEach(y => { if (y % 5 === 0) g.fillText(String(y), xv(y), T + ph + 6); });
    const bw = pw / years.length * 0.7, st = C.status || {};
    years.forEach(y => {
      const m = ((C.dfde || {})[y] || 0) / 1e6; if (m <= 0) return;
      const yy = yv(m), x0 = xv(y) - bw / 2, hgt = T + ph - yy, est = st[y] === "g" || st[y] === "e";
      g.fillStyle = css("--dfde"); g.globalAlpha = est ? 0.08 : 0.22; g.fillRect(x0, yy, bw, hgt); g.globalAlpha = 1;
      if (est) {   // estimate: hatched bar
        g.save(); g.beginPath(); g.rect(x0, yy, bw, hgt); g.clip();
        g.strokeStyle = css("--dfde"); g.globalAlpha = 0.5; g.lineWidth = 1;
        for (let k = -hgt; k < bw + hgt; k += 5) { g.beginPath(); g.moveTo(x0 + k, yy + hgt); g.lineTo(x0 + k + hgt, yy); g.stroke(); }
        g.restore();
      }
    });
    // DFDE status strip, one cell per year
    const sy = T + ph + 22, sh = 10, cw = pw / years.length;
    years.forEach(y => {
      const c = st[y], x0 = L + (y - Y0) * cw + 1, w0 = cw - 2;
      g.globalAlpha = 1; g.lineWidth = 1;
      if (c === "r") { g.fillStyle = css("--dfde"); g.globalAlpha = 0.55; g.fillRect(x0, sy, w0, sh); }
      else if (c === "z") { g.strokeStyle = css("--dfde"); g.globalAlpha = 0.6; g.strokeRect(x0 + 0.5, sy + 0.5, w0 - 1, sh - 1); }
      else if (c === "g" || c === "e") {
        g.save(); g.beginPath(); g.rect(x0, sy, w0, sh); g.clip(); g.strokeStyle = css("--dfde"); g.globalAlpha = 0.55;
        for (let k = -sh; k < w0 + sh; k += 4) { g.beginPath(); g.moveTo(x0 + k, sy + sh); g.lineTo(x0 + k + sh, sy); g.stroke(); }
        g.restore();
        if (c === "e") { g.fillStyle = css("--dfde"); g.globalAlpha = 0.8; g.beginPath(); g.arc(x0 + w0 / 2, sy + sh / 2, 1.8, 0, 7); g.fill(); }
      } else { g.strokeStyle = css("--muted"); g.globalAlpha = 0.7; g.beginPath(); g.moveTo(x0 + 2, sy + 2); g.lineTo(x0 + w0 - 2, sy + sh - 2);
        g.moveTo(x0 + w0 - 2, sy + 2); g.lineTo(x0 + 2, sy + sh - 2); g.stroke(); }
    });
    g.globalAlpha = 1; g.fillStyle = css("--muted"); g.textAlign = "right"; g.textBaseline = "middle";
    g.fillText(REF, L - 6, sy + sh / 2);
    RULES.forEach(r => {
      const M = (C.model || {})[r.id] || {}; const pts = years.filter(y => y in M).map(y => [xv(y), yv(M[y] / 1e6)]);
      if (!pts.length) return;
      g.strokeStyle = css(r.col); g.fillStyle = css(r.col); g.lineWidth = 2;
      g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.stroke();
      pts.forEach(([x, y]) => { g.beginPath(); g.arc(x, y, 2.5, 0, 7); g.fill(); });
    });
    const AG = AGENTS[S.agent];
    const hatch = "repeating-linear-gradient(135deg, var(--dfde) 0 1px, transparent 1px 4px)";
    document.getElementById("dclegend").innerHTML = `<span><i class="sw" style="background:var(--dfde);opacity:.3"></i>${REF} “${AG.dfde}” volume, reported (national, whole year)</span>`
      + `<span><i class="sw" style="background:${hatch};opacity:.7"></i>${REF} estimate (gap-filled or expert)</span>`
      + `<span class="note">${REF} row: <i class="sw" style="background:var(--dfde);opacity:.55"></i>reported (0 included) `
      + `<i class="sw" style="box-shadow:inset 0 0 0 1px var(--dfde)"></i>nothing reported, series judged complete = no damage `
      + `<i class="sw" style="background:${hatch}"></i>not reported, gap-filled `
      + `<i class="sw" style="background:radial-gradient(circle, var(--dfde) 25%, transparent 30%), ${hatch}"></i>no national data, expert value `
      + `× no ${REF} row</span>`
      + RULES.map(r => `<span><i class="sw line" style="background:var(${r.col})"></i>${r.name}</span>`).join("")
      + `<span>model: ${AG.model}</span>`
      + (log ? `<span>values below 0.01 drawn at 0.01</span>` : "");
  }
  function niceMax(v) { const p = Math.pow(10, Math.floor(Math.log10(v))); return [1, 2, 2.5, 5, 10].map(m => m * p).find(m => m >= v); }

  // ---- render
  let raf = 0;
  function render() { cancelAnimationFrame(raf); raf = requestAnimationFrame(renderNow); }
  function renderNow() {
    if (views.damage.hidden) return;
    save();
    const st = stormOf(S.storm); sel.value = st.id; csel.value = S.country;
    for (const [id, key] of [["dcolour", "colour"], ["dextent", "extent"], ["dscale", "scale"], ["dagent", "agent"]])
      document.querySelectorAll(`#${id} button`).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === S[key])));
    const yrs = RULES.map(r => (G.years[r.id] || []));
    document.getElementById("dstatus").textContent = "Years simulated: " + RULES.map((r, i) => `${r.name} ${yrs[i].length ? yrs[i][0] + "–" + yrs[i][yrs[i].length - 1] : "none"}`).join(" · ")
        + ". A storm outside a run's years shows no data for that run.";
    const rep = repCells(st), ref = dfdeFor(st);
    document.getElementById("dnote").innerHTML = `${esc(st.label)}, ${st.date}: ${rep.size} cells with reported damage`
      + (ref.countries.length ? ` in ${esc(ref.countries.join(", "))}; ${REF} ${st.date.slice(0, 4)} wind volume for these countries ${fmtM(ref.v)} million m³.` : ".");
    panels.forEach(p => {
      const rec = recOf(st.id, p.rule.id);
      if (!rec) { p.stats.innerHTML = `<span class="note">no data for this storm yet</span>`; draw(p, st); return; }
      const { v, k } = cellValues(rec);
      let tot = 0, inRep = 0; v.forEach((x, c) => { tot += x; if (rep.has(c)) inRep += x; });
      const repDet = [...rep].filter(c => k.has(c)).length;
      p.stats.innerHTML = `<span class="rate">${fmtM(tot)}</span><span>million m³ felled</span>
        <span>in reported cells <b>${tot > 0 ? Math.round(100 * inRep / tot) : 0} %</b></span>
        <span>storm ended in reported cells <b>${repDet} / ${rep.size}</b></span>
        <span>cells with a storm end <b>${k.size}</b></span>`;
      draw(p, st);
    });
    const B = BINS[S.colour];
    document.getElementById("dlegend").innerHTML = `<span>${S.colour === "pct" ? "Felled, % of standing volume:" : "Felled, m³ per ha of forest:"}</span>`
      + B.labels.map((l, i) => `<span><i class="sw" style="background:var(--d${4 - i})"></i>${l}</span>`).join("")
      + `<span><i class="sw" style="background:var(--cell-none)"></i>none</span>
         <span><i class="sw" style="background:transparent;box-shadow:inset 0 0 0 2px var(--obs)"></i>reported struck</span>
         <span><i class="sw" style="background:radial-gradient(circle, var(--dot) 30%, transparent 34%)"></i>storm ended (effective detection)</span>`;
    const rows = D.storms.filter(s => G.storms[s.id]);
    const sum = RULES.map(() => 0);
    const body = rows.map(s => {
      const r0 = dfdeFor(s);
      const cells = RULES.map((r, i) => { const rec = recOf(s.id, r.id); if (!rec) return `<td class="num">–</td>`;
        const t = rec.vol.reduce((a, b) => a + b, 0); sum[i] += t; return `<td class="num">${fmtM(t)}</td>`; }).join("");
      return `<tr class="click${s.id === st.id ? " sel" : ""}" data-id="${s.id}"><td>${esc(s.label)}</td><td class="num">${s.date}</td>${cells}<td class="num">${r0.countries.length ? fmtM(r0.v) : "–"}</td></tr>`;
    }).join("");
    document.getElementById("dtab").innerHTML = `<thead><tr><th>Storm</th><th>Date</th>${RULES.map(r => `<th>${r.name}</th>`).join("")}<th>${REF}, year</th></tr></thead>
      <tbody>${body}</tbody><tfoot><tr><td>Total over these storms</td><td></td>${sum.map(t => `<td class="num">${fmtM(t)}</td>`).join("")}<td></td></tr></tfoot>`;
    document.querySelectorAll("#dtab tr.click").forEach(tr => tr.addEventListener("click", () => { S.storm = tr.dataset.id; render(); }));
    chart();
  }
  let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(render, 120); });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", render);
  renderNow();
})();
