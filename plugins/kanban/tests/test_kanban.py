from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import STATUSES, Task, TaskResource, moves
from sqlalchemy import select
from tungsten_hr import LeaveRequest
from tungsten_kanban import Board, KanbanPlugin, MoveRefused
from tungsten_leads import Lead, LeadActivity
from tungsten_tickets import Ticket, TicketReply


def task(panel, title):
    with panel.db() as db:
        return db.scalar(select(Task).where(Task.title == title))


def order(panel, status):
    with panel.db() as db:
        return [t.title for t in db.scalars(select(Task).where(Task.status == status).order_by(Task.sort))]


# ---------------------------------------------------------------------- page
def test_board_page_shows_columns_cards_and_assets(admin):
    r = admin.get("/admin/tasks-board")
    assert r.status_code == 200
    html = r.text
    assert "Tasks board" in html
    for label in ("To do", "Doing", "Done"):
        assert f">{label}</h2>" in html
    assert "Write brief" in html and "notes 0" in html
    assert "kanban.css" in html and "kanban.js" in html
    assert 'data-move-url="/admin/_kanban/tasks-board/move"' in html
    assert "1/1" in html  # Doing has a limit of 1
    assert "Mine" in html  # badge from add_card_badges
    # a status no column has goes in "Other", where cards can't be dropped
    assert ">Other</h2>" in html and 'data-tk-lane="" data-accepts="false"' in html
    # the sidebar lists the board, and the auto boards of the other plugins
    for slug in ("leads-board", "tickets-board", "leave-board"):
        assert f'href="/admin/{slug}"' in html


def test_locked_and_final_cards_are_not_draggable(admin):
    html = admin.get("/admin/tasks-board").text
    locked = html.split('data-tk-card="5"')[0].rsplit("<article", 1)[1]
    assert "tk-locked" in locked
    # "done" may only go back to "doing"
    done = html.split('data-tk-card="4"')[1].split("</article>")[0]
    assert 'data-targets="doing,done"' in html.split('data-tk-card="4"')[1][:200]
    assert '<option value="todo">' not in done and '<option value="doing">' in done


def test_list_page_links_to_board(admin):
    assert 'href="/admin/tasks-board"' in admin.get("/admin/tasks").text
    assert "Board view" in admin.get("/admin/tasks").text


def test_board_needs_login(client, panel):
    r = client.get("/admin/tasks-board", follow_redirects=False)
    assert r.status_code in (302, 303)
    r = client.client.post("/admin/_kanban/tasks-board/move", data={"record": "1", "to": "doing"},
                           follow_redirects=False)
    assert r.status_code in (302, 303, 401, 419)
    assert task(panel, "Write brief").status == "todo"


# ---------------------------------------------------------------------- moves
def test_move_card_to_another_column(admin, panel):
    r = admin.move("tasks-board", 1, "doing", frm="todo", order=[1, 3])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["changed"]
    assert body["counts"]["doing"] == 2 and body["counts"]["todo"] == 2
    assert body["message"] == "Moved to Doing"
    assert task(panel, "Write brief").status == "doing"
    assert order(panel, "doing") == ["Write brief", "Build form"]
    assert moves == [("Write brief", "todo", "doing")]


def test_reorder_inside_a_column(admin, panel):
    r = admin.move("tasks-board", 2, "todo", frm="todo", order=[2, 1])
    assert r.json()["ok"]
    # the two on screen swapped; "Locked task" (not sent) kept its place
    assert order(panel, "todo") == ["Design page", "Write brief", "Locked task"]
    assert moves == []


def test_reorder_ignores_cards_of_other_columns(admin, panel):
    admin.move("tasks-board", 2, "todo", frm="todo", order=[4, 2, 999, "x", 1])
    assert order(panel, "todo") == ["Design page", "Write brief", "Locked task"]
    assert task(panel, "Ship it").status == "done"


def test_stale_move_is_refused(admin, panel):
    r = admin.move("tasks-board", 1, "doing", frm="done")
    assert r.status_code == 409 and r.json()["reload"]
    assert task(panel, "Write brief").status == "todo"


def test_unknown_column_and_card(admin, panel):
    r = admin.move("tasks-board", 1, "nope", frm="todo")
    assert r.status_code == 422 and r.json()["reload"]
    r = admin.move("tasks-board", 999, "doing")
    assert r.status_code == 404
    r = admin.move("tasks-board", "abc", "doing")
    assert r.status_code == 404
    r = admin.move("no-such-board", 1, "doing")
    assert r.status_code == 404 and not r.json()["ok"]
    # "Other" is not a target
    r = admin.move("tasks-board", 1, "", frm="todo")
    assert r.status_code == 422


def test_move_needs_csrf_token(admin, panel):
    r = admin.client.post("/admin/_kanban/tasks-board/move", data={"record": "1", "to": "doing"})
    assert r.status_code == 419
    assert task(panel, "Write brief").status == "todo"


