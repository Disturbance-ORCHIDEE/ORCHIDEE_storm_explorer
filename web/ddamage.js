(function () {
  const DD = window.STORMDDAMAGE;
  if (!DD) return;
  const REF = DD.ref_name || "reference", NREG = DD.regions.length - 1, P0 = DD.period[0], P1 = DD.period[1];
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const VIDS = Object.keys(DD.versions);
  const S = { v: VIDS[0], tune: null, idx: {} };
  try { Object.assign(S, JSON.parse(localStorage.getItem("sde-ddamage") || "{}")); } catch (e) {}
  if (!DD.versions[S.v]) S.v = VIDS[0];
  const save = () => { try { localStorage.setItem("sde-ddamage", JSON.stringify(S)); } catch (e) {} };
  const V = () => DD.versions[S.v];
  const fmtR = r => r === null || r === undefined ? "–" : r >= 10 ? r.toFixed(0) : r >= 1 ? r.toFixed(2) : r.toFixed(3);
  const band = (r, lo, hi) => r === null || r === undefined ? "" : r < lo ? "under" : r <= hi ? "ok" : "over";
  const pill = (r, lo = 0.5, hi = 2) => `<span class="pill ${band(r, lo, hi)}">${fmtR(r)}</span>`;

  // ---- controls
  const vsel = document.getElementById("ddversion"), tsel = document.getElementById("ddtune"), pbox = document.getElementById("ddparams");
  VIDS.forEach(id => { const o = document.createElement("option"); o.value = id; o.textContent = DD.versions[id].label; vsel.appendChild(o); });
  vsel.addEventListener("change", () => { S.v = vsel.value; S.tune = null; S.idx = {}; build(); });
  tsel.addEventListener("change", () => { S.tune = tsel.value; render(); });
  document.getElementById("ddreset").addEventListener("click", () => { S.idx = {}; build(); });
  let inputs = {};
  function build() {
    const v = V();
    if (!v.tunes.map(String).includes(String(S.tune))) S.tune = String(v.tunes[0]);
    tsel.innerHTML = v.tunes.map(t => `<option value="${t}">${t}</option>`).join("");
    tsel.value = S.tune; tsel.disabled = v.tunes.length < 2;
    pbox.innerHTML = ""; inputs = {};
    v.keys.forEach(k => {
      const vals = v.params[k]; if (S.idx[k] === undefined || S.idx[k] >= vals.length) S.idx[k] = 0;
      const row = document.createElement("div"); row.className = "prm";
      row.innerHTML = `<label for="dd-${k}">${k} ≥</label><div class="track"><input type="range" id="dd-${k}" min="0" max="${vals.length - 1}" step="1">
        <span class="mk opt" style="left:8px">run</span></div><output></output>`;
      const inp = row.querySelector("input"), out = row.querySelector("output");
      inp.value = S.idx[k]; out.textContent = vals[S.idx[k]];
      inp.addEventListener("input", () => { S.idx[k] = +inp.value; out.textContent = vals[+inp.value]; render(); });
      inputs[k] = inp; pbox.appendChild(row);
    });
    if (v.rule === "gate") pbox.querySelector('label[for="dd-Z"]').textContent = "Z (−σ) ≥";
    render();
  }
  const comboIdx = () => { const v = V(); let c = 0; v.keys.forEach(k => { c = c * v.params[k].length + S.idx[k]; }); return c; };
  const row = () => V().res[S.tune][comboIdx()];

  // ---- cards, table, chart
  function render() {
    save(); vsel.value = S.v;
    const v = V(), r = row(), E = DD.efda;
    const tot = k => r.area[k][0] + r.area[k][1];
    const ratio = k => tot(k) / E[k];
    const regOk = DD.regions.slice(1).filter(k => ratio(k) >= 0.5 && ratio(k) <= 2).length;
    const passA = ratio("Europe") >= 0.5 && ratio("Europe") <= 2 && regOk >= Math.max(1, NREG - 1);
    const passR = r.rho !== null && r.rho >= 0.5 && r.rho <= 2, passQ = r.quiet <= 0.2;
    const tag = ok => `<span class="pill ${ok ? "ok" : "over"}">${ok ? "pass" : "fail"}</span>`;
    document.getElementById("ddnote").innerHTML = `Bench run(s) of this version: ${esc(v.base)}, damage scaling ${S.tune}. Sliders can only tighten detection (episodes are removed, never added).`;
    document.getElementById("ddstrip").innerHTML = `
      <div class="card"><h3>Volume against ${REF}</h3><div class="set">median ratio model / ${REF} on the ${r.n} calibration storms</div>
        <div class="big">${pill(r.rho)}</div>
        <div class="row"><span>interquartile range</span><b>${r.iqr ? fmtR(r.iqr[0]) + " – " + fmtR(r.iqr[1]) : "–"}</b></div>
        ${Object.entries(r.valid).map(([k, x]) => `<div class="row"><span>held out: ${esc(k)}</span><b>${x === null ? "missed" : fmtR(x)}</b></div>`).join("")}
        <div class="row"><span>within ×2</span>${tag(passR)}</div></div>
      <div class="card"><h3>Disturbed forest area</h3><div class="set">storm + bark beetle, % of forest per decade, against EFDA agent 1</div>
        <div class="big">${tot("Europe").toFixed(2)} <small>% vs EFDA ${E.Europe.toFixed(2)}</small></div>
        <div class="row"><span>ratio, Europe</span>${pill(ratio("Europe"))}</div>
        <div class="row"><span>storm / bark beetle</span><b>${r.area.Europe[0].toFixed(2)} / ${r.area.Europe[1].toFixed(2)}</b></div>
        <div class="row"><span>×0.5–2, Europe and ≥ ${Math.max(1, NREG - 1)} regions (${regOk}/${NREG})</span>${tag(passA)}</div></div>
      <div class="card"><h3>Damage outside storms</h3><div class="set">share of the storm-damaged area in quiet cell-seasons (no catalogued storm, no EFDA anomaly)</div>
        <div class="big">${Math.round(100 * r.quiet)} <small>%</small></div>
        <div class="row"><span>≤ 20 %</span>${tag(passQ)}</div></div>
      <div class="card"><h3>Storm ends</h3><div class="set">damage episodes per cell and decade, ${P0}-${P1}</div>
        <div class="big">${r.ends.toFixed(2)}</div>
        <div class="row"><span>reference ≈ 0.9</span>${pill(r.ends, 0.9, 2)}</div></div>`;
    document.getElementById("ddtab").innerHTML = `<thead><tr><th>Region</th><th>Model storm</th><th>Model bark beetle</th><th>Model total</th><th>EFDA agent 1</th><th>Ratio</th></tr></thead><tbody>`
      + DD.regions.map(k => `<tr><td>${k}</td><td class="num">${r.area[k][0].toFixed(2)}</td><td class="num">${r.area[k][1].toFixed(2)}</td><td class="num">${tot(k).toFixed(2)}</td><td class="num">${E[k].toFixed(2)}</td><td class="num">${pill(ratio(k))}</td></tr>`).join("")
      + `</tbody>`;
    chart();
  }
  function chart() {
    const v = V(), k0 = v.keys[0], vals = v.params[k0], cv = document.getElementById("ddchart");
    const W = cv.clientWidth || 800, H = 280, dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const m = { l: 50, r: 14, t: 12, b: 36 }, ya = -2, yb = 2;
    const X = i => m.l + i / Math.max(vals.length - 1, 1) * (W - m.l - m.r), Y = y => m.t + (yb - y) / (yb - ya) * (H - m.t - m.b);
    g.font = "11px " + css("--f-data"); g.strokeStyle = css("--line"); g.fillStyle = css("--muted");
    g.fillStyle = css("--ok-soft"); g.fillRect(m.l, Y(Math.log10(2)), W - m.l - m.r, Y(Math.log10(0.5)) - Y(Math.log10(2)));
    g.fillStyle = css("--muted");
    [0.01, 0.1, 0.5, 1, 2, 10, 100].forEach(t => { const y = Y(Math.log10(t)); g.strokeStyle = css("--line"); g.beginPath(); g.moveTo(m.l, y); g.lineTo(W - m.r, y); g.stroke();
      g.textAlign = "right"; g.textBaseline = "middle"; g.fillText(String(t), m.l - 6, y); });
    vals.forEach((x, i) => { if (vals.length < 16 || i % 2 === 0) { g.textAlign = "center"; g.textBaseline = "top"; g.fillText(String(x), X(i), H - m.b + 6); } });
    g.textAlign = "center"; g.fillText(`${k0} (other thresholds as set)`, (m.l + W - m.r) / 2, H - 14);
    const fixed = {}; v.keys.forEach(k => fixed[k] = S.idx[k]);
    const at = i => { let c = 0; v.keys.forEach(k => { c = c * v.params[k].length + (k === k0 ? i : fixed[k]); }); return v.res[S.tune][c]; };
    const E = DD.efda;
    const series = [["--c-and", i => at(i).rho, `volume / ${REF}`], ["--c-peak", i => (at(i).area.Europe[0] + at(i).area.Europe[1]) / E.Europe, "area / EFDA (Europe)"],
                    ["--c-gate", i => at(i).ends / 0.9, "storm ends / 0.9 per decade"], ["--c-prod", i => at(i).quiet / 0.2, "outside-storm share / 20 %"]];
    series.forEach(([col, f]) => { g.strokeStyle = css(col); g.lineWidth = 2; g.beginPath(); let st = false;
      vals.forEach((_, i) => { const y = f(i); if (!(y > 0)) { st = false; return; } const py = Y(Math.max(ya, Math.min(yb, Math.log10(y))));
        if (st) g.lineTo(X(i), py); else { g.moveTo(X(i), py); st = true; } }); g.stroke(); });
    g.strokeStyle = css("--fg"); g.lineWidth = 1; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(X(S.idx[k0]), m.t); g.lineTo(X(S.idx[k0]), H - m.b); g.stroke(); g.setLineDash([]);
    document.getElementById("ddlegend").innerHTML = series.map(([c, , l]) => `<span><span class="sw line" style="background:var(${c})"></span>${l}</span>`).join("")
      + `<span>shaded = ×0.5–2 · log scale, 1 = on target · dashed = slider</span>`;
  }
  window.addEventListener("resize", () => { if (!document.getElementById("view-ddamage").hidden) chart(); });
  build();
})();
