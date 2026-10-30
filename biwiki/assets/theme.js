/* Theme choice: loaded blocking in <head>, so the stored choice is on <html> before the first paint.
   No choice (Auto) leaves the theme to prefers-color-scheme; site.js draws the switcher and calls window.a3theme. */
(function () {
  "use strict";
  var doc = document.documentElement;
  // Scripts run: style.css shows the side column folded as site.js will leave it, so nothing shifts when it does.
  doc.classList.add("js");
  var KEY = "theme";
  function stored() {
    try { var t = localStorage.getItem(KEY); return t === "light" || t === "dark" ? t : ""; } catch (e) { return ""; }
  }
  // "" is Auto. The theme-color metas keep their media queries for Auto; a forced theme switches one on for all.
  function apply(t) {
    if (t) doc.setAttribute("data-theme", t); else doc.removeAttribute("data-theme");
    var cs = document.querySelector('meta[name="color-scheme"]');
    if (cs) cs.setAttribute("content", t || "light dark");
    var metas = document.querySelectorAll('meta[name="theme-color"][data-scheme]');
    for (var i = 0; i < metas.length; i++) {
      var m = metas[i], s = m.getAttribute("data-scheme");
      m.setAttribute("media", t ? (t === s ? "all" : "not all") : "(prefers-color-scheme: " + s + ")");
    }
  }
  var current = stored();
  window.a3theme = {
    get: function () { return current; },
    set: function (t) {
      current = t;
      // without storage (blocked cookies) the choice still holds for this page
      try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch (e) { /* not stored */ }
      apply(t);
    }
  };
  if (current) apply(current);
})();
