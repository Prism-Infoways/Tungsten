---
title: Navigation
description: Control the sidebar with groups, icons, sort order, badges and nested items, and set up global search and the user menu.
---

Tungsten builds the sidebar for you. Every resource and custom page gets a menu item, and you can group, sort, nest and decorate them with a few class attributes.

## How items get into the sidebar

Each registered [resource](resources) and [custom page](custom-pages) adds one item. The dashboard comes first.

```python
panel.resources([ProductResource, OrderResource, CustomerResource])
panel.pages([Reports])
```

An item only shows when the current user may open it. A resource needs the `view_any` permission, and a page needs its `permission` (if it has one). See [Roles and permissions](roles-and-permissions).

To keep something out of the sidebar while still being able to open it by URL, set `show_in_navigation = False`:

```python
class TagResource(Resource):
    model = Tag
    show_in_navigation = False
```

## Labels

A resource's item uses its plural label (`Products` for a `Product` model). A page uses its title. Change it with `navigation_label`:

```python
class PostResource(Resource):
    model = Post
    navigation_label = "Blog"
```

Labels are translated automatically when the panel runs in another language. See [Translations](translations).

## Icons

Set `icon` to any [Lucide](https://lucide.dev/icons) icon name:

```python
class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"
```

The icons ship inside the package. Some Heroicon-style names also work, such as `heroicon-o-users` or `cog-6-tooth`, so names copied from Filament projects usually keep working. An unknown name shows a plain circle.

Resources use `file-text` and pages use `file` when you set no icon.

To show a different icon while the item is the current page, set `active_icon` too:

```python
class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"
    active_icon = "shopping-bag"
```

## Sort order

Items are sorted by `navigation_sort` (lowest first), then by label:

```python
class UserResource(Resource):
    model = User
    navigation_sort = 1

class OrderResource(Resource):
    model = Order
    navigation_sort = 3
```

The default is `0`. The dashboard uses `-100`, so it stays on top.

## Groups

Put items under a heading with `navigation_group`:

```python
class ProductResource(Resource):
    model = Product
    icon = "package"
    navigation_group = "Catalog"

class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"
    navigation_group = "Shop"
```

Items without a group appear at the top, above all groups. Users can click a group heading to fold it.

### Ordering groups

By default, groups appear in the order their first item comes up. To fix the order, list the groups on the panel:

```python
panel = Panel(
    ...,
    navigation_groups=["Shop", "Catalog", "Marketing", "Settings"],
)
```

Groups you do not list still appear, after the listed ones.

### Group icons

To show an icon next to a group heading, pass a `NavigationGroup` instead of a plain name:

```python
from tungsten import NavigationGroup

panel = Panel(
    ...,
    navigation_groups=[
        NavigationGroup("Shop", icon="store"),
        NavigationGroup("Catalog", icon="package"),
        "Settings",
    ],
)
```

You can also add a group with a method, which is handy in [plugins](plugins-and-hooks):

```python
panel.navigation_group("Blog", icon="newspaper")
```

### Folded and fixed groups

A group can start folded with `collapsed=True`. It still opens by itself when it holds the current page. With `collapsible=False`, the heading is plain text and the group always stays open:

```python
panel = Panel(
    ...,
    navigation_groups=[
        "Shop",
        NavigationGroup("Reports", collapsed=True),
        NavigationGroup("Settings", collapsible=False),
    ],
)

panel.navigation_group("Blog", icon="newspaper", collapsed=True)
```

## Badges

A badge is a small count or label next to the item, such as the number of pending orders. Define a `navigation_badge` class method that returns the value:

```python
from sqlalchemy import func, select


class OrderResource(Resource):
    model = Order
    navigation_badge_color = "danger"

    @classmethod
    def navigation_badge(cls, db):
        pending = db.scalar(select(func.count()).select_from(Order).where(Order.status == "pending"))
        return pending or None
```

- The method can ask for `db`, `user` or `ctx`. Tungsten passes in what it names.
- Return `None` (or an empty string) to hide the badge. Above, the badge disappears when nothing is pending.
- `navigation_badge_color` picks the color: `primary` (default), `success`, `danger`, `warning`, `info` or `gray`.

Custom pages support `navigation_badge` and `navigation_badge_color` in the same way.

> [!TIP]
> The badge runs on every page load. Keep the query cheap, like a single `count()`.

## Nested items

An item can sit under another item. Set `navigation_parent` to the parent's label:

```python
class CategoryResource(Resource):
    model = Category
    plural_label = "Categories"
    navigation_group = "Catalog"
    navigation_parent = "Products"


class BrandResource(Resource):
    model = Brand
    navigation_group = "Catalog"
    navigation_parent = "Products"
```

Now **Categories** and **Brands** appear indented under **Products**. The parent gets a small arrow to open and close the list, and it opens by itself when one of its children is the current page.

Some things to know:

- Use the parent's label in English, as written in your code. It still works when the panel is shown in another language.
- Nesting is one level deep.
- Child items show their label and badge, without an icon.
- Children appear in the order they were registered.

Pages and custom links can use `navigation_parent` too.

## Custom links

Add your own sidebar links with `NavigationItem`, for example to documentation or another app:

```python
from tungsten import NavigationItem

panel.navigation_items([
    NavigationItem("Documentation", "https://docs.example.com", icon="book-open",
                   group="Settings", sort=100, new_tab=True),
    NavigationItem("Shop front", "/", icon="store"),
])
```

`NavigationItem` takes these fields:

| Field | Default | What it does |
| --- | --- | --- |
| `label` | (required) | The text shown. |
| `url` | `"#"` | Where the link goes. |
| `icon` | `None` | A Lucide icon name. |
| `group` | `None` | The group to show it in. |
| `sort` | `0` | Sort order inside its group. |
| `badge` | `None` | A fixed badge value. |
| `badge_color` | `"primary"` | The badge color. |
| `parent` | `None` | The label of an item to nest it under. |
| `active_prefix` | the `url` | Highlight the item when the current path starts with this. |
| `active_icon` | `None` | An icon shown instead of `icon` while the item is highlighted. |
| `children` | `[]` | Items to nest under this one (other items can also join with `parent`). |
| `new_tab` | `False` | Open the link in a new browser tab. |
| `visible` | `True` | `True`, `False`, or a function that gets `user` or `ctx` and returns whether to show it. |

For example, a link that only staff can see:

```python
NavigationItem("Server status", "/status", icon="activity", visible=lambda user: user.is_staff)
```

## Clusters

A cluster puts several resources and pages behind **one** menu item, with their own sub-menu. Use it for areas with many small screens, like Settings:

```python
from tungsten.navigation import Cluster


class Settings(Cluster):
    icon = "settings"
    navigation_group = "Admin"
    description = "Taxes, currencies and shop details."   # optional line under the sub-menu title


class TaxResource(Resource):
    model = Tax
    cluster = Settings


class ShopDetails(Page):
    cluster = Settings
    navigation_sort = -1      # first in the sub-menu
```

- The main menu shows one **Settings** item. It is highlighted while any page of the cluster is open.
- Clicking it (or opening `/admin/settings`) goes to the first page of the cluster the user may open.
- Every page of the cluster shows the sub-menu beside the content. Members are sorted by their `navigation_sort`, then by label, and only show when the user may open them.
- A cluster with no page the user may open is hidden.

`Cluster` takes these class attributes:

| Attribute | Default | What it does |
| --- | --- | --- |
| `label` | from the class name | The name in the menu and above the sub-menu. |
| `slug` | from the class name | The URL that opens the first page (`/admin/settings`). |
| `icon` | `"squares-2x2"` | The menu icon. |
| `active_icon` | `None` | An icon shown while the cluster is open. |
| `navigation_group` | `None` | The menu group of the cluster's item. |
| `navigation_sort` | `0` | Its order in that group. |
| `navigation_label` | `None` | A different label for the menu item. |
| `sub_navigation_position` | `"start"` | `"start"` (beside the page), `"end"` (on the other side) or `"top"` (tabs above). |
| `description` | `None` | A short line under the sub-menu title. |

Members keep their own URLs (`/admin/taxes`), so old links keep working.

## Sub-menu on a record's pages

Give a resource's record pages their own sub-menu with `record_sub_navigation`. It lists page names and/or your own `NavigationItem` links:

```python
class CustomerResource(Resource):
    model = Customer
    record_sub_navigation = ("view", "edit")
    sub_navigation_position = "top"      # tabs; or "start" / "end" for a side menu
```

The View and Edit links only show when the resource has that page and the user may open it. For links that depend on the record, override `get_record_sub_navigation`:

```python
class CustomerResource(Resource):
    record_sub_navigation = ("view", "edit")

    @classmethod
    def get_record_sub_navigation(cls, ctx, record):
        return super().get_record_sub_navigation(ctx, record) + [
            NavigationItem("Orders", OrderResource.get_url(ctx, customer=record.id), icon="shopping-cart"),
        ]
```

The link of the page you are on is highlighted. A record sub-menu wins over a cluster's sub-menu on that record's pages.

## Menu along the top

To show the menu in a bar along the top instead of the sidebar:

```python
panel = Panel(..., top_navigation=True)
```

- Items without a group show as links in the bar.
- Each group becomes a dropdown with its items. Items with children also open a dropdown.
- The brand and the tenant switcher move into the bar.
- On phones the menu button still opens the usual side menu.

Plugins can add HTML at the start or end of the bar with the `topbar.nav.start` and `topbar.nav.end` render hooks.

## The dashboard item

The dashboard is a page too. To change its label, icon or position, subclass `Dashboard` and pass it to the panel:

```python
from tungsten import Dashboard


class ShopDashboard(Dashboard):
    title = "Overview"
    icon = "chart-pie"


panel = Panel(..., dashboard=ShopDashboard)
```

Set `show_in_navigation = False` on it to hide the item (the panel root still shows the dashboard). See [Widgets](widgets) for what goes on the dashboard.

## Global search

The search box in the top bar finds records across all your resources, and also matches menu items by name. Users can open it from anywhere with **Ctrl+K** (or **⌘K** on a Mac), and move through the results with the arrow keys.

A resource takes part when you list the attributes to search:

```python
class ProductResource(Resource):
    model = Product
    global_search_attributes = ["name", "sku", "category.name"]
```

- A dotted name like `category.name` searches through a relationship.
- Results show up to `global_search_limit` records per resource (default `5`).
- A result links to the edit page when the user may edit the record, otherwise to the view page.
- Only resources the user can list (`view_any`) are searched. Soft-deleted records are left out.

### What a result shows

By default, a result shows the record's title (from `record_title_attribute`, or a `name`, `title`, `label` or `email` attribute). You can add details and a picture:

```python
class ProductResource(Resource):
    model = Product
    global_search_attributes = ["name", "sku"]

    @classmethod
    def global_search_details(cls, record):
        return {"Category": record.category.name if record.category else "-", "SKU": record.sku}

    @classmethod
    def global_search_image(cls, record):
        return record.image_url
```

| Method | Returns |
| --- | --- |
| `global_search_title(record)` | The main text of the result. |
| `global_search_details(record)` | A dict shown under the title as `Key: value · Key: value`. |
| `global_search_image(record)` | An image URL to show instead of the resource icon. |

### Turning it off

```python
panel = Panel(..., global_search=False)
```

This removes the search box from the top bar, the **Search menu...** button in the sidebar and the **Ctrl+K** shortcut.

## User menu

The menu in the top-right corner shows the user's name and role, a **My profile** link, a language picker (when the panel has more than one language) and **Sign out**.

Add your own links with `user_menu_item`:

```python
panel.user_menu_item("Billing", "/billing", icon="credit-card")
panel.user_menu_item("Help center", "https://help.example.com", icon="life-buoy")
```

The profile link comes from `Auth(profile=True)`, which is the default. See [Authentication](authentication).

For anything more than a link, use the `user-menu.items` render hook. The sidebar also has hooks: `sidebar.nav.start`, `sidebar.nav.end` and `sidebar.footer`. See [Plugins and hooks](plugins-and-hooks).
