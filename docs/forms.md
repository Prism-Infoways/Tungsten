---
title: Forms
description: Build create and edit forms from Python fields, with validation, dependent fields and relationship saving.
---

A form is a list of fields and layouts. Tungsten uses it for the create and edit pages of a resource, for modal forms in actions, and for custom pages. You describe the form once in Python; Tungsten renders it, checks the input on the server and saves the record.

## Your first form

Give your resource a `form()` class method. It receives an empty form and returns it with a schema.

```python
from tungsten import Resource
from tungsten.forms import Select, Textarea, TextInput, Toggle


class ProductResource(Resource):
    model = Product

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(150),
            Select("category_id").label("Category").relationship("category", "name").searchable(),
            TextInput("price").numeric().prefix("₹").min_value(0).required(),
            Toggle("is_featured"),
            Textarea("description").column_span("full"),
        ])
```

Each field name is the model attribute it reads and writes. On the edit page the fields are filled from the record. On submit, Tungsten casts each value to the right Python type (text, number, date, list...), checks the rules and sets the attribute on the record.

> [!TIP]
> Every field and layout also has a Filament-style `make()` constructor, so `TextInput.make("name")` is the same as `TextInput("name")`.

### Form options

| Method | What it does |
| --- | --- |
| `schema([...])` | The fields and layouts in the form. |
| `columns(n)` | How many grid columns the form uses (default `2`). Supported: 1-6 and 12. |
| `model(Model)` | The model class. Resources set this for you. |
| `disabled(condition)` | Make the whole form read-only. Takes a bool or a closure. |

Inside `form(cls, form)` you can read `form.operation` (`"create"`, `"edit"` or `"view"`) and `form.record` (the record being edited, `None` on create). Use them to build different forms per page:

```python
@classmethod
def form(cls, form):
    if form.operation == "create":
        return form.schema([...])   # e.g. a wizard
    return form.schema([...])       # e.g. tabs
```

## Common field options

These methods work on every field type.

| Method | What it does |
| --- | --- |
| `label(text)` | The label. By default it comes from the name: `category_id` becomes "Category". |
| `hidden_label()` | Hide the label. |
| `default(value)` | The starting value on the create page. Can be a closure. |
| `required(condition=True)` | The field must have a value. |
| `disabled(condition=True)` | Show the value but don't allow changes. Disabled fields are not saved. |
| `helper_text(text)` | Small text under the field. |
| `hint(text, icon=None)` | Small text next to the label, with an optional icon. |
| `placeholder(text)` | Text shown in an empty input. |
| `autofocus()` | Put the cursor in this field when the page opens. |
| `visible(condition)` / `hidden(condition)` | Show or hide the field. Hidden fields are not checked and not saved. |
| `column_span(n)` | How many grid columns the field covers: a number or `"full"`. |
| `column_span_full()` | Same as `column_span("full")`. |
| `extra_attributes({...})` | Extra HTML attributes for the input, such as `{"data-test": "price"}`. |

```python
TextInput("sku")
    .label("SKU")
    .required()
    .placeholder("TSH-001")
    .hint("Must be unique", icon="info")
    .helper_text("Printed on the barcode label.")
    .column_span(1)
```

## Closures get what they ask for

Almost every option takes a plain value **or** a function. When you pass a function, Tungsten looks at its parameter names and passes only what you ask for.

```python
TextInput("password").required(lambda operation: operation == "create")
Placeholder("created").content(lambda record: record.created_at if record else "Not saved yet")
Hidden("owner_id").default(lambda user: user.id)
```

In form closures you can ask for:

| Name | What you get |
| --- | --- |
| `get` | Read another field's current value: `get("status")`. |
| `set` | Change another field's value: `set("slug", "hello")`. |
| `state` | The current value of this field. |
| `record` | The record being edited (`None` on create). |
| `operation` | `"create"`, `"edit"` or `"view"`. |
| `model` | The model class. |
| `user`, `db`, `request`, `ctx`, `tenant` | The signed-in user, the database session, the request, the request context and the current tenant. |
| `form` | The form itself. |

