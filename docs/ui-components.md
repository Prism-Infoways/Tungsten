---
title: UI components
description: The modern design system - rounded cards, pill navigation, chips, rings, gauges, meters, columns, timelines and more, ready to use in your own templates.
---

Tungsten's panel uses a modern design: a light gray page, white cards with big soft corners, a floating dark sidebar where the current page is a white pill, pill-shaped buttons and a black pill for the active tab. Dark mode flips all of it.

The same building blocks are available to you as **Jinja macros** and **CSS classes**, so your [custom pages](custom-pages) and widget templates look the same as the rest of the panel.

> [!TIP]
> See every component live: add the gallery as a custom page.
>
> ```python
> class UiKit(Page):
>     title = "UI kit"
>     content_template = "tungsten/components/gallery.html"
> ```
>
> The shop demo has it under **Settings → UI kit**.

## Using the macros

Import the UI kit at the top of your template:

```jinja
{% import "tungsten/components/ui.html" as ui %}

<div class="tw-card p-6">
  {{ ui.pill_tabs([{'label': 'Overview', 'url': '#', 'active': true}, {'label': 'Activity', 'url': '#'}]) }}
  {{ ui.meter('Upsell revenue', 56, 'success') }}
</div>
```

Colors are the panel's color names: `primary`, `success`, `danger`, `warning`, `info`, `gray`, `purple`, `teal`, `pink` and `indigo`. They follow `Panel(colors=...)`.

## Macros

### Cards and numbers

| Macro | What it draws |
| --- | --- |
| `ui.card(heading, description, padding, classes, link, link_label, icon_name, icon_color)` | A card with a header. Use with `{% call %}`. |
| `ui.stat_card(label, value, icon_name, color, description, trend_value, trend_direction, trend_color, chart, url, id, variant)` | A stats card. `variant` is `default`, `brand` (filled with the brand color) or `dark`. |
| `ui.kpi(label, value, trend_value, trend_direction, color, accent)` | A small number with a label, for inside a card. `accent` draws a colored line on the side. |
| `ui.banner(heading, text, button_label, button_url, eyebrow, variant, color, button_icon)` | A colored banner card. `variant` is `soft`, `brand` or `dark`. |

### Navigation

| Macro | What it draws |
| --- | --- |
| `ui.pill_tabs(items, muted=false)` | Pill tabs. `items` is a list of dicts with `label`, `url`, `active`, and optional `icon` and `badge`. The active one is a black pill. `muted=true` gives a gray bar with a white active pill. |
| `ui.segmented(name, options, value)` | A segmented control made of radio buttons, so it posts with your form. `options` is a dict of value to label. |
| `ui.breadcrumbs(items)` | Breadcrumbs from `(label, url)` pairs. |

### Labels

| Macro | What it draws |
| --- | --- |
| `ui.badge(text, color, icon_name)` | A rounded status badge. |
| `ui.chip(text, icon_name, dot_color, href)` | A small uppercase pill, like "JUNE 2025" or "USD". |
| `ui.trend_pill(value, direction, color)` | A "↑ 12%" pill. Up is green and down is red unless you pass a color. |
| `ui.count_pill(n, color)` | A round count, like menu badges. |
| `ui.dot(color)` | A small colored dot. |
| `ui.kbd(text)` | A keyboard key, like ⌘K. |

### Progress

| Macro | What it draws |
| --- | --- |
| `ui.progress_ring(percent, color, size, stroke, label, value)` | A ring that fills to `percent`, with the value in the middle. |
| `ui.gauge(percent, color, value, caption, label, on_dark)` | A half-circle gauge. Pass `on_dark=true` inside a dark or brand card. |
| `ui.meter(label, percent, color, value)` | A label and a thin bar. |
| `ui.columns(cols, color, height)` | Rounded columns. `cols` is a list of dicts with `label`, `display`, `height` (0 to 100) and `active`. |
| `ui.sparkline(points, color, id)` | A tiny line chart. |

Percent values are always kept between 0 and 100. Rings, gauges and meters have screen reader labels.

### Lists and people

| Macro | What it draws |
| --- | --- |
| `ui.list_row(title, description, value, icon_name, color, avatar_url, avatar_name, href, badge_text, badge_color)` | One row with an avatar or icon, text and a value. |
| `ui.timeline_item(title, description, time, icon_name, color, last, href)` | One timeline entry. Put them in an `<ol>` and pass `last=true` to the last one. |
| `ui.avatar(name, url, size, text)` | A round avatar, or colored initials without a URL. |
| `ui.avatar_group(people, max=4)` | Overlapping avatars with a "+2" bubble. `people` is a list of dicts with `name` and `avatar`. |
| `ui.week_strip(days)` | A week of days with today highlighted. `days` is a list of dicts with `name`, `day` and `today`. |

### Forms and feedback

| Macro | What it draws |
| --- | --- |
| `ui.switch(name, checked, label, description, value)` | An on/off switch (a styled checkbox that posts with the form). |
| `ui.alert(heading, text, color, icon_name)` | A message box. The icon follows the color. |
| `ui.button(label, color, icon_name, href, ...)` | A pill button. |
| `ui.empty_state(heading, description, icon_name)` | A friendly "nothing here" block. |
| `ui.skeleton(lines)` | Gray loading lines. |
| `ui.divider(label)` | A thin line with optional text in the middle. |

## CSS classes

These classes are in the panel's stylesheet, so you can use them in any template or in `Markup` returned from `content()`.

| Class | What it is |
| --- | --- |
| `tw-card` | The white card with big soft corners |
| `tw-card-hover` | Lifts the card a little on hover |
| `tw-card-dark` | A near-black card with white text |
| `tw-card-brand` | A card filled with the primary color |
| `tw-glass` | A frosted glass panel |
| `tw-well` | A soft gray block inside a card |
| `tw-pill-nav`, `tw-pill-nav-item`, `tw-pill-nav-item-active` | Pill navigation (add `tw-pill-nav-muted` for the gray version) |
| `tw-chip` | The small uppercase pill |
| `tw-round-btn` | The round white button of the top bar |
| `tw-btn` | The base of every button (pill shaped) |
| `tw-track`, `tw-track-bar` | A thin progress track and its bar |
| `tw-figure` | Big number text (tabular digits, tight letters) |
| `tw-skeleton` | A gray loading block |
| `tw-stripes` | Diagonal stripes, as on the empty columns |
| `tw-rise` | Fades a block up when the page opens (off for people who turn off motion) |
| `tw-dot` | A small round dot (set the color yourself) |

> [!NOTE]
> The stylesheet only has the Tailwind classes Tungsten's own templates use. The classes above, the macros and common utilities are safe. For other utilities, build a [custom theme](theming) so Tailwind scans your templates too.

## What changed in the panel

The modern design applies to every page, with no settings to change:

- The page is light gray and cards are white with 28px corners and a very soft shadow.
- The sidebar floats with a gap around it and round corners. The current page is a white pill with a colored icon. Collapsing it still works.
- The top bar blends into the page. Search is a white pill; the theme switch, bell and user menu are round white buttons.
- Buttons, badges, chips and dropdowns are pill shaped. Inputs have rounder corners.
- The top menu (`Panel(top_navigation=True)`), table tabs and sub-navigation are pill bars with a black (or white) active pill.
- Table headers are small uppercase labels.
- Stats cards show a bigger number and a round icon at the top right, and can be filled with `.highlight()`.

Brand colors still come from `Panel(colors=...)`, so a blue or green brand gets the same look in its own color.
