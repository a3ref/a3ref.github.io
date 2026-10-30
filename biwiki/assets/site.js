/* Arma 3 scripting reference: search, copy buttons, side navigation. No dependencies. */
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";

  /* ---- search ------------------------------------------------------------------------------- */

  var index = null, loading = [];
  function loadIndex(cb) {
    if (index) return cb();
    loading.push(cb);
    if (loading.length > 1) return;
    var s = document.createElement("script");
    s.src = root + "assets/search-index.js";
    s.onload = function () {
      index = (window.BIWIKI_INDEX || []).map(function (e) {
        var n = e[0].toLowerCase();
        return { name: e[0], kind: e[1], path: e[2], sum: e[3], op: e[4] || "", n: n, short: n.replace(/^[a-z0-9]+_fnc_/, ""), s: e[3].toLowerCase() };
      });
      loading.splice(0).forEach(function (f) { f(); });
    };
    document.head.appendChild(s);
  }

  function rank(q) {
    var words = q.split(/\s+/).filter(Boolean), out = [];
    for (var i = 0; i < index.length; i++) {
      var e = index[i], sc = -1, at;
      if (e.n === q || e.short === q || e.op === q) sc = 0;
      else if (e.n.indexOf(q) === 0) sc = 1 + e.n.length / 1000;
      else if (e.short.indexOf(q) === 0) sc = 1.5 + e.n.length / 1000;
      else if ((at = e.n.indexOf(q)) > -1) sc = 2 + at / 100;
      else if (words.length && words.every(function (w) { return e.n.indexOf(w) > -1 || e.s.indexOf(w) > -1; })) sc = e.s.indexOf(q) > -1 ? 4 : 5;
      if (sc >= 0) out.push([sc, e]);
    }
    out.sort(function (a, b) { return a[0] - b[0] || a[1].n.length - b[1].n.length; });
    return out.slice(0, 15).map(function (x) { return x[1]; });
  }

  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  // Results are a plain list of links: arrow keys move focus between the input and the links, the count is
  // announced through a live region. Simpler and better supported than a listbox/combobox widget.
  function initSearch(box) {
    var input = box.querySelector("input"), list = box.querySelector(".results"), items = [];
    var status = document.getElementById(input.id + "-status");

    function render() {
      var q = input.value.trim().toLowerCase();
      if (!q) { list.hidden = true; if (status) status.textContent = ""; return; }
      items = rank(q);
      list.innerHTML = items.length ? items.map(function (e) {
        return '<li class="' + (e.kind === "f" ? "r-fn" : "r-cmd") + '">' +
          '<a href="' + root + e.path + '.html"><span class="r-name">' + esc(e.name) + '</span>' +
          '<span class="r-kind">' + ({ f: "function", t: "topic" }[e.kind] || "command") + "</span>" +
          (e.sum ? '<span class="r-sum">' + esc(e.sum) + "</span>" : "") + "</a></li>";
      }).join("") : '<li class="r-empty">Nothing matches “' + esc(input.value.trim()) + '”. Try part of the name, e.g. “vehicle”.</li>';
      list.hidden = false;
      if (status) status.textContent = items.length ? items.length + " results" : "No results";
    }
    function links() { return Array.prototype.slice.call(list.querySelectorAll("a")); }
    function focusAt(i) {
      var all = links();
      if (i < 0) { input.focus(); return; }
      if (all.length) all[Math.min(i, all.length - 1)].focus();
    }
    input.addEventListener("focus", function () { loadIndex(render); });
    input.addEventListener("input", function () { loadIndex(render); });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown") { ev.preventDefault(); focusAt(0); }
      else if (ev.key === "Enter" && items.length) { location.href = root + items[0].path + ".html"; }
      else if (ev.key === "Escape") { list.hidden = true; }
    });
    list.addEventListener("keydown", function (ev) {
      var i = links().indexOf(document.activeElement);
      if (ev.key === "ArrowDown") { ev.preventDefault(); focusAt(i + 1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); focusAt(i - 1); }
      else if (ev.key === "Escape") { list.hidden = true; input.focus(); }
    });
    document.addEventListener("click", function (ev) { if (!box.contains(ev.target)) list.hidden = true; });
  }
  var boxes = document.querySelectorAll(".search");
  for (var i = 0; i < boxes.length; i++) initSearch(boxes[i]);

  document.addEventListener("keydown", function (ev) {
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (ev.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && !ev.ctrlKey && !ev.metaKey) {
      ev.preventDefault();
      (document.querySelector(".search-hero input") || document.querySelector(".search input")).focus();
    }
  });

  /* ---- copy buttons on code blocks ----------------------------------------------------------- */

  // The button sits in a wrapper around the <pre>, not in it: the <pre> scrolls sideways and would take
  // the button along. The wrapper has no margin, padding or border, so the layout does not move.
  var pres = document.querySelectorAll("pre.code");
  for (i = 0; i < pres.length; i++) {
    (function (pre) {
      var wrap = document.createElement("div");
      wrap.className = "code-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      var b = document.createElement("button");
      b.type = "button"; b.className = "copy"; b.textContent = "Copy";
      b.addEventListener("click", function () {
        var text = pre.querySelector("code").innerText;
        (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
          b.textContent = "Copied";
        }, function () { b.textContent = "Select and copy"; });
        setTimeout(function () { b.textContent = "Copy"; }, 1600);
      });
      wrap.appendChild(b);
    })(pres[i]);
  }
})();

