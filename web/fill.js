// Fill the page from window.SDE_CONFIG (written by build_data.py from storm_explorer_config.py) before the views start.
(function () {
  const C = window.SDE_CONFIG;
  // Python-like "{0}", "{1:.0f}", "{0:.3f}" formatting of a rule setting
  window.SDE_FMT = (tpl, p) => tpl.replace(/\{(\d+)(?::\.(\d+)f)?\}/g, (_, i, d) => {
    const v = p[+i]; return v === undefined ? "" : d === undefined ? String(v) : (+v).toFixed(+d);
  });
  window.SDE_RULE = id => C.rules.find(r => r.id === id);
  function fillFromConfig() {
    document.title = C.title;
    document.getElementById("sde-title").textContent = C.title;
    document.getElementById("sde-intro").innerHTML = C.intro;
    const sel = document.getElementById("forcing");
    C.forcings.forEach(f => { const o = document.createElement("option"); o.value = f.id; o.textContent = f.label; sel.appendChild(o); });
    if (C.forcings.length < 2) sel.closest(".ctl").hidden = true;
    for (const v in C.notes) {
      const el = document.getElementById("notes-" + v); if (!el) continue;
      el.innerHTML = C.notes[v].map(t => `<p>${t.replace(/\{first_year\}/g, C.first_year)}</p>`).join("");
    }
    const lv = (window.STORMDATA.iso && window.STORMDATA.iso.levels) || [];
    if (lv.length) document.querySelectorAll(".sde-range").forEach(el => {
      el.textContent = `onsets per cell and decade (${lv[0].toFixed(1)}–${lv[lv.length - 1].toFixed(1)})`; });
    const fcvs = document.getElementById("fcvs");
    C.forcing_tab_vsets.forEach((id, i) => {
      const v = C.vsets.find(x => x.id === id); if (!v) return;
      const b = document.createElement("button"); b.type = "button"; b.dataset.v = id; b.textContent = v.short || v.name;
      b.setAttribute("aria-pressed", i === 0 ? "true" : "false"); fcvs.appendChild(b);
    });
    // views without data are not offered
    const has = { damage: !!window.STORMDAMAGE, ddamage: !!window.STORMDDAMAGE, forcings: C.forcings.length > 1 };
    for (const v in has) if (!has[v]) document.getElementById("tab-" + v).hidden = true;
    const dd = window.STORMDDAMAGE;
    if (dd) document.getElementById("ddperiod").textContent =
      `% of forest area per decade, July ${dd.period[0]} to June ${dd.period[1]} (disturbance-raster years ${dd.period[0] + 1}-${dd.period[1]}), same cells.`;
  }
  fillFromConfig();
})();
