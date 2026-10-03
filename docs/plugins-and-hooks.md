---
title: Plugins and render hooks
description: Package resources, pages and widgets as reusable plugins, and add your own HTML to fixed spots in the panel layout.
---

Plugins let you bundle resources, pages, widgets, navigation links, permissions and HTML into one class, and add it to any panel with one line. Render hooks let you put your own HTML into named spots of the layout, such as the sidebar footer or the page head.

## Writing a plugin

A plugin is a subclass of `Plugin` with an `id` and up to three methods:

```python
from markupsafe import Markup
from tungsten import NavigationItem, Plugin

from .resources import CategoryResource, PostResource
from .widgets import LatestPosts


class BlogPlugin(Plugin):
    id = "blog"

    def register(self, panel):
        panel.resources([PostResource, CategoryResource])
        panel.widgets([LatestPosts])
        panel.navigation_group("Blog", icon="newspaper")

    def boot(self, panel):
        panel.render_hook("sidebar.footer", lambda: Markup('<p class="px-3 text-xs">Blog v1.2</p>'))

    def permissions(self):
        return [("blog.publish", "Publish posts")]
```

Add it to a panel:

```python
panel.plugin(BlogPlugin())
```

> [!TIP]
> `tungsten make:plugin Blog` writes a starter plugin to `admin/plugins/blog_plugin.py`. See [CLI](cli).

### Plugin methods

| Method | When it runs | Use it to |
| --- | --- | --- |
| `register(panel)` | Right away, when you call `panel.plugin(...)` | Add resources, pages, widgets, navigation items and groups |
| `boot(panel)` | Once, just before the panel starts serving (when it is mounted) | Add render hooks, or anything that needs the other registrations done |
| `permissions()` | When the Roles screen is drawn | Return extra `(permission, label)` pairs to show in the Roles screen |

A plugin can call any public `Panel` method on the panel it receives:

| Panel method | What it adds |
| --- | --- |
| `panel.resources([...])` | [Resources](resources) |
| `panel.pages([...])` | [Custom pages](custom-pages) |
| `panel.widgets([...])` | Dashboard [widgets](widgets) |
| `panel.navigation_items([...])` | Extra sidebar links (`NavigationItem`) |
| `panel.navigation_group(label, icon=None, collapsed=False, collapsible=True)` | A sidebar group |
| `panel.user_menu_item(label, url, icon=None)` | A link in the user menu |
| `panel.render_hook(name, fn)` | HTML at a named spot (see below) |
| `panel.routes` | Your own routes (see below) |

### Adding links

Use `NavigationItem` for a sidebar link:

```python
from tungsten import NavigationItem, Plugin


class DocsPlugin(Plugin):
    id = "docs"

    def register(self, panel):
        panel.navigation_items([
            NavigationItem("Documentation", "https://docs.acme.example", icon="book-open",
                           group="Settings", sort=100, new_tab=True),
        ])
        panel.user_menu_item("Help center", "https://help.acme.example", icon="life-buoy")
```

`NavigationItem` takes `label`, `url`, `icon`, `group`, `sort`, `badge`, `badge_color`, `parent`, `new_tab` and `visible` (a bool or a closure, e.g. `lambda user: user.is_admin`). See [Navigation](navigation).

### Plugin permissions

Permissions from `permissions()` appear in the [Roles screen](roles-and-permissions) as checkboxes, grouped by the part before the dot. Check them anywhere with `ctx.can()`:

```python
Action("publish").visible(lambda ctx: ctx.can("blog.publish"))
```

### Plugin settings

A plugin is a normal Python object, so give it settings through `__init__`:

```python
class BlogPlugin(Plugin):
    id = "blog"

    def __init__(self, navigation_group="Blog", show_widget=True):
        self.navigation_group = navigation_group
        self.show_widget = show_widget

    def register(self, panel):
        PostResource.navigation_group = self.navigation_group
        panel.resources([PostResource])
        if self.show_widget:
            panel.widgets([LatestPosts])


panel.plugin(BlogPlugin(navigation_group="Content"))
```

Get a plugin back by its id with `panel.get_plugin("blog")`. It returns `None` if the plugin isn't added.

## Render hooks

A render hook puts your HTML into a fixed spot in the layout. Register a function for a hook name. Tungsten calls it each time that spot is drawn:

