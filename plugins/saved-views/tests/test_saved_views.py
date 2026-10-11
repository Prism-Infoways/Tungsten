from __future__ import annotations

import re

import pytest
from conftest import client_for, make_panel
from sqlalchemy import select
from tungsten_saved_views import SavedView, SavedViewDefault, SavedViewsPlugin
from tungsten_saved_views.service import ViewError, clean_query, expand, match_key, query_pairs


def save(client, **data):
    payload = {"resource": "tasks", "query": "_f=1&filters.status.value=pending", "name": "Pending"}
    payload.update(data)
    return client.post("/admin/_views/save", payload)


def views(panel):
    with panel.db() as db:
        return list(db.scalars(select(SavedView).order_by(SavedView.id)).all())


def rows(html: str) -> set[str]:
    return {t for t in ("Alpha open", "Beta pending", "Gamma closed") if t in html}


def chip(html: str, name: str) -> str:
    """The <a> tag of a view chip."""
    m = re.search(r'<a href="[^"]*" data-view-match="[^"]*" title="' + re.escape(name) + r'"[^>]*>', html)
    assert m, f"no chip {name}"
    return m.group(0)


# ---------------------------------------------------------------------- the address
def test_query_is_cleaned():
    q = clean_query("?page=4&_panel=1&host=x&search=abc&filters.status.value=open&reordering=1&tab=done")
    assert q == "search=abc&filters.status.value=open&tab=done&_f=1"
    assert clean_query("") == ""
    assert clean_query("_f=1&_f=1&filters.a.value=1") == "_f=1&filters.a.value=1"
    assert match_key("b=1&tab=x&search=y&page=2") == match_key("search=y&tab=x")
    assert match_key("") == "[]"
    with pytest.raises(ViewError):
        clean_query("search=" + "x" * 5000)
    with pytest.raises(ViewError):
        query_pairs("&".join(f"filters.f{i}.value=1" for i in range(300)))


def test_placeholders():
    import datetime as dt

    q = clean_query("filters.owner.value={me}&filters.day.from={today}")
    assert expand(q, "7", dt.date(2026, 1, 2)) == "filters.owner.value=7&filters.day.from=2026-01-02&_f=1"
    assert expand("search=a", "7") == "search=a"


# ---------------------------------------------------------------------- saving and opening
def test_bar_shows_on_lists(admin):
    html = admin.get("/admin/tasks").text
    assert "data-tw-views" in html and "Save view" in html
    assert 'action="/admin/_views/save"' in html


def test_save_view_and_open_it(admin, panel):
    r = save(admin, query="page=3&_panel=1&_f=1&filters.status.value=pending&sort=title&direction=desc")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/tasks?_f=1&filters.status.value=pending&sort=title&direction=desc"
    [view] = views(panel)
    assert view.name == "Pending" and view.user_id == "1" and not view.is_shared
    assert view.hidden_columns == []  # the owner column was showing
    html = admin.get(r.headers["location"]).text
    assert rows(html) == {"Beta pending"}
    assert 'aria-current="page"' in chip(html, "Pending")
    plain = admin.get("/admin/tasks").text
    assert 'aria-current="page"' not in chip(plain, "Pending")
    assert rows(plain) == {"Alpha open", "Beta pending", "Gamma closed"}


def test_view_keeps_tab_and_search(admin):
    save(admin, query="tab=done", name="Done")
    html = admin.get("/admin/tasks?tab=done").text
    assert rows(html) == {"Gamma closed"}
    assert 'aria-current="page"' in chip(html, "Done")


def test_default_view_opens_first(admin, panel):
    save(admin, default="1")
    html = admin.get("/admin/tasks").text
    assert rows(html) == {"Beta pending"}
    assert "history.replaceState" in html and "/admin/tasks?_f=1\\u0026filters.status.value=pending" in html
    assert 'aria-current="page"' in chip(html, "Pending")
    every = admin.get("/admin/tasks?_view=all").text  # the "All" chip
    assert rows(every) == {"Alpha open", "Beta pending", "Gamma closed"}
    assert 'href="/admin/tasks?_view=all"' in every
    # turn it off again
    view = views(panel)[0]
    assert admin.post("/admin/_views/default", {"resource": "tasks", "key": ""}).status_code == 303
    assert rows(admin.get("/admin/tasks").text) == {"Alpha open", "Beta pending", "Gamma closed"}
    assert admin.post("/admin/_views/default", {"resource": "tasks", "key": str(view.id)}).status_code == 303
    assert rows(admin.get("/admin/tasks").text) == {"Beta pending"}


