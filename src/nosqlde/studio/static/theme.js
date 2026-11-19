// Pick the theme before first paint: ?theme=dark|light, then a saved choice, then the OS.
(function () {
  var t = null;
  try { t = new URLSearchParams(location.search).get("theme"); } catch (e) {}
  if (!t) { try { t = localStorage.getItem("nosql-studio-theme"); } catch (e) {} }
  if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
})();
