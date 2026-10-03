---
title: Form layouts
description: Arrange form fields with sections, grids, fieldsets, groups, tabs and step-by-step wizards.
---

Layouts arrange fields on the page. They hold no data of their own: the fields inside them are saved as if they were at the top of the form. You can nest layouts in any order.

```python
from tungsten.forms import Fieldset, Grid, Group, Section, Step, Tab, Tabs, Wizard
```

## The grid

Every form, and every layout, puts its children in a grid. The form uses 2 columns by default. Change it with `columns()`, and make a child wider with `column_span()`.

```python
form.columns(3).schema([
    Section("Order details").column_span(2).schema([...]),
    Section("Summary").column_span(1).schema([...]),
])
```

- `columns(n)` works with 1, 2, 3, 4, 5, 6 or 12 columns.
- `column_span(n)` takes a number or `"full"`. `column_span_full()` is a shortcut.
- On small screens everything stacks in one column.

All layouts also have `visible()` and `hidden()`. A hidden layout hides every field inside it, and those fields are not checked or saved.

```python
Section("Details").schema([...]).visible(lambda operation: operation != "create")
```

Layout closures get the same arguments as field closures (`get`, `record`, `operation`, `user`...), except `state`. See [Closures get what they ask for](forms#closures-get-what-they-ask-for).

## Section

A card with an optional heading, description and icon. It uses 2 columns and covers the full width by default.

```python
Section("Customer")
    .description("Contact details.")
    .icon("user")
    .schema([
        TextInput("name").required(),
        TextInput("email").email().required(),
    ])
```

You can also pass the fields as the second argument: `Section("Customer", [...])`.

| Method | What it does |
| --- | --- |
| `heading(text)` | The title (also the first argument). Leave it out for a plain card. |
| `description(text)` | Smaller text under the heading. |
| `icon(icon)` | An icon before the heading. |
| `columns(n)` | Grid columns inside the section (default `2`). |
| `collapsible()` | Click the heading to fold the section. |
| `collapsed()` | Start folded (also makes it collapsible). It opens by itself if a field inside has an error. |
| `aside()` | Put the heading and description in a column on the left, and the fields on the right. |
| `compact()` | Less padding. |

```python
Section("SEO").description("How the page looks in search results.").aside().schema([
    TextInput("meta_title").max_length(60),
    Textarea("meta_description").max_length(160),
])

Section("Advanced").collapsed().schema([KeyValue("attributes").column_span("full")])
```

## Grid

Lays out its children in columns without any card or border. It covers the full width of its parent.

```python
Grid(3).schema([
    TextInput("length").numeric().suffix("cm"),
    TextInput("width").numeric().suffix("cm"),
    TextInput("height").numeric().suffix("cm"),
])
```

The first argument is the number of columns (default `2`).

## Fieldset

A light box with a label in the border. Good for small groups of related fields inside a section.

```python
Fieldset("Shipping address").schema([
    TextInput("street").column_span("full"),
    TextInput("city"),
    TextInput("pin_code").length(6),
])
```

It uses 2 columns and the full width by default. Change the columns with `columns(n)`.

## Group

Groups fields with no visual wrapper. Use it to show or hide several fields together, or to stack sections in one column of the form grid.

```python
form.columns(3).schema([
    Tabs().column_span(2).tabs([...]),
    Group([
        Section("Status").schema([...]),
        Section("Details").schema([...]),
    ]).columns(1),
])
```

```python
Group([
    TextInput("company_name"),
    TextInput("gst_number"),
]).visible(lambda get: get("type") == "business")
```

A group uses 2 columns by default and covers one grid cell.

## Tabs

Split a long form into tabs. Each `Tab` has its own fields.

```python
Tabs().tabs([
    Tab("General").schema([
        TextInput("name").required().column_span("full"),
        RichEditor("description").column_span("full"),
    ]),
    Tab("Media").icon("image").schema([
        FileUpload("images").image().multiple().column_span("full"),
    ]),
    Tab("Pricing").icon("indian-rupee").schema([
        TextInput("price").numeric().required(),
    ]),
])
```

All tabs are part of one form and are saved together. When a field has an error, its tab shows the number of errors and opens by itself. The open tab stays open when a [live field](forms#dependent-fields) refreshes the form.

`Tabs` options:

| Method | What it does |
| --- | --- |
| `tabs([...])` | The tabs (or pass them as the second argument: `Tabs(None, [...])`). |
| `contained(False)` | Show the tabs without a card around them. Useful when each tab holds its own sections. |
| `key(name)` | A fixed name used to remember the open tab. Set it if you have several tab groups and want a stable name. |

`Tab` options:

| Method | What it does |
| --- | --- |
| `Tab(label)` | The tab title. |
| `icon(icon)` | An icon before the title. |
| `badge(value)` | A small count or text after the title. Can be a closure. |
| `columns(n)` | Grid columns inside the tab (default `2`). |
| `schema([...])` | The tab's fields. |

```python
Tabs().contained(False).tabs([
    Tab("General").icon("user").schema([
        Section("Basic information").schema([...]),
    ]),
    Tab("Orders").badge(lambda record: len(record.orders) if record else None).schema([...]),
])
```

## Wizard

A step-by-step form. When the user clicks **Next**, the fields of the current step are checked on the server. The user moves on only when the step is valid.

```python
form.schema([
    Wizard([
        Step("Basic information").description("User details").schema([
            TextInput("name").required(),
            TextInput("email").email().required().unique(),
        ]),
        Step("Role").description("Assign roles").icon("shield-check").schema([
            Select("role").options(["Admin", "Editor", "Viewer"]).required(),
        ]),
        Step("Review").schema([
            Placeholder("summary").content(lambda get: f"{get('/name')} ({get('/email')})"),
        ]),
    ]).submit_label("Create user"),
])
```

The last step shows the submit button instead of **Next**. On submit the whole form is checked; if a field in an earlier step has an error, that step opens. When the form's top level holds a wizard, the page's normal Save buttons are hidden.

A common pattern is a wizard on create and tabs on edit:

```python
@classmethod
def form(cls, form):
    if form.operation == "create":
        return form.schema([Wizard([...])])
    return form.schema([Tabs().tabs([...])])
```

`Wizard` options:

| Method | What it does |
| --- | --- |
| `steps([...])` | The steps (or pass them as the first argument). |
| `submit_label(text)` | Text on the final button (default "Submit"). |
| `skippable()` | Let users jump to any step from the step list. Without it, they can only go back to earlier steps. |
| `horizontal()` | Show the step list across the top. By default it is a column on the left. |
| `key(name)` | A fixed name used to remember the current step. |

`Step` options:

| Method | What it does |
| --- | --- |
| `Step(label)` | The step title. |
| `description(text)` | Smaller text under the title. |
| `icon(icon)` | An icon instead of the step number. |
| `columns(n)` | Grid columns inside the step (default `2`). |
| `schema([...])` | The step's fields. |
