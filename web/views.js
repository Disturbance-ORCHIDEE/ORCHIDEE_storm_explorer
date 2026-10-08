// View switch of the page header; runs last, once every view has set up its listeners.
(function () {
  const views = Object.fromEntries([...document.querySelectorAll(".view")].map(el => [el.id.slice(5), el]));
  const tabs = [...document.querySelectorAll(".viewtabs button")].filter(b => !b.hidden);
  function setView(v, keep) {
    Object.entries(views).forEach(([k, el]) => { el.hidden = k !== v; });
    tabs.forEach(b => b.setAttribute("aria-selected", String(b.dataset.view === v)));
    if (!keep) { try { localStorage.setItem("sde-view", v); } catch (e) {} }
    window.dispatchEvent(new Event("resize"));
  }
  tabs.forEach(b => b.addEventListener("click", () => setView(b.dataset.view)));
  const ok = v => tabs.some(b => b.dataset.view === v);
  let v0 = "detection";
  try { v0 = localStorage.getItem("sde-view") || v0; } catch (e) {}
  if (ok(location.hash.slice(1))) v0 = location.hash.slice(1);
  if (!ok(v0)) v0 = "detection";
  setView(v0, true);
})();
