# Design research crawler

`crawl.py` opens a dashboard demo site, follows every link in its menus, and saves a full-page
screenshot plus a short report (`report.json`: page title, headings and which kinds of components
each page has: cards, tables, charts, forms, timelines...). It is for looking at ideas only.
Nothing from the crawled site goes into Tungsten; the output folder is git-ignored.

```bash
pip install playwright && playwright install chromium   # once
python promo/inspiration/crawl.py https://example.com/pages/dashboards/analytics.html --out promo/inspiration/out
```

Set `CHROME_PATH` to use a Chromium that is already installed.