def test_policy_blocks_move(admin, panel):
    r = admin.move("tasks-board", 5, "doing", frm="todo")
    assert r.status_code == 403
    assert task(panel, "Locked task").status == "todo"


def test_transitions_block_move(admin, panel):
    r = admin.move("tasks-board", 4, "todo", frm="done")
    assert r.status_code == 422
    assert r.json()["error"] == "Done cards can't go to To do."
    assert admin.move("tasks-board", 4, "doing", frm="done").json()["ok"]


def test_card_from_other_column_can_be_moved_out(admin, panel):
    assert admin.move("tasks-board", 6, "todo", frm="archived").json()["ok"]
    assert task(panel, "Odd one").status == "todo"


def test_null_status_shows_in_other(admin, panel):
    with panel.db() as db:
        db.get(Task, 1).status = None
        db.commit()
    html = admin.get("/admin/tasks-board").text
    other = html.split(">Other</h2>")[1]
    assert "Write brief" in other
    assert admin.move("tasks-board", 1, "doing", frm="").json()["ok"]


def test_move_rules_and_errors(admin, panel):
    kanban = panel.get_plugin("kanban")
    board = kanban.boards["tasks-board"]

    board.can_move = lambda record, new: "Not on Fridays" if new == "doing" else True
    r = admin.move("tasks-board", 1, "doing", frm="todo")
    assert r.status_code == 422 and r.json()["error"] == "Not on Fridays"

    board.can_move = None

    def boom(record, new):
        record.status = new
        raise RuntimeError("database fell over")

    board.on_move = boom
    r = admin.move("tasks-board", 1, "doing", frm="todo")
    assert r.status_code == 500 and "try again" in r.json()["error"]
    assert task(panel, "Write brief").status == "todo"  # rolled back

    def refuse(record, new):
        record.status = new
        raise MoveRefused("Finish the checklist first")

    board.on_move = refuse
    r = admin.move("tasks-board", 1, "doing", frm="todo")
    assert r.status_code == 422 and r.json()["error"] == "Finish the checklist first"
    assert task(panel, "Write brief").status == "todo"

    def bad_listener(record):
        raise ValueError("Listener says no")

    board.on_move = None
    kanban.on_card_moved("bad", bad_listener)
    r = admin.move("tasks-board", 1, "doing", frm="todo")
    assert r.status_code == 422 and r.json()["error"] == "Listener says no"
    assert task(panel, "Write brief").status == "todo"


def test_broken_badge_function_does_not_break_board(admin, panel):
    panel.get_plugin("kanban").add_card_badges("test", lambda record: 1 / 0)
    assert admin.get("/admin/tasks-board").status_code == 200


# ---------------------------------------------------------------------- search, mine, more
def test_search_and_only_mine(admin):
    html = admin.get("/admin/tasks-board?q=design").text
    assert "Design page" in html and "Write brief" not in html
    # % and _ are searched as text, not as wildcards
    html = admin.get("/admin/tasks-board?q=%25").text
    assert "Design page" not in html
    html = admin.get("/admin/tasks-board?mine=1").text
    assert "Write brief" in html and "Design page" not in html and "Build form" not in html
    long = "x" * 5000
    assert admin.get(f"/admin/tasks-board?q={long}").status_code == 200


def test_load_more(admin, panel):
    board = panel.get_plugin("kanban").boards["tasks-board"]
    board.limit = 2
    html = admin.get("/admin/tasks-board").text
    assert "Load more" in html and "Locked task" not in html
    r = admin.get("/admin/_kanban/tasks-board/cards?column=todo&offset=2")
    assert r.status_code == 200 and "Locked task" in r.text and "Load more" not in r.text
    assert admin.get("/admin/_kanban/tasks-board/cards?column=nope").status_code == 404
    assert admin.get("/admin/_kanban/tasks-board/cards?column=todo&offset=-5").status_code == 200
    assert admin.get("/admin/_kanban/tasks-board/cards?column=todo&offset=abc").status_code == 200


# ---------------------------------------------------------------------- setup errors
def test_board_checks_its_settings():
    with pytest.raises(ValueError):
        Board(TaskResource, column="nope", columns=STATUSES)
    with pytest.raises(ValueError):
        Board(TaskResource, columns=STATUSES, order_column="nope")
    with pytest.raises(ValueError):
        Board(TaskResource, columns=STATUSES, search=["nope"])
    with pytest.raises(ValueError):
        Board(TaskResource, columns=STATUSES, slug="Bad Slug")
    with pytest.raises(ValueError):
        Board(object, columns=STATUSES)


def test_auto_boards_can_be_turned_off():
    from tungsten import Panel

    panel = Panel(path="/admin", secret_key="x")
    from tungsten_tickets import TicketsPlugin

    plugin = KanbanPlugin(auto_boards=False)
    panel.plugin(plugin)
    panel.plugin(TicketsPlugin())
    panel.boot()
    assert plugin.boards == {}
    with pytest.raises(RuntimeError):
        plugin.add_board(Board(TaskResource, columns=STATUSES))


