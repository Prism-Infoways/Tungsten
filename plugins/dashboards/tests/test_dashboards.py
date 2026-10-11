from __future__ import annotations

from sqlalchemy import select
from tungsten_dashboards import CustomDashboard, DashboardHome, DashboardItem
from tungsten_dashboards.service import humanize


def session(panel):
    db = panel.db()
    db.info["tungsten_panel"] = panel
    return db


def new_dashboard(client, name="Sales", **data):
    client.get("/admin/dashboards")
    return client.post("/admin/_tw/action", {"_tw_host": "page:dashboards", "_tw_scope": "page",
                                             "_tw_name": "new_dashboard", "name": name, **data})


def make(panel, name="Mine", owner="1", shared=False, widgets=(), home_for_all=False):
    with session(panel) as db:
        d = CustomDashboard(name=name, owner_id=owner, shared=shared, home_for_all=home_for_all)
        for i, key in enumerate(widgets):
            d.items.append(DashboardItem(widget=key, span=2, position=i))
        db.add(d)
        db.commit()
        return d.id


def items(panel, dashboard_id):
    with session(panel) as db:
        return [(i.widget, i.span, i.position) for i in db.scalars(
            select(DashboardItem).where(DashboardItem.dashboard_id == dashboard_id)
            .order_by(DashboardItem.position)).all()]


def toast(response) -> str:
    return response.headers.get("HX-Trigger", "")


# ---------------------------------------------------------------------- pages
def test_empty_page_and_normal_home(admin):
    r = admin.get("/admin/dashboards")
    assert r.status_code == 200, r.text[:500]
    assert "No dashboards yet" in r.text and "New dashboard" in r.text
    assert admin.get("/admin/").status_code == 200


def test_create_from_template_skips_unknown_widgets(admin, panel):
    r = new_dashboard(admin, "Sales board", start="template:Sales")
    assert r.status_code == 204 and "HX-Redirect" in r.headers, r.text
    with session(panel) as db:
        d = db.scalars(select(CustomDashboard)).one()
        assert d.name == "Sales board" and d.owner_id == "1" and not d.shared
    assert [w for w, _, _ in items(panel, d.id)] == ["sales-stats", "orders-chart"]
    assert items(panel, d.id)[0][1] == 4  # stats are full width by default
    page = admin.get(f"/admin/dashboards?d={d.id}").text
    assert "Sales board" in page and "Sales today" in page
    assert "/admin/dashboards/_w/" in page  # the chart loads in its own request


def test_create_from_plugin_group_and_home(admin, panel):
    assert new_dashboard(admin, "All", start="group:App").status_code == 204
    assert new_dashboard(admin, "Like home", start="home").status_code == 204
    with session(panel) as db:
        all_, home = db.scalars(select(CustomDashboard).order_by(CustomDashboard.id)).all()
    keys = [w for w, _, _ in items(panel, all_.id)]
    assert "sales-stats" in keys and "secret-stats" in keys and "only-on-dashboards" in keys
    assert [w for w, _, _ in items(panel, home.id)] == ["sales-stats", "orders-chart", "secret-stats", "broken-widget"]


def test_name_is_required_and_escaped(admin, panel):
    r = new_dashboard(admin, "   ")
    assert "HX-Redirect" not in r.headers
    new_dashboard(admin, "<script>alert(1)</script>")
    with session(panel) as db:
        d = db.scalars(select(CustomDashboard)).one()
    page = admin.get(f"/admin/dashboards?d={d.id}").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


