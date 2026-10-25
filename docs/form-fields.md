---
title: Form fields
description: Every form field type in Tungsten, with its own options and a short example.
---

This page lists every field in `tungsten.forms`. All fields also have the common options (label, default, required, helper text, visible, column span...) described on the [Forms](forms#common-field-options) page.

```python
from tungsten.forms import (
    Block, Builder, Checkbox, CheckboxList, ColorPicker, DatePicker, DateTimePicker, FileUpload,
    Hidden, KeyValue, MentionProvider, ModalTableSelect, Placeholder, Radio, Repeater, RichEditor,
    Select, Slider, TagsInput, Textarea, TextInput, TimePicker, Toggle, ToggleButtons, ViewField,
)
```

Want a field that is not here? See [Custom fields](#custom-fields) at the end of this page.

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

### Input masks

A mask formats the value while the user types. `9` is a digit, `a` a letter and `*` either; every other character is added for the user.

```python
TextInput("phone").mask("99999-99999").strip_characters("-")   # 98765-43210, saved as 9876543210
TextInput("vehicle").mask("aa-99-aa-9999")                       # MH-12-AB-1234
TextInput("pin").mask(["999 999", "9999 9999"])                  # the first pattern that fits the length
TextInput("price").money_mask(prefix="₹", indian=True)           # ₹12,34,567.50, saved as Decimal("1234567.50")
TextInput("betrag").money_mask(thousands=".", decimal=",")       # 1.234,50
```

| Method | What it does |
| --- | --- |
| `mask(pattern)` | A pattern, a list of patterns, or a closure returning one. |
| `money_mask(prefix="", thousands=",", decimal=".", precision=2, indian=False)` | Groups digits while typing. The saved value is a number, with the prefix and separators removed. `indian=True` groups as 12,34,567. |
| `strip_characters(chars)` | Characters removed before saving, e.g. the dashes a mask adds. |

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

### Create or edit an option in a modal

A `+` button next to the select opens a small form to add a new option. With a relationship the new record is saved for you (in the current tenant) and selected. A pencil button can open the selected record to change it.

```python
Select("brand_id").relationship("brand", "name")
    .create_option_form([TextInput("name").required().unique(), TextInput("website").url()])
    .edit_option_form([TextInput("name").required().unique(), TextInput("website").url()])
```

| Method | What it does |
| --- | --- |
| `create_option_form(schema, columns=1)` | The fields of the "create" modal. |
| `create_option_using(fn)` | Save the new option yourself: `fn(data)` returns its key. Needed when the select has no relationship. |
| `create_option_action(fn)` | Change the button: `lambda action: action.label("New brand").modal_width("2xl")`. |
| `edit_option_form(schema, columns=1)` | The fields of the "edit" modal, filled from the selected record. Shown when one option is selected. |
| `update_option_using(fn)` | Save the changes yourself: `fn(record, data)`. |
| `edit_option_action(fn)` | Change the edit button. |

When the related model has a resource, the buttons follow its `create` and `update` permissions.

### Dependent options

```python
Select("city").options(lambda get: CITIES.get(get("state"), []))
```

Add `.live()` to the `state` field so the city options update. See [Dependent fields](forms#dependent-fields).

## ModalTableSelect

Like a `Select`, but the user picks from a searchable, paged table in a modal. Good for long lists where a name alone is not enough to choose.

```python
ModalTableSelect("customer_id").relationship("customer", "name")
    .table_columns(["name", "email", ("city", "Town")])
    .searchable_columns(["name", "email"])

ModalTableSelect("tags").relationship("tags", "name").multiple()   # many-to-many: pick several
```

| Method | What it does |
| --- | --- |
| `relationship(name, title_attribute)` | Where the records come from (same as `Select`, including `modify_query`). |
| `table_columns([...])` | The table's columns: attribute names (`"company.name"` works) or `(attribute, label)` pairs. |
| `searchable_columns([...])` | Columns the search box looks in (default: the table's own columns). |
| `per_page(n)` | Rows per page (default 10). |
| `multiple()` | Pick several records. Picks on other pages are kept. |
| `select_action_label(text)`, `modal_heading(text)`, `modal_width(size)` | Change the button and the modal. |

It also takes `create_option_form()` and `edit_option_form()` like a `Select`. When the form is saved, the picked keys are checked against the same query, so a made-up key is refused.

## Slider

Pick a number by dragging.

```python
Slider("discount").range(0, 50).step(5).suffix("%").pips(10)
Slider("price_range").range(0, 10000).step(500).dual()   # two handles: saved as [low, high]
```

| Method | What it does |
| --- | --- |
| `range(min, max)` | The lowest and highest values (also `min_value()` / `max_value()`; closures work). |
| `step(n)` | The step between values. Values off the step are refused. |
| `dual()` | Two handles. The value is a `[low, high]` list. |
| `pips(every=None)` | Numbers under the track, every `every` units (default: 4 equal parts). |
| `prefix(text)`, `suffix(text)` | Shown around the value. |
| `decimal_places(n)` | Round to `n` places. |
| `show_value(False)` | Hide the value box. |

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

### Timezones

By default the time is shown and saved as it is. With `timezone()` the user types it in their own timezone, and it is saved in UTC (the class setting `DatePicker.storage_timezone`, like Laravel's `app.timezone`). The timezone is shown under the input.

```python
DateTimePicker("starts_at").timezone("Asia/Kolkata")
DateTimePicker("starts_at").timezone(lambda user: user.timezone)   # each user's own zone
DateTimePicker("starts_at").timezone("Asia/Kolkata", show=False)   # don't show the zone name
```

A plain `DatePicker` has no time, so it ignores the timezone.

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
| `toolbar_buttons([...])` | Exactly which buttons to show, in order. |
| `enable_toolbar_buttons([...])` | Add buttons to the default toolbar, e.g. `["underline", "h2", "h3"]`. |
| `disable_toolbar_buttons([...])` | Remove buttons from it. |
| `disable_all_toolbar_buttons()` | No toolbar (keyboard shortcuts still work). |
| `file_attachments()` | Users can drop or attach files. Images only by default. |
| `file_attachments_directory(path)` | Folder in the panel storage (default `attachments`). Also turns attachments on. |
| `file_attachments_accepted_types([...])` | MIME types, e.g. `["image/*", "application/pdf"]`. |
| `file_attachments_max_size(kb)` | Largest file (default 5 MB). |
| `mentions(...)` | `@mentions` (see below). |
| `blocks([...])` | Custom blocks (see below). |

Toolbar buttons: `bold`, `italic`, `underline`, `strike`, `link`, `h1`, `h2`, `h3`, `blockquote`, `codeBlock`, `bulletList`, `orderedList`, `outdent`, `indent`, `attachFiles`, `blocks`, `undo`, `redo`. The default is the first row of Trix: bold, italic, strike, link, h1, quote, code, lists, indent, attach (when attachments are on), undo and redo.

```python
RichEditor("body")
    .toolbar_buttons(["bold", "italic", "underline", "link", "h2", "h3", "bulletList", "orderedList", "attachFiles"])
    .file_attachments_directory("posts")
```

Attached files are stored in the panel storage. The panel only serves them to signed-in users, unless the storage is public (`LocalStorage(public=True)`), so use a public storage when the HTML is shown on your website.

### Mentions

Type `@` (or another trigger) to pick a person or thing from a list. The mention is kept in the HTML with its id.

```python
RichEditor("comment").mentions({1: "Asha", 2: "Ravi"})               # a short, fixed list

RichEditor("comment").mentions([
    MentionProvider("@").search_using(lambda search, db: {               # a long list: search on the server
        u.id: u.name for u in db.scalars(select(User).where(User.name.ilike(f"%{search}%")).limit(20))
    }).url(lambda id: f"/team/{id}"),
    MentionProvider("#").items(lambda db: {t.id: t.name for t in db.scalars(select(Topic))}),
])
```

To notify the people mentioned, read them from the saved HTML:

```python
from tungsten.forms import mentions_in

for m in mentions_in(record.comment, trigger="@"):
    notify(user_id=m["id"])          # each item: {"trigger", "id", "label"}
```

### Custom blocks

Blocks are ready-made pieces of content, like a call to action or a product card. Users insert them from the block button on the toolbar; a block with fields opens a form first. To change a block, click it in the editor and press the pencil.

```python
RichEditor("body").blocks([
    Block("cta").label("Call to action").icon("megaphone").schema([
        TextInput("text").required(),
        TextInput("url").url().required(),
    ]).render_using(lambda config: Markup('<a class="btn" href="{}">{}</a>').format(config["url"], config["text"])),
])
```

| Block method | What it does |
| --- | --- |
| `schema([...])`, `columns(n)` | The block's form. Without one the block is inserted at once. |
| `preview(fn)` | How the block looks inside the editor: `fn(config)` returns HTML (cleaned before use). Default: its label and settings. |
| `render_using(fn)` | The block's HTML on your site: `fn(config)` returns HTML. |

### Showing the HTML

Use `render_rich_content()` to show a saved value on a page. It cleans the HTML, draws each block with its `render_using`, and turns mentions into links (`MentionProvider.url`) or `<span class="tw-mention">`.

```python
from tungsten.forms import render_rich_content

html = render_rich_content(post.body, editor=RichEditor("body").blocks([...]).mentions([...]))
# or: render_rich_content(post.body, blocks=[...], mentions=[...])
```

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

## MarkdownEditor

Write Markdown with a toolbar, keyboard shortcuts (Ctrl+B, Ctrl+I, Ctrl+E, Ctrl+K) and a **Preview** tab. The value saved is the Markdown text.

```python
from tungsten.forms import MarkdownEditor

MarkdownEditor("body").toolbar_buttons(["bold", "italic", "link", "bulletList"]).html_column("body_html")
```

| Option | What it does |
| --- | --- |
| `toolbar_buttons([...])` | Which buttons to show: `bold`, `italic`, `strike`, `heading`, `quote`, `code`, `codeBlock`, `link`, `image`, `bulletList`, `orderedList`, `taskList`, `table`, `hr`. `[]` hides the toolbar. |
| `disable_toolbar_buttons([...])` | Hide some buttons. |
| `preview(False)` | No Preview tab. |
| `html_column("body_html")` | Also save the rendered HTML into this attribute, so your site can show it without converting. |
| `min_height(px)`, `max_height(px)`, `rows()`, `max_length()` | Size limits. |

To show the Markdown elsewhere, use `tungsten.support.markdown.markdown_to_html(text)`. It understands headings, bold, italic, strike-through, inline code, code blocks, links, images, quotes, bullet and numbered lists, task lists, tables and dividers, and cleans the result so user text can't add scripts. `markdown_text(text)` gives plain text for search or summaries.

## CodeEditor

A monospaced editor with line numbers, Tab indenting (Shift+Tab outdents, Enter keeps the indent) and a language chip. No JavaScript library is loaded.

```python
from tungsten.forms import CodeEditor

CodeEditor("script").language("python").line_numbers()
CodeEditor("settings").json()       # pretty JSON in, a dict or list out
```

| Option | What it does |
| --- | --- |
| `language("json")` | The chip text: `json`, `python`, `js`, `sql`, `bash`, `php`, `html`, `css`, `yaml`... Python makes Tab 4 spaces. |
| `json()` | The text must be valid JSON. It is shown pretty-printed and saved as data (for a `JSON` column). |
| `line_numbers(False)` | Hide the gutter. |
| `indent(4)` | Spaces per Tab (default 2). |
| `wrap()` | Wrap long lines instead of scrolling sideways. |
| `min_height(px)`, `max_height(px)` | Size limits (default 160 to 480 px). |

The matching read-only entry is `CodeEntry` in [infolists](infolists#code-entry).

## MorphToSelect

Point at a record from one of several models, like a comment that belongs to a product *or* a post. Two selects are shown: the type, then the record. The record list follows the chosen type without a page reload.

```python
from tungsten.forms import MorphToSelect, MorphType

MorphToSelect("commentable").types([
    MorphType(Product).title("name"),
    MorphType(Post, key="post").title(lambda record: record.title[:40]).label("Blog post"),
])
```

It saves two columns: `commentable_type` (the type key, the model name unless you pass `key=`) and `commentable_id`.

| Option | What it does |
| --- | --- |
| `types([...])` | The models. Each `MorphType(Model)` takes `title(attribute or closure)`, `label()`, `modify_query(lambda query: ...)` and `searchable()`. |
| `type_column("kind")`, `id_column("ref")` | Other column names. |
| `label()`, `required()` | Apply to both selects. |
| `searchable()` | A searchable record list. |

Read the record back yourself from the two columns, for example with a small property on the model.

## Custom fields

There are two ways to make your own field.

**A template.** `ViewField` draws the field with your own Jinja template. The value is saved like a text input (use `rule()`, `dehydrate_state_using()` and friends to check or change it).

```python
ViewField("rating").view("myapp/star-rating.html", {"max": 5}).default(3).required()
```

```html
{# templates/myapp/star-rating.html #}
{% from "tungsten/forms/macros.html" import wrapper %}
{% call wrapper(field, v) %}
<div x-data="{ value: {{ v.state or 0 }} }" class="flex gap-1">
  <input type="hidden" name="{{ v.path }}" :value="value" {{ v.live }}>
  {% for i in range(1, v.max + 1) %}
  <button type="button" @click="value = {{ i }}" :class="value >= {{ i }} ? 'text-warning-500' : 'text-gray-300'">★</button>
  {% endfor %}
</div>
{% endcall %}
```

The template gets `form`, `field` and `v`: `v.path` (the input name), `v.id`, `v.state` (the value), `v.label`, `v.errors`, `v.disabled`, `v.live` (attributes for [live fields](forms#dependent-fields)) and anything you pass to `view()` or `view_data_using()`. The `wrapper` macro draws the label, hint, errors and helper text. Add the template folder with `Panel(..., template_dirs=[...])` (see [Panel configuration](panel-configuration)).

**A class.** For a field you use often, subclass `Field`. Override only what you need:

```python
from tungsten.forms import Field

class PercentInput(Field):
    template = "myapp/percent.html"           # drawn like ViewField's template

    def cast(self, state):                    # form state (text) -> Python value; raise ValueError on bad input
        value = super().cast(state)
        if value is None:
            return None
        try:
            return float(value.rstrip("%")) / 100
        except ValueError:
            raise ValueError("The :attribute must be a percentage.") from None

    def to_state(self, value):                # Python value -> form state
        return "" if value is None else f"{value * 100:g}%"

    def validate_value(self, form, base, value):   # extra checks, return a list of messages
        return [] if 0 <= value <= 1 else ["The :attribute must be between 0% and 100%."]

    def view_data(self, form, base):          # extra template variables
        v = super().view_data(form, base)
        v["step"] = 5
        return v
```

Other hooks: `blank_state()` (empty value), `extract(formdata, path)` (read a submitted value, e.g. `getlist` for several), `hydrate(form, record)` (read from the record) and `fill_record(form, record, data)` (write to it). A custom field gets every common option (label, required, live, hint actions...) for free.

To show something that is not a value at all, use `View("myapp/notice.html")`, or the [content blocks](form-layouts#text-html-and-callout).