`async def` functions work too; Tungsten awaits them.

## Validation

When the form is submitted, every **visible** field is cast and checked on the server. If something is wrong, the form shows the message under the field. If the bad field is in another tab or wizard step, that tab or step opens for you.

```python
TextInput("email").email().required().unique()
TextInput("username").required().max_length(60)
    .regex(r"^[a-z0-9_.]+$", "Use lowercase letters, numbers, dots and underscores.")
TextInput("stock").integer().min_value(0)
DatePicker("date_of_birth").max_date(dt.date.today())
```

Empty text is saved as `None`, and spaces at the start and end are removed.

### Built-in rules

| Rule | Where | Message when it fails |
| --- | --- | --- |
| `required()` | every field | "The name field is required." (checkboxes: "must be accepted") |
| `email()`, `url()` | `TextInput` | "must be a valid email address / URL" |
| `min_length(n)`, `max_length(n)`, `length(n)` | `TextInput`, `Textarea` | "must be at least n characters" |
| `numeric()`, `integer()` | `TextInput` | "must be a number" |
| `min_value(n)`, `max_value(n)` | numeric `TextInput` | "must be at least n" |
| `regex(pattern, message=None)` | `TextInput` | your message, or "format is invalid" |
| `same("other_field")` | `TextInput` | "confirmation does not match" |
| `unique(column=None, model=None, ignore_record=True)` | every field | "has already been taken" |
| `min_date(d)`, `max_date(d)` | date pickers | "must be a date after or equal to ..." |
| options check | `Select`, `Radio`, `CheckboxList`, `ToggleButtons` | "The selected status is invalid." |
| `min_items(n)`, `max_items(n)` | `Repeater`, `Builder` | "must have at least n items" |

`unique()` checks the database. On the edit page it ignores the record you are editing. Pass `column=` if the database column has another name, or `model=` to check another table.

```python
TextInput("password_confirmation").password().same("password").dehydrated(False)
```

> [!NOTE]
> A field that is required but disabled is not checked, because the user cannot change it.

### Custom rules

Use `rule()` for your own checks. The function gets the clean `value` (plus any closure argument such as `get` or `record`). Return `True` or `None` when the value is fine. Return a string to show it as the error, or `False` to show the default message.

```python
TextInput("username").rule(lambda value: value != "admin" or "That name is reserved.")

TextInput("compare_price").numeric().rule(
    lambda value, get: value > Decimal(get("price") or 0) or "Must be higher than the price."
)
```

You can also pass the message as the second argument and return `False`:

```python
TextInput("code").rule(lambda value: value.isupper(), "Use capital letters only.")
```

`rules([fn1, fn2])` adds several rules at once. Inside a message, `:attribute` is replaced by the field label.

All messages go through the translator, so they appear in the user's language. See [Translations](translations).

## Dependent fields

Some fields depend on others: a city list that depends on the state, or a slug filled from the title. Add `.live()` to the field the others depend on. When it changes, the browser sends the form to the server, Tungsten re-renders it, and every closure runs again with the new values.

```python
STATES = {"Maharashtra": ["Mumbai", "Pune"], "Gujarat": ["Ahmedabad", "Surat"]}

form.schema([
    Select("state").options(list(STATES)).live(),
    Select("city")
        .options(lambda get: STATES.get(get("state"), []))
        .visible(lambda get: bool(get("state")))
        .required(lambda get: bool(get("state"))),
])
```

Pick a state and the city field appears with the right cities. You write no JavaScript.

### When the update happens

| Call | When the form refreshes |
| --- | --- |
| `.live()` | When the value changes. For text inputs, that is when the user leaves the field. |
| `.live(on_blur=True)` | When the user leaves the field. |
| `.live(debounce=400)` | While the user types, after a 400 ms pause. |

`reactive()` is another name for `live()`.

### Filling other fields

