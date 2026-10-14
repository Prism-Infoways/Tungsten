/* Translations for strings shown by this script (filled by the layout). */
window.twT = function (text) { return (window.twLang && window.twLang[text]) || text; };
/* Tungsten client glue: toasts, theme, charts, selects, rich editor. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ on-demand libraries
  // Big libraries (charts, rich editor, ...) load only on pages that use them.
  var vendor = {};
  try { vendor = JSON.parse(document.currentScript.getAttribute("data-tw-vendor") || "{}"); } catch (e) {}
  var loaded = {};
  function loadFile(name) {
    if (!loaded[name]) {
      loaded[name] = new Promise(function (resolve, reject) {
        var url = vendor[name];
        if (!url) return reject(new Error("unknown asset " + name));
        var el;
        if (/\.css$/.test(name)) {
          el = document.createElement("link");
          el.rel = "stylesheet";
          el.href = url;
        } else {
          el = document.createElement("script");
          el.src = url;
        }
        el.onload = function () { resolve(); };
        el.onerror = function () { delete loaded[name]; reject(new Error("could not load " + name)); };
        document.head.appendChild(el);
      });
    }
    return loaded[name];
  }
  var LIBS = {
    chart: { files: ["chart.umd.min.js"], ready: function () { return window.Chart; } },
    trix: { files: ["trix.css", "trix.umd.min.js"], ready: function () { return window.Trix; } },
    select: { files: ["tom-select.css", "tom-select.complete.min.js"], ready: function () { return window.TomSelect; } },
    sortable: { files: ["sortable.min.js"], ready: function () { return window.Sortable; } },
    qr: { files: ["qrcode.js"], ready: function () { return window.qrcode; } },
  };
  // twNeed("chart").then(...) — also handy for plugins
  window.twNeed = function (lib) {
    var def = LIBS[lib];
    if (!def) return Promise.reject(new Error("unknown library " + lib));
    if (def.ready()) return Promise.resolve();
    return Promise.all(def.files.map(loadFile));
  };
  // run `fn` on every match of `selector` inside `root`, after `lib` has loaded
  function withLib(root, selector, lib, fn) {
    var found = root.querySelectorAll(selector);
    if (!found.length) return;
    window.twNeed(lib).then(function () { found.forEach(fn); }, function (e) { console.error(e); });
  }

  // ------------------------------------------------------------------ Alpine stores
  document.addEventListener("alpine:init", function () {
    var Alpine = window.Alpine;

    Alpine.store("theme", {
      mode: "system",
      // Panel(dark_mode=False): always light, whatever the OS or a stored choice says
      allowed: document.documentElement.dataset.darkMode !== "false",
      init: function () {
        this.mode = document.documentElement.dataset.defaultTheme || "system";
        try { this.mode = localStorage.getItem("tw-theme") || this.mode; } catch (e) {}
        if (!this.allowed) return;
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
        var dark = this.allowed && (this.mode === "dark" || (this.mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches));
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

    // ui.dropdown(): while open, the panel floats next to the trigger (floatPanel below)
    Alpine.data("twDropdown", function (align) {
      return {
        open: false,
        init: function () {
          var root = this.$el, panel = this.$refs.panel, unfloat = function () {};
          this.$watch("open", function (open) {
            unfloat();
            unfloat = open ? floatPanel(panel, root, align) : function () {};
          });
        },
      };
    });
  });

  // ------------------------------------------------------------------ floating panels
  // An open dropdown panel goes to the browser's top layer (popover="manual") and is placed next to its
  // trigger here, so a table's scroll box or a card's overflow-hidden can't cut it off. It opens upwards
  // when there is more room above, scrolls inside when it fits neither way, and follows the trigger on
  // scroll and resize. Browsers without popovers keep the plain absolute panel. Returns a function that
  // puts the panel back.
  function floatPanel(panel, anchor, align) {
    if (!("popover" in panel) || !panel.isConnected) return function () {};
    var pad = 8, gap = 8;
    function place() {
      if (!panel.isConnected || !panel.matches(":popover-open")) return unfloat();
      var t = anchor.getBoundingClientRect();
      if (panel.classList.contains("w-full")) panel.style.width = t.width + "px"; // as wide as the trigger
      var w = panel.offsetWidth;
      if (!w) return; // x-show has not shown it yet; the ResizeObserver calls again when it does
      var h = panel.scrollHeight + panel.offsetHeight - panel.clientHeight;
      var vw = document.documentElement.clientWidth, vh = window.innerHeight;
      var below = vh - t.bottom - gap - pad, above = t.top - gap - pad;
      var up = h > below && above > below;
      var room = Math.max(up ? above : below, 120);
      var end = (align === "end") !== (getComputedStyle(anchor).direction === "rtl");
      Object.assign(panel.style, {
        maxHeight: h > room ? room + "px" : "",
        overflowY: h > room ? "auto" : "visible",
        left: Math.max(pad, Math.min(end ? t.right - w : t.left, vw - w - pad)) + "px",
        top: (up ? t.top - gap - Math.min(h, room) : t.bottom + gap) + "px",
      });
    }
    var observer = new ResizeObserver(place);
    function unfloat() {
      observer.disconnect();
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      if (panel.matches(":popover-open")) panel.hidePopover();
    }
    panel.setAttribute("popover", "manual");
    if (!panel.matches(":popover-open")) panel.showPopover();
    // drop the popover defaults (centred in the viewport, own colours) for a spot next to the trigger
    Object.assign(panel.style, { position: "fixed", inset: "auto", margin: "0", color: "inherit", overflow: "visible" });
    observer.observe(panel);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    place();
    return unfloat;
  }

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
        ds.borderWidth = 3;
        ds.hoverOffset = ds.hoverOffset === undefined ? 6 : ds.hoverOffset;
      } else {
        var c = ds.color || "primary";
        ds.borderColor = cssColor(c, 500);
        if (type === "bar") {
          // soft vertical gradient: lighter at the top, full color at the bottom
          ds.backgroundColor = function (context) {
            var area = context.chart.chartArea;
            if (!area) return cssColor(c, 500, 0.85);
            var g = context.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            g.addColorStop(0, cssColor(c, 400));
            g.addColorStop(1, cssColor(c, 600, 0.9));
            return g;
          };
          ds.hoverBackgroundColor = cssColor(c, 600);
          ds.borderRadius = ds.borderRadius === undefined ? { topLeft: 8, topRight: 8 } : ds.borderRadius;
          ds.borderSkipped = false;
          ds.borderWidth = 0;
          ds.maxBarThickness = ds.maxBarThickness || 30;
        } else {
          var gray = c === "gray";
          ds.borderColor = gray ? (dark ? "rgb(161 161 170)" : "rgb(82 82 91)") : ds.borderColor;
          ds.backgroundColor = cssColor(c, 500, 0.12);
          ds.fill = ds.fill === undefined ? true : ds.fill;
          ds.tension = ds.tension === undefined ? 0.4 : ds.tension;
          ds.pointRadius = ds.pointRadius === undefined ? 3 : ds.pointRadius;
          ds.pointHoverRadius = ds.pointHoverRadius === undefined ? 5 : ds.pointHoverRadius;
          ds.pointBackgroundColor = dark ? "rgb(24 24 27)" : "#fff";
          ds.pointBorderColor = ds.borderColor;
          ds.pointBorderWidth = 2;
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
        tooltip: {
          backgroundColor: "rgba(24,24,27,0.95)", padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true,
          titleFont: { weight: "500" }, titleColor: "#a1a1aa", bodyFont: { weight: "600" },
          callbacks: {
            // a dataset's "prefix"/"suffix" (e.g. "₹") is shown with its values
            label: function (item) {
              var ds = item.dataset, v = item.parsed;
              if (v && typeof v === "object") v = item.chart.options.indexAxis === "y" ? v.x : (v.r !== undefined ? v.r : v.y);
              if (v === null || v === undefined) v = item.raw;
              var n = typeof v === "number" ? v.toLocaleString() : v;
              return " " + (ds.label ? ds.label + ": " : "") + (ds.prefix || "") + n + (ds.suffix || "");
            },
          },
        },
      },
      cutout: cfg.type === "doughnut" ? "70%" : undefined,
      scales: round ? {} : {
        x: { grid: { display: false }, ticks: { color: text }, border: { display: false } },
        y: { grid: { color: grid }, ticks: { color: text }, border: { display: false }, beginAtZero: true },
        y1: { display: false },
      },
    };
    options = merge(options, cfg.options || {});
    // axis ticks: { prefix: "₹", compact: true } -> ₹300K
    Object.keys(options.scales || {}).forEach(function (k) {
      var t = (options.scales[k] || {}).ticks;
      if (!t || (!t.prefix && !t.suffix && !t.compact) || t.callback) return;
      var fmt = t.compact ? new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }) : null;
      t.callback = function (v) {
        var n = typeof v === "number" ? (fmt ? fmt.format(v) : v.toLocaleString()) : v;
        return (v === 0 ? "" : (t.prefix || "")) + n + (v === 0 ? "" : (t.suffix || ""));
      };
    });
    canvas._twChart = new window.Chart(canvas, { type: cfg.type, data: cfg.data, options: options });
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
    withLib(root, "[data-tw-qr]", "qr", initQr);
    withLib(root, "tbody[data-tw-sortable]", "sortable", initSortable);
    withLib(root, "canvas[data-tw-chart]", "chart", initChart);
    withLib(root, "select[data-tw-select]", "select", initSelect);
    withLib(root, "trix-editor", "trix", function () {});
    root.querySelectorAll("trix-editor[data-tw-live]").forEach(initRichEditor);
    initMasks(root);
  }

  // ------------------------------------------------------------------ live push
  // one WebSocket per tab while signed in: toasts and bell updates arrive at once (polling stays as fallback)
  var live = { ws: null, url: null, retry: 0, timer: null };
  function liveSync() {
    var el = document.getElementById("tw-live");
    var url = el ? el.getAttribute("data-tw-live-url") : null;
    if (url === live.url) return;
    liveClose();
    live.url = url;
    live.retry = 0;
    if (url) liveOpen();
  }
  function liveClose() {
    clearTimeout(live.timer);
    if (live.ws) {
      live.ws.onclose = null;
      live.ws.close();
      live.ws = null;
    }
  }
  function liveOpen() {
    if (!live.url || !window.WebSocket) return;
    var ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + live.url);
    live.ws = ws;
    ws.onopen = function () { live.retry = 0; };
    ws.onmessage = function (e) {
      var msg;
      try { msg = JSON.parse(e.data); } catch (err) { return; }
      if (msg.type === "toast" && msg.toast) window.twToast(msg.toast);
      if (msg.type === "notifications") document.body.dispatchEvent(new CustomEvent("tw-notifications-changed"));
    };
    ws.onclose = function () {
      live.ws = null;
      if (!live.url) return;
      live.retry = Math.min(live.retry + 1, 6);
      live.timer = setTimeout(liveOpen, 1000 * Math.pow(2, live.retry)); // 2s, 4s ... up to about a minute
    };
  }

  function boot() {
    init(document);
    liveSync();
    if (window.htmx) {
      window.htmx.onLoad(function (el) {
        if (el && el.querySelectorAll) init(el);
        liveSync();
      });
    }
  }

  // this script is deferred, so the page is already parsed
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

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

  // ------------------------------------------------------------------ input masks (TextInput.mask)
  function maskSlots(p) { return (p.match(/[9a*]/g) || []).length; }
  function applyPattern(value, patterns) {
    var chars = String(value).replace(/[^0-9a-zA-Z]/g, "");
    var list = Array.isArray(patterns) ? patterns : [patterns];
    var pattern = list.find(function (p) { return maskSlots(p) >= chars.length; }) || list[list.length - 1];
    var out = "", ci = 0;
    for (var i = 0; i < pattern.length && ci < chars.length; i++) {
      var p = pattern[i], c = chars[ci];
      if (p === "9" || p === "a" || p === "*") {
        var ok = p === "*" || (p === "9" ? /\d/.test(c) : /[a-zA-Z]/.test(c));
        ci++;
        if (ok) out += c; else i--;
      } else {
        out += p;
        if (c === p) ci++;
      }
    }
    return out;
  }
  function applyMoney(value, o) {
    var v = String(value), neg = /^\s*-/.test(v);
    var parts = v.split(o.decimal);
    var whole = parts[0].replace(/\D/g, "").replace(/^0+(?=\d)/, "");
    var frac = parts.length > 1 ? parts.slice(1).join("").replace(/\D/g, "").slice(0, o.precision) : null;
    var grouped;
    if (o.indian && whole.length > 3) {
      var head = whole.slice(0, -3), tail = whole.slice(-3);
      grouped = head.replace(/\B(?=(\d{2})+(?!\d))/g, o.thousands) + o.thousands + tail;
    } else {
      grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, o.thousands);
    }
    if (!whole && frac === null) return neg ? "-" : "";
    return (neg ? "-" : "") + o.prefix + (grouped || "0") + (frac !== null && o.precision > 0 ? o.decimal + frac : "");
  }
  function maskValue(el, value) {
    var m;
    try { m = JSON.parse(el.getAttribute("data-tw-mask")); } catch (e) { return value; }
    if (m && m.money) return applyMoney(value, m);
    return applyPattern(value, m);
  }
  function remask(el) {
    var m;
    try { m = JSON.parse(el.getAttribute("data-tw-mask")); } catch (e) { return; }
    // characters the user typed (the mask adds the rest)
    var typed = m && m.money
      ? function (c) { return /[0-9]/.test(c) || c === m.decimal; }
      : function (c) { return /[0-9a-zA-Z]/.test(c); };
    var before = el.value, caret = el.selectionStart == null ? before.length : el.selectionStart;
    var significant = before.slice(0, caret).split("").filter(typed).length;
    var after = maskValue(el, before);
    if (after === before) return;
    el.value = after;
    // keep the caret after the same number of typed characters
    var pos = 0, seen = 0;
    while (pos < after.length && seen < significant) { if (typed(after[pos])) seen++; pos++; }
    try { el.setSelectionRange(pos, pos); } catch (e) {}
  }
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("input[data-tw-mask]")) remask(e.target);
  });
  function initMasks(root) {
    root.querySelectorAll("input[data-tw-mask]").forEach(function (el) {
      var m;
      try { m = JSON.parse(el.getAttribute("data-tw-mask")); } catch (e) { return; }
      if (m && m.money && m.decimal !== "." && /^-?\d+(\.\d+)?$/.test(el.value)) el.value = el.value.replace(".", m.decimal);
      if (el.value) el.value = maskValue(el, el.value);
    });
  }
  window.twMask = maskValue;

  // ------------------------------------------------------------------ rich editor (Trix) extras
  function csrfToken() {
    try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"]; } catch (e) { return ""; }
  }
  // extra formats used by RichEditor.toolbar_buttons (underline, h2, h3)
  document.addEventListener("trix-before-initialize", function () {
    var T = window.Trix;
    if (!T || T._twConfigured) return;
    T._twConfigured = true;
    T.config.textAttributes.underline = {
      tagName: "u", inheritable: true,
      parser: function (el) { return el.tagName === "U"; },
    };
    T.config.blockAttributes.heading2 = { tagName: "h2", terminal: true, breakOnReturn: true, group: false };
    T.config.blockAttributes.heading3 = { tagName: "h3", terminal: true, breakOnReturn: true, group: false };
  });

  function typeAllowed(type, list) {
    if (!list) return true;
    return list.split(",").some(function (t) {
      t = t.trim();
      return t === type || (t.slice(-2) === "/*" && type.indexOf(t.slice(0, -1)) === 0);
    });
  }
  // Files: only editors with RichEditor.file_attachments() take them (FileUpload fields handle the rest)
  document.addEventListener("trix-file-accept", function (e) {
    var ed = e.target, url = ed.getAttribute("data-tw-attach-url");
    if (!url) { e.preventDefault(); return; }
    var file = e.file, max = parseInt(ed.getAttribute("data-tw-attach-max"), 10);
    if (!typeAllowed(file.type, ed.getAttribute("data-tw-attach-types"))) {
      e.preventDefault(); window.twToast({ title: twT("This file type is not allowed."), status: "danger" });
    } else if (max && file.size > max * 1024) {
      e.preventDefault(); window.twToast({ title: twT("The file is too large."), status: "danger" });
    }
  });
  document.addEventListener("trix-attachment-add", function (e) {
    var ed = e.target, url = ed.getAttribute("data-tw-attach-url"), att = e.attachment;
    if (!url || !att.file) return;
    var form = ed.closest("form");
    var data = form ? new FormData(form) : new FormData();
    data.set("_tw_field", ed.getAttribute("data-tw-field"));
    data.set("file", att.file);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.setRequestHeader("X-CSRF-Token", csrfToken());
    xhr.setRequestHeader("HX-Request", "true");
    xhr.upload.addEventListener("progress", function (ev) {
      if (ev.lengthComputable) att.setUploadProgress(ev.loaded / ev.total * 100);
    });
    xhr.addEventListener("load", function () {
      var body = {};
      try { body = JSON.parse(xhr.responseText); } catch (err) {}
      if (xhr.status === 200 && body.url) {
        att.setAttributes({ url: body.url, href: body.href || body.url });
      } else {
        att.remove();
        window.twToast({ title: body.error || twT("The file could not be uploaded."), status: "danger" });
      }
    });
    xhr.addEventListener("error", function () { att.remove(); window.twToast({ title: twT("The file could not be uploaded."), status: "danger" }); });
    xhr.send(data);
  });

  // remember the caret, so a block from the toolbar lands where the user was typing
  document.addEventListener("trix-selection-change", function (e) {
    var wrap = e.target.closest("[data-tw-form]") && e.target.parentElement;
    var input = wrap && wrap.querySelector("input[data-tw-rich-cursor]");
    if (input && e.target.editor) input.value = e.target.editor.getSelectedRange()[0];
  });

  // a block inserted or changed through its modal (the server sends it back with the form)
  document.addEventListener("trix-initialize", function (e) {
    var ed = e.target, raw = ed.getAttribute("data-tw-insert");
    if (!raw || !window.Trix) return;
    ed.removeAttribute("data-tw-insert");
    var info;
    try { info = JSON.parse(raw); } catch (err) { return; }
    var editor = ed.editor, length = editor.getDocument().getLength();
    var pos = typeof info.pos === "number" && info.pos >= 0 ? Math.min(info.pos, length - 1) : length - 1;
    editor.setSelectedRange(info.replace ? [pos, pos + 1] : [pos, pos]);
    editor.insertAttachment(new window.Trix.Attachment(info.attachment));
    ed.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // block menu: a plain click inserts a new block; the pencil edits the selected one
  document.addEventListener("click", function (e) {
    var menu = e.target.closest && e.target.closest("[data-tw-block-menu]");
    if (!menu) return;
    var wrap = menu.closest("trix-toolbar").parentElement;
    var editInput = wrap.querySelector("input[data-tw-rich-edit]");
    var ed = wrap.querySelector("trix-editor");
    if (e.target.closest("[data-tw-block-edit]")) {
      e.preventDefault();
      var editor = ed && ed.editor;
      if (!editor) return;
      var range = editor.getSelectedRange(), doc = editor.getDocument();
      var found = doc.getAttachments().find(function (a) {
        var r = doc.getRangeOfAttachment(a);
        return a.getContentType() === "application/vnd.tungsten.block" && r && r[0] <= range[0] && range[0] <= r[1] && (range[1] <= r[1]);
      });
      if (!found) { window.twToast({ title: twT("Click a block in the editor first."), status: "warning" }); return; }
      var attrs = found.getAttributes();
      var button = menu.querySelector('[data-tw-block="' + attrs.blockId + '"] [data-tw-form-action]');
      if (!button) return;
      editInput.value = JSON.stringify({ id: attrs.blockId, config: attrs.blockConfig || {}, pos: doc.getRangeOfAttachment(found)[0] });
      button._twEditing = true;
      button.click();
      return;
    }
    var action = e.target.closest("[data-tw-form-action]");
    if (action && !action._twEditing && editInput) editInput.value = "";
    if (action) action._twEditing = false;
  }, true);

  // @mentions
  var mention = null;
  function mentionProviders(ed) {
    if (!ed._twMentions) { try { ed._twMentions = JSON.parse(ed.getAttribute("data-tw-mentions")); } catch (e) { ed._twMentions = []; } }
    return ed._twMentions;
  }
  function closeMention() { if (mention) { mention.box.remove(); mention = null; } }
  function drawMention() {
    var m = mention;
    m.box.innerHTML = "";
    if (!m.items.length) { m.box.style.display = "none"; return; }
    m.box.style.display = "";
    m.items.forEach(function (item, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "block w-full rounded-md px-3 py-1.5 text-start text-sm " + (i === m.index ? "bg-primary-50 text-primary-700 dark:bg-white/10 dark:text-white" : "text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-white/5");
      b.textContent = item.label;
      b.addEventListener("mousedown", function (ev) { ev.preventDefault(); pickMention(i); });
      m.box.appendChild(b);
    });
  }
  function pickMention(i) {
    var m = mention, item = m && m.items[i];
    if (!item) return closeMention();
    var editor = m.ed.editor;
    editor.setSelectedRange([m.start, m.end]);
    var label = document.createElement("span");
    label.textContent = m.trigger + item.label;  // escaped: a label is text, never HTML
    editor.insertAttachment(new window.Trix.Attachment({
      content: '<span class="tw-mention">' + label.innerHTML + "</span>",
      contentType: "application/vnd.tungsten.mention",
      mentionId: String(item.id), mentionLabel: item.label, mentionTrigger: m.trigger,
    }));
    editor.insertString(" ");
    closeMention();
  }
  function updateMention(ed) {
    var providers = mentionProviders(ed);
    if (!providers.length || !ed.editor) return;
    var range = ed.editor.getSelectedRange();
    if (range[0] !== range[1]) return closeMention();
    var pos = range[0], text = ed.editor.getDocument().toString().slice(Math.max(0, pos - 40), pos);
    var triggers = providers.map(function (p) { return p.trigger.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&"); }).join("|");
    var match = new RegExp("(^|\\s)(" + triggers + ")([^\\s]{0,30})$").exec(text);
    if (!match) return closeMention();
    var trigger = match[2], query = match[3];
    var provider = providers.find(function (p) { return p.trigger === trigger; });
    if (!mention || mention.ed !== ed) {
      closeMention();
      var box = document.createElement("div");
      box.className = "fixed z-[70] max-h-60 w-56 overflow-y-auto rounded-lg bg-white p-1 shadow-lg ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10";
      document.body.appendChild(box);
      mention = { ed: ed, box: box, items: [], index: 0 };
    }
    mention.trigger = trigger;
    mention.start = pos - query.length - trigger.length;
    mention.end = pos;
    var rect = ed.editor.getClientRectAtPosition(mention.start) || ed.getBoundingClientRect();
    mention.box.style.left = rect.left + "px";
    mention.box.style.top = (rect.top + (rect.height || 18) + 4) + "px";
    var show = function (items) { if (!mention) return; mention.items = items.slice(0, 20); mention.index = 0; drawMention(); };
    if (provider.items) {
      var q = query.toLowerCase();
      show(provider.items.filter(function (it) { return it.label.toLowerCase().indexOf(q) !== -1; }));
    } else {
      clearTimeout(mention.timer);
      mention.timer = setTimeout(function () {
        var form = ed.closest("form"), data = form ? new FormData(form) : new FormData();
        data.set("_tw_field", ed.getAttribute("data-tw-field"));
        data.set("q", trigger + query);
        fetch(ed.getAttribute("data-tw-search-url"), { method: "POST", body: data, headers: { "X-CSRF-Token": csrfToken(), "HX-Request": "true" } })
          .then(function (r) { return r.json(); })
          .then(function (rows) { show(rows.map(function (r) { return { id: r.value, label: r.text }; })); })
          .catch(function () {});
      }, 250);
    }
  }
  document.addEventListener("trix-change", function (e) { if (e.target.hasAttribute("data-tw-mentions")) updateMention(e.target); });
  document.addEventListener("trix-blur", function () { setTimeout(closeMention, 150); });
  document.addEventListener("keydown", function (e) {
    if (!mention || !mention.items.length || e.target !== mention.ed) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      mention.index = (mention.index + (e.key === "ArrowDown" ? 1 : mention.items.length - 1)) % mention.items.length;
      drawMention();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault(); e.stopPropagation(); pickMention(mention.index);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation(); closeMention();
    }
  }, true);

  // ------------------------------------------------------------------ idle sign-out (Auth(idle_timeout=...))
  // Polling isn't activity: mark requests no user event started, so the server doesn't count them.
  document.addEventListener("htmx:configRequest", function (e) {
    if (!e.detail.triggeringEvent) e.detail.headers["X-TW-Background"] = "1";
  });
  (function () {
    var last = Date.now(), pinged = Date.now();
    function idleMinutes() { return parseFloat(document.body && document.body.getAttribute("data-tw-idle")) || 0; }
    function active() {
      last = Date.now();
      // typing in a long form makes no requests, so tell the server the user is still here
      var url = document.body && document.body.getAttribute("data-tw-ping");
      if (url && idleMinutes() && last - pinged > 60000) {
        pinged = last;
        fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } }).catch(function () {});
      }
    }
    ["mousedown", "keydown", "scroll", "touchstart", "mousemove"].forEach(function (name) {
      window.addEventListener(name, active, { passive: true, capture: true });
    });
    setInterval(function () {
      var minutes = idleMinutes();
      // the server has signed the user out by now; reloading shows the sign-in page instead of stale data
      if (minutes && Date.now() - last > minutes * 60000 + 5000) { last = Date.now(); window.location.reload(); }
    }, 15000);
  })();
})();
