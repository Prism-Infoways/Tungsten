# tungsten-pwa

PWA plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.

Your team can install the panel like an app on Android, iPhone, Windows, Mac and Linux. It opens in its own window with your icon and name, loads faster, and shows a clean offline page when the internet is down.

## What you get

- **Install app** button in the top bar (Chrome, Edge, Samsung Internet, Android). On iPhone and iPad: Share, then **Add to Home Screen**.
- **Web app manifest** with your brand name, theme color (taken from your primary color) and icons. Tungsten icons are built in; pass your own with `icons=`.
- **App shortcuts**: a long press on the app icon (or right click on desktop) opens pages like *New order* directly.
- **Faster loading**: CSS, JavaScript, fonts and images are cached on the device.
- **Offline page** instead of the browser's error page, which reloads by itself when the internet is back.
- **Offline bar** at the bottom of the panel while the device is offline.
- **Safe by design**: pages and data are **never** cached. They always come from your server, so nobody sees old data or another person's data, and login, logout, CSRF and permissions work exactly as before. Form posts and HTMX requests are not touched.
- Works with the SPA mode, many panels on one site, panels at `/` or at a path, and every other plugin's pages.

## Install

```bash
pip install tungsten-pwa
```

```python
from tungsten_pwa import PWAPlugin

panel.plugin(PWAPlugin())
```

That's it. Service workers need **https** (or `http://localhost` / `http://127.0.0.1` while you develop).

### Options

```python
PWAPlugin(
    name="Acme Admin",                 # default: panel brand_name
    short_name="Acme",                 # name under the icon on a phone (keep it short)
    description="Orders and customers on the go",   # default: panel brand_tagline
    theme_color="#4f46e5",             # default: your primary color
    background_color="#ffffff",        # splash screen color
    display="standalone",              # or "fullscreen", "minimal-ui", "browser"
    start_path="",                     # page the app opens on, e.g. "orders"
    icons=[                            # your own icons (PNG, at least 192 and 512)
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    apple_touch_icon="/static/apple-touch-icon.png",  # 180x180 PNG for iPhone
    shortcuts=[("New order", "orders/create"), ("Customers", "customers")],
    precache=["/static/logo.svg"],     # extra files to save on install
    install_button=True,               # Install app button in the top bar
    offline_banner=True,               # "You are offline" bar
    offline_title="You are offline",
    offline_text="Check your internet connection. This page opens again by itself when you are back online.",
)
```

### Shortcuts from other plugins

With [Quick Create](https://tungsten.prisminfoways.com/docs/quick-create) (`tungsten-quick-create`) installed, the app gets *New ...* shortcuts for your first resources by itself.

Any plugin can add app shortcuts. Add a `pwa_shortcuts` method to your plugin:

```python
class OrdersPlugin(Plugin):
    id = "orders"

    def pwa_shortcuts(self, panel):
        return [("New order", "orders/create"), {"name": "Today's orders", "url": "orders?tab=today"}]
```

Or from your own code:

```python
panel.get_plugin("pwa").add_shortcut("New invoice", "invoices/create")
```

A shortcut URL is a panel path (`"orders/create"`) or a full path (`"/admin/orders"`).

### Turning it off

Removing the plugin leaves the old service worker in browsers that installed the app. To remove it cleanly, deploy once with:

```python
panel.plugin(PWAPlugin(uninstall=True))
```

Each browser then deletes the worker and its caches on the next visit. After a few weeks you can remove the plugin.

## How it works

| Request | What the service worker does |
| --- | --- |
| Page (navigation) | Always from the server. If the network fails, the offline page. |
| CSS / JS with `?v=` hash | From the cache first (these files never change). |
| Other images, fonts, plugin files | From the cache, refreshed in the background. |
| Form posts, HTMX, exports, API, anything else | Not touched. |

The worker gets a new version whenever Tungsten's assets or your settings change. Browsers then install it by themselves and delete the old caches. Nothing personal is ever cached, so there is nothing to clear on logout.

Addresses it adds under your panel path: `/_tw/pwa/manifest.webmanifest`, `/_tw/pwa/sw.js` and `/_tw/pwa/offline`.

## Try it

```bash
pip install -e . -e plugins/pwa uvicorn
uvicorn plugins.pwa.example:app --reload
```

Open http://127.0.0.1:8000/admin and sign in with `admin@example.com` / `password`.

Full guide: https://tungsten.prisminfoways.com/docs/pwa
