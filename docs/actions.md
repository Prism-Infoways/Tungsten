---
title: Actions
description: Buttons that run your code, ask for confirmation or open a modal form, in table rows, bulk menus and page headers.
---

An action is a button. It can run some Python code, ask "Are you sure?" first, open a popup (a "modal") with a form, or simply link to a URL. You use the same `Action` class in table rows, in the bulk menu, above a table and in page headers. Tungsten also ships ready-made actions for create, edit, view, delete, restore, replicate, attach and detach.

## Your first action

Add an `Action` to a table's row actions. This one marks an order as shipped.

```python
from tungsten.actions import Action, EditAction


@classmethod
def table(cls, table):
    return table.columns([...]).actions([
        Action("ship").label("Mark shipped").icon("truck").color("info")
        .visible(lambda record: record.status == "paid")
        .requires_confirmation()
        .action(lambda record, db: (setattr(record, "status", "shipped"), db.commit()))
        .success_notification_title("Order shipped"),
        EditAction(),
    ])
```

What happens:

1. Each paid order gets a truck button.
2. A click opens a confirmation popup.
3. On confirm, the `action()` closure runs on the server with that `record`.
4. A "Order shipped" toast appears and the table reloads.

The name (`"ship"`) must be unique within the place the action lives. Without `label()`, the label is made from the name (`"reset_password"` → "Reset password").

## Where actions live

| Place | How to add it | Closures get |
| --- | --- | --- |
| Table rows | `table.actions([...])` | `record` |
| Bulk menu (selected rows) | `table.bulk_actions([...])` with `BulkAction` | `records` |
| Above the table | `table.header_actions([...])` | no record |
| Empty table | `table.empty_state_actions([...])` | no record |
| Resource page header | `header_actions(cls, ctx, page, record=None)` on the resource | `record` on edit and view pages |
| Custom page header | `header_actions(cls, ctx)` on the page | no record |