# ---------------------------------------------------------------------- editing
def test_add_move_resize_and_remove(admin, panel):
    d = make(panel)
    page = admin.get(f"/admin/dashboards?d={d}&edit=1").text
    assert "Add widgets" in page and "Extra numbers" in page and "Orders per day" in page
    assert admin.post(f"/admin/dashboards/{d}/add", {"widget": "sales-stats", "span": "4"}).headers.get("HX-Refresh")
    assert admin.post(f"/admin/dashboards/{d}/add", {"widget": "orders-chart"}).headers.get("HX-Refresh")
    again = admin.post(f"/admin/dashboards/{d}/add", {"widget": "orders-chart"})
    assert "already on the dashboard" in toast(again)
    unknown = admin.post(f"/admin/dashboards/{d}/add", {"widget": "nope"})
    assert "isn't available" in toast(unknown)
    assert [w for w, _, _ in items(panel, d)] == ["sales-stats", "orders-chart"]
    assert items(panel, d)[1][1] == 2  # the chart's own width

    with session(panel) as db:
        stats_id, chart_id = [i.id for i in db.scalars(select(DashboardItem).order_by(DashboardItem.position))]
    order = admin.post(f"/admin/dashboards/{d}/order", {"keys": [str(chart_id), str(stats_id), "999"]})
    assert order.status_code == 204
    assert [w for w, _, _ in items(panel, d)] == ["orders-chart", "sales-stats"]
    assert admin.post(f"/admin/dashboards/{d}/items/{chart_id}", {"span": "3"}).status_code == 204
    assert admin.post(f"/admin/dashboards/{d}/items/{chart_id}", {"span": "9"}).status_code == 204  # ignored
    assert items(panel, d)[0][1] == 3
    r = admin.post(f"/admin/dashboards/{d}/items/{chart_id}/remove")
    assert r.status_code == 200 and r.headers.get("X-Dash-Removed") == "1"
    assert [w for w, _, _ in items(panel, d)] == ["sales-stats"]
    # removing it twice is a quiet 404, not a crash
    assert "X-Dash-Removed" not in admin.post(f"/admin/dashboards/{d}/items/{chart_id}/remove").headers


def test_lazy_widget_and_broken_widget(admin, panel):
    d = make(panel, widgets=["orders-chart", "broken-widget"])
    with session(panel) as db:
        chart, broken = db.scalars(select(DashboardItem).order_by(DashboardItem.position)).all()
    r = admin.get(f"/admin/dashboards/_w/{chart.id}")
    assert r.status_code == 200 and "Orders per day" in r.text
    r = admin.get(f"/admin/dashboards/_w/{broken.id}")
    assert r.status_code == 200 and "could not load" in r.text
    assert "no longer available" in admin.get("/admin/dashboards/_w/9999").text
    assert "no longer available" in admin.get("/admin/dashboards/_w/abc").text
    assert admin.get(f"/admin/dashboards?d={d}").status_code == 200


def test_widget_whose_plugin_was_removed(admin, panel):
    d = make(panel, widgets=["sales-stats", "gone-widget"])
    view = admin.get(f"/admin/dashboards?d={d}").text
    assert "Sales today" in view and "no longer available" not in view  # hidden for viewers
    edit = admin.get(f"/admin/dashboards?d={d}&edit=1").text
    assert "no longer available" in edit and "gone-widget" in edit  # the owner can remove it


def test_builtin_widgets(admin, panel):
    d = make(panel)
    admin.get(f"/admin/dashboards?d={d}&edit=1")
    bad = admin.post(f"/admin/dashboards/{d}/add", {"widget": "dashboards.note", "text": "  "})
    assert "Write something" in toast(bad)
    admin.post(f"/admin/dashboards/{d}/add", {"widget": "dashboards.note", "title": "To do",
                                              "text": "Call Ravi\n<b>bold</b>"})
    none = admin.post(f"/admin/dashboards/{d}/add", {"widget": "dashboards.counts", "resources": ["nope"]})
    assert "at least one list" in toast(none)
    admin.post(f"/admin/dashboards/{d}/add", {"widget": "dashboards.counts", "resources": ["users", "nope"]})
    admin.post(f"/admin/dashboards/{d}/add", {"widget": "dashboards.links", "links": ["resource:users"]})
    assert [w for w, _, _ in items(panel, d)] == ["dashboards.note", "dashboards.counts", "dashboards.links"]
    page = admin.get(f"/admin/dashboards?d={d}").text
    assert "To do" in page and "Call Ravi" in page and "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "Users" in page and ">2<" in page.replace(" ", "")  # two users counted
    assert 'href="/admin/users"' in page
    with session(panel) as db:
        note = db.scalars(select(DashboardItem).where(DashboardItem.widget == "dashboards.note")).one()
    r = admin.post(f"/admin/dashboards/{d}/items/{note.id}", {"_reload": "1", "title": "", "text": "New text"})
    assert r.headers.get("HX-Refresh")
    with session(panel) as db:
        note = db.get(DashboardItem, note.id)
        assert note.settings == {"text": "New text"} and note.title is None


