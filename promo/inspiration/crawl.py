"""Crawl a dashboard demo site and screenshot every page in its sidebar.

Used for design research only: it saves screenshots and a list of the
components each page shows (cards, tables, charts, forms, ...) so we can
compare them with what Tungsten has. Nothing from the site is copied into
Tungsten; the output folder is git-ignored.

    python promo/inspiration/crawl.py START_URL [--out DIR] [--max 200]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

# Rough component detection by CSS class / tag names commonly used by
# Bootstrap-style dashboards.
PROBES = {
    "card": ".card",
    "table": "table",
    "chart": "canvas, svg.apexcharts-svg, .chart",
    "form": "form",
    "input": "input:not([type=hidden])",
    "select": "select, .choices",
    "checkbox": "input[type=checkbox]",
    "switch": ".form-switch",
    "progress": ".progress",
    "badge": ".badge",
    "avatar": ".avatar",
    "button": ".btn",
    "dropdown": ".dropdown-menu",
    "nav-pills": ".nav-pills",
    "tabs": ".nav-tabs, .nav-pills",
    "timeline": ".timeline",
    "calendar": ".fc, .calendar",
    "kanban": ".kanban-container, .kanban",
    "map": ".jvm-container, .map, [id*=map]",
    "modal": ".modal",
    "alert": ".alert",
    "pagination": ".pagination",
    "carousel": ".carousel",
    "accordion": ".accordion, .collapse",
    "wizard": ".multisteps-form, .wizard",
    "dropzone": ".dropzone",
    "editor": ".ql-editor, .ql-container",
    "slider": ".noUi-target",
    "tooltip": "[data-bs-toggle=tooltip]",
    "datatable": ".dataTable-wrapper, .datatable-wrapper",
    "breadcrumb": ".breadcrumb",
    "list-group": ".list-group",
    "image": "img",
}


def same_site(url: str, root: str) -> bool:
    a, b = urlparse(url), urlparse(root)
    return a.netloc == b.netloc and a.path.startswith(b.path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("--out", default="promo/inspiration/out")
    ap.add_argument("--max", type=int, default=200)
    args = ap.parse_args()

    out = Path(args.out)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    root = args.start.split("/pages/")[0] + "/pages/"

    seen: set[str] = set()
    queue = [args.start]
    report = []
    with sync_playwright() as p:
        import os
        exe = os.environ.get("CHROME_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        while queue and len(report) < args.max:
            url = queue.pop(0).split("#")[0]
            if url in seen or not url.endswith(".html"):
                continue
            seen.add(url)
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                report.append({"url": url, "error": str(exc)[:200]})
                continue
            page.wait_for_timeout(800)
            if "404" in page.title() or "not found" in page.title().lower():
                report.append({"url": url, "error": "404"})
                continue
            for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
                href = urljoin(url, href).split("#")[0]
                if same_site(href, root) and href not in seen:
                    queue.append(href)
            counts = {}
            for name, sel in PROBES.items():
                n = page.locator(sel).count()
                if n:
                    counts[name] = n
            headings = page.eval_on_selector_all(
                "h1,h2,h3,h4,h5,h6",
                "els => els.map(e => e.innerText.trim()).filter(Boolean).slice(0, 40)",
            )
            slug = re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.split("/pages/")[-1].lower()).strip("-")
            page.screenshot(path=str(out / "shots" / f"{slug}.png"), full_page=True)
            report.append({"url": url, "slug": slug, "title": page.title(), "components": counts, "headings": headings})
            print(f"[{len(report):3}] {slug}  {counts}")
        browser.close()
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(f"done: {len(report)} pages -> {out}")


if __name__ == "__main__":
    main()
