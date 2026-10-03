---
title: Import and export
description: Let users download table rows as CSV or Excel, and upload CSV or Excel files to create and update records.
---

Tungsten has ready-made actions to export table rows to CSV or Excel, and to import records from a CSV or Excel file. Export works with any table and needs no setup. Import needs a small `Importer` class that lists the columns.

## Installing Excel support

CSV works out of the box. For `.xlsx` files, install the `excel` extra (it adds `openpyxl`):

```bash
pip install "tungsten-admin[excel]"
```

## Exporting the whole table

Add `ExportAction()` to the table's header actions:

```python
from tungsten.importexport import ExportAction


class ProductResource(Resource):
    model = Product

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("category.name").label("Category"),
                TextColumn("price").money("INR"),
                IconColumn("is_featured").boolean(),
            ])
            .header_actions([ExportAction()])
        )
```

Clicking **Export** opens a small popup where the user picks:

- the **format**: CSV or Excel,
- the **columns** to include (all are ticked at first).

Then **Download** saves a file named after the table, for example `products.csv`.

What goes into the file:

- **Only the rows that match** the current search, filters and sort. What you see is what you export (all pages, not just the current one).
- **Column labels** as the header row.
- **Formatted values**, the same as in the table. A `.money("INR")` column exports with its currency sign, and a date column in its display format.
- Lists (like tags) are joined with commas. Toggle columns become `True` or `False`. HTML is turned into plain text.
- `ImageColumn`s are left out.

CSV files are UTF-8 with a byte-order mark, so Excel opens them with the right characters (₹, accents, Hindi...). Excel files have a bold header row and sensible column widths.

### Export options

```python
ExportAction()                       # CSV and Excel
ExportAction(formats=("csv",))       # CSV only
ExportAction(formats=("xlsx",))      # Excel only
```

`ExportAction` is a normal [action](actions), so you can change it like any other:

```python
ExportAction().label("Download").icon("file-down").visible(lambda ctx: ctx.can("products.update"))
```

The download only works when the table offers an export action that the user may run. If you hide it with `.visible()` or `.authorize()`, the download address refuses that user too.

### Choosing the columns yourself

By default the file has the table's columns. To export other columns, pass a list of `ExportColumn`s:

```python
from tungsten.importexport import ExportAction, ExportColumn

ExportAction(columns=[
    ExportColumn("sku", "SKU"),
    ExportColumn("name"),
    ExportColumn("category.name", "Category"),
    ExportColumn("price", format=lambda state: f"{state:.2f}"),
])
```

`ExportColumn(name, label=None, format=None)`:

- `name` is an attribute, and can follow relationships with dots (`category.name`). A list (like tags) is joined with commas.
- `label` is the header. By default it is made from the name.
- `format` changes the value. It can ask for `state` (the value) and `record`.

The popup then offers these columns. `ExportBulkAction(columns=[...])` works the same way.

## Exporting selected rows

`ExportBulkAction()` exports only the rows the user ticked. It downloads straight away, without a popup:

```python
from tungsten.actions import BulkActionGroup, DeleteBulkAction
from tungsten.importexport import ExportBulkAction

table.bulk_actions([
    DeleteBulkAction(),
    BulkActionGroup([ExportBulkAction()]).label("More actions"),
])
```

It exports all table columns as CSV. For Excel, pass `format`:

```python
ExportBulkAction(format="xlsx")
```