def test_settings_rename_share_and_delete(admin, panel):
    d = make(panel)
    admin.get(f"/admin/dashboards?d={d}&edit=1")
    r = admin.post(f"/admin/dashboards/{d}/settings", {"name": "Team", "description": "For all", "shared": "1",
                                                       "home_for_all": "1", "_my_home_shown": "1"})
    assert r.headers.get("HX-Refresh")
    with session(panel) as db:
        dash = db.get(CustomDashboard, d)
        assert (dash.name, dash.description, dash.shared, dash.home_for_all) == ("Team", "For all", True, True)
    assert "Your dashboard" not in admin.get("/admin/").text
    assert "Team" in admin.get("/admin/").text  # home page for everyone
    r = admin.post(f"/admin/dashboards/{d}/delete")
    assert r.headers.get("HX-Redirect") == "/admin/dashboards"
    with session(panel) as db:
        assert db.get(CustomDashboard, d) is None
        assert db.scalars(select(DashboardItem)).all() == []
    assert admin.get("/admin/").status_code == 200


def test_my_home_page(admin, panel):
    d = make(panel, name="Morning", widgets=["sales-stats"])
    assert "Morning" not in admin.get("/admin/").text
    admin.get(f"/admin/dashboards?d={d}")
    assert admin.post(f"/admin/dashboards/{d}/home", {"on": "1"}).headers.get("HX-Refresh")
    home = admin.get("/admin/").text
    assert "Morning" in home and "Sales today" in home and "All dashboards" in home
    admin.post(f"/admin/dashboards/{d}/home", {"on": "0"})
    assert "Morning" not in admin.get("/admin/").text
    admin.post(f"/admin/dashboards/{d}/home", {"on": "1"})
    admin.post(f"/admin/dashboards/{d}/delete")
    with session(panel) as db:
        assert db.scalars(select(DashboardHome)).all() == []
    assert admin.get("/admin/").status_code == 200


def test_copy(admin, panel):
    d = make(panel, name="Team", owner="1", shared=True, widgets=["sales-stats", "orders-chart"])
    admin.get(f"/admin/dashboards?d={d}")
    r = admin.post(f"/admin/dashboards/{d}/copy")
    assert "HX-Redirect" in r.headers
    with session(panel) as db:
        copy = db.scalars(select(CustomDashboard).where(CustomDashboard.id != d)).one()
        assert copy.name == "Team (copy)" and not copy.shared
    assert [w for w, _, _ in items(panel, copy.id)] == ["sales-stats", "orders-chart"]


