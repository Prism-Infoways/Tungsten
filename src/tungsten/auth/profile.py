"""The "My profile" page: name, email, avatar and password change."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..forms import FileUpload, Form, Section, TextInput
from ..hosts import Host

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..panel import Panel


class ProfileHost(Host):
    key = "profile"

    def __init__(self, panel: "Panel") -> None:
        self.panel = panel
        self.model = panel.auth.user_model

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        return ctx.user is not None

    def find_record(self, ctx: "Context", key: Any, with_trashed: bool = True) -> Any:
        return ctx.user

    def form(self, ctx: "Context", operation: str = "edit", record: Any = None) -> Form:
        auth = self.panel.auth
        details = [
            TextInput(auth.name_field).label("Full name").required().max_length(255),
            TextInput(auth.email_field).label("Email address").email().required().max_length(255).unique()
            .prefix_icon("mail"),
        ]
        if auth.avatar_field:
            details.insert(0, FileUpload(auth.avatar_field).label("Profile photo").avatar().directory("avatars")
                           .max_size(2048).column_span("full"))
        form = Form().model(self.model).schema([
            Section("Profile information").description("Update your name, email address and photo.").aside()
            .schema(details),
            Section("Update password").description("Use a long, random password to stay secure.").aside().schema([
                TextInput("current_password").label("Current password").password().revealable()
                .dehydrated(False).required(lambda get: bool(get("new_password"))).column_span("full")
                .rule(lambda value, ctx: auth.verify(value or "", getattr(ctx.user, auth.password_field, None))
                      or "The current password is incorrect."),
                TextInput("new_password").label("New password").password().revealable().min_length(8).dehydrated(False),
                TextInput("new_password_confirmation").label("Confirm password").password().revealable()
                .same("new_password").dehydrated(False),
            ]),
        ])
        form.bind(ctx, operation="edit", record=ctx.user,
                  source={"kind": "host", "host": self.key, "op": "edit", "record": ""})
        return form

    def update(self, ctx: "Context", record: Any, data: dict, form: Form) -> Any:
        auth = self.panel.auth
        old_email = str(getattr(record, auth.email_field, "") or "").lower()
        form.fill_record(record, data)
        new_password = form.get("new_password")
        if new_password:
            setattr(record, auth.password_field, auth.hash(new_password))
        email_changed = str(getattr(record, auth.email_field, "") or "").lower() != old_email
        if email_changed and auth.email_verification:
            # a new address must be confirmed again
            setattr(record, auth.verified_field, None)
        ctx.db.commit()
        if email_changed and auth.email_verification:
            from .verification import send

            ctx.session.pop("tw_verify_sent", None)
            send(ctx, record)
            ctx.redirect(self.panel.url("email-verification", "prompt"))
        return record
