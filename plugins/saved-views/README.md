# tungsten-saved-views

Saved table views for [Tungsten](https://tungsten.prisminfoways.com/). Users save their own filters, search, sort, tab and columns as one-click views like **My leads** or **Pending**, share them with the team, and pick the view a list opens with.

```bash
pip install tungsten-saved-views
```

```python
from tungsten_saved_views import SavedViewsPlugin

panel.plugin(SavedViewsPlugin())
panel.create_tables(engine)
```

Every resource list gets a views bar above the table:

- **Save view** keeps the filters, search, sort, tab, page size, grouping and visible columns.
- One click opens a view. The current view is highlighted.
- **Open the list with this view** makes it the user's default.
- Rename, update, share and delete from the arrow next to a view, or on the **Saved views** page in the user menu.
- Ready views from code with `preset()`, with `{me}` and `{today}`.
- **My tickets** and **My leads** are added when `tungsten-tickets` or `tungsten-leads` is installed.
- Permissions `saved_views.share` and `saved_views.manage` for panels with roles.

Full guide: https://tungsten.prisminfoways.com/docs/saved-views

Try it: `uvicorn example:app` in this folder, then open http://127.0.0.1:8000/admin (admin@example.com / password).

Needs `tungsten-admin` 0.1.7 or newer.
