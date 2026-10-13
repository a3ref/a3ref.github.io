/* GitHub Pages serves 404.html for every missing path: send people to the page they most likely meant
   (names are case-insensitive in SQF, URLs are not). Agents, which do not run scripts, read the page text. */
(function () {
  "use strict";
  var m = location.pathname.match(/\/(commands|functions|topics)\/([^\/]+?)(\.(md|json|html))?$/i);
  if (!m) return;
  var s = document.createElement("script");
  s.src = "/assets/search-index.js";
  s.onload = function () {
    var want = decodeURIComponent(m[2]).toLowerCase(), kind = m[1].toLowerCase(), ext = (m[4] || "html").toLowerCase();
    var hit = (window.BIWIKI_INDEX || []).find(function (e) {
      return e[2].toLowerCase() === kind + "/" + want || e[0].toLowerCase() === want;
    });
    if (hit) location.replace("/" + hit[2] + "." + ext);
  };
  document.head.appendChild(s);
})();
