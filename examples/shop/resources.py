"""Resources for the shop demo — one class per model."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from sqlalchemy import func, select

from tungsten import Notification, RelationManager, Resource
from tungsten.actions import (
    Action,
    ActionGroup,
    AttachAction,
    DetachAction,
    DetachBulkAction,
    BulkAction,
    BulkActionGroup,
    CreateAction,
    DeleteAction,
    DeleteBulkAction,
    EditAction,
    ForceDeleteBulkAction,
    ReplicateAction,
    RestoreAction,
    RestoreBulkAction,
    ViewAction,
)
from tungsten.auth import hash_password
from tungsten.auth.rbac import RolesField
from tungsten.forms import (
    Block,
    Builder,
    CheckboxList,
    ColorPicker,
    DatePicker,
    DateTimePicker,
    FileUpload,
    Group,
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
    ToggleButtons,
    Wizard,
)
from tungsten.infolists import IconEntry, ImageEntry, KeyValueEntry, TextEntry
from tungsten.importexport import ExportAction, ExportBulkAction, ImportAction, ImportColumn, Importer
from tungsten.models import Role, RoleAssignment
from tungsten.tables import (
    BooleanConstraint,
    DateConstraint,
    DateFilter,
    NumberConstraint,
    QueryBuilder,
    RelationshipConstraint,
    SelectConstraint,
    TextConstraint,
    Filter,
    Group as TableGroup,
    IconColumn,
    ListTab,
    SelectColumn,
    SelectFilter,
    Sum,
    TernaryFilter,
    TextColumn,
    TextInputColumn,
    ToggleColumn,
    TrashedFilter,
)

from .models import Brand, Category, Customer, Order, OrderStatus, Post, Product, User
from .widgets import OrderStats, ProductStats, UserStats

INR = "₹"

STATES = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara"],
    "Karnataka": ["Bengaluru", "Mysuru"],
    "Delhi": ["New Delhi"],
    "Tamil Nadu": ["Chennai", "Coimbatore"],
}


def slugify(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


# ---------------------------------------------------------------------- users
class UserResource(Resource):
    model = User
    icon = "users"
    navigation_sort = 1
    description = "Manage all users in your application."
    global_search_attributes = ["name", "email", "username"]
    widgets = [UserStats]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(User))

    @classmethod
    def basic_fields(cls, form):
        creating = form.operation == "create"
        return [
            TextInput("name").label("Full name").required().max_length(120).placeholder("Amit Sharma"),
            TextInput("email").label("Email address").email().required().unique().prefix_icon("mail"),
            TextInput("username").required().max_length(60).unique().prefix("@")
            .regex(r"^[a-z0-9_.]+$", "Use lowercase letters, numbers, dots and underscores."),
            TextInput("password").password().revealable().prefix_icon("lock")
            .required(creating).min_length(8)
            .helper_text(None if creating else "Leave empty to keep the current password.")
            .dehydrate_state_using(lambda state: hash_password(state))
            .dehydrated(lambda state: bool(state)),
            TextInput("phone").label("Phone number").tel().prefix("+91").placeholder("98765 43210"),
            Toggle("is_active").label("Status").state_labels("Active", "Inactive").default(True)
            .helper_text("Inactive users cannot access the system."),
        ]

    @classmethod
    def extra_fields(cls):
        return [
            FileUpload("avatar").label("Profile photo").avatar().directory("avatars").max_size(2048),
            DatePicker("date_of_birth").max_date(dt.date.today()),
            Select("department").options(["Operations", "Sales", "Marketing", "Engineering", "Support"]),
            Textarea("bio").rows(3).placeholder("A short bio about the user...").column_span("full"),
        ]

    @classmethod
    def form(cls, form):
        if form.operation == "create":
            return form.schema([
                Wizard([
                    Step("Basic information").description("User details").schema(cls.basic_fields(form)),
                    Step("Role & permissions").description("Assign roles").schema([
                        RolesField().column_span("full").helper_text("Roles decide what this user can see and do."),
                        Toggle("is_admin").label("Panel access").helper_text("Allow this user to sign in to the admin panel."),
                    ]),
                    Step("Additional details").description("Extra information").schema(cls.extra_fields()),
                    Step("Review").description("Confirm and create").schema([
                        Placeholder("summary_name").label("Name").content(lambda get: get("/name")),
                        Placeholder("summary_email").label("Email").content(lambda get: get("/email")),
                        Placeholder("summary_username").label("Username").content(lambda get: "@" + (get("/username") or "")),
                        Placeholder("summary_status").label("Status").content(lambda get: "Active" if get("/is_active") else "Inactive"),
                    ]),
                ]).submit_label("Create user"),
            ])
        return form.schema([
            Tabs().tabs([
                Tab("General").icon("user").schema([
                    Section("Basic information").description("Primary details about the user account.")
                    .schema(cls.basic_fields(form)),
                ]),
                Tab("Roles & permissions").icon("shield-check").schema([
                    Section("Roles").description("What this user is allowed to do.").schema([
                        RolesField().column_span("full"),
                        Toggle("is_admin").label("Panel access"),
                    ]),
                ]),
                Tab("Profile").icon("id-card").schema([
                    Section("Additional information").description("More details about the user.").schema(cls.extra_fields()),
                ]),
                Tab("Preferences").icon("settings").schema([
                    KeyValue("preferences").key_label("Setting").value_label("Value").column_span("full"),
                ]),
            ]).contained(False),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").avatar("avatar").description(lambda record: f"@{record.username}" if record.username else None)
                .weight("medium").searchable(columns=["name", "username"]).sortable(),
                TextColumn("email").searchable().sortable().copyable()
                .icon(lambda record: "badge-check" if record.email_verified_at else None, "after").icon_color("success"),
                TextColumn("roles").label("Role").badge().state(cls.role_names)
                .color(lambda state: {"Admin": "info", "Manager": "purple", "Editor": "gray", "Viewer": "warning"}.get(state, "primary")),
                TextColumn("is_active").label("Status").badge().sortable()
                .format_state_using(lambda state: "Active" if state else "Inactive")
                .color(lambda state: "success" if state else "danger"),
                TextColumn("department").toggleable(hidden_by_default=True),
                TextColumn("created_at").label("Created at").date().sortable().toggleable(),
            ])
            .row_index()
            .filters([
                SelectFilter("role").options(lambda db: [(r.id, r.name) for r in db.scalars(select(Role))])
                .query(cls.filter_by_role),
                TernaryFilter("is_active").label("Status").true_label("Active").false_label("Inactive"),
                DateFilter("created_at").label("Created"),
                SelectFilter("department").options(["Operations", "Sales", "Marketing", "Engineering", "Support"]).multiple(),
            ])
            .actions([ViewAction(), EditAction(), DeleteAction()])
            .bulk_actions([
                BulkAction("activate").label("Activate").icon("circle-check").color("success")
                .action(lambda records, db: (cls.set_active(records, True), db.commit()))
                .success_notification_title("Users activated"),
                BulkAction("deactivate").label("Deactivate").icon("circle-x").color("danger").requires_confirmation()
                .action(lambda records, db: (cls.set_active(records, False), db.commit()))
                .success_notification_title("Users deactivated"),
                DeleteBulkAction(),
                BulkActionGroup([ExportBulkAction()]).label("More actions"),
            ])
            .header_actions([ExportAction()])
            .tabs([
                ListTab("all").label("All users").badge(),
                ListTab("active").icon("user-check").badge(color="success")
                .query(lambda query, model: query.where(model.is_active.is_(True))),
                ListTab("inactive").icon("user-x").badge(color="danger")
                .query(lambda query, model: query.where(model.is_active.is_(False))),
            ])
            .default_sort("created_at", "desc")
        )

    @staticmethod
    def filter_by_role(query, data, model, db):
        if not data.get("value"):
            return query
        ids = db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role_id == int(data["value"]))).all()
        return query.where(model.id.in_([int(i) for i in ids]))

    @staticmethod
    def set_active(records, value):
        for r in records:
            r.is_active = value

    @staticmethod
    def role_names(record, ctx):
        uid = str(record.id)
        return [r.name for r in ctx.db.scalars(select(Role).join(RoleAssignment).where(RoleAssignment.user_id == uid))]

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page == "edit":
            return [
                ViewAction().button().color("gray"),
                Action("reset_password").label("Reset password").icon("key-round").color("gray")
                .form([TextInput("password").label("New password").password().revealable().required().min_length(8)])
                .action(lambda record, data, db: (setattr(record, "password", hash_password(data["password"])), db.commit()))
                .success_notification_title("Password updated"),
                DeleteAction().outlined(),
            ]
        return super().header_actions(ctx, page, record)

    @classmethod
    def global_search_details(cls, record):
        return {"Email": record.email}


# ---------------------------------------------------------------------- categories & brands
class CategoryResource(Resource):
    model = Category
    plural_label = "Categories"
    icon = "folder-tree"
    navigation_group = "Catalog"
    navigation_parent = "Products"
    simple = True
    global_search_attributes = ["name"]

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(100).unique().live(on_blur=True)
            .after_state_updated(lambda state, set, operation: set("slug", slugify(state)) if operation == "create" else None),
            TextInput("slug").required().unique().helper_text("Used in URLs."),
            TextInput("icon").placeholder("shirt").helper_text("Any Lucide icon name."),
            Toggle("is_visible").label("Visible to customers").default(True),
            Textarea("description").column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").icon(lambda record: record.icon).searchable().sortable().weight("medium"),
                TextColumn("slug").color("gray"),
                TextColumn("products_count").label("Products").state(lambda record: len(record.products)).align_end(),
                ToggleColumn("is_visible").label("Visible"),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .reorderable("sort")
            .default_sort("sort")
        )


class BrandResource(Resource):
    model = Brand
    icon = "badge-check"
    navigation_group = "Catalog"
    navigation_parent = "Products"
    simple = True

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().unique(), TextInput("website").url()])

    @classmethod
    def table(cls, table):
        return table.columns([
            TextInputColumn("name").required().input_width("w-48").searchable().sortable(),
            TextInputColumn("website").configure(lambda field: field.url()).input_width("w-64"),
            TextColumn("products").label("Products").state(lambda record: len(record.products)),
        ]).actions([EditAction(), DeleteAction()])


# ---------------------------------------------------------------------- products
class ProductImporter(Importer):
    model = Product
    unique_by = "sku"
    columns = [
        ImportColumn("name").required().example("Premium T-Shirt"),
        ImportColumn("sku").label("SKU").required().example("TSH-001"),
        ImportColumn("price").numeric().required().example("1299"),
        ImportColumn("stock").numeric().example("120"),
        ImportColumn("status").example("published")
        .rule(lambda value: value in ("draft", "published", "archived") or "Status must be draft, published or archived"),
        ImportColumn("category").relationship("category", "name").example("Clothing"),
    ]


def stock_color(stock: int) -> str:
    return "danger" if stock <= 0 else ("warning" if stock < 10 else "success")


def product_state(record) -> str:
    if record.status != "published":
        return record.status.title()
    if record.stock <= 0:
        return "Out of stock"
    if record.stock < 10:
        return "Low stock"
    return "Published"


class TagsRelationManager(RelationManager):
    """Many-to-many: link existing tags to a product, or create new ones."""

    relationship = "tags"
    icon = "tags"
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().max_length(60).unique()])

    @classmethod
    def table(cls, table):
        return (
            table.columns([TextColumn("name").badge().color("primary").searchable()])
            .header_actions([AttachAction(), CreateAction()])
            .actions([EditAction(), DetachAction()])
            .bulk_actions([DetachBulkAction()])
        )


class ProductResource(Resource):
    model = Product
    icon = "package"
    navigation_group = "Catalog"
    navigation_sort = 2
    description = "Manage your product catalog and inventory."
    global_search_attributes = ["name", "sku", "category.name"]
    widgets = [ProductStats]
    relations = [TagsRelationManager]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Product).where(Product.deleted_at.is_(None)))

    navigation_badge_color = "primary"

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Tabs().column_span(2).tabs([
                Tab("General").icon("file-text").schema([
                    TextInput("name").label("Product name").required().max_length(150).column_span("full"),
                    TextInput("short_description").max_length(255).column_span("full"),
                    RichEditor("description").column_span("full"),
                    Select("category_id").label("Category").relationship("category", "name").searchable().required(),
                    Select("brand_id").label("Brand").relationship("brand", "name"),
                    Select("tags").relationship("tags", "name").multiple().column_span("full"),
                ]),
                Tab("Media").icon("image").schema([
                    FileUpload("images").label("Product images").image().multiple().max_files(6)
                    .directory("products").max_size(2048).column_span("full"),
                ]),
                Tab("Inventory").icon("boxes").schema([
                    TextInput("sku").label("SKU").required().unique().max_length(40),
                    TextInput("stock").integer().min_value(0).default(0).required(),
                    CheckboxList("sizes").label("Available sizes").options(["S", "M", "L", "XL"]).columns(4),
                    DatePicker("available_from"),
                ]),
                Tab("Pricing").icon("indian-rupee").schema([
                    TextInput("price").numeric().prefix(INR).min_value(0).required(),
                    TextInput("compare_price").label("Compare-at price").numeric().prefix(INR).min_value(0)
                    .helper_text("Shown crossed out on the storefront."),
                    ColorPicker("color"),
                ]),
                Tab("SEO").icon("search").schema([
                    TagsInput("keywords").suggestions(["cotton", "summer", "casual", "sale"]).column_span("full"),
                    KeyValue("attributes").key_label("Attribute").value_label("Value").column_span("full"),
                ]),
            ]),
            Group([
                Section("Status").icon("circle-dot").schema([
                    Radio("status").options({"draft": "Draft", "published": "Published", "archived": "Archived"})
                    .descriptions({"draft": "Only admins can see it", "published": "Visible in the store"})
                    .default("draft").required().column_span("full"),
                    Toggle("is_featured").label("Featured").column_span("full"),
                ]),
                Section("Details").icon("info").schema([
                    Placeholder("created").label("Created").content(
                        lambda record: record.created_at.strftime("%d %b %Y, %H:%M") if record else "Not saved yet"),
                    Placeholder("in_stock").label("Stock status").content(
                        lambda get: "In stock" if int(get("stock") or 0) > 0 else "Out of stock"),
                ]).visible(lambda operation: operation != "create"),
            ]).columns(1),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").label("Product").avatar(lambda record: record.image, circular=False)
                .description(lambda record: record.short_description).weight("medium").searchable().sortable().wrap(),
                TextColumn("sku").label("SKU").searchable().font_mono().toggleable(),
                TextColumn("category.name").label("Category").badge().color("info").sortable(),
                TextColumn("price").money(INR, 0).sortable().summarize(Sum().money(INR, 0)),
                TextColumn("stock").icon("circle-dot").color(lambda record: stock_color(record.stock)).sortable()
                .summarize(Sum()),
                TextColumn("state").label("Status").badge().state(product_state).colors({
                    "success": "Published", "warning": ["Low stock", "Draft"], "danger": "Out of stock", "gray": "Archived",
                }),
                IconColumn("is_featured").label("Featured").boolean().toggleable(hidden_by_default=True),
                TextColumn("tags.name").label("Tags").badge().limit_list(2).toggleable(hidden_by_default=True),
                TextColumn("created_at").label("Created at").date().sortable().toggleable(),
            ])
            .filters([
                SelectFilter("category").relationship("category", "name").placeholder("All categories"),
                SelectFilter("brand").relationship("brand", "name").placeholder("All brands"),
                SelectFilter("status").options({"draft": "Draft", "published": "Published", "archived": "Archived"}),
                Filter("low_stock").label("Low stock only").query(lambda query, model: query.where(model.stock < 10)),
                TernaryFilter("is_featured").label("Featured"),
                TrashedFilter(),
                QueryBuilder().constraints([
                    TextConstraint("name"),
                    TextConstraint("sku").label("SKU"),
                    NumberConstraint("price"),
                    NumberConstraint("stock").integer(),
                    SelectConstraint("status").options({"draft": "Draft", "published": "Published",
                                                        "archived": "Archived"}),
                    BooleanConstraint("is_featured").label("Featured"),
                    DateConstraint("created_at").label("Created"),
                    TextConstraint("category.name").label("Category name"),
                    RelationshipConstraint("tags").selectable("name"),
                ]),
            ])
            .groups(["category.name", "status"])
            .actions([
                ViewAction(), EditAction(),
                ActionGroup([
                    ReplicateAction(excluded=["sku"]).before_replica_saved(
                        lambda replica: setattr(replica, "sku", f"{replica.name[:3].upper()}-{dt.datetime.now():%H%M%S}")),
                    Action("publish").icon("send").color("success").requires_confirmation()
                    .visible(lambda record: record.status != "published")
                    .action(lambda record, db: (setattr(record, "status", "published"), db.commit()))
                    .success_notification_title("Product published"),
                    RestoreAction(),
                    DeleteAction(),
                ]),
            ])
            .bulk_actions([
                BulkAction("publish").label("Publish").icon("circle-check").color("success")
                .action(lambda records, db: ([setattr(r, "status", "published") for r in records], db.commit()))
                .success_notification_title("Products published"),
                BulkAction("unpublish").label("Unpublish").icon("circle-x").color("danger")
                .action(lambda records, db: ([setattr(r, "status", "draft") for r in records], db.commit()))
                .success_notification_title("Products moved to draft"),
                DeleteBulkAction(),
                BulkActionGroup([RestoreBulkAction(), ForceDeleteBulkAction(), ExportBulkAction()]).label("More actions"),
            ])
            .header_actions([ImportAction(ProductImporter), ExportAction()])
            .tabs([
                ListTab("all").label("All products").badge(),
                ListTab("published").badge(color="success").query(lambda query, model: query.where(model.status == "published")),
                ListTab("draft").label("Drafts").badge(color="warning").query(lambda query, model: query.where(model.status == "draft")),
                ListTab("low").label("Low stock").icon("triangle-alert").badge(color="danger")
                .query(lambda query, model: query.where(model.stock < 10)),
            ])
            .default_sort("created_at", "desc")
        )

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Section("Product").column_span(2).schema([
                TextEntry("name").weight("semibold").size("lg").column_span("full"),
                TextEntry("short_description").color("gray").column_span("full"),
                TextEntry("description").html().column_span("full"),
                TextEntry("category.name").label("Category").badge().color("info"),
                TextEntry("brand.name").label("Brand"),
                TextEntry("tags.name").label("Tags").badge(),
                TextEntry("keywords").badge().color("gray"),
                ImageEntry("images").label("Images").stacked().column_span("full"),
            ]),
            Group([
                Section("Pricing & stock").schema([
                    TextEntry("price").money("INR", 0).weight("bold").size("lg"),
                    TextEntry("compare_price").label("Compare-at").money("INR", 0),
                    TextEntry("stock").icon("circle-dot").color(lambda record: stock_color(record.stock)),
                    TextEntry("state").label("Status").state(product_state).badge().colors({
                        "success": "Published", "warning": ["Low stock", "Draft"], "danger": "Out of stock"}),
                    IconEntry("is_featured").label("Featured").boolean(),
                    TextEntry("color").placeholder("No color"),
                ]),
                Section("Attributes").schema([
                    KeyValueEntry("attributes").hidden_label().column_span("full"),
                ]).collapsible(),
                Section("History").schema([
                    TextEntry("created_at").label("Created").datetime().inline_label().column_span("full"),
                    TextEntry("available_from").date().inline_label().column_span("full"),
                ]),
            ]).columns(1),
        ])

    @classmethod
    def global_search_details(cls, record):
        return {"Category": record.category.name if record.category else "—", "SKU": record.sku}

    @classmethod
    def global_search_image(cls, record):
        return record.image if record.image and record.image.startswith("http") else None


# ---------------------------------------------------------------------- customers
class OrdersRelationManager(RelationManager):
    relationship = "orders"
    icon = "shopping-cart"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("number").required().unique().default(lambda: f"ORD-{dt.datetime.now():%y%m%d%H%M%S}"),
            Select("status").options(OrderStatus).required().default("pending"),
            TextInput("total").numeric().prefix(INR).default(0),
            Textarea("notes").column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("#").weight("medium").searchable(),
                TextColumn("status").badge(),
                TextColumn("total").money(INR, 0).summarize(Sum().money(INR, 0)),
                TextColumn("created_at").label("Date").date().sortable(),
            ])
            .header_actions([CreateAction()])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("created_at", "desc")
            .paginated([5, 10], 5)
        )


class CustomerResource(Resource):
    model = Customer
    icon = "contact"
    navigation_group = "Shop"
    navigation_sort = 4
    description = "Everyone who has bought from your store."
    global_search_attributes = ["name", "email", "phone"]
    relations = [OrdersRelationManager]

    @classmethod
    def form(cls, form):
        return form.schema([
            Section("Customer").icon("user").description("Contact details.").schema([
                TextInput("name").required(),
                TextInput("email").email().required().unique(),
                TextInput("phone").tel().prefix("+91"),
                FileUpload("avatar").avatar().directory("customers"),
            ]),
            Section("Address").icon("map-pin").description("Pick a state to see its cities (a dependent field).").schema([
                Select("state").options(list(STATES)).live().after_state_updated(lambda set: set("city", "")),
                Select("city").options(lambda get: STATES.get(get("state"), []))
                .visible(lambda get: bool(get("state"))).required(lambda get: bool(get("state"))),
                Textarea("notes").column_span("full"),
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").avatar("avatar").searchable().sortable().weight("medium"),
                TextColumn("email").searchable().copyable(),
                TextColumn("phone").prefix("+91 ").toggleable(),
                TextColumn("city").description(lambda record: record.state).sortable(),
                TextColumn("orders_count").label("Orders").counts("orders"),
                TextColumn("created_at").label("Customer since").since().sortable(),
            ])
            .filters([SelectFilter("state").options(list(STATES))])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction(), ExportBulkAction()])
            .header_actions([ExportAction()])
        )


# ---------------------------------------------------------------------- orders
def items_total(get) -> Decimal:
    total = Decimal(0)
    for row in get("/items") or []:
        try:
            total += Decimal(str(row.get("quantity") or 0)) * Decimal(str(row.get("unit_price") or 0))
        except Exception:  # noqa: BLE001
            pass
    return total


class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"
    navigation_group = "Shop"
    navigation_sort = 3
    record_title_attribute = "number"
    description = "Track orders from checkout to delivery."
    widgets = [OrderStats]
    global_search_attributes = ["number", "customer.name"]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING)) or None

    navigation_badge_color = "danger"

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("Order details").icon("receipt").column_span(2).schema([
                TextInput("number").required().unique().default(lambda: f"ORD-{dt.datetime.now():%y%m%d%H%M%S}"),
                Select("customer_id").label("Customer").relationship("customer", "name").searchable().preload(False).required(),
                Select("status").options(OrderStatus).required().default("pending"),
                Textarea("shipping_address").rows(2),
                Textarea("notes").rows(2),
            ]),
            Section("Summary").icon("calculator").column_span(1).schema([
                Placeholder("items_total").label("Order total").content(lambda get: f"{INR}{items_total(get):,.2f}"),
                Placeholder("items_count").label("Items").content(lambda get: len(get("/items") or [])),
            ]).columns(1),
            Section("Items").icon("package").column_span("full").schema([
                Repeater("items").relationship("items", order_column="sort").table().hidden_label()
                .schema([
                    Select("product_id").label("Product").relationship("product", "name").required().live()
                    .after_state_updated(lambda state, set, db: set("unit_price", str(db.get(Product, int(state)).price) if state else "")),
                    TextInput("quantity").integer().min_value(1).default(1).required().live(debounce=400),
                    TextInput("unit_price").label("Unit price").numeric().prefix(INR).required().live(debounce=400),
                ])
                .min_items(1).add_action_label("Add item").column_span("full"),
            ]),
        ])

    @classmethod
    def after_create(cls, record, db, ctx):
        cls.after_save(record, db)
        admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
        Notification("New order").body(f"{record.number} was placed by {record.customer.name}.") \
            .icon("shopping-cart").color("primary").action("View order", ctx.url("orders", record.id, "edit")) \
            .send_to_database(admins, db)

    @classmethod
    def after_save(cls, record, db):
        db.flush()
        db.refresh(record)
        record.total = sum((i.quantity * i.unit_price for i in record.items), Decimal(0))

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("Order").weight("medium").searchable().sortable().copyable(),
                TextColumn("customer.name").label("Customer").avatar("customer.avatar").searchable().sortable()
                .description(lambda record: record.customer.email if record.customer else None),
                TextColumn("status").badge().sortable(),
                TextColumn("items").label("Items").state(lambda record: sum(i.quantity for i in record.items)),
                TextColumn("total").money(INR, 0).sortable().summarize(Sum().money(INR, 0)),
                TextColumn("created_at").label("Date").date().sortable(),
            ])
            .filters([
                SelectFilter("status").options(OrderStatus).multiple(),
                SelectFilter("customer").relationship("customer", "name").searchable(),
                DateFilter("created_at").label("Order date"),
            ])
            .groups([TableGroup("status"), TableGroup("customer.name").label("Customer")])
            .actions([
                Action("ship").label("Mark shipped").icon("truck").color("info").icon_button()
                .visible(lambda record: record.status in (OrderStatus.PENDING, OrderStatus.PROCESSING, OrderStatus.PAID))
                .requires_confirmation().modal_description("The customer will see the order as shipped.")
                .action(lambda record, db: (setattr(record, "status", OrderStatus.SHIPPED), db.commit()))
                .success_notification_title("Order shipped"),
                EditAction(),
                ActionGroup([ViewAction(), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("paid").label("Mark paid").icon("badge-indian-rupee").color("success")
                .action(lambda records, db: ([setattr(r, "status", OrderStatus.PAID) for r in records], db.commit()))
                .success_notification_title("Orders marked as paid"),
                DeleteBulkAction(),
                BulkActionGroup([ExportBulkAction()]),
            ])
            .header_actions([ExportAction()])
            .tabs([ListTab("all").label("All orders").badge()] + [
                ListTab(s.value).badge(color=s.color).query(lambda query, model, s=s: query.where(model.status == s))
                for s in (OrderStatus.PENDING, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.PAID)
            ])
            .default_sort("created_at", "desc")
            .striped()
        )


# ---------------------------------------------------------------------- blog
class PostResource(Resource):
    """Blog posts: a Builder field for the body and ToggleButtons for status."""

    model = Post
    icon = "newspaper"
    navigation_group = "Marketing"
    navigation_label = "Blog"
    global_search_attributes = ["title"]

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("Post").column_span(2).schema([
                TextInput("title").required().max_length(200).live(on_blur=True)
                .after_state_updated(lambda state, set, operation: set("slug", slugify(state)) if operation == "create" else None),
                TextInput("slug").required().unique().prefix("/blog/"),
                Builder("content").blocks([
                    Block("heading").icon("heading").columns(3).schema([
                        TextInput("text").required().column_span(2),
                        Select("level").options({"h2": "Heading 2", "h3": "Heading 3"}).default("h2"),
                    ]),
                    Block("paragraph").icon("pilcrow").schema([RichEditor("body").required()]),
                    Block("image").icon("image").schema([
                        FileUpload("image").image().directory("blog").required(), TextInput("alt").label("Alt text"),
                    ]),
                    Block("quote").icon("quote").columns(2).schema([Textarea("text").required(), TextInput("author")]),
                ]).add_action_label("Add block").collapsible().column_span("full"),
            ]),
            Section("Publishing").column_span(1).schema([
                ToggleButtons("status").options({"draft": "Draft", "review": "In review", "published": "Published"})
                .icons({"draft": "pencil", "review": "eye", "published": "circle-check"})
                .colors({"draft": "gray", "review": "warning", "published": "success"})
                .default("draft").required().column_span("full"),
                Select("author_id").label("Author").relationship("author", "name").searchable().column_span("full"),
                DateTimePicker("published_at").column_span("full"),
            ]).columns(1),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("title").searchable().sortable().weight("medium").description(lambda record: f"/blog/{record.slug}"),
                SelectColumn("status").options({"draft": "Draft", "review": "In review", "published": "Published"}),
                TextColumn("author.name").label("Author"),
                TextColumn("blocks").label("Blocks").state(lambda record: len(record.content or [])),
                TextColumn("published_at").date().sortable().placeholder("Not published"),
            ])
            .tabs([
                ListTab("all").badge(),
                ListTab("published").badge(color="success").query(lambda query, model: query.where(model.status == "published")),
                ListTab("review").label("In review").badge(color="warning").query(lambda query, model: query.where(model.status == "review")),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("created_at", "desc")
        )


ALL_RESOURCES = [UserResource, ProductResource, CategoryResource, BrandResource, OrderResource, CustomerResource,
                 PostResource]