All of these work the same way in resources, [relation managers](relation-managers), table widgets and [custom pages](custom-pages). See [Resources](resources#header-actions) for page header buttons.

In table rows, an action with an icon shows as an icon button (the label becomes its tooltip). Without an icon it shows as a text link.

## Closures get what they ask for

Almost every option takes a value **or** a function. Tungsten looks at the parameter names of your function and passes only what you ask for. These names are available in action closures:

| Name | What it is |
| --- | --- |
| `record` | The row or page record (`None` in headers). |
| `records` | The selected records (bulk actions). |
| `data` | The validated modal form data, as a dict (in `action()`). |
| `form` | The modal form object. |
| `ctx` | The request context: `ctx.db`, `ctx.user`, `ctx.panel`, `ctx.redirect(url)`... |
| `db` | The SQLAlchemy session. |
| `user` | The signed-in user. |
| `request` | The Starlette request. |
| `tenant` | The current tenant, with [multi-tenancy](multi-tenancy). |
| `host` | The table or page the action belongs to. |
| `action` | The action itself. |
| `result` | What `action()` returned (only in `success_redirect_url`). |

```python
Action("archive").visible(lambda record, user: user.is_admin and not record.archived)
Action("pdf").url(lambda record: f"/reports/{record.id}.pdf", open_in_new_tab=True)
```

A function that asks for a name that isn't available gets an error, so stick to the names above. A `**kwargs` parameter receives all of them. `async def` functions work too; Tungsten awaits them.

## Running code

`action()` is the code to run. Use `db` to save changes; Tungsten does not commit for you in a custom action.

```python
def ship(record, db, user):
    record.status = "shipped"
    record.shipped_by_id = user.id
    db.commit()

Action("ship").action(ship)
```

After it runs:

- In a table (row, bulk or header action), the modal closes and the table reloads.
- In a page header, the page reloads.

### Redirecting

To send the user to another page, call `ctx.redirect(url)` inside the action, or set `success_redirect_url()`. The latter can use the action's return value as `result`:

```python
ReplicateAction().success_redirect_url(lambda result, ctx: ProductResource.get_url(ctx, "edit", result))
```

If `action()` returns a Starlette `Response`, Tungsten sends it as is.

### Stopping an action

Raise `Halt` to stop quietly. If the action has a modal form, the modal stays open.

```python
from tungsten import Notification
from tungsten.actions import Action, Halt


def refund(record, data, ctx):
    if float(data["amount"]) > float(record.total):
        Notification("Too much").body("The refund is more than the order total.").danger().send(ctx)
        raise Halt()
    ...
```

To show an error under a modal field instead, raise a `ValidationError` with the field name:

```python
from tungsten.forms import ValidationError

raise ValidationError({"amount": ["The refund is more than the order total."]})
```

## Label, icon and color

| Method | What it does |
| --- | --- |
| `label("...")` | Button text. Can be a closure. |
| `icon("truck")` | Any Lucide icon name. Can be a closure. |
| `color("danger")` | `primary`, `gray`, `success`, `danger`, `warning`, `info`, or another palette color. Can be a closure. Default: `primary`. |
| `tooltip("...")` | Text on hover. |
| `badge(3)` | A small count on the button. Can be a closure. |
| `size("sm")` | `sm`, `md` or `lg`. |
| `button()` | Show as a filled button. |
| `link()` | Show as a text link. |
| `icon_button()` | Show as an icon-only button. |
| `soft()` | Show as a light colored button (used for bulk actions). |
| `outlined()` | Show as an outlined button. |
| `hidden_label()` | Keep the icon, hide the text. |
| `keyboard_shortcut("mod+e")` | Click the button with a key combination. `mod` is Ctrl or ⌘. The combination must include `mod` or `alt`; write the parts in the order `mod`, `alt`, `shift`, key (`"mod+shift+e"`). |

```python
Action("print").icon("printer").color("gray").button().size("sm").tooltip("Print invoice")
```

## Linking to a URL

`url()` turns the action into a plain link. No code runs on the server.

```python
Action("invoice").icon("file-text").url(lambda record: f"/invoices/{record.id}", open_in_new_tab=True)
```

## Confirmation

`requires_confirmation()` shows a confirmation popup before the action runs. You can change everything in it.

```python
Action("cancel").icon("ban").color("danger")
    .requires_confirmation()
    .modal_heading("Cancel order")
    .modal_description("The customer will get an email. This cannot be undone.")
    .modal_icon("triangle-alert", color="danger")
    .modal_submit_action_label("Yes, cancel it")
    .modal_cancel_action_label("Keep order")
    .action(lambda record, db: (setattr(record, "status", "cancelled"), db.commit()))
```

| Method | What it does |
| --- | --- |
| `requires_confirmation()` | Ask before running. |
| `modal_heading("...")` | Popup heading. Default: the action label. |
| `modal_description("...")` | Text under the heading. Default for confirmations: "Are you sure you would like to do this?" |
| `modal_icon(icon, color=None)` | An icon at the top of the popup. |
| `modal_submit_action_label("...")` | Submit button text (also `modal_submit_label()`). Default: "Confirm", or "Submit" with a form. |
| `modal_cancel_action_label("...")` | Cancel button text. Default: "Cancel". |
| `modal_width("2xl")` | `sm`, `md`, `lg` (default), `xl`, `2xl`, `3xl`, `4xl` or `5xl`. |
| `slide_over()` | Open as a panel from the side instead of a centered popup. |
| `modal_content(html)` | Extra HTML in the popup (`Markup`, or a closure returning it). |

The heading, description and labels can be closures too, for example `modal_heading(lambda record: f"Cancel {record.number}?")`.

## Modal forms

Give an action a `form()` and it opens a popup with those fields. When the user submits, the values are checked with the field rules, and your `action()` gets them as `data`.

```python
from tungsten.forms import Select, Textarea, TextInput

Action("email").icon("mail").form([
    TextInput("subject").required(),
    Textarea("body").rows(6),
]).action(lambda record, data: send_mail(record.email, data["subject"], data["body"]))
```

Fill the form with starting values with `fill_form()`:

```python
Action("change_status").icon("refresh-cw")
    .form([Select("status").options(OrderStatus).required()])
    .fill_form(lambda record: {"status": record.status})
    .action(lambda record, data, db: (setattr(record, "status", data["status"]), db.commit()))
```

- `form(schema, columns=1)` takes a list of fields and layouts, and the number of grid columns.
- `form()` can also take a closure, which can ask for `record`, `form` and the other names, and returns the list of fields (or the form).
- Fields can use everything from [Forms](forms): rules, `.live()` dependent fields, file uploads, relationship selects. The form knows the table's model, so `.unique()` and `.relationship()` work.

```python
Action("refund").form(lambda record: [
    TextInput("amount").numeric().required().max_value(float(record.total)),
    Textarea("reason"),
])
```

## Notifications after an action

| Method | What it does |
| --- | --- |
| `success_notification_title("...")` | Show a success toast after the action. Can be a closure. |
| `success_notification_body("...")` | Text under the title. Can be a closure. |
| `failure_notification_title("...")` | Show a red toast when the action fails. Can be a closure. |

An action fails when it returns `False`, or when it raises an error. On an error, the database changes are rolled back and the error is logged. Without a failure title, an error is not caught and shows as a server error, as before. After a failure, a modal form stays open so the user can try again.

```python
(
    Action("sync")
    .action(lambda record: shop_api.sync(record))   # return False (or raise) when it did not work
    .success_notification_title("Synced")
    .failure_notification_title("Could not reach the shop")
)
```

Without a title, a custom action shows no toast. You can always send your own with [Notification](notifications):

```python
def approve(record, db, ctx):
    record.approved = True
    db.commit()
    Notification("Approved").body(f"{record.name} can now sign in.").success().send(ctx)
```

## Visibility and authorization

| Method | What it does |
| --- | --- |
| `visible(fn)` | Show the action only when this is true. |
| `hidden(fn)` | Hide the action when this is true. |
| `disabled(fn)` | Show the button greyed out, so it can't be clicked. |
| `authorize(ability)` | Show the action only if the user has this ability. |

`authorize()` takes:

- **A string**, an ability checked like other resource abilities. In a resource, `.authorize("publish")` checks the permission `products.publish` (or the policy's `publish` method). See [Resources](resources#authorization).
- **A closure**, for example `lambda user, record: user.id == record.owner_id`.
- **A bool**.

```python
Action("publish").authorize("publish").visible(lambda record: record.status == "draft")
```

Hidden and unauthorized actions are checked again on the server when the action runs, so a user can't run them by sending the request by hand.

## Bulk actions

A `BulkAction` runs on the rows the user selected with the checkboxes. Its closures get `records`, a list.

```python
from tungsten.actions import BulkAction, DeleteBulkAction

table.bulk_actions([
    BulkAction("publish").label("Publish").icon("circle-check").color("success")
    .action(lambda records, db: ([setattr(r, "status", "published") for r in records], db.commit()))
    .success_notification_title("Products published"),
    DeleteBulkAction(),
])
```

- Bulk actions are gray light buttons by default.
- If nothing is selected, the user sees "Select some records first".
- The default confirmation text includes the number of selected rows.
- After the action, the selection is cleared. Call `.deselect_records_after_completion(False)` to keep it.

## Action groups

Put several actions behind one dropdown button with `ActionGroup`.

```python
from tungsten.actions import ActionGroup, BulkActionGroup, DeleteAction, EditAction, ViewAction

table.actions([
    EditAction(),
    ActionGroup([ViewAction(), ReplicateAction(), DeleteAction()]),
])

table.bulk_actions([
    DeleteBulkAction(),
    BulkActionGroup([RestoreBulkAction(), ForceDeleteBulkAction()]).label("More actions"),
])
```

| Method | What it does |
| --- | --- |
| `label("...")` | Dropdown text. Default: "More actions". |
| `icon("...")` | Dropdown icon. Default: `"ellipsis"`. |
| `color("...")` | Dropdown color. Default: `"gray"`. |
| `button()` | Show as a labelled button instead of an icon. |

`BulkActionGroup` is the same, but shows as a button by default. Actions the user can't see are left out, and an empty group is not shown.

## Ready-made actions

All ready-made actions are in `tungsten.actions`. Each one checks an ability before it shows up.

| Action | What it does | Ability |
| --- | --- | --- |
| `CreateAction()` | Links to the create page, or opens the form in a popup when there is no create page (simple resources, relation managers). | `create` |
| `EditAction()` | Links to the edit page, or opens the form in a popup. Hidden for deleted records. | `update` |
| `ViewAction()` | Links to the view page, or opens a read-only popup with the [infolist](infolists). | `view` |
| `DeleteAction()` | Asks, then deletes (or soft-deletes) the record. In a page header it goes back to the list. | `delete` |
| `RestoreAction()` | Restores a soft-deleted record. Only shown for deleted records. | `restore` |
| `ForceDeleteAction()` | Deletes a soft-deleted record for good. Only shown for deleted records. | `force_delete` |
| `ReplicateAction(excluded=[...])` | Asks, then copies the record. | `create` |
| `DeleteBulkAction()` | Deletes the selected records (skips rows the user may not delete). | `delete_any` |
| `RestoreBulkAction()` | Restores the selected deleted records. | `restore_any` |
| `ForceDeleteBulkAction()` | Deletes the selected records for good. | `force_delete_any` |
| `AttachAction(title_attribute=None)` | Many-to-many: pick existing records to link. Relation managers only. | `attach` |
| `DetachAction()` | Unlinks a record. | `detach` |
| `DetachBulkAction()` | Unlinks the selected records. | `detach` |

`ExportAction`, `ExportBulkAction` and `ImportAction` live in `tungsten.importexport`. See [Import and export](import-export).

### Customizing ready-made actions

Ready-made actions are normal actions, so every method above works on them:

```python
DeleteAction().label("Remove").modal_description("The product will be hidden from the store.")
EditAction().icon("pencil").color("primary")
CreateAction().label("Add product").keyboard_shortcut("alt+n")
```

`CreateAction`, `EditAction` and `ViewAction` use the resource's (or relation manager's) own form. `CreateAction` and `EditAction` also have:

| Method | What it does |
| --- | --- |
| `mutate_form_data_using(fn)` | Change the data before saving. Gets `data` and `ctx` (and `record` for edit); return the new data. |
| `using(fn)` | Replace the save code. Gets `data`, `ctx`, `form`, `host` (and `record` for edit). |
| `fill_form(fn)` | Change starting values: return a dict of values to set. |

```python
CreateAction().mutate_form_data_using(lambda data, ctx: {**data, "created_by_id": ctx.user.id})
```

When `CreateAction` opens in a popup, it has a **Create & create another** button next to **Create**. It saves the record, refreshes the table and opens an empty form again. Turn it off with `CreateAction().create_another(False)`.

`CreateAction`, `EditAction` and `DeleteAction` run your own `action()` instead of their default code when you give one.

`ReplicateAction` copies every column except the primary key, `created_at`, `updated_at` and the `excluded` names. Relationships are not copied. Change the copy before it is saved with `before_replica_saved()`, which can ask for `replica`, `record` and `data`:

```python
ReplicateAction(excluded=["sku"]).before_replica_saved(
    lambda replica: setattr(replica, "name", f"{replica.name} (copy)")
)
```
