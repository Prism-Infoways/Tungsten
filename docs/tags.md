---
title: Tags
description: Put colored tags on any record (leads, tickets, employees, invoices or your own models), filter lists by tag, tag many rows at once, and merge duplicate tags.
---

The `tungsten-tags` plugin lets you put tags like **VIP**, **Follow up** or **Delhi** on any record and filter by them. One list of tags is shared by every module, so a VIP lead, a VIP ticket and a VIP customer all use the same tag.

## Install

```bash
pip install tungsten-tags
```

```python
from tungsten_tags import TagsPlugin

panel.plugin(TagsPlugin())
panel.create_tables(engine)   # also creates the tag tables
```

This adds a **Tags** page. It needs `tungsten-admin` 0.1.7 or newer.

## Works with the other plugins

When these plugins are on the same panel, their records get tags with no extra code:

| Plugin | Records |
| --- | --- |
| `tungsten-leads` | Leads (uses the leads' own Tags box) |
| `tungsten-tickets` | Tickets (uses the tickets' own Tags box) |
| `tungsten-hr` | Employees |
| `tungsten-finance` | Customers and vendors, invoices, quotes, bills, credit and debit notes, expenses |

Each of them gets:

- a **Tags** box on the form, which suggests the tags you already have,
- a **Tags** column with colored badges,
- a **Tags** filter: show rows with *any* or *all* of the picked tags,
- **Add tags** and **Remove tags** for the selected rows.

The order of `panel.plugin(...)` calls does not matter. Pass `TagsPlugin(auto_attach=False)` to choose yourself.

## Your own resources

```python
tags = panel.get_plugin("tags")
tags.attach(ProductResource)                    # shares the tags with everything else
tags.attach(ProductResource, type="product")    # or keeps its own set of tags
```

The model needs one primary key column. If the model already keeps tags in a JSON list column, pass `column="tags"`: the plugin keeps the tag tables in step with it however the record is saved (panel, API, scripts).

In code:

```python
tags.set_tags(db, product, ["Sale", "New arrival"])   # exactly these
tags.add_tags(db, product, ["Sale"])
tags.remove_tags(db, product, ["Sale"])
tags.tags_for(db, product)                             # ["New arrival"]
db.commit()
```

Want the pieces somewhere else? `tags_column(Resource)`, `tags_input(Resource)`, `TagFilter(Resource)` and `bulk_actions(Resource)` are the same parts the plugin adds.

To filter a query yourself, use `tagged(Model, [tag_id], match="any")` from `tungsten_tags.service`.

## The Tags page

- **Name** and **color** (gray, brand, blue, green, amber, red, purple, indigo, teal, pink).
- **Group**: empty means shared by every module. A group (like *Industry*) keeps a set of tags apart.
- **Order**: smaller numbers come first in lists.
- **Used on**: open a tag to see how many leads, tickets, employees... carry it, with a link to each filtered list.
- **Merge**: select duplicates like *VIP* and *V.I.P.*, press **Merge** and pick the one to keep. Every record moves to it.
- **Rename** or **delete** a tag and every record is updated, including the Tags box of leads and tickets.
- **Sync tags** copies tags saved on leads and tickets before the plugin was added, and removes tags of records deleted outside the panel.

## Rules

- Names ignore capital letters: *vip*, *VIP* and *Vip* are one tag. The first spelling stays.
- Extra spaces are removed and names are cut at 50 characters. Hindi and other scripts work.
- A record has at most 20 tags. Change it with `TagsPlugin(max_tags=50)` (`None`: no limit).
- `TagsPlugin(allow_new=False)`: people pick existing tags only; new ones are made on the Tags page.
- Deleting a record removes its tags. Soft-deleted records keep them, so a restore brings them back.
- Another panel in the same app without the Tags plugin is not affected.

## Settings

| Option | Default | What it does |
| --- | --- | --- |
| `auto_attach` | `True` | Tag the records of Leads, Tickets, HR and Finance |
| `allow_new` | `True` | Let people type new tags on a record |
| `max_tags` | `20` | Most tags on one record |
| `navigation_group` | `None` | Menu group of the Tags page |
| `navigation_sort` | `90` | Its place in the menu |
