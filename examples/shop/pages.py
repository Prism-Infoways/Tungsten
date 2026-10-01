"""Custom pages: system settings (a form page) and reports (a widgets page)."""

from __future__ import annotations

import json
from pathlib import Path

from markupsafe import Markup

from tungsten import Page
from tungsten.forms import ColorPicker, KeyValue, Section, Select, TextInput, Toggle

from .widgets import RevenueChart, SalesByCategory, UsersByRole

SETTINGS_FILE = Path("storage/settings.json")
DEFAULTS = {
    "store_name": "Tungsten Store",
    "support_email": "support@example.com",
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "brand_color": "#f97316",
    "email_notifications": True,
    "system_notifications": True,
    "marketing_emails": False,
    "extra": {"gst_number": "27ABCDE1234F1Z5"},
}


class SystemSettings(Page):
    icon = "settings"
    navigation_group = "Settings"
    navigation_sort = 99
    subheading = "Store-wide settings. Saved to storage/settings.json in this demo."
    permission = "page.settings"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Section("General").description("Basic store information.").schema([
                TextInput("store_name").required(),
                TextInput("support_email").email().required(),
                Select("currency").options({"INR": "Indian Rupee (₹)", "USD": "US Dollar ($)", "EUR": "Euro (€)"}).required(),
                Select("timezone").options(["Asia/Kolkata", "UTC", "Europe/London", "America/New_York"]).searchable(),
                ColorPicker("brand_color"),
            ]),
            Section("Notification settings").description("Configure notification preferences.").schema([
                Toggle("email_notifications").helper_text("Receive email notifications").column_span("full"),
                Toggle("system_notifications").helper_text("Receive in-app notifications").column_span("full"),
                Toggle("marketing_emails").helper_text("Product updates and marketing emails").column_span("full"),
            ]),
            Section("Extra settings").description("Any other key/value settings.").schema([
                KeyValue("extra").column_span("full"),
            ]).column_span("full"),
        ])

    @classmethod
    def mount(cls, ctx):
        if SETTINGS_FILE.exists():
            return {**DEFAULTS, **json.loads(SETTINGS_FILE.read_text())}
        return DEFAULTS

    @classmethod
    def save(cls, ctx, data):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2, default=str))


class Reports(Page):
    icon = "chart-column"
    navigation_group = "Shop"
    navigation_sort = 10
    subheading = "Sales and customer reports."
    widgets = [RevenueChart, UsersByRole, SalesByCategory]

    @classmethod
    def content(cls, ctx):
        return Markup(
            '<div class="tw-card p-6 text-sm text-gray-600 dark:text-gray-300">'
            "Custom pages can show any HTML, widgets, a form, or all of them together.</div>"
        )