> [!TIP]
> Export actions work on any table: resource lists, [relation managers](relation-managers) and [table widgets](widgets#table-widgets).

## Importing records

Importing has two parts: an `Importer` class that describes the file, and an `ImportAction` that shows the upload popup.

```python
from tungsten.importexport import ExportAction, ImportAction, ImportColumn, Importer


class ProductImporter(Importer):
    model = Product
    unique_by = "sku"
    columns = [
        ImportColumn("name").required(),
        ImportColumn("sku").label("SKU").required(),
        ImportColumn("price").numeric().required(),
        ImportColumn("stock").numeric(),
        ImportColumn("status").rule(
            lambda value: value in ("draft", "published") or "Status must be draft or published"),
        ImportColumn("category").relationship("category", "name"),
    ]


class ProductResource(Resource):
    model = Product

    @classmethod
    def table(cls, table):
        return table.columns([...]).header_actions([
            ImportAction(ProductImporter),
            ExportAction(),
        ])
```

Clicking **Import** opens a popup with a file upload, a list of the expected columns (required ones have a `*`) and a **Download example CSV** link. The user uploads a `.csv` or `.xlsx` file of up to 10 MB and clicks **Import**.

The first row of the file must hold the column names. For example:

```text
Name,SKU,Price,Stock,Status,Category
Premium T-Shirt,TSH-001,1299,120,published,Clothing
Running Shoes,SHO-014,"3,499",40,draft,Footwear
```

When it's done, a notification says how many rows were created and updated.

The `ImportAction` needs the `create` permission on the resource. See [Roles and permissions](roles-and-permissions).

### Matching file headers

A column in the file is matched to an `ImportColumn` by:

1. the column name (`sku`),
2. its label (`SKU`),
3. any extra names you give with `.guess()`.

Matching ignores upper and lower case. Columns in the file that don't match anything are ignored.

```python
ImportColumn("price").guess(["cost", "amount", "mrp"])
```

### ImportColumn options

| Method | What it does |
| --- | --- |
| `.label("SKU")` | The name shown in the popup, also accepted as a header |
| `.required()` | The row fails if this value is empty |
| `.guess(["cost", "mrp"])` | Other header names that mean this column |
| `.numeric()` | Turns the text into a number. Commas are removed (`"3,499"` → `3499`). Whole numbers become `int`. |
| `.boolean()` | `1`, `true`, `yes`, `y` and `on` become `True`, anything else `False` |
| `.relationship("category", "name")` | Finds the related record by that attribute (case doesn't matter) and sets the relationship |
| `.cast_state_using(fn)` | Changes the value yourself. `fn` can ask for `state` (the value) and `row` (the whole row as a dict). |
| `.rule(fn)` | Checks the value. `fn` gets `value` and `row`, and returns `True` (or `None`) when fine, or an error message. |
| `.example("TSH-001")` | A sample value for the example CSV file |

The steps run in this order: empty check, `numeric` / `boolean`, `relationship`, `cast_state_using`, then the rules.

Empty cells are skipped: the attribute is not set, so the model's default is kept (or, when updating, the old value stays).

```python
ImportColumn("email").required().rule(lambda value: "@" in value or "Not a valid email")
ImportColumn("name").cast_state_using(lambda state: state.title())
ImportColumn("is_featured").boolean()
```

### Updating existing records

Set `unique_by` to an attribute. If a row's value matches an existing record, that record is updated instead of creating a new one:

```python
class ProductImporter(Importer):
    model = Product
    unique_by = "sku"
```

Without `unique_by`, every row creates a new record.

With [multi-tenancy](multi-tenancy), only the current tenant's records are matched, so an import never changes another tenant's records. Relationship columns also only find the current tenant's related records.

### Failed rows

Rows with problems are skipped, and the rest are still imported. A row fails when:

- a required value is missing,
- a number can't be read,
- a related record isn't found ("Category “Toys” was not found"),
- a rule returns an error message,
- the database refuses the row (for example a duplicate unique value).

Each row is saved on its own, so one bad row doesn't undo the others. When some rows failed, the notification stays open and offers **Download failed rows**: a CSV with the original columns plus an **Error** column explaining each problem. Users can fix the file and import it again. Only signed-in users can download this file.

## Customizing the importer

Override these class methods for more control. Each gets `ctx` (the request context), so you can use `ctx.db` and `ctx.user`.

| Method | What it does |
| --- | --- |
| `resolve_record(ctx, data)` | Returns the record to fill: an existing one, or a new one. Default: look up `unique_by`, else `model()`. |
| `fill_record(ctx, record, data)` | Copies the values onto the record. Default: `setattr` for each value. |
| `before_save(ctx, record, data)` | Runs just before the record is saved. |
| `get_columns()` | Returns the column list. Default: `columns`. |

For example, to fill in who imported each product and keep a slug in sync:

```python
class ProductImporter(Importer):
    model = Product
    unique_by = "sku"
    columns = [ImportColumn("name").required(), ImportColumn("sku").required()]

    @classmethod
    def before_save(cls, ctx, record, data):
        record.slug = record.name.lower().replace(" ", "-")
        if record.created_by_id is None:
            record.created_by_id = ctx.user.id
```

`data` is a dictionary of the cleaned values. For relationship columns the key is the relationship name and the value is the related record.

> [!NOTE]
> Imports set values directly on the model. They don't run your resource's form validation or hooks (like `before_create`). Put any rules the import needs on the `ImportColumn`s or in `before_save`.

With [multi-tenancy](multi-tenancy), new records get the current tenant set automatically.

### A sample file

The **Download example CSV** link in the import popup gives a file with the column labels as the header row and the `.example()` values as one sample row:

```text
Name,SKU,Price,Stock,Status,Category
Premium T-Shirt,TSH-001,1299,120,published,Clothing
```

Only signed-in users who may use the import action (the `create` permission by default) can download it.

`Importer.example_csv()` returns the same CSV bytes, if you want to offer it somewhere else:

```python
ProductImporter.example_csv()
# b'\xef\xbb\xbfName,SKU,Price,...\r\nPremium T-Shirt,TSH-001,1299,...\r\n'
```
