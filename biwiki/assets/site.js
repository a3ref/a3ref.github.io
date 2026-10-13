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

/* keep the current page visible in the side navigation (scrolls the list only, not the page) */
(function () {
  "use strict";
  var side = document.querySelector(".sidenav"), cur = side && side.querySelector("[aria-current]");
  // next frame: reading layout right after the code-block wrappers were added would force a reflow
  if (cur) requestAnimationFrame(function () { side.scrollTop = cur.offsetTop - side.offsetTop - side.clientHeight / 2; });
})();
