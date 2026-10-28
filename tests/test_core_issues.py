"""Core gaps from GitHub issues #88-#93, #98, #100, #110 (one small app, one test per ask)."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from tungsten import Auth, LocalStorage, Notification, Page, Panel, RelationManager, Resource, hash_password
from tungsten.actions import Action, BulkAction, DownloadAction, Halt
from tungsten.actions import download
from tungsten.forms import FileUpload, Section, Step, TextInput, UploadedFile, ValidationError, Wizard
from tungsten.forms.form import Form
from tungsten.i18n import Translator
from tungsten.tables import Filter, Group, Table, TextColumn

from .conftest import PanelClient

ACTION = "/admin/_tw/action"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="staff")


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    items: Mapped[list["Item"]] = relationship(back_populates="shop")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(20), default="")
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    shop: Mapped[Shop | None] = relationship(back_populates="items")


seen: list = []


class ItemsManager(RelationManager):
    relationship = "items"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").default(lambda owner_record: f"{owner_record.name} item")])

    @classmethod
    def table(cls, table):
        return (table.columns([TextColumn("name")])
                .filters([Filter("mine").default(lambda owner_record: owner_record.name == "Main")
                          .query(lambda query: query)]))


class ShopResource(Resource):
    model = Shop
    relations = [ItemsManager]

    @classmethod
    def get_navigation_label(cls, ctx=None):
        return "Stores" if ctx is not None and ctx.user is not None and ctx.user.role == "admin" else "Shops"

    @classmethod
    def get_navigation_group(cls, ctx=None):
        return "Admin" if ctx is not None and ctx.user is not None and ctx.user.role == "admin" else "Work"

    @classmethod
    def page_title(cls, ctx, page, record=None):
        return "All the shops" if page == "list" else None

    @classmethod
    def navigation_badge(cls, ctx):
        return 2

    @classmethod
    def navigation_badge_tooltip(cls, ctx):
        return "Two shops"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required(),
            TextInput("meta.title"),
            Section("More").collapsible().collapsed(lambda record: record is None).schema([TextInput("code_hint")]),
        ])

    @classmethod
    def before_save(cls, record, data):
        if data.get("name") == "refuse":
            raise ValidationError({"name": ["The bank said no."]})
        if data.get("name") == "halt":
            raise Halt()

    @classmethod
    def table(cls, table):
        return (table.columns([TextColumn("name").cell_attributes(lambda record: {"class": "keep", "data-id": record.id}),
                               TextColumn("name_html").label("Html").state(lambda record: f'<span class="text-danger-600">{record.name}</span>')
                               .html(keep_classes=True)])
                .header_actions([Action("ask").form([TextInput("q")]).action(lambda: None)])
                .actions([Action("peek").form([TextInput("note")]).action(lambda: None)])
                .bulk_actions([BulkAction("touch").action(lambda records: seen.append(len(records)))])
                .max_selectable_records(2)
                .record_action("peek"))


class GenerateItems(Page):
    title = "Generate items"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("count").required()])

    @classmethod
    def save(cls, data):
        if data["count"] == "0":
            raise ValidationError({"count": "Pick at least one."})
        seen.append(("generated", data["count"]))


class ItemResource(Resource):
    model = Item
    custom_pages = {"generate": GenerateItems}

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("code").read_only()])

    @classmethod
    def table(cls, table):
        return (table.columns([TextColumn("name"), TextColumn("code")])
                .groups([Group("code").order("desc")]).default_group("code").hide_group_picker())


class Report(Page):
    """A page with its own table and the widgets under it."""

    table_model = Item
    widgets_position = "below"

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")])


class Logs(Resource):
    model = User
    slug = "logs"
    pages = ("index",)

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")])

    @classmethod
    def query(cls, ctx):
        return select(User).where(User.id < 0)


@pytest.fixture()
def env(tmp_path):
    seen.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        db.add_all([User(name="Ann", email="ann@x.com", password=hash_password("password"), role="admin"),
                    User(name="Bob", email="bob@x.com", password=hash_password("password"), role="staff")])
        main = Shop(name="Main", meta={"title": "Old", "keep": 1})
        db.add_all([main, Shop(name="Side")])
        db.flush()
        db.add_all([Item(name="Pen", code="a", shop_id=main.id), Item(name="Ink", code="b", shop_id=main.id),
                    Item(name="Cap", code="c")])
        db.commit()
    panel = Panel(session_factory=Session, secret_key="s", storage=LocalStorage(tmp_path / "storage"),
                  auth=Auth(User, email_placeholder="name@shop.in", password_placeholder=None))
    panel.resources([ShopResource, ItemResource, Logs]).pages([Report])
    panel.user_menu_item("Billing", lambda user: f"/billing/{user.id}", visible=lambda user: user.role == "admin",
                         new_tab=True)
    panel.user_role_label(lambda user: f"Team {user.role}")
    panel.render_hook("page.header-actions.before", lambda: '<span id="hooked">hi</span>')
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    return app, Session, panel


def client(app, email="ann@x.com"):
    c = PanelClient(TestClient(app))
    assert c.login(email).status_code == 303
    c.get("/admin/shops")
    return c


# ---------------------------------------------------------------------- #88 labels per user, #92 badge tooltip
def test_navigation_label_and_group_follow_the_user(env):
    app, _, _ = env
    html = client(app).get("/admin/shops").text
    assert ">Stores<" in html and "Admin" in html and 'title="Two shops"' in html
    assert "All the shops" in html  # #91 page title
    html = client(app, "bob@x.com").get("/admin/shops").text
    assert ">Shops<" in html and "Work" in html


# ---------------------------------------------------------------------- #89 a custom page under a resource
def test_custom_page_under_resource(env):
    app, _, _ = env
    c = client(app)
    r = c.get("/admin/items/generate")
    assert r.status_code == 200 and "Generate items" in r.text
    r = c.post("/admin/items/generate", {"count": "0"})
    assert "Pick at least one." in r.text and seen == []  # #91: save() refuses and keeps the form
    c.post("/admin/items/generate", {"count": "3"})
    assert seen == [("generated", "3")]
    assert c.get("/admin/items/1").status_code in (200, 303, 307)  # records still open


# ---------------------------------------------------------------------- #90 tables, pages
def test_max_selectable_records(env):
    app, _, _ = env
    c = client(app)
    html = c.get("/admin/shops").text
    assert "max: 2" in html and "full('1')" in html
    r = c.post(ACTION, {"_tw_host": "resource:shops", "_tw_scope": "bulk", "_tw_name": "touch",
                        "records": ["1", "2", "3"]})
    assert r.status_code != 200 or "Forbidden" in r.text or seen == []
    assert seen == []
    c.post(ACTION, {"_tw_host": "resource:shops", "_tw_scope": "bulk", "_tw_name": "touch", "records": ["1", "2"]})
    assert seen == [2]


def test_group_order_and_hidden_picker(env):
    app, _, _ = env
    html = client(app).get("/admin/items").text
    assert 'name="group"' not in html
    assert html.index("Cap</span>") < html.index("Ink</span>") < html.index("Pen</span>")  # groups c, b, a


def test_filter_default_gets_owner_record(env):
    app, Session, panel = env
    from starlette.requests import Request

    from tungsten.context import Context
    from tungsten.hosts import RelationHost

    with Session() as db:
        main = db.get(Shop, 1)
        ctx = Context(panel, Request({"type": "http", "query_string": b"", "headers": [], "method": "GET",
                                      "path": "/", "session": {}}), db)
        host = RelationHost(ShopResource, main, ItemsManager)
        table = host.get_table(ctx).bind(ctx, host)
        assert table.filter_data["mine"] == {"isActive": True}
        form = host.form(ctx, "create")
        form.bind(ctx, operation="create")
        form.fill()
        assert form.get("name") == "Main item"  # #93: owner record in relation manager form closures


def test_page_table_and_widgets_below(env):
    app, _, _ = env
    html = client(app).get("/admin/report").text
    assert "Pen</span>" in html and "data-tw-table" in html


# ---------------------------------------------------------------------- #91 edit page refusals, header id
def test_edit_page_refusal_redraws_form(env):
    app, Session, _ = env
    c = client(app)
    r = c.post("/admin/shops/1/edit", {"name": "refuse"})
    assert r.status_code == 200 and "The bank said no." in r.text
    r = c.post("/admin/shops/1/edit", {"name": "halt"})
    assert r.status_code == 200
    with Session() as db:
        assert db.get(Shop, 1).name == "Main"
    html = c.get("/admin/shops/1/edit").text
    assert 'id="tw-page-header"' in html and 'id="tw-page-header-actions"' in html


# ---------------------------------------------------------------------- #92 user menu, ?action=, new tabs, downloads
def test_user_menu_visibility_and_role_label(env):
    app, _, _ = env
    html = client(app).get("/admin/shops").text
    assert 'href="/billing/1" target="_blank"' in html and "Team admin" in html
    assert "/billing/" not in client(app, "bob@x.com").get("/admin/shops").text


def test_action_from_url(env):
    app, _, _ = env
    html = client(app).get("/admin/shops?action=ask").text
    assert 'hx-trigger="load"' in html and "&#34;_tw_name&#34;: &#34;ask&#34;" in html
    assert 'hx-trigger="load"' not in client(app).get("/admin/shops?action=nope").text


def test_record_action_and_new_tab(env):
    app, _, _ = env
    html = client(app).get("/admin/shops").text
    assert '"_tw_name": "peek"' in html.replace("&#34;", '"') and "text-start" in html
    table = Table().record_url(lambda record: "/x", new_tab=True)
    assert table._record_url_new_tab
    note = Notification("Done").action("Open", "/x", new_tab=True).to_dict()
    assert note["actions"][0]["new_tab"] is True


def test_download_link_lifetime(monkeypatch):
    class P:
        secret_key = "k"

    token = download.make_token(P, {"a": 1, "ttl": 60})
    assert download.read_token(P, token) == {"a": 1, "ttl": 60}
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(download.dt, "datetime", Clock)
    assert download.read_token(P, token) is None
    assert DownloadAction("x").link_lifetime(900)._link_lifetime == 900


# ---------------------------------------------------------------------- #93 forms and columns
def test_dotted_field_saves_into_json_column(env):
    app, Session, _ = env
    c = client(app)
    c.post("/admin/shops/1/edit", {"name": "Main", "meta.title": "New"})
    with Session() as db:
        assert db.get(Shop, 1).meta == {"title": "New", "keep": 1}
    form = Form([TextInput("a.b")])
    form.fill_from({"a": {"b": "x"}})
    assert form.validate() == {"a": {"b": "x"}}


def test_section_collapsed_closure_and_html_classes(env):
    app, _, _ = env
    c = client(app)
    edit = c.get("/admin/shops/1/edit").text
    create = c.get("/admin/shops/create").text
    assert "{ open: true }" in edit and "{ open: false }" in create  # collapsed(lambda record: record is None)
    html = c.get("/admin/shops").text
    assert '<span class="text-danger-600">Main</span>' in html
    assert 'class="keep' not in html.split("<td", 1)[0]
    assert re.search(r'<td class="[^"]*keep[^"]*"[^>]*data-id="1"', html)


def test_read_only_keeps_the_saved_value(env):
    app, Session, _ = env
    c = client(app)
    assert "readonly" in c.get("/admin/items/1/edit").text
    c.post("/admin/items/1/edit", {"name": "Pen 2", "code": "hacked"})
    with Session() as db:
        item = db.get(Item, 1)
        assert item.name == "Pen 2" and item.code == "a"


def test_store_files_false_gives_uploaded_file():
    field = FileUpload("sheet").store_files(False)
    value = field.cast("tmp-uploads/abc/list.xlsx")
    assert isinstance(value, UploadedFile) and value.name == "list.xlsx"
    record = type("R", (), {"sheet": "kept"})()
    field.fill_record(Form([field]), record, {"sheet": value})
    assert record.sheet == "kept"


# ---------------------------------------------------------------------- #98 table defaults, hook, login placeholders
def test_table_defaults_and_header_hook(env):
    app, _, _ = env
    configure = Table.configure_using(lambda table: table.striped())
    try:
        assert Table()._striped is True
    finally:
        Table._configurators.remove(configure)
    assert Table()._striped is False
    assert 'id="hooked"' in client(app).get("/admin/shops").text


def test_login_placeholders(env):
    app, _, _ = env
    html = TestClient(app).get("/admin/login").text
    assert 'placeholder="name@shop.in"' in html and "Enter your password" not in html


# ---------------------------------------------------------------------- #100 uploads, English overrides
def test_upload_hint_and_messages():
    field = FileUpload("sheet").accepted_file_types(
        ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".csv"]).max_size(20 * 1024)
    assert field.accepted_labels() == ["XLSX", "CSV"] and field.size_label() == "20 MB"
    assert field.check_upload("a.pdf", "application/pdf", 10) == "The Sheet field must be a file of type: xlsx, csv."
    assert field.check_upload("a.csv", "text/csv", 30 * 1024 * 1024) == \
        "The Sheet field must not be greater than 20480 kilobytes."
    field.validation_messages({"max": "Too big (max :max KB)."})
    assert field.check_upload("a.csv", "text/csv", 30 * 1024 * 1024) == "Too big (max 20480 KB)."


def test_english_overrides_are_used(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"Create one to get started.": "Nothing here yet."}))
    tr = Translator(dirs=[tmp_path])
    assert tr.translate("Create one to get started.", "en") == "Nothing here yet."


# ---------------------------------------------------------------------- #110 no "Create one" without a create button
def test_empty_table_without_create(env):
    app, _, _ = env
    html = client(app).get("/admin/logs").text
    assert "No " in html and "Create one to get started." not in html


def test_wizard_step_after_validation_and_schema_closure():
    def check(data):
        if data.get("vat") == "bad":
            raise ValidationError({"vat": ["The tax office does not know this number."]})

    wizard = Wizard([
        Step("Company", [TextInput("vat").required()]).after_validation(check),
        Step("Details", lambda get: [TextInput("gst_state").required()] if get("vat") == "IN1" else
             [TextInput("country")]),
    ]).key("w")
    form = Form([wizard])
    form.fill_from({"vat": "bad"})
    wizard.handle_ui_action(form, "next", "")
    assert form.ui["w"] == "0" and form.errors["vat"] == ["The tax office does not know this number."]
    form = Form([wizard])
    form.fill_from({"vat": "IN1"})
    wizard.handle_ui_action(form, "next", "")
    assert form.ui["w"] == "1"
    form.load({"vat": "IN1", "gst_state": "MH"} | {})
    assert [f.name for f, _, _ in form.walk_fields()] == ["vat", "gst_state"]


def test_filter_after_state_updated_resets_dependent(env):
    app, Session, panel = env
    from starlette.datastructures import QueryParams
    from starlette.requests import Request

    from tungsten.context import Context
    from tungsten.forms import Select

    table = Table().columns([TextColumn("name")]).filters([
        Filter("place").form([
            Select("state").options({"mh": "MH", "ka": "KA"}).after_state_updated(lambda set: set("city", None)),
            Select("city").options({"pune": "Pune", "blr": "Bengaluru"}),
        ]).query(lambda query: query),
    ])
    with Session() as db:
        request = Request({"type": "http", "query_string": b"", "method": "GET", "path": "/", "session": {},
                           "headers": [(b"hx-trigger-name", b"filters.place.state")]})
        ctx = Context(panel, request, db)
        host = ItemResource.host()
        table.bind(ctx, host, params=QueryParams("_f=1&filters.place.state=ka&filters.place.city=pune"))
        assert table.filter_data["place"].get("city") in (None, "")