`after_state_updated(fn)` runs after a live update of this field. Use `set` to change other fields. It turns on `live()` for you.

```python
TextInput("name").required().live(on_blur=True)
    .after_state_updated(lambda state, set, operation: set("slug", slugify(state)) if operation == "create" else None),
TextInput("slug").required().unique(),
```

Clear a dependent field when its parent changes:

```python
Select("state").options(list(STATES)).live().after_state_updated(lambda set: set("city", ""))
```

> [!NOTE]
> `after_state_updated` runs only when the user changes the field in the browser. It does not run when the form is saved.

### Paths inside repeaters

Inside a [Repeater](form-fields#repeater) row, `get("price")` reads a field in the same row. Use `../` to go up out of the row, and a leading `/` for a path from the top of the form.

```python
Repeater("items").schema([
    Select("product_id").relationship("product", "name").live()
        .after_state_updated(lambda state, set, db: set("unit_price", str(db.get(Product, int(state)).price) if state else "")),
    TextInput("quantity").integer().live(debounce=400),
    TextInput("unit_price").numeric().live(debounce=400),
])

Placeholder("items_count").content(lambda get: len(get("/items") or []))
```

## Controlling what is saved

By default the clean value of every visible, enabled field is written to the record attribute with the same name. These methods change that.

| Method | What it does |
| --- | --- |
| `dehydrated(False)` | Don't save this field. Takes a closure too, e.g. `lambda state: bool(state)`. |
| `dehydrate_state_using(fn)` | Change the value before it is saved. `fn` gets `state`. |
| `format_state_using(fn)` | Change how the record value is shown in the field. `fn` gets `state` and `record`. |
| `save_relationships_using(fn)` | Run your own save code after the record is stored. Turns off normal saving for this field. |

A password field that hashes the value and only saves when it is filled:

```python
from tungsten.auth import hash_password

TextInput("password").password().revealable()
    .required(lambda operation: operation == "create")
    .min_length(8)
    .dehydrate_state_using(lambda state: hash_password(state))
    .dehydrated(lambda state: bool(state))
```

Password inputs are always empty on the edit page, so leaving them empty keeps the old password.

`mutate_dehydrated_state_using()` is another name for `dehydrate_state_using()`.

## Saving relationships

Tungsten saves the common relationship types for you.

```python
# many-to-one: saves the foreign key
Select("category_id").relationship("category", "name")

# many-to-many: field name = relationship name, plus multiple()
Select("tags").relationship("tags", "name").multiple()

# one-to-many: each row becomes a related record
Repeater("items").relationship("items", order_column="sort").schema([...])
```

Many-to-many and repeater relationships are saved after the record itself, so they also work on the create page.

For anything else, write the save code yourself with `save_relationships_using`. The function gets the `record` (already stored, so it has an id) and the field's `state`.

```python
from sqlalchemy import select

CheckboxList("tag_ids").label("Tags")
    .options(lambda db: {t.id: t.name for t in db.scalars(select(Tag))})
    .format_state_using(lambda record: [str(t.id) for t in record.tags])
    .save_relationships_using(
        lambda record, state, db: setattr(
            record, "tags", list(db.scalars(select(Tag).where(Tag.id.in_([int(i) for i in state]))))
        )
    )
```

## Changing data before it is saved

To change the whole data dict, or to run code around the save, use the resource hooks: `mutate_form_data_before_create`, `before_create`, `after_create`, `mutate_form_data_before_save`, `before_save` and `after_save`.

```python
@classmethod
def mutate_form_data_before_create(cls, data, user):
    data["created_by_id"] = user.id
    return data
```

See [Resources](resources) for the full list.

## Where else forms are used

The same fields work in other places:

- Modal forms on buttons: `Action("email").form([...])`. See [Actions](actions).
- Settings and other custom pages. See [Custom pages](custom-pages).
- Relation managers on a record page. See [Relation managers](relation-managers).

Next, see every field type in [Form fields](form-fields), and how to arrange them in [Form layouts](form-layouts).