```python
from markupsafe import Markup

panel.render_hook("head.end", lambda: Markup('<link rel="stylesheet" href="/static/admin.css">'))
panel.render_hook("topbar.end", lambda: Markup('<span class="text-xs text-gray-500">Staging</span>'))
```

You can call `panel.render_hook()` from a plugin's `boot()`, or directly on the panel. Several functions can use the same hook. They are drawn in the order you added them.

### Using the built-in JavaScript libraries

To keep pages light, the big libraries (Chart.js, Trix, Tom Select, SortableJS and the QR code maker) load only on pages that use them. If your own script needs one, ask for it with `twNeed()` first:

```python
panel.render_hook("body.end", lambda: Markup("""
<script>
  twNeed("chart").then(() => new Chart(document.getElementById("my-chart"), {type: "bar", data: {...}}));
</script>
"""))
```

The names are `chart`, `trix`, `select`, `sortable` and `qr`. `twNeed()` loads each library once and returns a promise.

### Hook names

| Hook | Where it appears |
| --- | --- |
| `head.end` | At the end of `<head>`, on every page (including login) |
| `body.start` | Right after `<body>` opens, on every page |
| `body.end` | Just before `</body>`, on every page |
| `sidebar.nav.start` | At the top of the sidebar navigation |
| `sidebar.nav.end` | At the bottom of the sidebar navigation |
| `sidebar.footer` | At the bottom of the sidebar, below the brand card |
| `topbar.start` | In the top bar, before the global search |
| `topbar.end` | In the top bar, on the right, before the theme and notification buttons |
| `user-menu.items` | In the user menu, after "My profile" and your menu items |
| `content.start` | Above the main content of every panel page |
| `content.end` | Below the main content of every panel page |
| `auth.login.form.after` | Under the login form |
| `resource.list.before-table` | On every resource list page, just above the table |

### Hook functions get what they ask for

Like other closures, the function can ask for `ctx`, `panel` and `user`:

```python
from markupsafe import Markup, escape


def staging_banner(user):
    name = escape(user.name) if user else "guest"
    return Markup(f'<div class="mb-4 rounded-lg bg-warning-50 p-3 text-sm">Staging server. Hi {name}!</div>')


panel.render_hook("content.start", staging_banner)
```

On the login page and other sign-in pages there is no signed-in user, so `user` is `None`.

The function can return `Markup`, a string, or `None` to show nothing. Whatever it returns is placed in the page **as HTML, without escaping**.

> [!WARNING]
> Because hook output is not escaped, escape any user data you put in it (with `markupsafe.escape`), as in the example above.

### Showing a hook on one page only

Hooks run on every page that has that spot. Use the request to decide:

```python
def products_note(ctx):
    if not ctx.request.url.path.startswith(ctx.url("products")):
        return None
    return Markup('<p class="mb-4 text-sm text-gray-500">Prices include GST.</p>')


panel.render_hook("resource.list.before-table", products_note)
```

### Rendering a template

For bigger pieces of HTML, render a Jinja template with the panel's renderer. The template can use the same helpers as Tungsten's own templates, such as `__()` and `icon()`:

```python
def help_card(ctx):
    return ctx.panel.renderer.render("admin/help-card.html", ctx=ctx)


panel = Panel(..., template_dirs=["templates"])
panel.render_hook("sidebar.nav.end", help_card)
```

## Adding routes

`panel.routes` is a decorator for adding your own FastAPI routes to the panel app. Your function gets the panel's app (as `router`) and the panel:

```python
@panel.routes
def blog_routes(router, panel):
    @router.get("/blog/api/stats")
    def blog_stats():
        return {"posts": 42}
```

The route is served under the panel path, here `/admin/blog/api/stats`.

> [!WARNING]
> These are plain FastAPI routes. They don't check login, permissions or the CSRF token, so protect them yourself.
>
> Any path works, even short ones like `/admin/feed`. Your routes come before the panel's page and resource routes, so a route with the same path as a page or resource (like `/admin/products`) replaces it. Pick paths that don't clash.

## Overriding templates

Plugins and apps can also replace any of Tungsten's templates. Pass `template_dirs` to the panel and put a file at the same path as the built-in one:

```python
panel = Panel(..., template_dirs=["templates"])
# templates/tungsten/components/brand.html now replaces the built-in brand block
```

See [Theming](theming) for more.