def test_hidden_columns_are_part_of_the_view(admin, panel):
    admin.get("/admin/_tw/table?host=resource:tasks&_cols=1&cols=")  # hide the owner column
    save(admin, name="Narrow")
    assert views(panel)[0].hidden_columns == ["owner"]
    admin.get("/admin/_tw/table?host=resource:tasks&_cols=1&cols=owner")  # show it again
    html = admin.get("/admin/tasks").text
    assert "_cols=1" in chip(html, "Narrow") and "cols=owner" not in chip(html, "Narrow")


# ---------------------------------------------------------------------- mistakes people make
@pytest.mark.parametrize("data,message", [
    ({"name": "   "}, "Give the view a name."),
    ({"name": "x" * 81}, "Keep the name under 80 letters."),
    ({"query": "page=2"}, "Nothing to save yet."),
    ({"query": "search=" + "y" * 5000}, "too long"),
])
def test_bad_input_is_refused(admin, panel, data, message):
    r = save(admin, **data)
    assert r.status_code == 303
    assert views(panel) == []
    assert message in admin.get(r.headers["location"]).text


def test_duplicate_names_are_refused(admin, panel):
    save(admin)
    r = save(admin, name="  pending ")
    assert len(views(panel)) == 1
    assert "already have a view with this name" in admin.get(r.headers["location"]).text


def test_limit_per_list(tmp_path):
    panel = make_panel(tmp_path, SavedViewsPlugin(max_views=2))
    client = client_for(panel)
    client.login()
    client.get("/admin/tasks")
    save(client, name="One")
    save(client, name="Two")
    r = save(client, name="Three")
    assert [v.name for v in views(panel)] == ["One", "Two"]
    html = client.get(r.headers["location"]).text
    assert "up to 2 views" in html
    assert "@click=\"saving = true\"" not in html  # no more Save button


def test_unknown_or_excluded_lists(admin, tmp_path):
    assert save(admin, resource="nope").status_code == 404
    assert save(admin, resource="").status_code == 404
    panel = make_panel(tmp_path / "x", SavedViewsPlugin(exclude=["tasks"])) if (tmp_path / "x").mkdir() is None else None
    client = client_for(panel)
    client.login()
    assert "data-tw-views" not in client.get("/admin/tasks").text
    assert save(client).status_code == 404


def test_needs_csrf_and_login(client, panel):
    client.get("/admin/login")
    assert client.client.post("/admin/_views/save", data={"resource": "tasks", "name": "x"},
                              follow_redirects=False).status_code in (302, 303)  # sent to the login page
    client.login()
    r = client.client.post("/admin/_views/save", data={"resource": "tasks", "name": "x", "query": "search=a"})
    assert r.status_code == 419
    assert views(panel) == []


def test_names_are_escaped(admin):
    save(admin, name='<script>alert(1)</script>')
    html = admin.get("/admin/tasks").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_broken_view_does_not_break_the_list(admin, panel):
    with panel.db() as db:
        db.add(SavedView(user_id="1", resource="tasks", name="Old", query="_f=1&filters.gone.value=1&sort=nope"))
        db.add(SavedViewDefault(user_id="1", resource="tasks", view_key="999"))  # its view was deleted
        db.commit()
    html = admin.get("/admin/tasks").text
    assert rows(html) == {"Alpha open", "Beta pending", "Gamma closed"}
    old = admin.get("/admin/tasks?_f=1&filters.gone.value=1&sort=nope")
    assert old.status_code == 200 and rows(old.text) == {"Alpha open", "Beta pending", "Gamma closed"}


