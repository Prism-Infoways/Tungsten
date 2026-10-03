---
title: Form fields
description: Every form field type in Tungsten, with its own options and a short example.
---

This page lists every field in `tungsten.forms`. All fields also have the common options (label, default, required, helper text, visible, column span...) described on the [Forms](forms#common-field-options) page.

```python
from tungsten.forms import (
    Block, Builder, Checkbox, CheckboxList, ColorPicker, DatePicker, DateTimePicker, FileUpload,
    Hidden, KeyValue, Placeholder, Radio, Repeater, RichEditor, Select, TagsInput, Textarea,
    TextInput, TimePicker, Toggle, ToggleButtons,
)
```

## TextInput

A one-line input. By default it holds text; the methods below change its type and rules.

```python
TextInput("name").required().max_length(150)
TextInput("email").email().required().unique().prefix_icon("mail")
TextInput("price").numeric().prefix("₹").min_value(0)
TextInput("stock").integer().min_value(0).default(0)
TextInput("password").password().revealable().min_length(8)
```

| Method | What it does |
| --- | --- |
| `email()` | Email input; checks the format. |
| `url()` | URL input; must start with `http://` or `https://`. |
| `tel()` | Phone number input. |
| `password()` | Hidden characters. Never filled from the record. |
| `revealable()` | Adds an eye button to show a password. |
| `type(value)` | Any HTML input type, e.g. `"search"`. |
| `numeric()` | Number input. Saved as `int` or `Decimal`. |
| `integer()` | Whole numbers only. Saved as `int`. |
| `min_length(n)`, `max_length(n)`, `length(n)` | Text length limits. |
| `min_value(n)`, `max_value(n)` | Number limits (also `min()` / `max()`). Can be closures. |
| `step(n)` | Step for number inputs. |
| `regex(pattern, message=None)` | The value must match the pattern. |
| `same("field")` | Must equal another field, e.g. a password confirmation. |
| `prefix(text)`, `suffix(text)` | Text inside the input, before or after the value. |
| `prefix_icon(icon)`, `suffix_icon(icon)` | A [Lucide](https://lucide.dev) icon before or after the value. |
| `autocomplete(value)` | The HTML `autocomplete` value; `False` turns it off. |
| `datalist(options)` | Suggestions shown while typing (the user can still type anything). |

```python
TextInput("phone").tel().prefix("+91").placeholder("98765 43210")
TextInput("weight").numeric().suffix("kg").step(0.5)
TextInput("country").datalist(["India", "Nepal", "Sri Lanka"])
```

## Textarea

Several lines of text.

```python
Textarea("bio").rows(3).autosize().max_length(500).column_span("full")
```

| Method | What it does |
| --- | --- |
| `rows(n)` | Starting height in lines (default `3`). |
| `autosize()` | Grow taller as the user types. |
| `min_length(n)`, `max_length(n)` | Length limits. |

## Select

A dropdown. Options can be a dict, a list, a list of `(value, label)` pairs, an `Enum` class, or a closure that returns one of these.

```python
Select("status").options({"draft": "Draft", "published": "Published"}).default("draft")
Select("department").options(["Sales", "Marketing", "Support"])
Select("status").options(OrderStatus).required()          # an Enum class
```

When the options are an `Enum` class, the saved value is the enum member. If a member has a `label` attribute (or method), it is used as the option text.

| Method | What it does |
| --- | --- |
| `options(options)` | The choices. A closure makes them dependent on other fields. |
| `relationship(name, title_attribute, modify_query=None, title=None)` | Load options from a SQLAlchemy relationship. |
| `multiple()` | Pick several values (saved as a list). |
| `searchable()` | Add a search box to the dropdown. |
| `preload(False)` | With a searchable relationship: load options from the server while typing, instead of all at once. |
| `native(False)` | Use the styled dropdown even without search. |
| `boolean(true_label="Yes", false_label="No")` | Yes/No choice saved as `True` / `False`. |
| `disable_option_when(fn)` | Grey out some options. `fn` gets `value` and `label`. |

### Relationship options

```python
# many-to-one: the field is the foreign key
Select("category_id").label("Category").relationship("category", "name").searchable().required()

# a big table: search on the server
Select("customer_id").relationship("customer", "name").searchable().preload(False)

# many-to-many: field name = relationship name
Select("tags").relationship("tags", "name").multiple()

# narrow the list, or build your own option text
Select("brand_id").relationship(
    "brand", "name",
    modify_query=lambda query: query.where(Brand.is_active.is_(True)),
)
Select("author_id").relationship("author", title=lambda record: f"{record.name} ({record.email})")
```

Options are sorted by the title attribute. For a many-to-many select, Tungsten replaces the related records after the main record is saved.

### Dependent options

```python
Select("city").options(lambda get: CITIES.get(get("state"), []))
```

Add `.live()` to the `state` field so the city options update. See [Dependent fields](forms#dependent-fields).

## CheckboxList

A list of checkboxes. Saved as a list of the checked values.

```python
CheckboxList("sizes").label("Available sizes").options(["S", "M", "L", "XL"]).columns(4)
```

| Method | What it does |
| --- | --- |
| `options(...)` / `relationship(...)` | Same as [Select](#select). |
| `columns(n)` | Show the checkboxes in `n` columns. |
| `bulk_toggleable()` | Add "Select all" and "Deselect all" links. |
| `descriptions({value: text})` | A line of help text under each option. |
| `disable_option_when(fn)` | Grey out some options. |
| `grouped(fn)` | Show the options under group headings. `fn` gets `value` and `label` and returns the group name. |

To show options in groups, you can also give them as a dict of dicts. Each key is a group heading:

```python
CheckboxList("sizes").options({
    "Shirts": {"s": "Small", "m": "Medium", "l": "Large"},
    "Shoes": {"uk8": "UK 8", "uk9": "UK 9"},
})

CheckboxList("permissions").options(PERMISSIONS).grouped(lambda value: value.split(".")[0].title())
```

## Radio

Pick one option from a list of radio buttons.

```python
Radio("status")
    .options({"draft": "Draft", "published": "Published", "archived": "Archived"})
    .descriptions({"draft": "Only admins can see it", "published": "Visible in the store"})
    .default("draft")
    .required()
```

| Method | What it does |
| --- | --- |
| `options(...)` / `relationship(...)` | Same as [Select](#select). |
| `descriptions({value: text})` | Help text under each option. |
| `inline()` | Put the options on one line. |
| `boolean(true_label="Yes", false_label="No")` | Yes/No choice saved as `True` / `False`. |
| `disable_option_when(fn)` | Grey out some options. |

## ToggleButtons

Options shown as a row of buttons, each with an optional icon and color.

```python
ToggleButtons("status")
    .options({"draft": "Draft", "review": "In review", "published": "Published"})
    .icons({"draft": "pencil", "review": "eye", "published": "circle-check"})
    .colors({"draft": "gray", "review": "warning", "published": "success"})
    .default("draft")
```

| Method | What it does |
| --- | --- |
| `options(...)` / `relationship(...)` | Same as [Select](#select). |
| `icons({value: icon})` | An icon per option. |
| `colors({value: color})` | A color per option (default `primary`). |
| `multiple()` | Allow several buttons to be on (saved as a list). |
| `grouped(False)` | Space the buttons apart instead of joining them into one bar. |
| `boolean(true_label="Yes", false_label="No")` | Yes/No buttons with check and x icons, saved as `True` / `False`. |

Colors are `primary`, `success`, `warning`, `danger`, `info`, `gray`, `purple`, `teal`, `pink` and `indigo`.

## Checkbox

One checkbox, saved as `True` or `False`.

```python
Checkbox("accepts_marketing").label("Send me offers by email")
Checkbox("terms").label("I accept the terms").required()
```

On a checkbox, `required()` means it must be ticked ("The terms must be accepted.").

## Toggle

An on/off switch, saved as `True` or `False`.

```python
Toggle("is_active").label("Status").state_labels("Active", "Inactive").default(True)
Toggle("is_featured").on_color("success").on_icon("star")
```

| Method | What it does |
| --- | --- |
| `state_labels(on, off)` | Text next to the switch that changes with it. |
| `on_color(color)` | Color when on: `primary` (default), `success`, `danger`, `warning`, `info` or `gray`. |
| `off_color(color)` | Color when off. Same colors; the default is a light `gray`. |
| `on_icon(icon)` | An icon shown on the switch when it is on. |
| `off_icon(icon)` | An icon shown on the switch when it is off. |

## DatePicker

A date input. The value is saved as a `datetime.date`.

```python
DatePicker("available_from")
DatePicker("date_of_birth").max_date(dt.date.today())
DatePicker("ends_on").min_date(lambda get: get("starts_on"))
```

| Method | What it does |
| --- | --- |
| `min_date(value)` | Earliest allowed date: a `date`, an ISO string (`"2024-01-01"`) or a closure. |
| `max_date(value)` | Latest allowed date. |

When the value is `None` or an empty string (for example, a closure that reads a field the user has not filled yet), there is no limit.

## DateTimePicker

A date and time input, saved as a `datetime.datetime`. It has `min_date()` and `max_date()`. Pass `datetime` values, or plain `date` values: a date as `min_date` means the start of that day, and as `max_date` the end of that day. It also has:

```python
DateTimePicker("published_at").seconds()
```

| Method | What it does |
| --- | --- |
| `seconds()` | Also pick seconds. |

## TimePicker

A time input, saved as a `datetime.time`.

```python
TimePicker("opens_at")
TimePicker("closes_at").seconds()
```

## FileUpload

Upload one or more files. Files are stored as soon as the user picks them, and the field holds the stored path (or a list of paths). Files go to the panel storage, which is a local folder unless you pass `storage=` to the `Panel` (see [Panel configuration](panel-configuration)).

```python
FileUpload("avatar").label("Profile photo").avatar().directory("avatars").max_size(2048)

FileUpload("images").image().multiple().max_files(6).directory("products").max_size(2048)

FileUpload("manual").accepted_file_types([".pdf", "application/pdf"]).directory("manuals")
```

| Method | What it does |
| --- | --- |
| `directory(path)` | Folder inside the storage. |
| `multiple()` | Allow several files (saved as a list of paths). |
| `image()` | Images only, shown as previews. |
| `avatar()` | A round image preview, for profile photos. Also sets `image()`. |
| `accepted_file_types([...])` | Allowed types: MIME types (`"application/pdf"`), wildcards (`"image/*"`) or extensions (`".csv"`). |
| `max_size(kilobytes)` | Largest file size in KB. |
| `max_files(n)` | Most files allowed with `multiple()`. |

## RichEditor

A rich text editor (bold, lists, links...). The HTML is cleaned on save, so scripts and unsafe attributes are removed.

```python
RichEditor("description").column_span("full")
RichEditor("summary").max_length(500)
```

| Method | What it does |
| --- | --- |
| `max_length(n)` | Most characters allowed. Only the text counts, not the HTML tags. A counter under the editor shows how many are used. |

## ColorPicker

Pick a color. The value must be a hex color like `#ff8800` or `#f80`.

```python
ColorPicker("color")
```

## TagsInput

Type a word and press Enter (or a comma) to add it as a tag. Duplicates are removed. Saved as a list, or as one string with `separator()`.

```python
TagsInput("keywords").suggestions(["cotton", "summer", "casual", "sale"])
TagsInput("keywords_csv").separator(",")        # saved as "cotton,summer"
```

| Method | What it does |
| --- | --- |
| `suggestions(values)` | Words offered while typing. A list or a closure. |
| `separator(sep=",")` | Store the tags as one string joined by `sep`, instead of a list. |
| `color(color)` | Color of the tag chips (default `primary`). |

## Repeater

A list of rows, each with the same fields. Users can add, remove, move and clone rows.

Without a relationship, the rows are saved as a JSON list of dicts on the record:

```python
Repeater("contacts").schema([
    TextInput("name").required(),
    TextInput("phone").tel(),
]).columns(2).add_action_label("Add contact")
```

With `.relationship()`, each row is a related record (one-to-many):

```python
Repeater("items").relationship("items", order_column="sort").table().schema([
    Select("product_id").label("Product").relationship("product", "name").required(),
    TextInput("quantity").integer().min_value(1).default(1).required(),
    TextInput("unit_price").numeric().prefix("₹").required(),
]).min_items(1).add_action_label("Add item")
```

Existing rows update their related record. New rows create one. Rows that were removed are taken out of the relationship; whether they are deleted from the database depends on your SQLAlchemy cascade (use `cascade="all, delete-orphan"` to delete them).

| Method | What it does |
| --- | --- |
| `schema([...])` | The fields in each row. Layouts work too. |
| `relationship(name=None, order_column=None)` | Save rows as related records. `order_column` stores the row position. |
| `columns(n)` | Grid columns inside each row (default `1`). |
| `table()` | Show rows as a compact table, one line per row. |
| `default_items(n)` | Empty rows on the create page (default `1`). |
| `min_items(n)`, `max_items(n)` | Limits on the number of rows. |
| `add_action_label(text)` | Text on the add button. |
| `addable(condition)`, `deletable(condition)` | Allow adding or removing rows. |
| `reorderable(False)` | Hide the move up/down buttons (also `orderable()`). |
| `collapsible()` | Rows can be folded. |
| `item_label(fn)` | A title for each row. `fn` gets the row `state` (a dict). |

```python
Repeater("faq").schema([TextInput("question").required(), Textarea("answer")])
    .collapsible()
    .item_label(lambda state: state.get("question") or "New question")
```

Inside a row, `get("field")` reads the same row and `get("../field")` reads outside the repeater. See [Paths inside repeaters](forms#paths-inside-repeaters).

## Builder

Like a repeater, but each row can be a different kind of block: a page builder. Saved as a JSON list: `[{"type": "heading", "data": {...}}, ...]`.

```python
Builder("content").blocks([
    Block("heading").icon("heading").columns(3).schema([
        TextInput("text").required().column_span(2),
        Select("level").options({"h2": "Heading 2", "h3": "Heading 3"}).default("h2"),
    ]),
    Block("paragraph").icon("pilcrow").schema([RichEditor("body").required()]),
    Block("image").icon("image").schema([
        FileUpload("image").image().directory("blog").required(),
        TextInput("alt").label("Alt text"),
    ]),
]).add_action_label("Add block").collapsible().column_span("full")
```

The add button opens a menu of block types. A builder starts with no rows. It has the same row options as a repeater (`min_items`, `max_items`, `collapsible`, `addable`, `deletable`, `reorderable`, `item_label`), but not `relationship()`.

`Block(name)` options:

| Method | What it does |
| --- | --- |
| `label(text)` | Name in the add menu (default from the block name). |
| `icon(icon)` | Icon in the add menu and the row header. |
| `columns(n)` | Grid columns inside the block. |
| `schema([...])` | The block's fields. |

## KeyValue

Edit a dict as rows of key and value. Saved as a JSON object. Rows with an empty key are dropped.

```python
KeyValue("attributes").key_label("Attribute").value_label("Value").column_span("full")
```

| Method | What it does |
| --- | --- |
| `key_label(text)`, `value_label(text)` | Column headings. |
| `add_action_label(text)` | Text on the add button (default "Add row"). |
| `addable(False)`, `deletable(False)` | Stop users adding or removing rows. |
| `editable_keys(False)` | Users can only change values, not keys. |

## Hidden

A hidden input. Its value is saved like any other field.

```python
Hidden("source").default("admin")
```

## Placeholder

Read-only text inside the form. It is never saved. Use it for summaries and computed values.

```python
Placeholder("created").label("Created").content(
    lambda record: record.created_at.strftime("%d %b %Y") if record else "Not saved yet"
)
Placeholder("order_total").content(lambda get: f"₹{items_total(get):,.2f}")
```

When `content` is empty, the field shows "—". If it reads other fields with `get`, add `.live()` to those fields so the text updates.
