---
title: Table columns
description: Every table column type, from text and badges to images, icons, colors and inline-editable cells.
---

Columns decide what each table cell shows. Most of the time you will use `TextColumn`, which can also show badges, money, dates, icons and avatars. Other columns show images, icons and colors, or let users edit a value right in the table.

```python
from tungsten.tables import (
    BadgeColumn, CheckboxColumn, ColorColumn, IconColumn, ImageColumn, SelectColumn,
    TextColumn, TextInputColumn, ToggleColumn, ViewColumn,
)
```

## Options for every column

| Method | What it does |
| --- | --- |
| `label(text)` | The heading. By default it comes from the name: `customer.name` becomes "Customer name". |
| `sortable(condition=True, query=None)` | Users can sort by this column. See [Sorting](tables#sorting). |
| `searchable(condition=True, query=None, columns=None, is_global=True, is_individual=False)` | Include it in the table search. `is_individual=True` adds a search box for this column only. See [Search](tables#search). |
| `toggleable(condition=True, hidden_by_default=False)` | Users can show or hide it. See [Table features](table-features#show-and-hide-columns). |
| `state(fn)` | Compute the value instead of reading an attribute. Also `get_state_using()`. |
| `format_state_using(fn)` | Change how the value is shown. `fn` gets `state` and `record`. Also `formatted()`. |
| `default(value)` | Value to use when the attribute is `None` (or an empty list). |
| `placeholder(text)` | Grey text shown when a text cell is empty. |
| `description(text, position="below")` | A second line of smaller text, `"below"` or `"above"`. |
| `url(fn, open_in_new_tab=False)` | Make the cell a link. |
| `tooltip(text)` | Text shown on hover. |
| `alignment("start" \| "center" \| "end")` | Align the cell. Shortcuts: `align_center()`, `align_end()`. |
| `width(value)` | Column width, e.g. `"120px"` or `"20%"`. |
| `wrap()` | Let long text wrap onto several lines. |
| `extra_classes(classes)` | Extra CSS classes on the cell content. |
| `summarize(...)` | Totals in the table footer. See [Table features](table-features#totals-and-summaries). |
| `visible(condition)` / `hidden(condition)` | Show or hide the whole column. |

Most options take a value or a closure. Column closures can ask for `record`, `state` (the cell value), `column`, plus `user`, `db` and the other [table closure arguments](tables#closures-in-tables).

```python
TextColumn("orders_count").label("Orders").state(lambda record: len(record.orders)).align_end()
TextColumn("city").description(lambda record: record.state)
TextColumn("published_at").date().placeholder("Not published")
TextColumn("website").url(lambda record: record.website, open_in_new_tab=True)
```

## TextColumn

Shows text. A dotted name reads through relationships. When the path goes through a to-many relationship (like `tags.name`), the cell shows every value.

```python
TextColumn("name").searchable().sortable().weight("medium")
TextColumn("tags.name").label("Tags").badge()
```

Values are formatted for you: dates as `05 Mar 2025`, booleans as Yes/No, enums by their `label` (or their name).

### Badges and colors

`badge()` shows the value as a colored pill. Pick the color with `color()` (a name or a closure) or `colors()` (a map from color to values).

```python
TextColumn("category.name").badge().color("info")

TextColumn("status").badge().colors({
    "success": "paid",
    "warning": ["pending", "processing"],
    "danger": lambda state: state in ("failed", "refunded"),
})

TextColumn("is_active").label("Status").badge()
    .format_state_using(lambda state: "Active" if state else "Inactive")
    .color(lambda state: "success" if state else "danger")
```

In `colors()`, each value can be a single value, a list, or a function that gets `state`. Badges with no matching color are gray.

If the value is an enum with a `color` attribute, the badge uses it with no extra code:

```python
class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"

    @property
    def color(self):
        return {"pending": "danger", "paid": "success"}[self.value]

TextColumn("status").badge()
```

Colors are `primary`, `success`, `warning`, `danger`, `info`, `gray`, `purple`, `teal`, `pink` and `indigo`. Without `badge()`, `color()` colors the text.

`BadgeColumn("status")` is a shortcut for `TextColumn("status").badge()`.

### Icons

```python
TextColumn("stock").icon("circle-dot").color(lambda record: "danger" if record.stock < 10 else "success")

TextColumn("email").icon(lambda record: "badge-check" if record.email_verified_at else None, "after")
    .icon_color("success")

TextColumn("priority").icons({"arrow-up": "high", "minus": ["normal", "low"]})
```

| Method | What it does |
| --- | --- |
| `icon(icon, position="before")` | A [Lucide](https://lucide.dev) icon name or closure; position `"before"` or `"after"`. |
| `icons({icon: values})` | Pick the icon from the value, like `colors()`. |
| `icon_color(color)` | Color the icon only; the text keeps its own color. |

### Number, money and date formats

```python
TextColumn("price").money("INR")               # ₹1,299.00
TextColumn("price").money("INR", 0)            # ₹1,299
TextColumn("amount_paise").money("INR", divide_by=100)
TextColumn("views").numeric()                  # 12,345
TextColumn("rating").numeric(1)                # 4.5
TextColumn("created_at").date()                # 05 Mar 2025
TextColumn("created_at").datetime()            # 05 Mar 2025, 14:30
TextColumn("starts_at").time()                 # 14:30
TextColumn("created_at").since()               # 3 days ago
TextColumn("created_at").date("%Y-%m-%d")      # any strftime format
```

| Method | What it does |
| --- | --- |
| `money(currency="$", decimals=2, divide_by=1)` | Currency format. `USD`, `EUR`, `GBP`, `INR` and `JPY` become their symbol; any other text is used as is (`money("₹")`). |
| `numeric(decimals=0, thousands=True)` | Number with thousands separators. |
| `date(fmt="%d %b %Y")` | Date format. |
| `datetime(fmt="%d %b %Y, %H:%M")` | Date and time format. |
| `time(fmt="%H:%M")` | Time format. |
| `since()` | Relative time: "5 minutes ago", "in 2 days". |
| `prefix(text)`, `suffix(text)` | Text before or after the value. |

### Text style and length

| Method | What it does |
| --- | --- |
| `weight("medium" \| "semibold" \| "bold")` | Font weight. `bold()` is `weight("semibold")`. |
| `size("xs" \| "sm" \| "base" \| "lg")` | Font size (default `sm`). |
| `font_mono()` | Monospace font, good for codes and SKUs. |
| `limit(n)` | Cut the text after `n` characters, with "…". The full text shows on hover. |
| `words(n)` | Cut the text after `n` words. |
| `html()` | Render the value as HTML. It is cleaned first, so scripts are removed. |
| `copyable()` | Add a button that copies the value. |

```python
TextColumn("sku").label("SKU").font_mono().copyable()
TextColumn("short_description").limit(60).wrap()
```

### Lists of values

For to-many values (or a string you split), a cell shows several items.

| Method | What it does |
| --- | --- |
| `list()` | Show the values as a bulleted list. |
| `separator(",")` | Split a text value into items. |
| `limit_list(n)` | Show only the first `n` items, then "+3 more". |

```python
TextColumn("tags.name").label("Tags").badge().limit_list(2)
TextColumn("keywords").separator(",").badge().color("gray")
```

### Avatars

`avatar()` shows a picture before the text. Pass an attribute name, a closure that returns a URL or stored path, or `True` to show the initials only.

```python
TextColumn("name").avatar("avatar")
TextColumn("customer.name").avatar("customer.avatar")
TextColumn("name").avatar(lambda record: record.image, circular=False)
```

When there is no picture, the initials are shown. Stored file paths (from a [FileUpload](form-fields#fileupload)) are turned into URLs for you.

## ImageColumn

Shows an image, or several when the value is a list of paths. Values can be full URLs or paths in the panel storage.

```python
ImageColumn("logo").circular()
ImageColumn("images").stacked().limit(3).size(32)
ImageColumn("photo").default_image_url("/static/placeholder.png")
```

| Method | What it does |
| --- | --- |
| `circular()` | Round images. |
| `square()` | Square images with sharp corners. By default the corners are slightly rounded. |
| `size(px)` | Width and height in pixels (default `40`). |
| `stacked()` | Overlap several images. |
| `limit(n)` | Show at most `n` images. |
| `default_image_url(url)` | Image to show when the value is empty. |

## IconColumn

Shows an icon chosen from the value.

```python
IconColumn("is_featured").boolean()

IconColumn("status")
    .icons({"circle-check": "published", "pencil": "draft", "archive": "archived"})
    .colors({"success": "published", "warning": "draft"})
```

| Method | What it does |
| --- | --- |
| `boolean()` | A green check for true, a red cross for false, nothing for `None`. |
| `true_icon(icon, color="success")`, `false_icon(icon, color="danger")` | Change the boolean icons. |
| `icon(icon)` | One icon (or a closure). |
| `icons({icon: values})` | Pick the icon from the value. |
| `color(color)`, `colors({color: values})` | Icon color. |
| `size("sm" \| "md" \| "lg")` | Icon size (default `md`). |

Icon columns are centered by default.

## ColorColumn

Shows a color swatch with its hex code. Pairs well with a [ColorPicker](form-fields#colorpicker) field.

```python
ColorColumn("color")
```

## ViewColumn

Renders the cell with your own Jinja template. The template gets `record`, `column`, `table` and `v` (`v.state` is the cell value).

```python
ViewColumn("rating", "shop/columns/stars.html")
```

```html
{# templates/shop/columns/stars.html #}
<span>{{ "★" * (v.state or 0) }}</span>
```

Add your template folder with `Panel(template_dirs=[...])`.

## Editable columns

These columns let users change a value right in the table. The change is saved as soon as they click or leave the input, and a small "Saved" message appears.

```python
ToggleColumn("is_visible").label("Visible")
CheckboxColumn("is_featured")
TextInputColumn("stock").integer().configure(lambda field: field.min_value(0))
SelectColumn("status").options({"draft": "Draft", "review": "In review", "published": "Published"})
```

The value is checked by a real [form field](form-fields) behind the scenes, so every field rule works. A bad value is not saved, and an error message explains why. Users without permission to update the record see the cell disabled.

### Options for all editable columns

| Method | What it does |
| --- | --- |
| `required()` | The value can't be empty. |
| `rules([fn, ...])` | Custom rules, like [field rules](forms#custom-rules). |
| `configure(fn)` | Change the hidden form field: `configure(lambda field: field.max_length(20))`. |
| `disabled(condition)` | Turn editing off, e.g. `disabled(lambda record: record.is_locked)`. |
| `before_state_updated(fn)` | Run before the new value is set. `fn` gets `state` and `record`. |
| `after_state_updated(fn)` | Run after the new value is set, before saving. |

```python
TextInputColumn("name").required().input_width("w-48").searchable().sortable()
TextInputColumn("website").configure(lambda field: field.url()).input_width("w-64")

ToggleColumn("is_active").after_state_updated(
    lambda record, state, db: db.add(AuditLog(message=f"{record.name} active={state}"))
)
```

The column name must be a normal attribute of the model (not a dotted path).

### ToggleColumn

An on/off switch. Clicking it flips the value.

### CheckboxColumn

A checkbox. Centered by default.

### TextInputColumn

A small text input. The value is saved when the input changes (on Enter or when the user leaves it).

| Method | What it does |
| --- | --- |
| `numeric()` | Number input, saved as a number. |
| `integer()` | Whole numbers only. |
| `input_width(css_class)` | Width class for the input (default `w-28`). |

### SelectColumn

A dropdown. Options work like a [Select field](form-fields#select): a dict, list, pairs, an Enum class or a closure.

```python
SelectColumn("status").options(OrderStatus)
```