# ---------------------------------------------------------------------- who sees what
def test_private_dashboards_stay_private(ravi, panel):
    d = make(panel, name="Asha only", owner="1", widgets=["sales-stats"])
    page = ravi.get(f"/admin/dashboards?d={d}").text
    assert "Asha only" not in page and "gone or not shared" in page
    assert ravi.get("/admin/dashboards?d=abc").status_code == 200
    with session(panel) as db:
        item = db.scalars(select(DashboardItem)).one()
    assert "no longer available" in ravi.get(f"/admin/dashboards/_w/{item.id}").text
    for url in (f"/admin/dashboards/{d}/add", f"/admin/dashboards/{d}/settings", f"/admin/dashboards/{d}/delete",
                f"/admin/dashboards/{d}/order", f"/admin/dashboards/{d}/copy",
                f"/admin/dashboards/{d}/items/{item.id}/remove"):
        r = ravi.post(url, {"widget": "orders-chart", "name": "Hacked", "keys": [str(item.id)]})
        assert "X-Dash-Removed" not in r.headers and "HX-Redirect" not in r.headers, url
    assert items(panel, d) == [("sales-stats", 2, 0)]
    with session(panel) as db:
        assert db.get(CustomDashboard, d).name == "Asha only"


def test_shared_dashboards_are_read_only_for_others(ravi, panel):
    d = make(panel, name="Company", owner="1", shared=True, widgets=["sales-stats", "secret-stats"])
    page = ravi.get(f"/admin/dashboards?d={d}").text
    assert "Company" in page and "Sales today" in page
    assert "Profit" not in page  # a widget Ravi may not see is left out
    assert "Edit dashboard" not in page and "Make my own copy" in page
    assert "Add widgets" not in ravi.get(f"/admin/dashboards?d={d}&edit=1").text
    ravi.post(f"/admin/dashboards/{d}/add", {"widget": "orders-chart"})
    assert len(items(panel, d)) == 2
    # Ravi can still make it his own home page
    assert ravi.post(f"/admin/dashboards/{d}/home", {"on": "1"}).headers.get("HX-Refresh")
    assert "Company" in ravi.get("/admin/").text


def test_staff_cannot_share_or_pick_secret_widgets(ravi, panel):
    assert "HX-Redirect" in new_dashboard(ravi, "Ravi board", shared="1").headers  # the hidden switch is ignored
    with session(panel) as db:
        d = db.scalars(select(CustomDashboard)).one()
        assert d.owner_id == "2" and not d.shared
    edit = ravi.get(f"/admin/dashboards?d={d.id}&edit=1").text
    assert "Share with everyone" not in edit and "Secret stats" not in edit
    assert "isn't available" in toast(ravi.post(f"/admin/dashboards/{d.id}/add", {"widget": "secret-stats"}))
    r = ravi.post(f"/admin/dashboards/{d.id}/settings", {"name": "Ravi board", "shared": "1"})
    assert "can't share" in toast(r)
    with session(panel) as db:
        assert not db.get(CustomDashboard, d.id).shared


def test_new_dashboard_starts_skip_widgets_the_person_cannot_see(ravi, panel):
    new_dashboard(ravi, "Like home", start="home")
    with session(panel) as db:
        d = db.scalars(select(CustomDashboard)).one()
    assert "secret-stats" not in [w for w, _, _ in items(panel, d.id)]


def test_humanize():
    assert humanize("HRStats") == "HR stats"
    assert humanize("LatestOrdersWidget") == "Latest orders"
    assert humanize("CashFlowChart") == "Cash flow chart"


def test_quick_create_gets_a_dashboard_entry(tmp_path):
    import pytest

    quick_create = pytest.importorskip("tungsten_quick_create")
    from conftest import Base, PanelClient, User, UserResource, gate
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from tungsten_dashboards import DashboardsPlugin

    from tungsten import Auth, Panel, hash_password

    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(User(name="A", email="admin@example.com", password=hash_password("password"), is_admin=True))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="t", auth=Auth(User, gate=gate))
    panel.resources([UserResource])
    panel.plugin(DashboardsPlugin())
    panel.plugin(quick_create.QuickCreatePlugin())
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    client.login()
    assert "/admin/dashboards?new=1" in client.get("/admin/").text
    page = client.get("/admin/dashboards?new=1").text
    assert 'hx-trigger="load"' in page and "new_dashboard" in page
