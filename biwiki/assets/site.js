/* Arma 3 scripting reference: terrain masthead, search, copy buttons. No dependencies. */
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";

  /* ---- terrain: contour lines seeded by the page title, so every page has its own map ---- */

  function hash(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function rng(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function closedPath(pts) {
    // Catmull-Rom through the points, as cubic Béziers
    var n = pts.length, d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
    for (var i = 0; i < n; i++) {
      var p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      d += "C" + (p1[0] + (p2[0] - p0[0]) / 6).toFixed(1) + " " + (p1[1] + (p2[1] - p0[1]) / 6).toFixed(1) + " " +
        (p2[0] - (p3[0] - p1[0]) / 6).toFixed(1) + " " + (p2[1] - (p3[1] - p1[1]) / 6).toFixed(1) + " " +
        p2[0].toFixed(1) + " " + p2[1].toFixed(1);
    }
    return d + "Z";
  }
  function terrain(el, seedText) {
    var W = 1200, H = 340, rand = rng(hash(seedText));
    var hills = 2 + Math.floor(rand() * 2), paths = [];
    for (var h = 0; h < hills; h++) {
      var cx = W * (0.5 + rand() * 0.55), cy = H * (0.1 + rand() * 0.8);
      var rings = 6 + Math.floor(rand() * 8), step = 14 + rand() * 10;
      var shape = [], detail = [];
      for (var w = 0; w < 3; w++) shape.push([2 + w, rand() * Math.PI * 2, 0.04 + rand() * 0.07]);
      for (w = 0; w < 2; w++) detail.push([5 + Math.floor(rand() * 4), rand() * Math.PI * 2]);
      var sx = 1.2 + rand() * 0.9, tilt = rand() * Math.PI;
      for (var r = 1; r <= rings; r++) {
        var pts = [], rad = r * step;
        for (var k = 0; k < 40; k++) {
          var a = (k / 40) * Math.PI * 2, f = 1;
          // one shared shape for every ring keeps them nested; a little per-ring detail keeps them natural
          for (w = 0; w < shape.length; w++) f += shape[w][2] * Math.sin(shape[w][0] * a + shape[w][1]);
          for (w = 0; w < detail.length; w++) f += 0.012 * Math.sin(detail[w][0] * a + detail[w][1] + r * 0.9);
          var x = Math.cos(a) * rad * f * sx, y = Math.sin(a) * rad * f;
          pts.push([cx + x * Math.cos(tilt) - y * Math.sin(tilt) * 0.35, cy + x * Math.sin(tilt) * 0.35 + y * Math.cos(tilt)]);
        }
        paths.push('<path d="' + closedPath(pts) + '"' + (r % 5 === 0 ? ' class="index"' : "") + "/>");
      }
    }
    el.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMaxYMid slice">' +
      '<g fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke" opacity=".7">' +
      paths.join("").replace(/class="index"/g, 'stroke-width="2"') + "</g></svg>";
  }
  var t = document.querySelector(".terrain"), h1 = document.querySelector("h1");
  if (t && h1) terrain(t, h1.textContent);

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
        return { name: e[0], kind: e[1], path: e[2], sum: e[3], n: n, short: n.replace(/^[a-z0-9]+_fnc_/, ""), s: e[3].toLowerCase() };
      });
      loading.splice(0).forEach(function (f) { f(); });
    };
    document.head.appendChild(s);
  }

  function rank(q) {
    var words = q.split(/\s+/).filter(Boolean), out = [];
    for (var i = 0; i < index.length; i++) {
      var e = index[i], sc = -1, at;
      if (e.n === q || e.short === q) sc = 0;
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

  function initSearch(box) {
    var input = box.querySelector("input"), list = box.querySelector(".results"), active = -1, items = [];

    function render() {
      var q = input.value.trim().toLowerCase();
      if (!q) { list.hidden = true; return; }
      items = rank(q);
      active = items.length ? 0 : -1;
      list.innerHTML = items.length ? items.map(function (e, i) {
        return '<li role="option" id="r' + i + '"' + (i === 0 ? ' aria-selected="true"' : "") + ' class="' + (e.kind === "f" ? "r-fn" : "r-cmd") + '">' +
          '<a href="' + root + e.path + '.html"><span class="r-name">' + esc(e.name) + '</span>' +
          '<span class="r-kind">' + (e.kind === "f" ? "function" : "command") + "</span>" +
          (e.sum ? '<span class="r-sum">' + esc(e.sum) + "</span>" : "") + "</a></li>";
      }).join("") : '<li class="r-empty">Nothing matches “' + esc(input.value.trim()) + '”. Try part of the name, e.g. “vehicle”.</li>';
      list.hidden = false;
    }
    function move(d) {
      if (!items.length) return;
      var lis = list.querySelectorAll("[role=option]");
      lis[active].removeAttribute("aria-selected");
      active = (active + d + items.length) % items.length;
      lis[active].setAttribute("aria-selected", "true");
      lis[active].scrollIntoView({ block: "nearest" });
    }
    input.addEventListener("focus", function () { loadIndex(render); });
    input.addEventListener("input", function () { loadIndex(render); });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown") { ev.preventDefault(); move(1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); move(-1); }
      else if (ev.key === "Enter" && active > -1) { location.href = root + items[active].path + ".html"; }
      else if (ev.key === "Escape") { list.hidden = true; input.blur(); }
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

  var pres = document.querySelectorAll("pre.code");
  for (i = 0; i < pres.length; i++) {
    (function (pre) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "copy"; b.textContent = "Copy";
      b.addEventListener("click", function () {
        var text = pre.querySelector("code").innerText;
        (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
          b.textContent = "Copied";
        }, function () { b.textContent = "Select and copy"; });
        setTimeout(function () { b.textContent = "Copy"; }, 1600);
      });
      pre.appendChild(b);
    })(pres[i]);
  }
})();
