---
title: Kanban boards
description: Show any resource as a drag-and-drop board with columns by status, with ready boards for leads, tickets and leave requests.
---

The `tungsten-kanban` plugin shows the records of any resource as a board. Each column is one value of a field, like a status or a stage. Drag a card to another column and the record changes.

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
    }),
]))
```

The board is a page in the menu, next to its resource, at `/admin/tasks-board`. The resource's list gets a **Board view** button, and the board has **List view** and **New** buttons. With the [Quick Create](quick-create) plugin, **New** opens the form in a side panel and the new card shows on the board right away. It needs `tungsten-admin` 0.1.5 or newer. The plugin has no tables of its own.

## Ready boards for other plugins

When these plugins are on the same panel, their boards are added for you. It does not matter which plugin you add first.

| Plugin | Board | What a move does |
| --- | --- | --- |
| `tungsten-leads` | **Leads board**: New, Contacted, Qualified, Proposal sent, Won, Lost | Changes the stage and writes it on the lead's timeline |
| `tungsten-tickets` | **Tickets board**: Open, In progress, Waiting on customer, Resolved, Closed | Changes the status like the ticket page does: it is logged, and the customer gets the "resolved" email |
| `tungsten-hr` | **Leave board**: Pending, Approved, Rejected, Cancelled | Approves, rejects or cancels with the same checks as the buttons: leave balance, clashes, and no approving your own leave |

These boards also have search, **Only mine** (leads and tickets), and badges such as priority, overdue, source and leave type.

```python
KanbanPlugin(auto_boards=False)            # no ready boards
KanbanPlugin(auto_boards=["tickets"])      # only the tickets board
```

To change a ready board, make your own `Board` for that resource. Yours is used instead.

## Columns

`columns` maps each value to a label, or to `(label, color)`. Colors are `gray`, `primary`, `info`, `success`, `warning`, `danger`, `indigo`, `pink`, `purple` and `teal`.

```python
Board(TaskResource, column="status", columns={"todo": "To do", "done": ("Done", "success")})
```

It can also be a function, so the columns follow settings that change while the app runs:

```python
Board(LeadResource, column="status", columns=lambda ctx: load_stages(ctx.db))
```

For an `Enum` field you can leave `columns` out: each member becomes a column.

Records whose value is in no column (an old status, or empty) show in an **Other** column at the end, so nothing is hidden. Cards can be dragged out of it, but not into it. Turn it off with `show_other=False`.

`hidden=["closed"]` leaves a column out of the board.

## Cards

```python
Board(
    TaskResource, column="status", columns=STATUSES,
    title="name",                                  # default: the resource's record title
    description="notes",                           # a short grey line
    fields={"Due": "due_date", "Owner": "owner.name"},
    badges=["priority", lambda record: ("Late", "danger") if record.is_late else None],
    color=lambda record: "danger" if record.urgent else None,   # a colored edge
)
```

- Every option is an attribute name (`"owner.name"` follows relations) or a function. Functions can ask for `record`, `ctx`, `db`, `user` and `board`.
- Dates, numbers and yes/no values are written in a readable way. Long text is cut short.
- A badge is text, `(text, color)`, or a list of them. Up to 6 show on a card.
- The card title opens the record's view page, or its edit page. Set `card_url` to link somewhere else.

## Order inside a column

Give an integer field and people can drag cards up and down inside a column too:

```python
Board(TaskResource, column="status", columns=STATUSES, order_column="sort")
```

The cards on screen take the places they held before, in their new order. Cards not on screen (because of a search, or not loaded yet) keep their place. Without `order_column`, cards are sorted newest first, or by `sort_by="-created_at"` / `sort_by=["priority", "-id"]`.

## Rules for moves

```python
Board(
    LeaveResource, column="status", columns=LEAVE_STATUSES,
    transitions={"pending": ["approved", "rejected"], "approved": ["cancelled"]},
    can_move=lambda record, new, user: new != "approved" or user.is_manager or "Only managers approve leave.",
    on_move=lambda record, new, db, ctx: approve_or_reject(db, record, new, ctx),
)
```

- `transitions` lists where each column may go. A column that is not listed may go anywhere. A column with an empty list is final: its cards can't move.
- `can_move` gets `record`, `old`, `new`, `ctx`, `user` and `db`. Return `True` to allow, or `False` or a reason to refuse. The reason is shown to the user.
- `on_move` does the move itself, for example through your own service that logs and sends emails. Without it, the field is set. Raise `MoveRefused("reason")` (or `ValueError`) to stop the move with a message.
- Cards the user may not move, by the resource's `update` permission or policy, show without a drag handle.

The board shows the allowed columns while you drag, and the **Move to** menu only lists them. The server checks again on every move.

## Search, "Only mine" and big columns

```python
Board(TicketResource, column="status", columns=STATUSES,
      search=["number", "subject", "requester_email"], assignee="assigned_to", limit=50,
      wip_limits={"in_progress": 5}, query=lambda query, model: query.where(model.archived.is_(False)))