# ---------------------------------------------------------------------- changing views
def test_rename_update_delete(admin, panel):
    save(admin, default="1")
    view = views(panel)[0]
    r = admin.post(f"/admin/_views/{view.id}/rename", {"name": "Waiting", "_sharing": "1", "shared": "1"})
    assert r.status_code == 303
    view = views(panel)[0]
    assert view.name == "Waiting" and view.is_shared
    r = admin.post(f"/admin/_views/{view.id}/update", {"query": "_f=1&filters.status.value=open&page=2"})
    assert r.status_code == 303
    assert views(panel)[0].query == "_f=1&filters.status.value=open"
    assert rows(admin.get("/admin/tasks").text) == {"Alpha open"}  # still the default
    assert admin.post(f"/admin/_views/{view.id}/update", {"query": ""}).status_code == 303
    assert views(panel)[0].query == "_f=1&filters.status.value=open"  # an empty update is refused
    r = admin.post(f"/admin/_views/{view.id}/delete")
    assert r.status_code == 303
    assert views(panel) == []
    with panel.db() as db:
        assert db.scalars(select(SavedViewDefault)).all() == []
    assert rows(admin.get("/admin/tasks").text) == {"Alpha open", "Beta pending", "Gamma closed"}
    assert admin.post(f"/admin/_views/{view.id}/delete").status_code == 404
    assert admin.post("/admin/_views/abc/delete").status_code == 404


def test_rename_to_a_taken_name(admin, panel):
    save(admin, name="One")
    save(admin, name="Two", query="search=Beta")
    one = views(panel)[0]
    admin.post(f"/admin/_views/{one.id}/rename", {"name": "two"})
    assert views(panel)[0].name == "One"


# ---------------------------------------------------------------------- other people
def test_private_and_shared_views(admin, panel):
    save(admin, name="Mine")
    save(admin, name="Team", query="search=Alpha", shared="1", default="1")
    mine, team = views(panel)
    ravi = client_for(panel)
    ravi.login("ravi@example.com")
    html = ravi.get("/admin/tasks").text
    assert 'title="Mine"' not in html
    assert 'title="Team"' in html and "Shared by a teammate." in html
    assert rows(html) == {"Alpha open", "Beta pending", "Gamma closed"}  # the admin's default is theirs only
    for path in (f"{mine.id}/rename", f"{team.id}/rename", f"{team.id}/update", f"{team.id}/delete"):
        assert ravi.post(f"/admin/_views/{path}", {"name": "Hacked", "query": "search=x"}).status_code == 403
    assert [v.name for v in views(panel)] == ["Mine", "Team"]
    # a shared view can be their own default
    assert ravi.post("/admin/_views/default", {"resource": "tasks", "key": str(team.id)}).status_code == 303
    assert rows(ravi.get("/admin/tasks").text) == {"Alpha open"}
    # but not someone's private view
    assert ravi.post("/admin/_views/default", {"resource": "tasks", "key": str(mine.id)}).status_code == 404


def test_sharing_can_be_turned_off(tmp_path):
    panel = make_panel(tmp_path, SavedViewsPlugin(sharing=False))
    client = client_for(panel)
    client.login()
    html = client.get("/admin/tasks").text
    assert "Share with everyone" not in html
    save(client, shared="1")
    assert views(panel)[0].is_shared is False


def test_roles_decide_who_shares(tmp_path):
    def gate(user, permission):
        if permission.startswith("saved_views."):
            return user.id == 1  # only the admin may share and manage
        return True

    panel = make_panel(tmp_path)
    panel.auth.gate = gate
    admin, ravi = client_for(panel), client_for(panel)
    admin.login()
    ravi.login("ravi@example.com")
    ravi.get("/admin/tasks")
    save(ravi, name="Ravi's", shared="1")
    assert views(panel)[0].is_shared is False
    admin.get("/admin/tasks")
    save(admin, name="Team", shared="1", query="search=a")
    team = views(panel)[1]
    assert team.is_shared
    # the admin may manage views others shared; make Ravi's shared and let the admin rename it
    with panel.db() as db:
        db.get(SavedView, views(panel)[0].id).is_shared = True
        db.commit()
    assert admin.post(f"/admin/_views/{views(panel)[0].id}/rename", {"name": "Renamed"}).status_code == 303
    assert views(panel)[0].name == "Renamed"


