"""Built-in roles & permissions: a Roles resource and fields to assign roles."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ..forms.fields import CheckboxList, Select
from ..resources.resource import Resource


class PermissionsField(CheckboxList):
    """Checkboxes for every permission in the panel, grouped by resource, with search."""

    template = "tungsten/forms/fields/permissions.html"

    def __init__(self, name: str = "permissions") -> None:
        super().__init__(name)
        self._options = lambda ctx: ctx.panel.permission_options() if ctx else []
        self.bulk_toggleable()

    def hydrate(self, form, record):  # type: ignore[override]
        """Show ``products.*`` style wildcards as every matching box ticked."""
        stored = list(getattr(record, self.name, None) or [])
        options = [str(k) for k, _ in self.get_options(form)]
        out: list[str] = []
        for perm in stored:
            if perm.endswith(".*"):
                prefix = perm[:-1]
                out.extend(o for o in options if o.startswith(prefix))
            else:
                out.append(perm)
        return list(dict.fromkeys(out))

    def view_data(self, form, base):  # type: ignore[override]
        v = super().view_data(form, base)
        groups: dict[str, list] = {}
        labels = form.ctx.panel.permission_group_labels() if form.ctx else {}
        for opt in v["options"]:
            prefix = opt["value"].rsplit(".", 1)[0] if "." in opt["value"] else "general"
            groups.setdefault(prefix, []).append(opt)
        v["groups"] = [{"key": k, "label": labels.get(k, k.replace("-", " ").title()), "options": opts}
                       for k, opts in groups.items()]
        return v


class RolesField(Select):
    """Assign roles to a user (works on any user model). Use in your UserResource form."""

    def __init__(self, name: str = "roles") -> None:
        super().__init__(name)
        self.multiple()
        self._options = self._role_options
        self._dehydrated = False
        self.label("Roles")

    @staticmethod
    def _role_options(ctx: Any = None) -> list:
        from ..models import Role

        if ctx is None:
            return []
        return [(r.id, r.name) for r in ctx.db.scalars(select(Role).order_by(Role.name)).all()]

    def hydrate(self, form, record):  # type: ignore[override]
        from ..models import RoleAssignment

        if form.ctx is None or record is None:
            return []
        uid = form.ctx.panel.auth.user_id(record)
        rows = form.ctx.db.scalars(select(RoleAssignment.role_id).where(RoleAssignment.user_id == uid)).all()
        return [str(r) for r in rows]

    def fill_record(self, form, record, data):  # type: ignore[override]
        return None

    def save_relationships(self, form, record, data):  # type: ignore[override]
        if form.ctx is None or not self.is_field_visible(form, "") or self.is_disabled(form, ""):
            return
        keys = [k for k in (self.cast(self.get_state(form, "")) or []) if str(k).isdigit()]
        form.ctx.panel.auth.sync_roles(form.ctx.db, record, keys)
        form.ctx.db.flush()


class RoleResource(Resource):
    from ..models import Role as _Role

    model = _Role
    slug = "roles"
    icon = "shield-check"
    navigation_group = "Settings"
    navigation_label = "Roles & Permissions"
    navigation_sort = 90
    record_title_attribute = "name"
    description = "Define what each role can see and do."
    pages = ("index", "create", "edit")

    @classmethod
    def form(cls, form):
        from ..forms import Section, Textarea, TextInput

        return form.schema([
            Section("Role").description("A name and short description for this role.").schema([
                TextInput("name").required().max_length(100).unique(),
                Select("color").options({
                    "primary": "Orange", "info": "Blue", "success": "Green", "warning": "Amber",
                    "danger": "Red", "purple": "Purple", "teal": "Teal", "pink": "Pink", "gray": "Gray",
                }).default("primary"),
                Textarea("description").rows(2).column_span("full"),
            ]),
            Section("Permissions").description("Tick what this role is allowed to do. Use * in a "
                                               "role named Super Admin to allow everything.").schema([
                PermissionsField("permissions").hidden_label().column_span("full"),
            ]),
        ])

    @classmethod
    def table(cls, table):
        from ..actions import DeleteAction, DeleteBulkAction, EditAction
        from ..models import RoleAssignment
        from ..tables import TextColumn

        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "primary").searchable().sortable(),
                TextColumn("description").limit(60).placeholder("—").toggleable(),
                TextColumn("permissions").label("Permissions").state(
                    lambda record: "All" if "*" in (record.permissions or []) else len(record.permissions or [])),
                TextColumn("users").label("Users").state(
                    lambda record, db: db.scalar(select(func.count()).select_from(RoleAssignment)
                                                 .where(RoleAssignment.role_id == record.id))),
                TextColumn("created_at").date().sortable().toggleable(hidden_by_default=True),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("name")
        )
