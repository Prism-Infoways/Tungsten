---
title: Theming
description: Change brand colors, font, logo, favicon and dark mode, and turn on SPA mode and other layout options.
---

Tungsten looks good out of the box, and you can make it match your brand with a few `Panel(...)` options. No CSS build step is needed.

## Colors

Pass a `colors` dict to the panel. Each value can be a Tailwind palette name or a hex color:

```python
panel = Panel(
    ...,
    colors={
        "primary": "indigo",     # a Tailwind palette name
        "danger": "#e11d48",     # or any hex color
    },
)
```

`primary` is the main brand color, used for buttons, links, the active menu item and focus rings. The other colors are used for badges, notifications, stats and actions.

### Color names you can set

| Name | Default | Used for |
| --- | --- | --- |
| `primary` | `orange` | Buttons, links, active items, the brand icon. |
| `success` | `green` | Success messages, "paid" or "active" badges. |
| `danger` | `red` | Delete buttons, errors. |
| `warning` | `amber` | Warnings. |
| `info` | `blue` | Info messages and badges. |
| `gray` | `zinc` | Text, borders and backgrounds across the whole panel. |
| `sidebar` | `zinc` | The dark sidebar and the login page side panel. |
| `purple` | `violet` | Extra badge and stat color. |
| `teal` | `teal` | Extra badge and stat color. |
| `pink` | `pink` | Extra badge and stat color. |
| `indigo` | `indigo` | Extra badge and stat color. |

You only pass the ones you want to change. The rest keep their defaults.

### Palette names

Any of the Tailwind CSS palettes work: `slate`, `gray`, `zinc`, `neutral`, `stone`, `red`, `orange`, `amber`, `yellow`, `lime`, `green`, `emerald`, `teal`, `cyan`, `sky`, `blue`, `indigo`, `violet`, `purple`, `fuchsia`, `pink` and `rose`.

```python
colors={"primary": "emerald", "gray": "slate", "sidebar": "slate"}
```

### Hex colors

Pass one hex color and Tungsten makes the full set of 11 shades from it (lighter tints and darker shades), using your color as the middle shade:

```python
colors={"primary": "#ec5b1d"}
```

### Exact shades

If your brand guide gives exact shades, pass a dict from shade number to hex color. Shades you leave out fall back to the `500` shade.

```python
colors={
    "primary": {
        50: "#eef6ff", 100: "#d9eaff", 200: "#bcdaff", 300: "#8ec3ff", 400: "#59a1ff",
        500: "#337dfc", 600: "#1d5ef1", 700: "#1549de", 800: "#183db4", 900: "#1a378e", 950: "#152356",
    },
}
```

## Font

The panel uses the **Inter** font from Google Fonts. Pick another family by name:

```python
panel = Panel(..., font="Poppins")
```

The name must match a family on [Google Fonts](https://fonts.google.com). Weights 400 to 800 are loaded.

To use no web font at all (and make no request to Google), pass `None`. The panel then uses Inter if the user has it installed, or the system font.

```python
panel = Panel(..., font=None)
```

## Brand name and logo

```python
panel = Panel(
    ...,
    brand_name="Acme Shop",
    brand_logo="/static/acme-logo.svg",
)
```

- `brand_name` shows in the sidebar, on the login page and in the browser tab title (`Products · Acme Shop`).
- Without a logo, the sidebar shows a small Tungsten icon (in your primary color) next to the brand name.
- With `brand_logo`, the image replaces both the icon and the name. Use a logo that includes your name, and make sure it reads well on a dark background, because the sidebar is dark.

The logo is shown 32px high. Any URL works: a file served by your app, or a full `https://` address.

## Favicon

```python
panel = Panel(..., favicon="/static/favicon.png")
```

Without it, the browser tab shows the Tungsten icon.

## Dark mode

Users can switch between **light**, **dark** and **system** (follow the computer's setting) with the switch in the top bar. Their choice is remembered in the browser.

Pick the theme users see before they choose with `default_theme`:

```python
panel = Panel(..., default_theme="dark")   # "light", "dark" or "system" (default)
```

To keep the panel light and hide the switch, turn dark mode off:

```python
panel = Panel(..., dark_mode=False)
```

## Login page

The login page has your brand and a short message on the left side (on wide screens). Change the message with `login_hero`:

```python
panel = Panel(
    ...,
    login_hero={
        "heading": "Acme Shop back office",
        "text": "Orders, products and customers in one place.",
    },
)
```

Both texts are translated when the panel runs in another language.

## Sidebar footer

At the bottom of the sidebar there is a small card with the brand name and the Tungsten version. Replace it with your own HTML:

```python
from markupsafe import Markup

panel = Panel(
    ...,
    sidebar_footer=Markup('<p class="px-3 text-xs text-sidebar-400">Acme Shop · Support: help@acme.com</p>'),
)
```

Wrap the HTML in `Markup` so it is not escaped. To add something below the card instead of replacing it, use the `sidebar.footer` render hook (see [below](#render-hooks)).

## SPA mode

Normally each click on a link loads a full new page. In SPA mode ("single-page app"), Tungsten fetches the next page in the background and swaps it in. Moving around feels faster, with no white flash between pages.

```python
panel = Panel(..., spa=True)
```

Your code does not change; only how pages load. The browser's back and forward buttons keep working.

## Layout and UX options

### Collapsible sidebar

On desktop, a button in the top bar shrinks the sidebar to icons only, giving more room to wide tables. The choice is remembered in the browser. It is on by default; turn it off with:

```python
panel = Panel(..., sidebar_collapsible=False)
```

On phones and small screens, the sidebar always opens as a slide-in menu.

### Unsaved changes warning

When a user changes a form and tries to leave the page without saving, Tungsten asks first. It is on by default:

```python
panel = Panel(..., unsaved_changes_alerts=False)   # turn the warning off
```

### Keyboard shortcuts

These work in every panel:

| Keys | What happens |
| --- | --- |
| **Ctrl+S** / **⌘S** | Saves the form on create and edit pages. |
| **Ctrl+K** / **⌘K** | Opens the global search. |
| **↑** / **↓** | Moves through global search results. |

Give any action its own shortcut with `.keyboard_shortcut()`. `mod` means Ctrl on Windows and Linux, and ⌘ on a Mac:

```python
EditAction().keyboard_shortcut("mod+e")
```

See [Actions](actions).

## Overriding templates

Every screen is a Jinja2 template. To change one, copy it from Tungsten's `templates/tungsten/` folder into your own folder at the same path, edit it, and point the panel at your folder:

```python
panel = Panel(..., template_dirs=["templates"])
```

For example, `templates/tungsten/components/brand.html` replaces the brand block in the sidebar and on the login page. Your folders are checked first, and anything you do not override comes from Tungsten.

> [!WARNING]
> Overridden templates may need updating when you upgrade Tungsten. Override as little as you can, and prefer render hooks for small additions.

## Render hooks

Render hooks let you add HTML at named spots in the layout without overriding a template, for example a banner at the top of every page or a script in the `<head>`:

```python
from markupsafe import Markup

panel.render_hook("content.start", lambda: Markup(
    '<div class="tw-card mb-6 p-4 text-sm">Scheduled maintenance on Sunday at 10 PM.</div>'
))
```

See [Plugins and hooks](plugins-and-hooks) for the full list of hook names.
