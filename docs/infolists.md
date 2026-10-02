---
title: Infolists
description: Show a record read-only on the view page, with formatted entries in the same layouts as forms.
---

An infolist is a read-only layout for one record. Instead of a disabled form, the view page shows nicely formatted values: badges, money, dates, icons, images and lists. Infolists use the same layouts as forms (sections, grids, tabs) and entries that format values like [table columns](table-columns).

## Adding an infolist

Give your resource an `infolist()` class method. It receives an empty infolist and returns it with a schema.

```python
from tungsten.forms import Group, Section
from tungsten.infolists import IconEntry, ImageEntry, KeyValueEntry, TextEntry


class ProductResource(Resource):
    model = Product

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Section("Product").column_span(2).schema([
                TextEntry("name").weight("semibold").size("lg").column_span("full"),
                TextEntry("description").html().column_span("full"),
                TextEntry("category.name").label("Category").badge().color("info"),
                TextEntry("tags.name").label("Tags").badge(),
                ImageEntry("images").stacked().column_span("full"),
            ]),
            Group([
                Section("Pricing").schema([
                    TextEntry("price").money("INR", 0).weight("bold"),
                    IconEntry("is_featured").label("Featured").boolean(),
                ]),
                Section("Attributes").schema([
                    KeyValueEntry("attributes").hidden_label().column_span("full"),
                ]).collapsible(),
            ]).columns(1),
        ])
```

Open a product's view page (`/admin/products/5`) to see it.

## Where infolists are used

