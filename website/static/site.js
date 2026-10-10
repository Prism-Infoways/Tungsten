(() => {
  const root = document.documentElement;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
  };

  // ---- theme: toggles between light and dark (starts from the system setting)
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    const label = () => btn.setAttribute("aria-label", isDark() ? "Switch to light theme" : "Switch to dark theme");
    label();
    btn.addEventListener("click", () => {
      root.dataset.theme = isDark() ? "light" : "dark";
      store.set("tw-site-theme", root.dataset.theme);
      label();
    });
  });

  // ---- copy buttons
  async function copy(text, done) {
    try { await navigator.clipboard.writeText(text); done(true); } catch (e) { done(false); }
  }
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => copy(btn.dataset.copy, (ok) => {
      const out = btn.querySelector(".copied");
      if (out) { out.textContent = ok ? "Copied" : "Press Ctrl+C"; setTimeout(() => (out.textContent = ""), 1600); }
      if (!ok) { const sel = getSelection(); sel.selectAllChildren(btn.querySelector("code")); }
    }));
  });
  document.querySelectorAll(".prose .codehilite, .split-copy .codehilite").forEach((block) => {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "copy-code"; btn.textContent = "Copy";
    btn.addEventListener("click", () => copy(block.querySelector("pre").innerText.trimEnd(), (ok) => {
      btn.textContent = ok ? "Copied" : "Select and copy";
      setTimeout(() => (btn.textContent = "Copy"), 1500);
    }));
    block.appendChild(btn);
  });

  // ---- home page tabs (arrow keys move between tabs)
  document.querySelectorAll("[data-tabs]").forEach((box) => {
    const tabs = [...box.querySelectorAll('[role="tab"]')];
    const select = (tab) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        const next = tabs[(i + step + tabs.length) % tabs.length];
        select(next); next.focus();
      });
    });
  });

  // ---- docs menu on small screens
  const toggle = document.querySelector("[data-nav-toggle]");
  const setNav = (open) => {
    document.body.classList.toggle("nav-open", open);
    if (toggle) toggle.setAttribute("aria-expanded", open);
  };
  toggle?.addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
  document.querySelectorAll("[data-nav-close]").forEach((el) => el.addEventListener("click", () => setNav(false)));
  document.querySelector(".sidebar [aria-current]")?.scrollIntoView({ block: "center" });

  // ---- "On this page" highlights the section you are reading
  const tocLinks = [...document.querySelectorAll(".toc a")];
  if (tocLinks.length) {
    const heads = tocLinks.map((a) => document.getElementById(decodeURIComponent(a.hash.slice(1)))).filter(Boolean);
    const onScroll = () => {
      let current = heads[0];
      for (const h of heads) if (h.getBoundingClientRect().top < 120) current = h;
      tocLinks.forEach((a) => a.classList.toggle("active", current && a.hash === "#" + current.id));
    };
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ---- search
  const modal = document.querySelector("[data-search]");
  const input = document.getElementById("search-input");
  const list = document.getElementById("search-results");
  const empty = document.getElementById("search-empty");
  const base = (window.TW_ROOT || "") + "docs/";
  let results = [], active = 0;

  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const mark = (text, words) => {
    let out = esc(text);
    words.forEach((w) => { if (w.length > 1) out = out.replace(new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>"); });
    return out;
  };
  function snippet(text, word) {
    const i = text.toLowerCase().indexOf(word);
    if (i < 0) return "";
    const start = Math.max(0, i - 50);
    return (start ? "…" : "") + text.slice(start, i + 110) + "…";
  }
  function find(q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return (window.TW_SEARCH || []).slice(0, 8).map((p) => ({ page: p, score: 0 }));
    const out = [];
    for (const p of window.TW_SEARCH || []) {
      const title = p.title.toLowerCase(), text = p.text.toLowerCase(), desc = p.description.toLowerCase();
      if (!words.every((w) => title.includes(w) || text.includes(w) || desc.includes(w) || p.headings.some((h) => h[1].toLowerCase().includes(w)))) continue;
      let score = 0, heading = null;
      for (const w of words) {
        if (title.startsWith(w)) score += 12; else if (title.includes(w)) score += 8;
        if (desc.includes(w)) score += 3;
        const h = p.headings.find((h) => h[1].toLowerCase().includes(w));
        if (h) { score += 5; heading = heading || h; }
        score += Math.min(4, text.split(w).length - 1) * 0.5;
      }
      out.push({ page: p, score, heading, words });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, 12);
  }
  function render() {
    const q = input.value.trim();
    results = find(q);
    active = 0;
    empty.hidden = results.length > 0;
    list.innerHTML = results.map((r, i) => {
      const words = r.words || [];
      const href = base + r.page.slug + (r.heading ? "#" + r.heading[0] : "");
      const meta = r.page.section + (r.heading ? " › " + r.heading[1] : "");
      const text = words.length ? snippet(r.page.text, words[0]) || r.page.description : r.page.description;
      return `<li><a href="${href}" role="option" aria-selected="${i === 0}">
        <div class="r-title">${mark(r.page.title, words)}</div><div class="r-meta">${esc(meta)}</div>
        <div class="r-text">${mark(text, words)}</div></a></li>`;
    }).join("");
  }
  function move(step) {
    const links = list.querySelectorAll("a");
    if (!links.length) return;
    links[active].setAttribute("aria-selected", "false");
    active = (active + step + links.length) % links.length;
    links[active].setAttribute("aria-selected", "true");
    links[active].scrollIntoView({ block: "nearest" });
  }
  const open = () => { modal.hidden = false; input.value = ""; render(); input.focus(); };
  const close = () => { modal.hidden = true; };
  document.querySelectorAll("[data-search-open]").forEach((b) => b.addEventListener("click", open));
  document.querySelectorAll("[data-search-close]").forEach((b) => b.addEventListener("click", close));
  input.addEventListener("input", render);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter") { const a = list.querySelectorAll("a")[active]; if (a) location.href = a.href; }
  });
  addEventListener("keydown", (e) => {
    if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !/input|textarea/i.test(document.activeElement.tagName))) {
      e.preventDefault(); modal.hidden ? open() : close();
    } else if (e.key === "Escape") { close(); setNav(false); }
  });
})();
