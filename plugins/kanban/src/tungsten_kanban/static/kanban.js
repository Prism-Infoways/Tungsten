/* Tungsten Kanban boards: drag and drop with SortableJS (bundled with Tungsten), plus a
   "Move to" menu on every card for keyboards and small screens. The server checks every move. */
(function () {
  "use strict";

  function csrf() {
    try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || ""; }
    catch (e) { return ""; }
  }

  function toast(title, body, status) {
    if (window.twToast) window.twToast({ title: title, body: body || null, status: status || "danger",
      icon: status === "success" ? "circle-check" : "circle-x", duration: status === "success" ? 2000 : 6000 });
  }

  function cardsOf(list) { return Array.prototype.filter.call(list.children, function (el) { return el.hasAttribute("data-tk-card"); }); }
  function laneOf(el) { return el.closest("[data-tk-lane]"); }

  function allowed(card, lane) {
    if (!lane || lane.getAttribute("data-accepts") === "false") return false;
    if (card.classList.contains("tk-locked")) return false;
    var targets = card.getAttribute("data-targets");
    if (targets === null) return true;
    return targets.split(",").indexOf(lane.getAttribute("data-tk-lane")) !== -1;
  }

  // keep "Load more" at the bottom and the "No cards" note in step
  function tidy(list) {
    var more = list.querySelector(":scope > [data-tk-more]");
    if (more && more !== list.lastElementChild) list.appendChild(more);
    var empty = laneOf(list).querySelector("[data-tk-empty]");
    if (empty) empty.hidden = cardsOf(list).length > 0;
  }

  function setCounts(board, counts) {
    if (!counts) return;
    board.querySelectorAll("[data-tk-lane]").forEach(function (lane) {
      var key = lane.getAttribute("data-tk-lane");
      if (!(key in counts)) return;
      var el = lane.querySelector("[data-tk-count]");
      var limit = parseInt(el.getAttribute("data-limit") || "", 10);
      el.textContent = counts[key] + (limit ? "/" + limit : "");
      el.classList.toggle("tk-over", !!limit && counts[key] > limit);
    });
  }

  // the "Move to" menu lists the columns this card may go to from where it is now
  function refreshMenu(board, card) {
    var select = card.querySelector("[data-tk-move]");
    if (!select) return;
    var here = laneOf(card).getAttribute("data-tk-lane");
    while (select.options.length > 1) select.remove(1);
    board.querySelectorAll("[data-tk-lane]").forEach(function (lane) {
      var key = lane.getAttribute("data-tk-lane");
      if (key === here || !allowed(card, lane)) return;
      var title = lane.querySelector(".tk-lane-title");
      select.add(new Option(title ? title.textContent : key, key));
    });
    select.value = "";
  }

  function putBack(card, from, index) {
    if (card.parentNode) card.parentNode.removeChild(card);
    var ref = cardsOf(from)[index] || from.querySelector(":scope > [data-tk-more]");
    from.insertBefore(card, ref || null);
  }

  function send(board, card, from, to, oldIndex, oldKey) {
    var lane = laneOf(to);
    var data = new FormData();
    data.append("record", card.getAttribute("data-tk-card"));
    data.append("to", lane.getAttribute("data-tk-lane"));
    data.append("from", oldKey);
    data.append("q", board.getAttribute("data-q") || "");
    data.append("mine", board.getAttribute("data-mine") || "");
    if (board.getAttribute("data-sortable") === "true") {
      cardsOf(to).forEach(function (c) { data.append("order", c.getAttribute("data-tk-card")); });
    }
    card.classList.add("tk-busy");
    var failed = function (title, body, reload) {
      putBack(card, from, oldIndex);
      tidy(from); tidy(to);
      toast(title, body);
      if (reload) setTimeout(function () { window.location.reload(); }, 1500);
    };
    fetch(board.getAttribute("data-move-url"), {
      method: "POST", body: data, credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf(), "Accept": "application/json" },
    }).then(function (res) {
      var type = res.headers.get("content-type") || "";
      if (type.indexOf("json") === -1) {  // signed out, page expired, or a proxy error page
        failed(board.getAttribute("data-t-error"), board.getAttribute("data-t-expired"), false);
        return null;
      }
      return res.json().then(function (body) {
        if (!body.ok) { failed(board.getAttribute("data-t-error"), body.error, body.reload); return; }
        if ("targets" in body) {
          if (body.targets === null) card.removeAttribute("data-targets");
          else card.setAttribute("data-targets", body.targets.join(","));
        }
        setCounts(board, body.counts);
        refreshMenu(board, card);
        if (body.message) toast(body.message, null, "success");
        card.classList.add("tk-flash");
        setTimeout(function () { card.classList.remove("tk-flash"); }, 900);
      });
    }).catch(function () {
      failed(board.getAttribute("data-t-error"), board.getAttribute("data-t-offline"), false);
    }).then(function () { card.classList.remove("tk-busy"); });
  }

  function initList(board, list) {
    if (list._tkSortable || !window.Sortable) return;
    var name = "tk-" + (board.getAttribute("data-move-url") || "");
    var start = null;
    list._tkSortable = window.Sortable.create(list, {
      group: {
        name: name,
        pull: true,
        put: function (to, from, dragged) { return allowed(dragged, laneOf(to.el)); },
      },
      sort: board.getAttribute("data-sortable") === "true",
      draggable: ".tk-card:not(.tk-locked):not(.tk-busy)",
      filter: "a, select, button, input",
      preventOnFilter: false,
      delay: 150,
      delayOnTouchOnly: true,
      animation: 150,
      ghostClass: "tk-ghost",
      chosenClass: "tk-chosen",
      dragClass: "tk-drag",
      scroll: true,
      bubbleScroll: true,
      onStart: function (evt) {
        start = { key: laneOf(evt.from).getAttribute("data-tk-lane") };
        board.querySelectorAll("[data-tk-lane]").forEach(function (lane) {
          if (lane === laneOf(evt.from)) return;
          lane.classList.add(allowed(evt.item, lane) ? "tk-can-drop" : "tk-no-drop");
        });
      },
      onEnd: function (evt) {
        board.querySelectorAll(".tk-can-drop, .tk-no-drop").forEach(function (lane) {
          lane.classList.remove("tk-can-drop", "tk-no-drop");
        });
        tidy(evt.from); tidy(evt.to);
        if (evt.from === evt.to && evt.oldIndex === evt.newIndex) return;
        send(board, evt.item, evt.from, evt.to, evt.oldIndex, start ? start.key : "");
      },
    });
  }

  function initBoard(board) {
    if (board._tkBoard) return;
    board._tkBoard = true;
    board.addEventListener("change", function (e) {
      var select = e.target.closest && e.target.closest("[data-tk-move]");
      if (!select || !select.value) return;
      var card = select.closest("[data-tk-card]");
      var lane = board.querySelector('[data-tk-lane="' + (window.CSS && CSS.escape ? CSS.escape(select.value) : select.value) + '"]');
      select.value = "";
      if (!card || !lane || card.classList.contains("tk-busy")) return;
      if (!allowed(card, lane)) { toast(board.getAttribute("data-t-error"), board.getAttribute("data-t-not-allowed")); return; }
      var from = card.parentElement;
      var oldIndex = cardsOf(from).indexOf(card);
      var oldKey = laneOf(from).getAttribute("data-tk-lane");
      var to = lane.querySelector("[data-tk-cards]");
      to.insertBefore(card, cardsOf(to)[0] || to.firstChild);
      tidy(from); tidy(to);
      card.scrollIntoView({ block: "nearest", inline: "nearest" });
      send(board, card, from, to, oldIndex, oldKey);
    });
  }

  function init(root) {
    var boards = (root.matches && root.matches("[data-tk-board]")) ? [root] : [];
    boards = boards.concat(Array.prototype.slice.call(root.querySelectorAll ? root.querySelectorAll("[data-tk-board]") : []));
    var inside = root.closest ? root.closest("[data-tk-board]") : null;  // "Load more" added cards
    if (inside) boards.push(inside);
    if (!boards.length) return;
    boards.forEach(initBoard);
    var ready = window.twNeed ? window.twNeed("sortable") : Promise.resolve();
    ready.then(function () {
      boards.forEach(function (board) {
        board.querySelectorAll("[data-tk-cards]").forEach(function (list) { initList(board, list); tidy(list); });
      });
    }, function (e) { console.error(e); });
  }

  function boot() {
    init(document);
    if (window.htmx) window.htmx.onLoad(function (el) { if (el) init(el); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
