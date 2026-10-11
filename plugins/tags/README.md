# tungsten-tags

Tags for [Tungsten](https://tungsten.prisminfoways.com/): put colored tags on any record (leads, tickets, employees, invoices or your own models) and filter by them.

```bash
pip install tungsten-tags
```

```python
from tungsten_tags import TagsPlugin

panel.plugin(TagsPlugin())
panel.create_tables(engine)
```

- A **Tags** page: name, color, group, where each tag is used, merge duplicates, sync.
- With `tungsten-leads`, `tungsten-tickets`, `tungsten-hr` and `tungsten-finance` on the panel, their records get a Tags box, a Tags column, a tag filter (any / all) and **Add tags** / **Remove tags** bulk actions. No extra code.
- Your own resources: `panel.get_plugin("tags").attach(ProductResource)`.
- In code: `set_tags`, `add_tags`, `remove_tags`, `tags_for`.
- "VIP" and "vip" are one tag. Deleted records lose their tags. Rename, merge or delete a tag and every record follows.

Guide: https://tungsten.prisminfoways.com/docs/tags

## Try it

```bash
pip install -e . -e plugins/tags -e plugins/leads -e plugins/tickets -e plugins/hr uvicorn
uvicorn plugins.tags.example:app --reload
```

## Tests

```bash
pip install -e ".[dev]" -e plugins/tags -e plugins/leads -e plugins/tickets -e plugins/hr -e plugins/finance
pytest plugins/tags/tests
```