# ---------------------------------------------------------------------- presets and other plugins
def test_presets_from_code(tmp_path):
    plugin = SavedViewsPlugin().preset("tasks", "My tasks", "filters.owner.value={me}", icon="user", color="primary")
    plugin.preset("tasks", "Hidden", "search=x", visible=lambda user: user.id == 99)
    panel = make_panel(tmp_path, plugin)
    client = client_for(panel)
    client.login()
    html = client.get("/admin/tasks?_f=1&filters.owner.value=1").text
    tag = chip(html, "My tasks")
    assert 'href="/admin/tasks?filters.owner.value=1&amp;_f=1' in tag and 'aria-current="page"' in tag
    assert rows(html) == {"Alpha open", "Gamma closed"}
    assert "A ready view from the app." in html and 'title="Hidden"' not in html
    # a preset can be the default too
    assert client.post("/admin/_views/default", {"resource": "tasks", "key": "preset:my-tasks"}).status_code == 303
    assert rows(client.get("/admin/tasks").text) == {"Alpha open", "Gamma closed"}
    ravi = client_for(panel)
    ravi.login("ravi@example.com")
    assert rows(ravi.get("/admin/tasks?_f=1&filters.owner.value=2").text) == {"Beta pending"}
    assert 'href="/admin/tasks?filters.owner.value=2' in chip(ravi.get("/admin/tasks").text, "My tasks")


def test_views_for_other_plugins(admin, panel):
    save(admin, name="Pending")
    seen = []
    plugin = panel.get_plugin("saved-views")
    plugin.on_view_saved("test", lambda view: seen.append(("saved", view.name)))
    plugin.on_view_deleted("test", lambda view: seen.append(("deleted", view.name)))
    plugin.on_view_saved("broken", lambda view: 1 / 0)  # a broken listener must not lose the view
    save(admin, name="Open", query="_f=1&filters.status.value=open")
    from tungsten.context import Context

    with panel.db() as db:
        class Req:
            session: dict = {}
            headers: dict = {}
            query_params: dict = {}
        ctx = Context(panel, Req(), db)
        from conftest import User

        ctx.user = db.get(User, 1)
        items = plugin.views_for(ctx, "tasks")
    assert [i.name for i in items] == ["Pending", "Open"]
    assert items[1].url.startswith("/admin/tasks?_f=1&filters.status.value=open")
    assert plugin.views_for(ctx, "nope") == []
    admin.post(f"/admin/_views/{items[0].id}/delete")
    assert seen == [("saved", "Open"), ("deleted", "Pending")]


def test_my_tickets_preset_when_tickets_is_installed(tmp_path):
    tickets = pytest.importorskip("tungsten_tickets")
    panel = make_panel(tmp_path, SavedViewsPlugin())
    panel.plugin(tickets.TicketsPlugin(portal=False))
    panel.create_tables(panel.db.kw["bind"])
    client = client_for(panel)
    client.login()
    html = client.get("/admin/tickets").text
    assert 'href="/admin/tickets?filters.assigned_to.value=1&amp;_f=1' in chip(html, "My tickets")


def test_no_presets_without_the_plugin(admin):
    assert "My tickets" not in admin.get("/admin/tasks").text


# ---------------------------------------------------------------------- the Saved views page
def test_manage_page(admin, panel):
    save(admin, name="Mine")
    ravi = client_for(panel)
    ravi.login("ravi@example.com")
    ravi.get("/admin/tasks")
    save(ravi, name="Ravi only", query="search=Beta")
    html = admin.get("/admin/saved-views").text
    assert "Mine" in html and "Ravi only" not in html
    assert "Saved views" in admin.get("/admin/tasks").text  # user menu link
    mine, ravis = views(panel)
    assert admin.get("/admin/saved-views/create").status_code in (403, 404)
    plugin = panel.get_plugin("saved-views")
    from tungsten_saved_views.resources import SavedViewPolicy

    class Ctx:
        user = None
        tenant = None
        panel = None

    ctx = Ctx()
    ctx.panel = panel
    with panel.db() as db:
        from conftest import User

        ctx.user = db.get(User, 1)
        ctx.can = lambda permission, record=None: True
        assert SavedViewPolicy.update(ctx, mine) and not SavedViewPolicy.update(ctx, ravis)
        assert not SavedViewPolicy.create(ctx)
    assert plugin.user_key(ctx) == "1"


def test_without_login(tmp_path):
    """A panel with no login still saves views (for everyone)."""
    from conftest import Base, PanelClient, TaskResource
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tungsten import Panel

    engine = create_engine(f"sqlite:///{tmp_path / 'open.db'}")
    Base.metadata.create_all(engine)
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="t")
    panel.resources([TaskResource])
    panel.plugin(SavedViewsPlugin())
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    assert client.get("/admin/tasks").status_code == 200
    r = client.post("/admin/_views/save", {"resource": "tasks", "query": "search=a", "name": "A"})
    assert r.status_code == 303
    assert 'title="A"' in client.get("/admin/tasks").text


