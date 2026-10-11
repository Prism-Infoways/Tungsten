# tungsten-kanban

Kanban boards for [Tungsten](https://tungsten.prisminfoways.com/). Show the records of any resource as columns (by status, stage or any field) and move them by drag and drop.

- Drag a card to another column to change it. With an order field, drag cards up and down too.
- Works with touch screens. Every card also has a **Move to** menu, for keyboards and small phones.
- The server checks every move: login, CSRF, permissions, tenancy, allowed moves and your own rules.
- If two people move the same card, the second one is told and the board refreshes. Nothing is lost.
- Search, "Only mine", counts per column, soft work-in-progress limits and "Load more" for big columns.
- Ready boards for the official plugins: **Leads** (stages), **Tickets** (status) and **HR** (leave requests).
- Every resource with a board gets a **Board view** button above its list.

## Install

```bash
pip install tungsten-kanban
```

```python
from tungsten_kanban import Board, KanbanPlugin

panel.plugin(KanbanPlugin(boards=[
    Board(TaskResource, column="status", columns={
        "todo": ("To do", "gray"),
        "doing": ("Doing", "primary"),
        "done": ("Done", "success"),
    }, description="notes", fields={"Due": "due_date"}, order_column="sort"),
]))
```

With `tungsten-leads`, `tungsten-tickets` or `tungsten-hr` added to the panel, their boards appear on their own. Turn them off with `KanbanPlugin(auto_boards=False)`, or pick some with `auto_boards=["tickets"]`.

Full guide: https://tungsten.prisminfoways.com/docs/kanban

## License

MIT
