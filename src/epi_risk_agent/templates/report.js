(function () {
  "use strict";
  var data;
  try { data = JSON.parse(document.getElementById("report-data").textContent); } catch (e) { data = null; }

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  /* ---------- theme ---------------------------------------------------- */
  var THEMES = ["auto", "light", "dark"];
  var THEME_LABEL = { auto: "主題：自動", light: "主題：淺色", dark: "主題：深色" };
  function applyTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    var b = $("themeBtn"); if (b) b.textContent = THEME_LABEL[t];
  }
  var theme = "auto";
  try { theme = localStorage.getItem("epi-risk-theme") || "auto"; } catch (e) { /* storage unavailable */ }
  if (THEMES.indexOf(theme) < 0) theme = "auto";
  applyTheme(theme);
  if ($("themeBtn")) $("themeBtn").addEventListener("click", function () {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(theme);
    try { localStorage.setItem("epi-risk-theme", theme); } catch (e) { /* ignore */ }
  });

  /* ---------- print: expand all <details> ------------------------------- */
  var reopened = [];
  window.addEventListener("beforeprint", function () {
    reopened = [];
    document.querySelectorAll("details:not([open])").forEach(function (d) { d.open = true; reopened.push(d); });
  });
  window.addEventListener("afterprint", function () { reopened.forEach(function (d) { d.open = false; }); reopened = []; });
  if ($("printBtn")) $("printBtn").addEventListener("click", function () { window.print(); });

  /* ---------- tooltip --------------------------------------------------- */
  var tip = $("tip");
  function showTip(text, x, y) {
    if (!tip) return;
    tip.textContent = text; tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, x + 12), window.innerWidth - w - 8);
    var top = y - h - 10; if (top < 8) top = y + 16;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hideTip() { if (tip) tip.hidden = true; }
  document.querySelectorAll(".bar-row[data-tip]").forEach(function (row) {
    row.addEventListener("pointermove", function (ev) { showTip(row.getAttribute("data-tip"), ev.clientX, ev.clientY); });
    row.addEventListener("pointerleave", hideTip);
    row.addEventListener("focus", function () { var r = row.getBoundingClientRect(); showTip(row.getAttribute("data-tip"), r.left + r.width / 2, r.top); });
    row.addEventListener("blur", hideTip);
  });

  if (!data) return;

  /* ---------- matrix detail -------------------------------------------- */
  var detail = $("matrixDetail");
  var tpl = $("itemDetails");
  function showItem(id, btn) {
    if (!detail || !tpl) return;
    var src = tpl.content.querySelector('[data-item="' + CSS.escape(id) + '"]');
    detail.innerHTML = "";
    if (src) detail.appendChild(src.cloneNode(true));
    document.querySelectorAll(".marker[data-item]").forEach(function (m) { m.setAttribute("aria-pressed", m === btn ? "true" : "false"); });
  }
  document.querySelectorAll(".marker[data-item]").forEach(function (m) {
    m.setAttribute("aria-pressed", "false");
    m.addEventListener("click", function () { showItem(m.getAttribute("data-item"), m); });
  });

  /* ---------- what-if (試算) -------------------------------------------- */
  var M = data.matrix, M3 = data.matrixTo3, I3 = data.impactTo3, P3 = data.probTo3;
  var ORDER = { "低": 0, "中": 1, "高": 2, "極高": 3 };
  var items = data.items;
  var trial = {};
  function resetTrial() { trial = {}; items.forEach(function (it) { trial[it.id] = { p: it.p, i: it.inherit ? null : it.i }; }); }
  resetTrial();

  function compute(state) {
    var shared = null;
    items.forEach(function (it) { if (it.kind === "衝擊") { var v = state[it.id].i; if (shared === null || v > shared) shared = v; } });
    var res = {}, best = null;
    items.forEach(function (it) {
      var s = state[it.id];
      if (it.kind === "衝擊") { res[it.id] = { level: I3[String(s.i)], matrix: null, p: null, i: s.i }; return; }
      var ii = s.i == null ? shared : s.i;
      var m = M[String(s.p)][String(ii)];
      // item result = probability of occurrence alone (article convention); P x I kept as matrix risk
      res[it.id] = { level: P3[String(s.p)], matrix: m, p: s.p, i: ii };
      if (!best || ORDER[m] > ORDER[best.matrix] || (ORDER[m] === ORDER[best.matrix] && s.p > best.p)) best = { matrix: m, p: s.p, i: ii, id: it.id };
    });
    return { items: res, overall: best ? { level: M3[best.matrix], matrix: best.matrix, from: best.id } : null };
  }
  var official = compute(trial);

  var selItem = $("wiItem"), selP = $("wiP"), selI = $("wiI"), out = $("wiOut");
  function opt(sel, value, label) { var o = el("option", null, label); o.value = value; sel.appendChild(o); }
  function fillScores(sel, labels, allowInherit) {
    sel.innerHTML = "";
    if (allowInherit) opt(sel, "", "沿用衝擊項目");
    for (var k = 1; k <= 5; k++) opt(sel, String(k), k + "（" + labels[String(k)] + "）");
  }
  function itemById(id) { for (var k = 0; k < items.length; k++) if (items[k].id === id) return items[k]; return null; }

  function syncControls() {
    var it = itemById(selItem.value); if (!it) return;
    var s = trial[it.id];
    fillScores(selP, data.pLabels, false);
    fillScores(selI, data.iLabels, it.kind === "機率" && it.inherit);
    selP.disabled = it.kind === "衝擊";
    selP.value = s.p == null ? "" : String(s.p);
    selI.value = s.i == null ? "" : String(s.i);
  }

  function badge(level) {
    var span = el("span", "lv lv-" + data.levelClass[level]);
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ic"); svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#lvicon-" + data.levelClass[level]);
    svg.appendChild(use); span.appendChild(svg); span.appendChild(el("span", null, level));
    return span;
  }

  function placeGhost(res) {
    document.querySelectorAll(".marker.ghost").forEach(function (g) { g.remove(); });
    items.forEach(function (it) {
      var r = res.items[it.id], o = official.items[it.id];
      if (it.kind !== "機率" || (r.p === o.p && r.i === o.i)) return;
      var cell = document.querySelector('.cell[data-p="' + r.p + '"][data-i="' + r.i + '"] .markers');
      if (!cell) return;
      var g = el("span", "marker ghost", String(it.n));
      g.setAttribute("title", "試算位置：" + it.name); g.setAttribute("aria-hidden", "true");
      g.style.display = "inline-grid"; g.style.placeItems = "center";
      cell.appendChild(g);
    });
  }

  function renderTrial() {
    var res = compute(trial);
    out.innerHTML = "";
    var tbl = el("table", "tbl");
    var thead = el("thead"); var hr = el("tr");
    ["項目", "正式結果", "試算結果", "變化"].forEach(function (h) { var th = el("th", null, h); th.scope = "col"; hr.appendChild(th); });
    thead.appendChild(hr); tbl.appendChild(thead);
    var tb = el("tbody");
    function cell(r, label) {
      var td = el("td");
      if (label) td.appendChild(el("span", "small muted", label + " "));
      td.appendChild(badge(r.level));
      if (r.matrix) { td.appendChild(el("span", "small", " 矩陣風險 ")); td.appendChild(badge(r.matrix)); }
      return td;
    }
    function change(a, b, what) {
      var d = ORDER[b] - ORDER[a];
      return d > 0 ? what + "▲" : d < 0 ? what + "▼" : "";
    }
    function row(name, off, trl, label) {
      var tr = el("tr");
      tr.appendChild(el("td", null, name));
      tr.appendChild(cell(off, label));
      tr.appendChild(cell(trl, label));
      var parts = [change(off.level, trl.level, label || "結果")];
      if (off.matrix && trl.matrix) parts.push(change(off.matrix, trl.matrix, "矩陣風險"));
      var txt = parts.filter(Boolean).join("　");
      tr.appendChild(el("td", "delta", txt || "＝ 不變"));
      tb.appendChild(tr);
    }
    items.forEach(function (it) {
      row(it.n + ". " + it.name, official.items[it.id], res.items[it.id], it.kind === "衝擊" ? "衝擊" : "機率");
    });
    if (res.overall && official.overall) row("綜合研判", { level: official.overall.level }, { level: res.overall.level }, "");
    tbl.appendChild(tb);
    out.appendChild(el("p", "small", "以下為試算，非正式評估結果。正式結果請見上方風險評估表。"));
    out.appendChild(tbl);
    placeGhost(res);
  }

  if (selItem && selP && selI && out) {
    items.forEach(function (it) { opt(selItem, it.id, it.n + ". " + it.name); });
    syncControls(); renderTrial();
    selItem.addEventListener("change", syncControls);
    selP.addEventListener("change", function () { trial[selItem.value].p = selP.value ? Number(selP.value) : null; renderTrial(); });
    selI.addEventListener("change", function () { trial[selItem.value].i = selI.value ? Number(selI.value) : null; renderTrial(); });
    $("wiReset").addEventListener("click", function () { resetTrial(); syncControls(); renderTrial(); });
  }

  /* ---------- recommendation filters ----------------------------------- */
  var fCat = $("fCat"), fPri = $("fPri"), fTime = $("fTime");
  function filterRecs() {
    var c = fCat.value, p = fPri.value, t = fTime.value, n = 0;
    document.querySelectorAll("#recList .rec").forEach(function (li) {
      var ok = (!c || li.dataset.cat === c) && (!p || li.dataset.pri === p) && (!t || li.dataset.time === t);
      li.hidden = !ok; if (ok) n++;
    });
    $("fCount").textContent = "顯示 " + n + " 項";
    $("recEmpty").hidden = n !== 0;
  }
  if (fCat && fPri && fTime) [fCat, fPri, fTime].forEach(function (s) { s.addEventListener("change", filterRecs); });

  /* ---------- optional time-series chart -------------------------------- */
  var ts = data.timeseries || [];
  var host = $("tsChart");
  if (host && ts.length) {
    var series = {}; ts.forEach(function (p) { (series[p.series] = series[p.series] || []).push(p); });
    var names = Object.keys(series).slice(0, 3);
    var colors = ["var(--accent)", "#eb6834", "#1baf7a"];
    var dates = Array.from(new Set(ts.map(function (p) { return p.date; }))).sort();
    var maxV = Math.max.apply(null, ts.map(function (p) { return p.value; })) || 1;
    var W = 640, H = 240, L = 44, R = 12, T = 12, B = 30;
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "病例數時間序列，資料見表格檢視");
    function x(d) { return L + (dates.length < 2 ? 0 : (W - L - R) * dates.indexOf(d) / (dates.length - 1)); }
    function y(v) { return T + (H - T - B) * (1 - v / maxV); }
    function line(x1, y1, x2, y2, stroke) { var l = document.createElementNS(NS, "line"); l.setAttribute("x1", x1); l.setAttribute("y1", y1); l.setAttribute("x2", x2); l.setAttribute("y2", y2); l.setAttribute("stroke", stroke); l.setAttribute("stroke-width", "1"); return l; }
    function text(xx, yy, s, anchor) { var t = document.createElementNS(NS, "text"); t.setAttribute("x", xx); t.setAttribute("y", yy); t.setAttribute("font-size", "11"); t.setAttribute("fill", "var(--muted)"); t.setAttribute("text-anchor", anchor || "start"); t.textContent = s; return t; }
    for (var g = 0; g <= 4; g++) { var vv = maxV * g / 4; svg.appendChild(line(L, y(vv), W - R, y(vv), "var(--grid)")); svg.appendChild(text(L - 6, y(vv) + 4, String(Math.round(vv)), "end")); }
    svg.appendChild(text(L, H - 8, dates[0])); svg.appendChild(text(W - R, H - 8, dates[dates.length - 1], "end"));
    names.forEach(function (nm, k) {
      var pts = series[nm].slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
      var path = document.createElementNS(NS, "path");
      path.setAttribute("d", pts.map(function (p, j) { return (j ? "L" : "M") + x(p.date) + "," + y(p.value); }).join(""));
      path.setAttribute("fill", "none"); path.setAttribute("stroke", colors[k]); path.setAttribute("stroke-width", "2"); path.setAttribute("stroke-linejoin", "round");
      svg.appendChild(path);
    });
    var cross = line(0, T, 0, H - B, "var(--axis)"); cross.style.display = "none"; svg.appendChild(cross);
    svg.addEventListener("pointermove", function (ev) {
      var r = svg.getBoundingClientRect(); var px = (ev.clientX - r.left) * W / r.width;
      var best = dates[0], bd = 1e9; dates.forEach(function (d) { var dd = Math.abs(x(d) - px); if (dd < bd) { bd = dd; best = d; } });
      cross.setAttribute("x1", x(best)); cross.setAttribute("x2", x(best)); cross.style.display = "";
      var parts = names.map(function (nm) { var p = series[nm].filter(function (q) { return q.date === best; })[0]; return (p ? p.value : "—") + " " + nm; });
      showTip(best + "：" + parts.join("；"), ev.clientX, ev.clientY);
    });
    svg.addEventListener("pointerleave", function () { cross.style.display = "none"; hideTip(); });
    host.appendChild(svg);
    if (names.length > 1) {
      var lg = el("div", "matrix-legend");
      names.forEach(function (nm, k) { var s = el("span", "small"); var sw = el("span"); sw.style.cssText = "display:inline-block;width:16px;height:2px;vertical-align:middle;margin-right:4px;background:" + colors[k]; s.appendChild(sw); s.appendChild(document.createTextNode(nm)); lg.appendChild(s); });
      host.appendChild(lg);
    }
  }
})();