def test_manage_page_edit_and_delete(admin, panel):
    save(admin, name="Mine", default="1")
    view = views(panel)[0]
    admin.get("/admin/saved-views")
    action = "/admin/_tw/action"
    r = admin.post(action, {"_tw_host": "resource:saved-views", "_tw_scope": "row", "_tw_name": "edit",
                            "_tw_record": str(view.id), "name": "Renamed", "color": "success", "sort": "3",
                            "icon": "star"}, headers={"HX-Request": "true"})
    assert r.status_code in (200, 204)
    view = views(panel)[0]
    assert (view.name, view.color, view.icon) == ("Renamed", "success", "star")
    r = admin.post(action, {"_tw_host": "resource:saved-views", "_tw_scope": "row", "_tw_name": "delete",
                            "_tw_record": str(view.id)}, headers={"HX-Request": "true"})
    assert r.status_code in (200, 204)
    assert views(panel) == []
    with panel.db() as db:
        assert db.scalars(select(SavedViewDefault)).all() == []


def test_icon_cannot_carry_html(admin, panel):
    save(admin, name="Sneaky", shared="1")
    with panel.db() as db:
        db.get(SavedView, views(panel)[0].id).icon = '<svg onload="alert(1)"></svg>'
        db.commit()
    html = admin.get("/admin/tasks").text
    assert "onload" not in html


def test_works_on_every_official_list(tmp_path):
    """Leads, Tickets, HR and Finance lists all get the bar, and a view saved on one of them opens."""
    plugins = []
    for module, cls, kw in [("tungsten_leads", "LeadsPlugin", {}), ("tungsten_tickets", "TicketsPlugin", {"portal": False}),
                            ("tungsten_hr", "HRPlugin", {}), ("tungsten_finance", "FinancePlugin", {"state": "27"})]:
        try:
            plugins.append(getattr(__import__(module), cls)(**kw))
        except ImportError:
            pass
    if not plugins:
        pytest.skip("no official plugins installed")
    panel = make_panel(tmp_path, SavedViewsPlugin())
    for p in plugins:
        panel.plugin(p)
    panel.create_tables(panel.db.kw["bind"])
    client = client_for(panel)
    client.login()
    slugs = [r.get_slug() for r in panel.get_resources() if r.has_page("index") and r.get_slug() != "saved-views"]
    assert len(slugs) > 5
    for slug in slugs:
        r = client.get(f"/admin/{slug}")
        assert r.status_code == 200, slug
        assert "data-tw-views" in r.text, slug
        r = client.post("/admin/_views/save", {"resource": slug, "query": "search=zz&sort=id", "name": "Mine"})
        assert r.status_code == 303, slug
        assert client.get(r.headers["location"]).status_code == 200, slug
    if "leads" in slugs:
        assert "My leads" in client.get("/admin/leads").text


def test_async_database(tmp_path):
    """Panels on an async engine save and open views the same way."""
    pytest.importorskip("aiosqlite")
    from conftest import Base, PanelClient, Task, TaskResource, User
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tungsten import Auth, Panel, hash_password

    path = tmp_path / "async.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    with sessionmaker(sync_engine)() as db:
        db.add(User(name="A", email="admin@example.com", password=hash_password("password")))
        db.add_all([Task(title="Alpha open", status="open"), Task(title="Beta pending", status="pending")])
        db.commit()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    panel = Panel(path="/admin", session_factory=async_sessionmaker(engine, expire_on_commit=False),
                  secret_key="t", auth=Auth(User))
    panel.resources([TaskResource])
    panel.plugin(SavedViewsPlugin())
    panel.create_tables(sync_engine)
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    client.login()
    client.get("/admin/tasks")
    r = client.post("/admin/_views/save", {"resource": "tasks", "query": "_f=1&filters.status.value=pending",
                                           "name": "Pending", "default": "1"})
    assert r.status_code == 303
    html = client.get("/admin/tasks").text
    assert "Beta pending" in html and "Alpha open" not in html
