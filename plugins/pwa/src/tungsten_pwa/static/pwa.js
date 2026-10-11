/* Tungsten PWA: registers the service worker, shows the Install app button and the offline bar. */
(function () {
  "use strict";
  if (window.twPwa) return;
  var me = document.currentScript;
  if (!me) return;
  window.twPwa = { prompt: null };

  if ("serviceWorker" in navigator && me.dataset.sw) {
    var register = function () {
      navigator.serviceWorker.register(me.dataset.sw, { scope: me.dataset.scope, updateViaCache: "none" })
        .catch(function (err) { console.warn("Tungsten PWA: the service worker was not registered.", err); });
    };
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register);
  }

  // ------------------------------------------------------------------ install button
  function standalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
  }

  function showInstall() {
    var on = !!window.twPwa.prompt && !standalone();
    document.querySelectorAll("[data-tw-pwa-install]").forEach(function (b) { b.style.display = on ? "" : "none"; });
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    window.twPwa.prompt = e;
    showInstall();
  });
  window.addEventListener("appinstalled", function () {
    window.twPwa.prompt = null;
    showInstall();
  });
  document.addEventListener("click", function (e) {
    var button = e.target && e.target.closest ? e.target.closest("[data-tw-pwa-install]") : null;
    var prompt = window.twPwa.prompt;
    if (!button || !prompt) return;
    e.preventDefault();
    window.twPwa.prompt = null;  // a prompt can be shown only once
    showInstall();
    try {
      Promise.resolve(prompt.prompt()).catch(function () {});
    } catch (err) { /* the browser refused, e.g. the prompt was already used */ }
  });

  // ------------------------------------------------------------------ offline bar
  function showOffline() {
    var bar = document.getElementById("tw-pwa-offline");
    if (bar) bar.style.display = navigator.onLine === false ? "flex" : "none";
  }
  window.addEventListener("online", showOffline);
  window.addEventListener("offline", showOffline);

  function refresh() { showInstall(); showOffline(); }
  // with the SPA mode on, HTMX swaps the page body: show the button and bar again on the new body
  document.addEventListener("htmx:afterSettle", refresh);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", refresh);
  else refresh();
})();
