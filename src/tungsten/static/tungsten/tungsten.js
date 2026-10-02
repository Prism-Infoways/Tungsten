/* Translations for strings shown by this script (filled by the layout). */
window.twT = function (text) { return (window.twLang && window.twLang[text]) || text; };
/* Tungsten client glue: toasts, theme, charts, selects, rich editor. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ Alpine stores
  document.addEventListener("alpine:init", function () {
    var Alpine = window.Alpine;

    Alpine.store("theme", {
      mode: "system",
      init: function () {
        try { this.mode = localStorage.getItem("tw-theme") || document.documentElement.dataset.defaultTheme || "system"; } catch (e) {}
        var self = this;
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { self.apply(); });
      },
      set: function (mode) {
        this.mode = mode;
        try { localStorage.setItem("tw-theme", mode); } catch (e) {}
        this.apply();
        document.dispatchEvent(new CustomEvent("tw-theme-changed"));
      },
      apply: function () {
        var dark = this.mode === "dark" || (this.mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
        document.documentElement.classList.toggle("dark", dark);
      },
    });

    var TONES = {
      success: "bg-success-50 text-success-600 dark:bg-success-500/10 dark:text-success-400",
      danger: "bg-danger-50 text-danger-600 dark:bg-danger-500/10 dark:text-danger-400",
      warning: "bg-warning-50 text-warning-600 dark:bg-warning-500/10 dark:text-warning-400",
      info: "bg-info-50 text-info-600 dark:bg-info-500/10 dark:text-info-400",
      primary: "bg-primary-50 text-primary-600 dark:bg-primary-500/10 dark:text-primary-400",
      gray: "bg-gray-100 text-gray-600 dark:bg-white/5 dark:text-gray-400",
    };
    var nextId = 1;

    Alpine.store("toasts", {
      items: [],
      init: function (initial) {
        var self = this;
        (initial || []).forEach(function (t) { self.push(t); });
      },
      push: function (t) {
        var self = this;
        var toast = Object.assign({ id: nextId++, visible: true, color: t.status || "gray" }, t);
        this.items.push(toast);
        if (toast.duration !== null && toast.duration !== undefined) {
          setTimeout(function () { self.dismiss(toast.id); }, toast.duration || 5000);
        }
      },
      dismiss: function (id) {
        var self = this;
        var t = this.items.find(function (x) { return x.id === id; });
        if (t) t.visible = false;
        setTimeout(function () { self.items = self.items.filter(function (x) { return x.id !== id; }); }, 200);
      },
      tone: function (color) { return TONES[color] || TONES.gray; },
      icon: function (name) {
        var tpl = document.getElementById("tw-toast-icons");
        if (!tpl) return "";
        var el = tpl.content.querySelector('[data-icon="' + name + '"]') || tpl.content.querySelector('[data-icon="bell"]');
        return el ? el.innerHTML : "";
      },
    });
  });

  window.twToast = function (t) {
    if (window.Alpine) window.Alpine.store("toasts").push(t);
  };

  // HX-Trigger: {"tw-notify": [ ... ]}
  document.addEventListener("tw-notify", function (e) {
    var list = Array.isArray(e.detail) ? e.detail : (e.detail && e.detail.value) || [];
    if (!Array.isArray(list)) list = [list];
    list.forEach(function (t) { window.twToast(t); });
  });

  // ------------------------------------------------------------------ htmx errors
  document.addEventListener("htmx:responseError", function (e) {
    var status = e.detail.xhr ? e.detail.xhr.status : 0;
    var title = status === 419 ? twT("Page expired") : status === 403 ? twT("Not allowed") : twT("Something went wrong");
    var body = status === 419 ? twT("Please refresh the page and try again.") : twT("The server could not complete the request (:status).").replace(":status", status);
    window.twToast({ title: title, body: body, status: "danger", icon: "circle-x", duration: 6000 });
  });
  document.addEventListener("htmx:sendError", function () {
    window.twToast({ title: twT("Connection lost"), body: twT("Check your internet connection."), status: "danger", icon: "circle-x" });
  });

  // ------------------------------------------------------------------ components
  function cssColor(name, shade, alpha) {
    var v = getComputedStyle(document.documentElement).getPropertyValue("--tw-c-" + name + "-" + (shade || 500)).trim();
    if (!v) v = getComputedStyle(document.documentElement).getPropertyValue("--tw-c-primary-500").trim();
    return alpha === undefined ? "rgb(" + v + ")" : "rgb(" + v + " / " + alpha + ")";
  }

  function merge(target, source) {
    Object.keys(source || {}).forEach(function (k) {
      var v = source[k];
      if (v && typeof v === "object" && !Array.isArray(v)) {
        target[k] = merge(target[k] && typeof target[k] === "object" ? target[k] : {}, v);
      } else {
        target[k] = v;
      }
    });
    return target;
  }

  function initChart(canvas) {
    if (!window.Chart || canvas._twChart) return;
    var cfg;
    try { cfg = JSON.parse(canvas.getAttribute("data-tw-chart")); } catch (e) { return; }
    var dark = document.documentElement.classList.contains("dark");
    var round = ["pie", "doughnut", "polarArea"].indexOf(cfg.type) !== -1;
    (cfg.data.datasets || []).forEach(function (ds) {
      var type = ds.type || cfg.type;
      if (ds.colors) {
        ds.backgroundColor = ds.colors.map(function (c) { return cssColor(c, 500); });
        ds.borderColor = dark ? "rgb(24 24 27)" : "#fff";
        ds.borderWidth = 2;
      } else {
        var c = ds.color || "primary";
        ds.borderColor = cssColor(c, 500);
        if (type === "bar") {
          ds.backgroundColor = cssColor(c, 500, 0.85);
          ds.borderRadius = ds.borderRadius === undefined ? 6 : ds.borderRadius;
          ds.borderWidth = 0;
          ds.maxBarThickness = ds.maxBarThickness || 28;
        } else {
          ds.backgroundColor = cssColor(c, 500, 0.12);
          ds.fill = ds.fill === undefined ? true : ds.fill;
          ds.tension = ds.tension === undefined ? 0.35 : ds.tension;
          ds.pointRadius = ds.pointRadius === undefined ? 3 : ds.pointRadius;
          ds.pointBackgroundColor = "#fff";
          ds.borderWidth = 2;
        }
      }
      delete ds.color; delete ds.colors;
    });
    var grid = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
    var text = dark ? "#a1a1aa" : "#71717a";
    var options = {
      maintainAspectRatio: false,
      responsive: true,
      interaction: { intersect: false, mode: round ? "nearest" : "index" },
      plugins: {
        legend: { display: !round || !canvas.closest("section").querySelector("ul"), position: round ? "bottom" : "top", align: "end",
                  labels: { usePointStyle: true, boxWidth: 8, color: text } },
        tooltip: { backgroundColor: "#18181b", padding: 10, cornerRadius: 8, boxPadding: 4 },
      },
      cutout: cfg.type === "doughnut" ? "68%" : undefined,
      scales: round ? {} : {
        x: { grid: { display: false }, ticks: { color: text }, border: { display: false } },
        y: { grid: { color: grid }, ticks: { color: text }, border: { display: false }, beginAtZero: true },
        y1: { display: false },
      },
    };
    canvas._twChart = new window.Chart(canvas, { type: cfg.type, data: cfg.data, options: merge(options, cfg.options || {}) });
  }

  function initSelect(el) {
    if (!window.TomSelect || el.tomselect) return;
    var remote = el.getAttribute("data-search-url");
    var settings = {
      plugins: el.multiple ? ["remove_button"] : [],
      allowEmptyOption: !el.multiple,
      maxOptions: 200,
      placeholder: el.getAttribute("data-placeholder") || "",
      wrapperClass: "ts-wrapper tw-ts",
      controlInput: el.getAttribute("data-searchable") === "false" && !el.multiple ? null : undefined,
    };
    if (settings.controlInput === undefined) delete settings.controlInput;
    if (remote) {
      settings.valueField = "value";
      settings.labelField = "text";
      settings.searchField = ["text"];
      settings.load = function (query, callback) {
        var form = el.closest("form");
        var data = form ? new FormData(form) : new FormData();
        data.set("_tw_field", el.getAttribute("data-field"));
        data.set("q", query);
        var token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"];
        fetch(remote, { method: "POST", body: data, headers: { "X-CSRF-Token": token, "HX-Request": "true" } })
          .then(function (r) { return r.json(); }).then(callback).catch(function () { callback(); });
      };
    }
    // TomSelect fires "change" on the original <select>, which htmx listens to
    new window.TomSelect(el, settings);
  }

  function initRichEditor(editor) {
    var liveId = editor.getAttribute("data-tw-live");
    if (!liveId || editor._twLive) return;
    editor._twLive = true;
    var timer;
    var changed = false;
    function send() {
      var input = document.getElementById(liveId);
      if (input) input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (editor.hasAttribute("data-tw-live-blur")) {
      // live(on_blur=True): refresh when the user leaves the editor
      editor.addEventListener("trix-change", function () { changed = true; });
      editor.addEventListener("trix-blur", function () { if (changed) { changed = false; send(); } });
      return;
    }
    var delay = parseInt(editor.getAttribute("data-tw-live-delay"), 10) || 600;
    editor.addEventListener("trix-change", function () {
      clearTimeout(timer);
      timer = setTimeout(send, delay);
    });
  }

  function initSortable(tbody) {
    if (!window.Sortable || tbody._twSortable) return;
    tbody._twSortable = window.Sortable.create(tbody, {
      handle: ".tw-drag-handle",
      animation: 150,
      ghostClass: "opacity-40",
      onEnd: function () {
        var keys = Array.prototype.map.call(tbody.querySelectorAll("tr[data-key]"), function (tr) { return tr.dataset.key; });
        window.htmx.ajax("POST", tbody.dataset.twSortable, { values: { host: tbody.dataset.host, keys: keys }, swap: "none", source: tbody });
      },
    });
  }

  function initQr(el) {
    if (!window.qrcode || el._twQr) return;
    el._twQr = true;
    var qr = window.qrcode(0, "M");
    qr.addData(el.getAttribute("data-tw-qr"));
    qr.make();
    el.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
    el.firstChild.setAttribute("class", "h-44 w-44");
  }

  function init(root) {
    root.querySelectorAll("[data-tw-qr]").forEach(initQr);
    root.querySelectorAll("tbody[data-tw-sortable]").forEach(initSortable);
    root.querySelectorAll("canvas[data-tw-chart]").forEach(initChart);
    root.querySelectorAll("select[data-tw-select]").forEach(initSelect);
    root.querySelectorAll("trix-editor[data-tw-live]").forEach(initRichEditor);
  }

  function boot() {
    init(document);
    if (window.htmx) {
      window.htmx.onLoad(function (el) { if (el && el.querySelectorAll) init(el); });
    }
  }

  // libraries load with `defer`; wait for all of them
  if (document.readyState === "complete") boot();
  else window.addEventListener("load", boot);

  // redraw charts when the theme changes (colors differ)
  document.addEventListener("tw-theme-changed", function () {
    document.querySelectorAll("canvas[data-tw-chart]").forEach(function (c) {
      if (c._twChart) { c._twChart.destroy(); c._twChart = null; }
      initChart(c);
    });
  });

  // ------------------------------------------------------------------ sidebar collapse (desktop)
  window.twToggleSidebar = function () {
    var collapsed = document.documentElement.classList.toggle("tw-sidebar-collapsed");
    try { localStorage.setItem("tw-sidebar", collapsed ? "collapsed" : "open"); } catch (e) {}
  };

  // ------------------------------------------------------------------ keyboard shortcuts
  // Any element with data-tw-keys="mod+s" (mod = Ctrl on Windows/Linux, Cmd on Mac) is clicked.
  function comboOf(e) {
    var parts = [];
    if (e.ctrlKey || e.metaKey) parts.push("mod");
    if (e.altKey) parts.push("alt");
    if (e.shiftKey) parts.push("shift");
    parts.push((e.key || "").toLowerCase());
    return parts.join("+");
  }
  document.addEventListener("keydown", function (e) {
    if (!e.ctrlKey && !e.metaKey && !e.altKey) return;
    var combo = comboOf(e);
    var target = Array.prototype.find.call(document.querySelectorAll("[data-tw-keys]"), function (el) {
      return el.getAttribute("data-tw-keys").toLowerCase().split(",").map(function (k) { return k.trim(); })
        .indexOf(combo) !== -1 && el.offsetParent !== null;
    });
    if (target) { e.preventDefault(); target.click(); }
  });

  // ------------------------------------------------------------------ global search: arrow keys
  document.addEventListener("keydown", function (e) {
    var results = document.getElementById("tw-search-results");
    if (!results || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    var input = document.querySelector("input[name=q]");
    var links = Array.prototype.slice.call(results.querySelectorAll("a"));
    if (!links.length) return;
    var i = links.indexOf(document.activeElement);
    if (document.activeElement !== input && i === -1) return;
    e.preventDefault();
    if (e.key === "ArrowDown") (links[i + 1] || links[0]).focus();
    else if (i <= 0) input.focus();
    else links[i - 1].focus();
  });

  // ------------------------------------------------------------------ unsaved changes
  var dirty = false;
  function alertsOn() { return document.body && document.body.getAttribute("data-tw-unsaved-alerts") === "true"; }
  document.addEventListener("input", function (e) {
    if (e.target.closest && e.target.closest("form[data-tw-unsaved]") && !e.target.closest("[data-tw-local]")) dirty = true;
  });
  document.addEventListener("change", function (e) {
    if (e.target.closest && e.target.closest("form[data-tw-unsaved]") && !e.target.closest("[data-tw-local]")) dirty = true;
  });
  document.addEventListener("submit", function (e) {
    if (e.target.matches && e.target.matches("form[data-tw-unsaved]")) dirty = false;
  }, true);
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail.elt && e.detail.elt.closest && e.detail.elt.closest("form[data-tw-unsaved]");
    if (form && e.detail.requestConfig && e.detail.requestConfig.verb === "post" && e.detail.elt === form && e.detail.successful) dirty = false;
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty && alertsOn()) { e.preventDefault(); e.returnValue = ""; }
  });
  document.addEventListener("htmx:beforeRequest", function (e) {
    // boosted navigation away from a changed form (SPA mode)
    if (dirty && alertsOn() && e.detail.boosted && !(e.detail.elt.closest && e.detail.elt.closest("form[data-tw-unsaved]"))) {
      if (!window.confirm(twT("You have unsaved changes. Leave this page?"))) e.preventDefault();
      else dirty = false;
    }
  });
  document.addEventListener("htmx:afterSettle", function (e) {
    if (e.detail.boosted) dirty = false;
  });

  // Trix: block file attachments (uploads go through FileUpload fields)
  document.addEventListener("trix-file-accept", function (e) { e.preventDefault(); });
})();