- The **view page** of a resource.
- The popup of a `ViewAction`. This is how [simple resources](resources#simple-resources) and [relation managers](relation-managers#view-popup) show a record.

If `infolist()` is not defined (or returns `None`), these places show the form with every field disabled instead.

## Reading values

An entry's name is the attribute it shows. Use dot notation to go through relationships:

```python
TextEntry("customer.name").label("Customer")
TextEntry("tags.name").badge()        # to-many: one badge per tag
```

When the value is a list (a to-many relationship or a JSON list), each item is shown separately.

To show a computed value, use `state()`. To change how the value is written, use `formatted()`. Both take closures that get what they ask for, such as `record` and `state`.

```python
TextEntry("items_count").label("Items").state(lambda record: len(record.items))
TextEntry("status").formatted(lambda state: state.replace("_", " ").title())
```

> [!NOTE]
> On entries, use `formatted()`. The form-field method `format_state_using()` has no effect on an entry.

An empty value shows "—". Change it with `.placeholder("Not set")`, or show a fallback value with `.default(...)`.

## Common entry options

These work on every entry.

| Method | What it does |
| --- | --- |
| `label("...")` | The label. Default: made from the name (`created_at` → "Created at"). |
| `hidden_label()` | Hide the label. |
| `inline_label()` | Put the label to the left of the value instead of above it. |
| `helper_text("...")` | Small text under the value. |
| `hint("...", icon=None)` | Small text (and icon) at the end of the label row. |
| `column_span(2)` / `column_span("full")` | How many grid columns the entry takes. |
| `visible(fn)` / `hidden(fn)` | Show or hide. Closures can ask for `record` and `state`. |
| `placeholder("...")` | Text for an empty value. |
| `default(value)` | Value to use when the attribute is empty. |
| `state(fn)` | Compute the value instead of reading an attribute. |
| `formatted(fn)` | Change how the value is displayed. |
| `url(fn, open_in_new_tab=False)` | Make the value a link. |
| `tooltip("...")` | Tooltip on hover. |
| `description("...", position="below")` | Small extra text with the value. |

## Text entry

`TextEntry` is the main entry. It has every formatting option of `TextColumn`.

```python
TextEntry("status").badge().colors({"success": "paid", "danger": ["failed", "refunded"]})
TextEntry("total").money("INR")
TextEntry("created_at").datetime().inline_label()
TextEntry("email").copyable().icon("mail")
TextEntry("notes").words(30)
```

| Method | What it does |
| --- | --- |
| `badge()` | Show the value as a badge. |
| `color("success")` | Text or badge color. Can be a closure: `lambda state: ...`. |
| `colors({...})` | Pick a color by value: `{"success": "paid", "danger": ["failed", "refunded"]}`. |
| `icon("mail", position="before")` | An icon before (or `"after"`) the value. Can be a closure. |
| `icon_color("success")` | Color of the icon only. |
| `icons({...})` | Pick an icon by value, like `colors()`. |
| `money("INR", decimals=2, divide_by=1)` | Format as money. `INR`, `USD`, `EUR`, `GBP` and `JPY` become symbols; any other text is used as the symbol. |
| `numeric(decimals=0, thousands=True)` | Format as a number. |
| `date(fmt)` / `datetime(fmt)` / `time(fmt)` | Format dates with a `strftime` pattern. Defaults: `%d %b %Y`, `%d %b %Y, %H:%M`, `%H:%M`. |
| `since()` | Relative time, like "3 days ago". |
| `prefix("...")` / `suffix("...")` | Text before or after the value. |
| `limit(50)` | Cut the text after 50 characters. |
| `words(20)` | Cut the text after 20 words. |
| `weight("medium")` / `bold()` | Font weight: `medium`, `semibold`, `bold`. |
| `size("lg")` | Text size: `xs`, `sm`, `base`, `lg`. |
| `font_mono()` | Monospace font. |
| `copyable()` | Click to copy the value. |
| `html()` | Render the value as HTML (cleaned to safe tags). Good for rich text. |
| `list()` | Show list values as a bulleted list. |
| `separator(",")` | Split a text value into several items. |
| `limit_list(3)` | Show the first 3 items, then "+N more". |
| `avatar("photo")` | Show an image before the text (an attribute name or a closure). |

## Icon entry

`IconEntry` shows an icon. With `boolean()` it shows a check or a cross.

```python
IconEntry("is_featured").boolean()
IconEntry("is_active").boolean().true_icon("badge-check").false_icon("ban", color="gray")
IconEntry("status").icons({"clock": "pending", "truck": "shipped"}).colors({"warning": "pending", "info": "shipped"})
```

| Method | What it does |
| --- | --- |
| `boolean()` | Check icon for true, cross for false. |
| `true_icon(icon, color="success")` / `false_icon(icon, color="danger")` | Change the boolean icons. |
| `icon("star")` | A fixed icon (or a closure). |
| `icons({...})` / `colors({...})` | Pick the icon and color by value. |
| `color("warning")` | Icon color. |
| `size("lg")` | `sm`, `md` or `lg`. |

## Image entry

`ImageEntry` shows one image, or several when the value is a list. Paths from a `FileUpload` field are turned into URLs for you.

```python
ImageEntry("images").stacked().limit(4)
ImageEntry("avatar").circular().size(64)
```

| Method | What it does |
| --- | --- |
| `size(px)` | Image width and height in pixels. Default: `80`. |
| `circular()` / `square()` | Image shape. |
| `stacked()` | Overlap several images. |
| `limit(n)` | Show at most `n` images. |
| `default_image_url(url)` | Image to show when there is none. |

## Color entry

`ColorEntry` shows a color swatch and the value for a hex color, like one saved by a `ColorPicker`.

```python
ColorEntry("brand_color")
```

## Key-value entry

`KeyValueEntry` shows a dict (for example a JSON column filled by a `KeyValue` field) as a two-column table.

```python
KeyValueEntry("attributes").key_label("Attribute").value_label("Value")
```

## Repeatable entry

`RepeatableEntry` shows each item of a to-many relationship or a JSON list, with its own entries inside. Inside the schema, entry names are read from each item.

```python
from tungsten.infolists import RepeatableEntry, TextEntry

RepeatableEntry("items").columns(3).schema([
    TextEntry("product.name").label("Product"),
    TextEntry("quantity"),
    TextEntry("unit_price").money("INR"),
])
```

| Method | What it does |
| --- | --- |
| `schema([...])` | The entries shown for each item. |
| `columns(n)` | Grid columns inside each item. Default: `2`. |
| `grid(n)` | How many items per row. Default: `1`. |

For a JSON list of dicts, entry names are the dict keys.

## Layouts

Infolists use the form layouts from `tungsten.forms`. See [Form layouts](form-layouts) for all their options.

```python
from tungsten.forms import Fieldset, Grid, Section, Tab, Tabs

infolist.schema([
    Tabs().tabs([
        Tab("Details").icon("info").schema([
            TextEntry("name"),
            TextEntry("sku").font_mono(),
        ]),
        Tab("Shipping").icon("truck").schema([
            Grid(3).schema([TextEntry("city"), TextEntry("state"), TextEntry("pin_code")]),
        ]),
    ]),
    Section("Notes").description("Internal only.").collapsed().schema([
        TextEntry("notes").hidden_label().column_span("full"),
    ]),
])
```

| Layout | What it does |
| --- | --- |
| `Section("Heading")` | A card with a heading. Supports `description()`, `icon()`, `collapsible()`, `collapsed()`, `aside()`, `compact()`. 2 columns by default. |
| `Grid(3)` | Lay children out in 3 columns, without a card. |
| `Group([...])` | Group entries without a wrapper. Useful for a side column or one `visible()` rule. |
| `Fieldset("Label")` | A bordered box with a label. |
| `Tabs().tabs([Tab("...")])` | Tabs. `Tab` supports `icon()` and `badge()`. |

The infolist itself has 2 columns by default. Change it with `infolist.columns(3)`.
