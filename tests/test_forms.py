"""Form builder unit tests (no database needed)."""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

import pytest
from starlette.datastructures import FormData

from tungsten.forms import (
    Checkbox,
    CheckboxList,
    ColorPicker,
    DatePicker,
    DateTimePicker,
    Form,
    Grid,
    KeyValue,
    Placeholder,
    Radio,
    Repeater,
    RichEditor,
    Section,
    Select,
    Step,
    Tab,
    Tabs,
    TagsInput,
    Textarea,
    TextInput,
    Toggle,
    ValidationError,
    Wizard,
)


def make(schema, operation="create"):
    form = Form().schema(schema)
    form.bind(None, operation=operation, refresh_url="/refresh")
    form.fill()
    return form


def submit(form, pairs):
    form.load(FormData(pairs))
    return form.validate()


def errors_of(form, pairs):
    with pytest.raises(ValidationError) as exc:
        submit(form, pairs)
    return exc.value.errors


def test_required_and_text_rules():
    form = make([
        TextInput("name").required().max_length(5),
        TextInput("email").email(),
        TextInput("code").regex(r"^[A-Z]+$", "Capitals only."),
        Textarea("bio").min_length(3),
    ])
    errs = errors_of(form, [("name", ""), ("email", "nope"), ("code", "abc"), ("bio", "x")])
    assert errs["name"] == ["The name field is required."]
    assert "valid email" in errs["email"][0]
    assert errs["code"] == ["Capitals only."]
    assert "at least 3" in errs["bio"][0]
    data = submit(form, [("name", " Amit "), ("email", "a@b.co"), ("code", "ABC"), ("bio", "")])
    assert data == {"name": "Amit", "email": "a@b.co", "code": "ABC", "bio": None}


def test_numbers_are_cast_and_bounded():
    form = make([TextInput("qty").integer().min_value(1), TextInput("price").numeric().max_value(100)])
    errs = errors_of(form, [("qty", "0"), ("price", "abc")])
    assert "at least 1" in errs["qty"][0]
    assert "must be a number" in errs["price"][0]
    data = submit(form, [("qty", "3"), ("price", "9.50")])
    assert data == {"qty": 3, "price": Decimal("9.50")}


def test_password_dehydrated_only_when_filled():
    pw = TextInput("password").password().dehydrate_state_using(lambda state: "hashed:" + state) \
        .dehydrated(lambda state: bool(state))
    form = make([pw], operation="edit")
    assert submit(form, [("password", "")]) == {}
    assert submit(form, [("password", "secret")]) == {"password": "hashed:secret"}


def test_select_options_enum_and_validation():
    class Status(str, enum.Enum):
        DRAFT = "draft"
        LIVE = "live"

    form = make([Select("status").options(Status).required(), Select("size").options({1: "Small", 2: "Large"})])
    errs = errors_of(form, [("status", "gone"), ("size", "3")])
    assert "invalid" in errs["status"][0] and "invalid" in errs["size"][0]
    data = submit(form, [("status", "live"), ("size", "2")])
    assert data["status"] is Status.LIVE
    assert data["size"] == 2


def test_multiple_select_checkbox_list_radio_tags():
    form = make([
        Select("tags").options(["a", "b", "c"]).multiple(),
        CheckboxList("sizes").options(["S", "M", "L"]),
        Radio("ok").boolean(),
        TagsInput("keywords"),
        TagsInput("csv").separator(","),
    ])
    data = submit(form, [("tags", "a"), ("tags", "c"), ("sizes", "M"), ("ok", "1"),
                         ("keywords", "x"), ("keywords", "y"), ("keywords", "x"), ("csv", "p"), ("csv", "q")])
    assert data == {"tags": ["a", "c"], "sizes": ["M"], "ok": True, "keywords": ["x", "y"], "csv": "p,q"}


def test_booleans_dates_colors():
    form = make([
        Checkbox("terms").required(), Toggle("active"), DatePicker("born").max_date(dt.date(2020, 1, 1)),
        DateTimePicker("at"), ColorPicker("color"),
    ])
    errs = errors_of(form, [("born", "2021-05-01"), ("color", "red"), ("at", "bad")])
    assert errs["terms"] == ["The terms must be accepted."]
    assert "before or equal" in errs["born"][0]
    assert "hex color" in errs["color"][0]
    assert "not a valid date" in errs["at"][0]
    data = submit(form, [("terms", "1"), ("active", "on"), ("born", "2019-02-03"), ("at", "2024-01-02T10:30"),
                         ("color", "#ff8800")])
    assert data == {"terms": True, "active": True, "born": dt.date(2019, 2, 3),
                    "at": dt.datetime(2024, 1, 2, 10, 30), "color": "#ff8800"}


def test_rich_editor_is_sanitized():
    form = make([RichEditor("body")])
    data = submit(form, [("body", '<p onclick="x()">Hi <script>alert(1)</script><a href="javascript:x">l</a></p>')])
    assert data["body"] == "<p>Hi <a>l</a></p>"


