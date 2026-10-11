---
title: Install as an app (PWA)
description: Let your team install the Tungsten panel like an app on Android, iPhone, Windows and Mac, with app icons, shortcuts, faster loading and an offline page.
---

The `tungsten-pwa` plugin turns your panel into a Progressive Web App (PWA). Your team can install it from the browser, and it then opens in its own window with your name and icon, like any other app on their phone or computer.

## Install

```bash
pip install tungsten-pwa
```

```python
from tungsten_pwa import PWAPlugin

panel.plugin(PWAPlugin())
```

Your site must use **https**. While you develop, `http://localhost` and `http://127.0.0.1` work too.

## What your team sees

- An **Install app** button in the top bar in Chrome, Edge and on Android. On iPhone and iPad they tap Share, then **Add to Home Screen**.
- The app opens on its own, without the browser's address bar, in your brand color.
- A long press on the app icon (or a right click on a computer) shows **shortcuts** such as *New order*.
- Pages open faster, because CSS, JavaScript, fonts and images are kept on the device.
- When the internet is down, a clean **You are offline** page shows instead of the browser's error. It reloads by itself when the internet is back.
- A small **offline bar** at the bottom of the panel while the device is offline.

> [!NOTE]
> Pages and data are never cached. They always come from your server, so nobody sees old data or another person's data. Login, logout, CSRF protection and permissions work exactly as before, and form posts and HTMX requests are not touched.

## Options

```python
PWAPlugin(
    name="Acme Admin",                 # default: the panel's brand_name
    short_name="Acme",                 # name under the icon on a phone
    description="Orders on the go",    # default: the panel's brand_tagline
    theme_color="#4f46e5",             # default: your primary color
    background_color="#ffffff",        # splash screen color
    display="standalone",              # or "fullscreen", "minimal-ui", "browser"
    start_path="orders",               # the page the app opens on (default: the dashboard)
    shortcuts=[("New order", "orders/create"), ("Customers", "customers")],
    install_button=True,
    offline_banner=True,
    offline_title="You are offline",
    offline_text="Check your internet connection. This page opens again by itself when you are back online.",
)
```

## Your own icons

Tungsten icons are built in. To use your logo, pass PNG icons of at least 192 and 512 pixels. A *maskable* icon has its logo in the middle 80%, so Android can cut it into a circle or a rounded square.

```python
PWAPlugin(
    icons=[
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    apple_touch_icon="/static/apple-touch-icon.png",   # 180x180, for iPhone and iPad
)
```

## Shortcuts from other plugins

With [Quick Create](https://tungsten.prisminfoways.com/docs/quick-create) (`tungsten-quick-create`) installed, the app gets *New ...* shortcuts for your first resources by itself.

Any plugin can add app shortcuts with a `pwa_shortcuts` method. It returns `(label, url)` pairs or dicts with `name`, `url` and an optional `description`:

```python
class OrdersPlugin(Plugin):
    id = "orders"

    def pwa_shortcuts(self, panel):
        return [("New order", "orders/create"), {"name": "Today's orders", "url": "orders?tab=today"}]
```

You can also add one from your own code:

```python
panel.get_plugin("pwa").add_shortcut("New invoice", "invoices/create")
```

A URL is a panel path such as `"orders/create"`, or a full path such as `"/admin/orders"`. Shortcuts with the same URL are shown once. A plugin whose `pwa_shortcuts` fails is skipped and logged, so it never breaks the app.

## How the caching works

| Request | What happens |
| --- | --- |
| A page | Always from your server. If the network fails, the offline page. |
| Tungsten CSS and JavaScript (with a `?v=` hash) | From the device first. These files never change. |
| Other images, fonts and plugin files | From the device, refreshed in the background. |
| Form posts, HTMX requests, exports, APIs | Not touched. |

When you upgrade Tungsten or change the plugin settings, the app gets a new version. Browsers install it by themselves on the next visit and delete the old files. Each panel on a site keeps its own files, so `/admin` and `/portal` never mix.

The plugin adds three addresses under your panel path: `/_tw/pwa/manifest.webmanifest`, `/_tw/pwa/sw.js` and `/_tw/pwa/offline`. They work without login and never show any user's data.

## Turning it off

Taking the plugin out leaves the old service worker in browsers that installed the app. To remove it cleanly, deploy once with:

```python
panel.plugin(PWAPlugin(uninstall=True))
```

Each browser then removes the worker and its files on the next visit. After a few weeks you can take the plugin out.

## Questions

**Does it work on iPhone?** Yes. Open the panel in Safari, tap Share, then Add to Home Screen. iPhone has no install button, so the top bar button shows only in browsers that support it.

**Can people use the panel with no internet?** They can open the app and see the offline page. Pages and data need the internet, because they are never stored on the device. That keeps data safe on shared and lost phones.

**Why don't I see the Install app button?** The site must be on https, and the browser must support installing (Chrome, Edge, Samsung Internet, Android). The button also hides once the app is installed.
