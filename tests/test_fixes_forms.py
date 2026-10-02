"""Fixes in form fields and infolist entries (no database needed)."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from starlette.datastructures import FormData

from tungsten.forms import (
    Checkbox,
    CheckboxList,
    DatePicker,
    DateTimePicker,
    Form,
    RichEditor,
    Select,
    TagsInput,
    Textarea,
    TextInput,
    Toggle,
    ValidationError,
)
from tungsten.forms.fields import DataRecord
from tungsten.infolists import Infolist, TextEntry


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


def trigger_of(field):
    html = str(make([field]).render())
    return re.search(r'hx-trigger="([^"]*)"', html).group(1)


# ---------------------------------------------------------------------- rich editor


def test_rich_editor_max_length_counts_text_only():
    form = make([RichEditor("body").max_length(5)])
    # 5 letters of text inside a lot of HTML is fine
    assert submit(form, [("body", "<div><strong>Hello</strong></div>")]) == {"body": "<div><strong>Hello</strong></div>"}
    assert submit(form, [("body", "<p>a&amp;b</p>")])["body"] == "<p>a&amp;b</p>"  # "a&b" is 3 characters
    errs = errors_of(form, [("body", "<div>Hello world</div>")])
    assert errs["body"] == ["The body may not be greater than 5 characters."]


def test_rich_editor_shows_the_limit():
    form = make([RichEditor("body").max_length(500)])
    form.state["body"] = "<div>Hi <em>there</em></div>"
    html = str(form.render())
    assert "data-tw-length" in html and "/ 500" in html and '<span x-text="length">8</span>' in html
    assert "data-tw-length" not in str(make([RichEditor("body")]).render())


def test_rich_editor_live_puts_htmx_on_the_hidden_input():
    html = str(make([RichEditor("body").live(on_blur=True)]).render())
    assert re.search(r'<input type="hidden" id="[^"]*" name="body" value="" [^>]*hx-trigger="change"', html)
    assert "data-tw-live-blur" in html
    html = str(make([RichEditor("body").live(debounce=900)]).render())
    assert 'data-tw-live-delay="900"' in html and "data-tw-live-blur" not in html


# ---------------------------------------------------------------------- toggle


def test_toggle_off_color_and_icons_render():
    html = str(make([Toggle("active").on_color("success").off_color("danger").on_icon("check").off_icon("x")]).render())
    assert "on ? 'bg-success-600' : 'bg-danger-600'" in html
    assert 'x-show="!on"' in html and "text-danger-600" in html  # off icon in the off color
    assert 'x-show="on"' in html and "text-success-600" in html  # on icon in the on color
    # the default off color stays light gray
    assert "on ? 'bg-primary-600' : 'bg-gray-200 dark:bg-gray-700'" in str(make([Toggle("active")]).render())


# ---------------------------------------------------------------------- checkbox list


def test_checkbox_list_nested_options_show_group_headings():
    form = make([CheckboxList("sizes").options({
        "Tops": {"s": "Small", "m": "Medium"},
        "Shoes": {"8": "UK 8", "9": "UK 9"},
    })])
    html = str(form.render())
    assert html.count("data-group") == 2
    assert html.index("Tops") < html.index("Small") < html.index("Shoes") < html.index("UK 8")
    assert "{" not in re.sub(r"x-data=\"[^\"]*\"", "", html.split("Tops", 1)[1])  # no dict printed as a label
    assert submit(form, [("sizes", "m"), ("sizes", "9")]) == {"sizes": ["m", "9"]}
    errs = errors_of(form, [("sizes", "Tops")])
    assert "invalid" in errs["sizes"][0]


def test_checkbox_list_grouped_closure():
    form = make([CheckboxList("perms").options({"posts.view": "View posts", "posts.edit": "Edit posts",
                                                "users.view": "View users"})
                 .grouped(lambda value: value.split(".")[0].title())])
    html = str(form.render())
    assert html.count("data-group") == 2
    assert html.index("Posts") < html.index("Edit posts") < html.index("Users") < html.index("View users")
    assert submit(form, [("perms", "users.view")]) == {"perms": ["users.view"]}


def test_checkbox_list_without_groups_is_unchanged():
    html = str(make([CheckboxList("sizes").options(["S", "M"])]).render())
    assert "data-group" not in html and 'value="S"' in html


# ---------------------------------------------------------------------- dates


def test_empty_date_bound_from_closure_means_no_limit():
    form = make([
        DatePicker("starts_on"),
        DatePicker("ends_on").min_date(lambda get: get("starts_on")).max_date(lambda get: get("starts_on")),
    ])
    html = str(form.render())  # used to crash in parse("")
    assert "min=" not in html and "max=" not in html
    assert submit(form, [("starts_on", ""), ("ends_on", "2024-05-01")]) == {"starts_on": None,
                                                                          "ends_on": dt.date(2024, 5, 1)}
    errs = errors_of(form, [("starts_on", "2024-06-01"), ("ends_on", "2024-05-01")])
    assert "after or equal" in errs["ends_on"][0]


def test_date_time_picker_accepts_date_bounds():
    form = make([DateTimePicker("at").min_date(dt.date(2024, 1, 10)).max_date(dt.date(2024, 1, 20))])
    html = str(form.render())
    assert 'min="2024-01-10T00:00"' in html and 'max="2024-01-20T23:59"' in html
    # the whole last day is allowed
    assert submit(form, [("at", "2024-01-20T18:30")]) == {"at": dt.datetime(2024, 1, 20, 18, 30)}
    assert submit(form, [("at", "2024-01-10T00:00")]) == {"at": dt.datetime(2024, 1, 10)}
    assert "after or equal" in errors_of(form, [("at", "2024-01-09T23:59")])["at"][0]
    assert "before or equal" in errors_of(form, [("at", "2024-01-21T00:00")])["at"][0]


def test_date_time_picker_accepts_date_strings_and_date_picker_datetimes():
    form = make([DateTimePicker("at").max_date("2024-01-20"), DatePicker("on").min_date(dt.datetime(2024, 1, 5, 9))])
    assert submit(form, [("at", "2024-01-20T22:00"), ("on", "2024-01-05")]) == {
        "at": dt.datetime(2024, 1, 20, 22), "on": dt.date(2024, 1, 5)}


# ---------------------------------------------------------------------- live triggers


def test_live_triggers_per_field_type():
    assert trigger_of(TextInput("name").live()) == "change"
    assert trigger_of(TextInput("name").live(on_blur=True)) == "blur"
    assert trigger_of(TextInput("name").live(debounce=400)) == "input changed delay:400ms"
    assert trigger_of(Textarea("bio").live(on_blur=True)) == "blur"
    assert trigger_of(DatePicker("on").live(on_blur=True)) == "blur"
    # picked values: checkboxes keep the same value, so they always use "change"
    assert trigger_of(Checkbox("ok").live(on_blur=True)) == "change"
    assert trigger_of(Toggle("ok").live(debounce=300)) == "change delay:300ms"
    assert trigger_of(CheckboxList("s").options(["a"]).live(debounce=300)) == "change delay:300ms"
    assert trigger_of(Select("s").options(["a"]).live()) == "change"
    assert trigger_of(TagsInput("t").live(on_blur=True)) == "change"


# ---------------------------------------------------------------------- infolists


def test_text_entry_format_state_using():
    infolist = Infolist().schema([
        TextEntry("status").format_state_using(lambda state: state.replace("_", " ").title()),
        TextEntry("code").formatted(lambda state: state.upper()),
    ])
    infolist.bind(None, record=DataRecord({"status": "in_stock", "code": "ab"}))
    html = str(infolist.render())
    assert "In Stock" in html and "in_stock" not in html
    assert "AB" in html