/* ---- theme switcher: Auto, Light, Dark (theme.js applies and stores the choice) --------------------- */
(function () {
  "use strict";
  var b = document.getElementById("theme-switch"), theme = window.a3theme;
  if (!b || !theme) return;
  var order = ["", "light", "dark"], names = { "": "Auto", light: "Light", dark: "Dark" };
  function label(t) {
    var name = "Theme: " + names[t];
    b.setAttribute("aria-label", name);
    b.title = name;
  }
  b.addEventListener("click", function () {
    var t = order[(order.indexOf(theme.get()) + 1) % order.length];
    theme.set(t);
    label(t);
  });
  label(theme.get());
  b.hidden = false;
})();

/* ---- side column: folding sections, current page, section being read ---------------------------- */
(function () {
  "use strict";
  // Open on wide screens, folded on narrow ones, where the column sits above the page. The HTML ships them
  // open, so without scripts nothing is hidden; with scripts, style.css already shows them folded from the first
  // paint (html.js, set by theme.js), and this only makes the buttons and [hidden] agree.
  var mq = window.matchMedia("(max-width: 900px)");
  var btns = document.querySelectorAll("button.fold[aria-controls]");
  function set(b, open) {
    b.setAttribute("aria-expanded", open ? "true" : "false");
    document.getElementById(b.getAttribute("aria-controls")).hidden = !open;
  }
  function reset() { for (var i = 0; i < btns.length; i++) set(btns[i], !mq.matches); }
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener("click", function () { set(this, this.getAttribute("aria-expanded") !== "true"); });
  }
  if (mq.matches) reset();
  if (mq.addEventListener) mq.addEventListener("change", reset);

  // The page list scrolls on its own: bring the current page into view, once. Next frame: reading layout right
  // after the code-block wrappers were added would force a reflow.
  var body = document.getElementById("side-body"), cur = body && body.querySelector("[aria-current]");
  if (cur && !mq.matches) requestAnimationFrame(function () {
    body.scrollTop += cur.getBoundingClientRect().top - body.getBoundingClientRect().top - body.clientHeight / 2;
  });

  // The column is fixed beside the page: once the footer scrolls into view, end the column above it (--foot
  // shortens its max-height; its top never moves, so nothing shakes).
  var side = document.querySelector(".frame-one > .side"), foot = document.querySelector(".footer"), footPending = false;
  function fitSide() {
    footPending = false;
    var over = mq.matches ? 0 : Math.max(0, Math.ceil(window.innerHeight - foot.getBoundingClientRect().top + 16));
    side.style.setProperty("--foot", over + "px");
  }
  if (side && foot) {
    window.addEventListener("scroll", function () { if (!footPending) { footPending = true; requestAnimationFrame(fitSide); } }, { passive: true });
    window.addEventListener("resize", fitSide);
    fitSide();
  }

  // Contents subsections fold. The HTML ships them open, so without scripts nothing is hidden; here they fold
  // to the top level and open only by their own toggles. As in the wiki's contents, reading never opens a
  // branch: a folded branch holding the section being read marks its own entry instead (style.css).
  var tocBtns = document.querySelectorAll("button.toc-fold[aria-controls]");
  function setBranch(b, open) {
    b.setAttribute("aria-expanded", open ? "true" : "false");
    document.getElementById(b.getAttribute("aria-controls")).hidden = !open;
  }
  for (i = 0; i < tocBtns.length; i++) {
    setBranch(tocBtns[i], false);
    tocBtns[i].addEventListener("click", function () { setBranch(this, this.getAttribute("aria-expanded") !== "true"); });
  }
  // The buttons and [hidden] now say what style.css showed before this script ran (html.js); from here on they rule.
  document.documentElement.classList.add("js-ready");

  // Keep the entry being read in view in a contents list taller than its box: the entry itself, or the entry of
  // the folded branch holding it.
  var tocList = document.getElementById("toc-list");
  function reveal(a) {
    if (!a || !tocList || tocList.scrollHeight <= tocList.clientHeight) return;
    var t = a;
    for (var ol = a.closest("ol[hidden]"); ol; ol = t.closest("ol[hidden]")) t = ol.parentNode.children[0];
    var box = tocList.getBoundingClientRect(), r = t.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom) tocList.scrollTop += r.top - box.top - tocList.clientHeight / 3;
  }

  // Mark the contents entry of the section being read. The scroll handler only reads positions, once per
  // frame, and touches the DOM only when the section changes; then it may scroll the contents list, never the page.
  var links = document.querySelectorAll('.toc a[href^="#"]'), heads = [], byId = {}, current = null, pending = false;
  for (i = 0; i < links.length; i++) {
    var h = document.getElementById(decodeURIComponent(links[i].getAttribute("href").slice(1)));
    if (h) { heads.push(h); byId[h.id] = links[i]; }
  }
  if (!heads.length) return;
  var line = (parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 72) + 24;
  function update() {
    pending = false;
    var pick = null;
    for (var j = 0; j < heads.length; j++) { if (heads[j].getBoundingClientRect().top <= line) pick = heads[j]; else break; }
    var a = pick ? byId[pick.id] : null;
    if (a === current) return;
    if (current) current.removeAttribute("aria-current");
    current = a;
    if (a) a.setAttribute("aria-current", "location");
    reveal(a);
  }
  window.addEventListener("scroll", function () { if (!pending) { pending = true; requestAnimationFrame(update); } }, { passive: true });
  requestAnimationFrame(update);
})();