```

- `search` adds a search box. It looks in those fields.
- `assignee` adds an **Only mine** switch. The field holds the user's id.
- `limit` is how many cards a column shows (default 50, at most 200). The rest load with **Load more**.
- `wip_limits` shows the count as `4/5` and turns it red above the limit. It does not block moves.
- `query` narrows the records on the board.

Every column shows how many cards it has, for the current search.

## Who can see and move cards

- A board uses its resource's permissions. You need `view_any` to open it and `update` (or the policy's `update`) to move a card.
- `permission="board.tasks"` adds an extra permission. It shows on the Roles screen.
- Records follow the resource's own `query()`, multi-tenancy and soft delete. A user never sees or moves a record they can't see in the list.
- Moves are sent with the panel's CSRF token and need a signed-in user.

## When something goes wrong

- **Someone else moved the card first.** The move is refused, the user is told, and the board refreshes.
- **The record is gone, or the column was removed.** Same: a message, then a refresh.
- **A rule says no.** The card goes back to where it was, with the reason.
- **No internet, or the session ended.** The card goes back, with a message to try again or sign in.
- **An error in your code.** The change is undone, the error is logged, and the user sees "Could not save the move".

## Phones and keyboards

Cards can be dragged with a finger: a short press picks one up, so the board still scrolls. Every card also has a **Move to** menu, which works with a keyboard and screen readers. Columns scroll sideways on small screens. Dark mode works.

## For other plugins

```python
kanban = panel.get_plugin("kanban")

kanban.add_board(Board(...))                                   # before the panel starts
kanban.on_card_moved("slack", lambda record, old, new, board: post_to_slack(record, new))
kanban.add_card_badges("tags", lambda record: [(t, "info") for t in (record.tags or [])])
kanban.board_for(LeadResource)                                 # the board, or None
kanban.board_url("leads-board")                                # "/admin/leads-board"
```

`on_card_moved` runs before the move is saved, so an error there undoes the move. A broken badge function is logged and skipped, and the board still shows.

## All options

| Option | Default | What it does |
| --- | --- | --- |
| `column` | `"status"` | The field that says which column a record is in |
| `columns` | from an Enum | Values and their labels and colors |
| `slug` | `<resource>-board` | The page address |
| `label` | "Tasks board" | The page title and menu label |
| `subheading` | a short help line | The line under the title |
| `icon` | `"square-kanban"` | Menu icon |
| `navigation_group`, `navigation_sort` | the resource's | Where it sits in the menu |
| `show_in_navigation` | `True` | `False` hides the menu item (the Board view button still links to it) |
| `title`, `description`, `fields`, `badges`, `color`, `card_url` | | What a card shows |
| `order_column` | `None` | Integer field for the order inside a column |
| `sort_by` | newest first | Order when there is no `order_column` |
| `search`, `assignee`, `query` | | Search box, Only mine, and the records on the board |
| `limit` | `50` | Cards per column before Load more |
| `wip_limits`, `hidden`, `show_other` | | Column limits, hidden columns, and the Other column |
| `transitions`, `can_move`, `on_move` | | Rules for moves, and how a move is saved |
| `permission` | `None` | An extra permission to open the board |
| `empty_text` | "No cards here" | The text in an empty column |