def test_dependent_fields_visibility_and_options():
    cities = {"gj": ["Surat"], "mh": ["Pune"]}
    form = make([
        Select("state").options(list(cities)).live(),
        Select("city").options(lambda get: cities.get(get("state"), [])).visible(lambda get: bool(get("state")))
        .required(),
    ])
    assert 'name="city"' not in str(form.render())
    assert submit(form, [("state", "")]) == {"state": None}
    form.load(FormData([("state", "gj")]))
    html = str(form.render())
    assert "Surat" in html and "Pune" not in html
    assert 'hx-post="/refresh"' in html
    errs = errors_of(form, [("state", "gj"), ("city", "Pune")])
    assert "invalid" in errs["city"][0]


def test_after_state_updated_can_set_other_fields():
    form = make([
        TextInput("name").live().after_state_updated(lambda state, set: set("slug", (state or "").lower().replace(" ", "-"))),
        TextInput("slug"),
    ])
    form.load(FormData([("name", "Kids Wear"), ("slug", "")]))
    form.state_updated("name")
    assert form.get("slug") == "kids-wear"


def test_repeater_rows_validation_and_ui_actions():
    form = make([Repeater("items").schema([TextInput("sku").required(), TextInput("qty").integer()]).min_items(1)])
    assert form.get("items") == [{"sku": "", "qty": ""}]
    form.handle_ui_action("repeater.add:items")
    assert len(form.get("items")) == 2
    form.load(FormData([("items.0.__row", "1"), ("items.0.sku", "A"), ("items.0.qty", "2"),
                        ("items.3.__row", "1"), ("items.3.sku", ""), ("items.3.qty", "x")]))
    assert len(form.get("items")) == 2  # gaps are closed up
    with pytest.raises(ValidationError) as exc:
        form.validate()
    assert set(exc.value.errors) == {"items.1.sku", "items.1.qty"}
    form.handle_ui_action("repeater.remove:items:1")
    assert form.validate() == {"items": [{"sku": "A", "qty": 2}]}
    form.handle_ui_action("repeater.remove:items:0")
    assert "at least 1" in errors_of(form, [])["items"][0]


def test_repeater_relative_get():
    form = make([
        TextInput("currency").default("INR"),
        Repeater("lines").schema([
            TextInput("price"),
            Placeholder("label").content(lambda get: f"{get('price')} {get('../currency')}"),
        ]),
    ])
    form.load(FormData([("currency", "USD"), ("lines.0.__row", "1"), ("lines.0.price", "5")]))
    assert "5 USD" in str(form.render())


def test_repeater_rule_checks_all_rows():
    def balanced(value):
        return True if sum(int(r["qty"] or 0) for r in value) == 10 else "Rows must add up to 10."

    form = make([Repeater("items").schema([TextInput("qty").integer()]).rule(balanced)])
    rows = [("items.0.__row", "1"), ("items.0.qty", "4"), ("items.1.__row", "1"), ("items.1.qty", "5")]
    assert errors_of(form, rows)["items"] == ["Rows must add up to 10."]
    assert submit(form, [*rows[:3], ("items.1.qty", "6")]) == {"items": [{"qty": 4}, {"qty": 6}]}


def test_key_value_field():
    form = make([KeyValue("meta")])
    form.handle_ui_action("keyvalue.add:meta")
    assert form.get("meta") == [{"key": "", "value": ""}]
    data = submit(form, [("meta.0.key", "color"), ("meta.0.value", "red"), ("meta.1.key", ""), ("meta.1.value", "x")])
    assert data == {"meta": {"color": "red"}}


def test_wizard_validates_each_step_and_tabs_jump_to_errors():
    wizard = Wizard([
        Step("One").schema([TextInput("a").required()]),
        Step("Two").schema([TextInput("b").required()]),
    ])
    form = make([wizard])
    key = wizard._ui_key
    form.load(FormData([("a", "")]))
    form.handle_ui_action(f"wizard.next:{key}")
    assert form.ui[key] == "0" and "a" in form.errors
    form.load(FormData([("a", "x"), (f"_tw_ui.{key}", "0")]))
    form.errors = {}
    form.handle_ui_action(f"wizard.next:{key}")
    assert form.ui[key] == "1"

    tabs = Tabs().tabs([Tab("A").schema([TextInput("x")]), Tab("B").schema([TextInput("y").required()])])
    form = make([tabs])
    errors_of(form, [("x", "1")])
    assert form.ui[tabs._ui_key] == "1"


def test_layouts_render_and_hidden_sections_skip_validation():
    form = make([
        Section("Main").description("desc").schema([Grid(3).schema([TextInput("a"), TextInput("b"), TextInput("c")])]),
        Section("Secret").schema([TextInput("hidden_req").required()]).visible(lambda get: get("a") == "show"),
    ])
    html = str(form.render())
    assert "Main" in html and "desc" in html and "md:grid-cols-3" in html
    assert submit(form, [("a", "x")]) == {"a": "x", "b": None, "c": None}
    assert "hidden_req" in errors_of(form, [("a", "show")])


def test_disabled_fields_are_not_saved_but_kept_on_refresh():
    form = make([TextInput("code").disabled().default("ABC"), TextInput("name")])
    html = str(form.render())
    assert 'type="hidden" name="code" value="ABC"' in html
    assert submit(form, [("code", "HACK"), ("name", "n")]) == {"name": "n"}
