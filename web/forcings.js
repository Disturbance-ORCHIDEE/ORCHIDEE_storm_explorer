(function () {
  // Guillaume M. -- Forcings tab: every rule on every forcing, all at the same onset rate (onsets per cell and decade).
  // At equal rate the false alarms are about equal, so the detection gap between two curves is a gap of skill.
  const view = document.getElementById("view-forcings");
  if (!view || !window.SDE) return;
  const C = window.SDE_CONFIG;
  const FORC = C.forcings.map(f => ({ id: f.id, name: f.short, col: f.colour_var, period: f.period }));
  const RULES = C.rules.map(r => ({ id: r.id, name: r.short, dash: r.dash, fmt: r.fmt_short }));
  const VS = C.forcing_tab_vsets.map(id => C.vsets.find(v => v.id === id)).filter(Boolean).map(v => ({ id: v.id, name: v.short || v.name }));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const S = { L: 1.0, vs: VS[0].id, set: "common" };
  try { Object.assign(S, JSON.parse(localStorage.getItem("sde-forcings") || "{}")); } catch (e) {}
  const save = () => { try { localStorage.setItem("sde-forcings", JSON.stringify(S)); } catch (e) {} };
  const DATA = {}, BITS = {};
  const status = document.getElementById("fcstatus");
  const b64 = s => { const bin = atob(s); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; };
  let started = false;

  async function start() {
    if (started) return; started = true;
    for (const f of FORC) {
      status.textContent = `Loading ${f.name} …`;
      try { DATA[f.id] = await window.SDE.load(f.id); } catch (e) { status.textContent = `Could not load ${f.name}: ${e.message}`; }
      render();
    }
    status.textContent = "Settings of each level were found by replaying each rule on each forcing.";
  }
  const levels = () => { for (const f of FORC) if (DATA[f.id] && DATA[f.id].iso) return DATA[f.id].iso.levels; return []; };
  function bits(f, r) {
    const k = f + "/" + r; if (!BITS[k]) BITS[k] = b64(DATA[f].grid[r].bits); return BITS[k];
  }
  function common() {
    const sets = FORC.filter(f => DATA[f.id]).map(f => new Set(DATA[f.id].storms.map(s => s.id)));
    if (!sets.length) return new Set();
    return new Set([...sets[0]].filter(id => sets.every(s => s.has(id))));
  }
  // pooled detection of the chosen set at level index i of rule r on forcing f (null if the level is out of reach)
  function score(f, r, L, keep) {
    const D = DATA[f], g = D && D.grid[r]; if (!g || !g.params.L) return null;
    const i = g.params.L.findIndex(x => Math.abs(x - L) < 0.051); if (i < 0) return null;
    const NC = D.cells.lon.length, NS = D.storms.length, B = bits(f, r);
    let hit = 0, n = 0, per = {};
    D.storms.forEach((s, si) => {
      if (keep && !keep.has(s.id)) return;
      const v = s.val[S.vs]; if (!v || !v.obs.length) return;
      let h = 0;
      v.obs.forEach(k => { const j = (i * NS + si) * NC + k; h += (B[j >> 3] >> (j & 7)) & 1; });
      hit += h; n += v.obs.length; per[s.id] = [h, v.obs.length];
    });
    return { hit, n, rate: n ? hit / n : null, per, setting: g.settings[i], mean: g.means[i] };
  }
  const fmtSet = (r, p) => window.SDE_FMT(RULES.find(x => x.id === r).fmt, p);

  // ---- controls
  const lv = document.getElementById("fclevel"), lvo = document.getElementById("fclevelout");
  lv.addEventListener("input", () => { S.L = levels()[+lv.value]; render(); });
  document.querySelectorAll("#fcvs button").forEach(b => b.addEventListener("click", () => { S.vs = b.dataset.v; render(); }));
  document.querySelectorAll("#fcset button").forEach(b => b.addEventListener("click", () => { S.set = b.dataset.v; render(); }));

  function chart(keep) {
    const cv = document.getElementById("fcchart"), W = cv.clientWidth || 800, H = Math.max(260, Math.min(420, W * 0.45));
    const dpr = window.devicePixelRatio || 1; cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const Lv = levels(); if (!Lv.length) return;
    const L0 = 52, R0 = 12, T0 = 12, B0 = 38, pw = W - L0 - R0, ph = H - T0 - B0;
    const x = v => L0 + (v - Lv[0]) / (Lv[Lv.length - 1] - Lv[0]) * pw, y = v => T0 + ph - v / 100 * ph;
    g.strokeStyle = css("--line"); g.fillStyle = css("--muted"); g.font = "12px " + css("--f-data"); g.lineWidth = 1;
    for (let p = 0; p <= 100; p += 20) { g.beginPath(); g.moveTo(L0, y(p)); g.lineTo(L0 + pw, y(p)); g.stroke();
      g.textAlign = "right"; g.textBaseline = "middle"; g.fillText(p + " %", L0 - 6, y(p)); }
    g.textAlign = "center"; g.textBaseline = "top";
    for (let v = 0.5; v <= 3.0001; v += 0.5) g.fillText(v.toFixed(1), x(v), T0 + ph + 6);
    g.fillText("onsets per cell and decade (all rules set to this rate)", L0 + pw / 2, T0 + ph + 22);
    g.strokeStyle = css("--fg"); g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x(S.L), T0); g.lineTo(x(S.L), T0 + ph); g.stroke(); g.setLineDash([]);
    FORC.forEach(f => { if (!DATA[f.id]) return; RULES.forEach(r => {
      const pts = Lv.map(L => [L, score(f.id, r.id, L, keep)]).filter(([, s]) => s && s.rate !== null);
      if (pts.length < 2) return;
      g.strokeStyle = css(f.col); g.lineWidth = !r.dash.length ? 2.6 : 1.8; g.setLineDash(r.dash);
      g.beginPath(); pts.forEach(([L, s], i) => i ? g.lineTo(x(L), y(100 * s.rate)) : g.moveTo(x(L), y(100 * s.rate))); g.stroke(); g.setLineDash([]);
    }); });
    document.getElementById("fclegend").innerHTML =
      FORC.map(f => `<span><i class="sw line" style="background:var(${f.col})"></i>${f.name}</span>`).join("")
      + RULES.map(r => `<span><i class="sw" style="height:0;width:34px;border-radius:0;vertical-align:4px;border-top:${!r.dash.length ? "3px solid" : r.dash[0] > 4 ? "2px dashed" : "2px dotted"} var(--fg)"></i>${r.name}</span>`).join("");
  }

  function render() {
    save();
    const Lv = levels(); if (!Lv.length) return;
    lv.min = 0; lv.max = Lv.length - 1; lv.step = 1;
    let i = Lv.findIndex(v => Math.abs(v - S.L) < 0.051); if (i < 0) { i = Lv.findIndex(v => Math.abs(v - 1.0) < 0.051); S.L = Lv[i]; }
    lv.value = i; lvo.textContent = S.L.toFixed(1);
    document.querySelectorAll("#fcvs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === S.vs)));
    document.querySelectorAll("#fcset button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === S.set)));
    const keep = S.set === "common" ? common() : null;
    chart(keep);
    // table at the chosen rate
    const sc = {}; FORC.forEach(f => RULES.forEach(r => { sc[f.id + r.id] = DATA[f.id] ? score(f.id, r.id, S.L, keep) : null; }));
    const bestOf = r => Math.max(...FORC.map(f => (sc[f.id + r.id] || {}).rate ?? -1));
    document.getElementById("fctab").innerHTML = `<thead><tr><th>Rule</th>${FORC.map(f => `<th>${f.name}</th>`).join("")}</tr></thead><tbody>`
      + RULES.map(r => `<tr><td>${r.name}</td>` + FORC.map(f => {
          const s = sc[f.id + r.id]; if (!DATA[f.id]) return `<td class="num">loading</td>`; if (!s || s.rate === null) return `<td class="num">–</td>`;
          const b = s.rate === bestOf(r.id);
          return `<td class="num${b ? " win" : ""}" title="actual rate ${s.mean.toFixed(2)}">${Math.round(100 * s.rate)} % <span class="note">(${s.hit}/${s.n})</span><br><span class="note">${esc(fmtSet(r.id, s.setting))}</span></td>`;
        }).join("") + "</tr>").join("") + "</tbody>";
    // per storm
    const ids = new Set(); FORC.forEach(f => { if (DATA[f.id]) DATA[f.id].storms.forEach(s => { if (!keep || keep.has(s.id)) ids.add(s.id); }); });
    const meta = {}; FORC.forEach(f => { if (DATA[f.id]) DATA[f.id].storms.forEach(s => { meta[s.id] = s; }); });
    const order = [...ids].sort((a, b) => meta[a].date < meta[b].date ? -1 : 1);
    const cols = []; FORC.forEach(f => RULES.forEach(r => cols.push([f, r])));
    document.getElementById("fcstorms").innerHTML = `<thead><tr><th>Storm</th><th>Date</th>${cols.map(([f, r]) => `<th>${f.name}<br>${r.name}</th>`).join("")}</tr></thead><tbody>`
      + order.map(id => { const vals = cols.map(([f, r]) => { const s = sc[f.id + r.id]; return s && s.per[id] ? s.per[id] : null; });
          const rates = vals.map(v => v ? v[0] / v[1] : -1), b = Math.max(...rates), nb = rates.filter(x => x === b).length;
          return `<tr><td>${esc(meta[id].label)}</td><td class="num">${meta[id].date}</td>` + vals.map((v, k) =>
            v ? `<td class="num${b > 0 && rates[k] === b && nb === 1 ? " win" : ""}">${Math.round(100 * v[0] / v[1])} %</td>` : `<td class="num">–</td>`).join("") + "</tr>"; }).join("")
      + "</tbody>";
    const per = FORC.map(f => `${f.name} ${C.first_year}-${f.period[1]}`).join("; ");
    document.getElementById("fcnote").textContent = keep ? `${keep.size} storms present on every forcing (${per}).` : `Each forcing scored on all its storms (${per}).`;
  }
  const obs = new MutationObserver(() => { if (!view.hidden) { start(); render(); } });
  obs.observe(view, { attributes: true, attributeFilter: ["hidden"] });
  if (!view.hidden) start();
  window.addEventListener("resize", () => { if (!view.hidden) render(); });
})();