def test_board_lookup_helpers(panel):
    panel.boot()
    kanban = panel.get_plugin("kanban")
    assert kanban.board_for(TaskResource).slug == "tasks-board"
    assert kanban.board_for("tickets").slug == "tickets-board"
    assert kanban.board_url("tasks-board") == "/admin/tasks-board"
    assert kanban.board_for("nothing") is None


# ---------------------------------------------------------------------- other plugins
def test_leads_board_logs_the_move(admin, panel):
    with panel.db() as db:
        db.add(Lead(name="Meera", company="Acme", status="new", value=50000))
        db.commit()
    html = admin.get("/admin/leads-board").text
    assert "Meera" in html and "Acme" in html and "50,000" in html
    r = admin.move("leads-board", 1, "contacted", frm="new")
    assert r.json()["ok"], r.text
    with panel.db() as db:
        assert db.get(Lead, 1).status == "contacted"
        notes = [a.body for a in db.scalars(select(LeadActivity))]
    assert any("on the board" in n and "by Asha Admin" in n for n in notes)
    assert 'href="/admin/leads-board"' in admin.get("/admin/leads").text


def test_tickets_board_uses_help_desk_rules(admin, panel):
    from tungsten_tickets import create_ticket

    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        create_ticket(db, subject="Printer broken", requester_name="Kiran", priority="urgent")
        db.commit()
    html = admin.get("/admin/tickets-board").text
    assert "Printer broken" in html and "Urgent" in html
    r = admin.move("tickets-board", 1, "resolved", frm="open")
    assert r.json()["ok"], r.text
    with panel.db() as db:
        ticket = db.get(Ticket, 1)
        assert ticket.status == "resolved" and ticket.resolved_at is not None
        events = [e.body for e in db.scalars(select(TicketReply))]
    assert any("Status changed from Open to Resolved" in e for e in events)


def test_leave_board_approves_with_hr_rules(admin, panel):
    from tungsten_hr import Employee
    from tungsten_hr.service import request_leave

    day = dt.date.today() + dt.timedelta(days=30)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ravi = db.scalar(select(Employee).where(Employee.code == "EMP-2"))
        asha = db.scalar(select(Employee).where(Employee.code == "EMP-1"))
        request_leave(db, ravi, 1, day)
        request_leave(db, asha, 1, day)
        db.commit()
    html = admin.get("/admin/leave-board").text
    assert "Ravi Staff" in html and "Casual" in html
    # pending can't come back from approved, and your own request can't be approved by you
    r = admin.move("leave-board", 2, "approved", frm="pending")
    assert r.status_code == 422 and "own leave" in r.json()["error"]
    r = admin.move("leave-board", 1, "approved", frm="pending")
    assert r.json()["ok"], r.text
    assert r.json()["targets"] == ["approved", "cancelled"]
    r = admin.move("leave-board", 1, "pending", frm="approved")
    assert r.status_code == 422
    with panel.db() as db:
        assert db.get(LeaveRequest, 1).status == "approved"
        assert db.get(LeaveRequest, 2).status == "pending"


def test_leave_board_shows_hr_balance_errors(admin, panel):
    from tungsten_hr import Employee
    from tungsten_hr.service import request_leave

    day = dt.date.today() + dt.timedelta(days=40)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ravi = db.scalar(select(Employee).where(Employee.code == "EMP-2"))
        first = request_leave(db, ravi, 1, day)
        nxt = day + dt.timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += dt.timedelta(days=1)
        # made by hand: asking for it now is fine, approving both would go over the one day a year
        second = LeaveRequest(employee_id=ravi.id, leave_type_id=1, start_date=nxt, end_date=nxt, days=1,
                              status="pending")
        db.add(second)
        db.commit()
        ids = first.id, second.id
    # HR counts both open requests against the one day, so it refuses, and says why
    r = admin.move("leave-board", ids[0], "approved", frm="pending")
    assert r.status_code == 422 and "day(s) left" in r.json()["error"]
    with panel.db() as db:
        assert db.get(LeaveRequest, ids[0]).status == "pending"
    # rejecting needs no balance
    assert admin.move("leave-board", ids[1], "rejected", frm="pending").json()["ok"]
    assert admin.move("leave-board", ids[0], "approved", frm="pending").json()["ok"]


def test_json_answers_are_valid(admin):
    r = admin.move("tasks-board", 2, "doing", frm="todo")
    json.loads(r.text)


def test_card_text_is_escaped(admin, panel):
    with panel.db() as db:
        db.add(Task(title="<script>alert(1)</script>", notes="<b>bold</b>", status="todo", sort=99))
        db.commit()
    html = admin.get("/admin/tasks-board").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<b>bold</b>" not in html
