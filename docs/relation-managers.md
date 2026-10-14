---
title: Relation managers
description: Manage related records, like a customer's orders or a product's tags, in a table on the record's page.
---

A relation manager shows the related records of one record in a table under its form. For example, the customer edit page can list that customer's orders, with buttons to add, edit and delete them, without leaving the page.

## Defining a relation manager

Subclass `RelationManager`, name the SQLAlchemy relationship, and give it a form and a table, just like a resource.

```python
import datetime as dt

from tungsten import RelationManager
from tungsten.actions import CreateAction, DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Select, Textarea, TextInput
from tungsten.tables import TextColumn


class OrdersRelationManager(RelationManager):
    relationship = "orders"            # Customer.orders
    icon = "shopping-cart"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("number").required().unique().default(lambda: f"ORD-{dt.datetime.now():%y%m%d%H%M%S}"),
            Select("status").options(OrderStatus).required().default("pending"),
            TextInput("total").numeric().prefix("₹").default(0),
            Textarea("notes").column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("#").searchable(),
                TextColumn("status").badge(),
                TextColumn("total").money("INR"),
                TextColumn("created_at").label("Date").date().sortable(),
            ])
            .header_actions([CreateAction()])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("created_at", "desc")
        )
```

Then list it in the resource's `relations`:

```python
class CustomerResource(Resource):
    model = Customer
    relations = [OrdersRelationManager]
```

The customer edit page now has an "Orders" table under the form. **New order** opens the form in a popup. The new order is linked to the customer for you, so the form does not need a `customer_id` field.

> [!TIP]
> `tungsten make:relation-manager Customer orders` writes the class for you. Add `--attach` for a many-to-many relationship. See [CLI](cli).

## Where it appears

- On the **edit** and **view** pages of the owner record. It is not shown on the create page, because the record does not exist yet.
- With one relation manager, the table has a heading. With several, they become tabs, and each tab shows a count of related records.
- Set `show_on_view = False` to show it on the edit page only.

The table works like any other [table](tables): search, sort, filters, pagination, row actions and bulk actions. `EditAction`, `ViewAction` and `CreateAction` open popups here, unless the records have [nested pages](#nested-resources).

## Options

| Attribute | What it does |
| --- | --- |
| `relationship` | Name of the relationship on the owner model (required). |
| `title` | Heading and tab text. Default: made from the relationship name ("Orders"). |
| `label` | Singular name used in buttons ("New order"). Default: the title without a trailing "s". |
| `icon` | Icon next to the heading or tab. |
| `record_title_attribute` | Attribute used as the record title in popup headings and in the attach list. Without it, popups use the first of `name`, `title`, `number` or `email`. |
| `soft_delete_column` | Soft-delete column of the related model. Default: `"deleted_at"` when it exists. `None` turns it off. |
| `show_on_view` | `False` hides it on the view page. Default: `True`. |
| `separate_page` | `True` shows the table on [its own page](#related-records-on-their-own-page) instead of under the form. |
| `slug` | URL part of that page. Default: the relationship name in kebab-case. |
| `related_resource` | A resource whose form, table and infolist are used, with [nested pages](#nested-resources) for its records. |
| `linkable` | `False` turns off creating and linking records. Default: off for "through" paths and read-only relationships. |

### The count badge

When there are several relation managers, the number on each tab is the length of the relationship. Override `badge()` to show something else, or return `None` to hide it. It can ask for `ctx` and `owner`.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def badge(cls, owner):
        return sum(1 for o in owner.orders if o.status == "pending") or None
```

## Many-to-many relationships

For a many-to-many relationship (one with a `secondary` table), use `AttachAction` to link existing records and `DetachAction` / `DetachBulkAction` to unlink them.

```python
from tungsten.actions import AttachAction, CreateAction, DetachAction, DetachBulkAction, EditAction


class TagsRelationManager(RelationManager):
    relationship = "tags"              # Product.tags
    icon = "tags"
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().max_length(60).unique()])

    @classmethod
    def table(cls, table):
        return (
            table.columns([TextColumn("name").badge().searchable()])
            .header_actions([AttachAction(), CreateAction()])
            .actions([EditAction(), DetachAction()])
            .bulk_actions([DetachBulkAction()])
        )
```

| Action | What it does |
| --- | --- |
| `AttachAction()` | Opens a popup with a searchable multi-select of records that are not linked yet. The chosen ones are linked. |
| `DetachAction()` | Unlinks one record, after a confirmation. The record itself is kept. |
| `DetachBulkAction()` | Unlinks the selected records. |
| `CreateAction()` | Creates a new record and links it. |
| `DeleteAction()` | Unlinks the record **and deletes it**. Use `DetachAction` if the record is shared. |

The attach list shows up to 500 records, using `record_title_attribute` for the text (without it, the first of `name`, `title`, `number` or `email`). Pass `AttachAction(title_attribute="name")` to use another attribute, `.record_select_options_query(lambda query: ...)` to narrow the list, and `.multiple(False)` to pick one record at a time.

### Extra fields on the link table

When the link table has its own columns (a member's `role` in a team), give `AttachAction` a form. The fields appear under the record picker and are saved on the link table.

```python
team_members = Table("team_members", Base.metadata,
    Column("team_id", ForeignKey("teams.id"), primary_key=True),
    Column("member_id", ForeignKey("members.id"), primary_key=True),
    Column("role", String(20), nullable=False),
)


class MembersRelationManager(RelationManager):
    relationship = "members"           # Team.members, secondary=team_members

    @classmethod
    def table(cls, table):
        return (
            table.columns([TextColumn("name"), TextColumn("pivot.role").label("Role").badge()])
            .header_actions([
                AttachAction().form([
                    Select("role").options({"lead": "Lead", "dev": "Developer"}).required(),
                ]),
            ])
            .actions([DetachAction()])
        )
```

In the table, each row has a `pivot` with the link table's extra columns, so `TextColumn("pivot.role")` shows the role. (Pivot columns can't be sorted or searched.)

## One-to-many: associate and dissociate

For a one-to-many relationship, `CreateAction` makes a new related record. To link records that already exist, use `AssociateAction`. It offers the records not linked to this owner and points them at it (`project.team_id = 1`). `DissociateAction` and `DissociateBulkAction` unlink them again by emptying that column; the records are kept.

```python
from tungsten.actions import AssociateAction, CreateAction, DissociateAction, DissociateBulkAction


class ProjectsRelationManager(RelationManager):
    relationship = "projects"          # Team.projects

    @classmethod
    def table(cls, table):
        return (
            table.columns([TextColumn("name")])
            .header_actions([CreateAction(), AssociateAction()])
            .actions([DissociateAction()])
            .bulk_actions([DissociateBulkAction()])
        )
```

Dissociate buttons only show when the link column allows empty values (`nullable=True`). `AssociateAction` has the same options as `AttachAction`.

## Polymorphic relationships

A polymorphic relationship lets several models own the same kind of record: comments on posts and on videos, stored with a `commentable_id` and a `commentable_type`. Build these relationships with `morph_many` and `morph_to_many`:

```python
from tungsten.relations import morph_many, morph_to_many

taggables = Table("taggables", Base.metadata,
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
    Column("taggable_id", Integer, primary_key=True),
    Column("taggable_type", String(20), primary_key=True),
)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]
    commentable_id: Mapped[int | None]
    commentable_type: Mapped[str | None]


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    comments = morph_many("Comment", "commentable")                 # one-to-many
    tags = morph_to_many("Tag", "taggable", table="taggables")      # many-to-many


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    comments = morph_many("Comment", "commentable")
```

The type saved is the owner's table name (`"posts"`); pass `type="post"` to use another value, and `id_column=` / `type_column=` for other column names. A relation manager on `comments` or `tags` works as usual: create, associate, dissociate, attach and detach all fill in the type column.

Your own SQLAlchemy relationships work too: when the join has a fixed value (`Comment.commentable_type == "posts"`), Tungsten fills it when linking.

## Has many through

To list records two (or more) relationships away, give a dotted path. A team's tasks, through its projects:

```python
class TasksRelationManager(RelationManager):
    relationship = "projects.tasks"    # Team.projects -> Project.tasks
    title = "Tasks"
```

The records can be viewed, edited and deleted, but not created, attached or associated here, because Tungsten can't know which project a new task belongs to. A read-only (`viewonly=True`) SQLAlchemy relationship behaves the same way.

## Related records on their own page

Set `separate_page = True` to move a relation manager off the record's page. Its table gets a page of its own, like `/admin/teams/1/projects`, and the record's pages show links between the record and each of these pages. These links are the record's [sub-menu](navigation#sub-menu-on-a-records-pages), so you can move them to the side or add your own.

```python
class ProjectsRelationManager(RelationManager):
    relationship = "projects"
    separate_page = True
```

## Nested resources

When related records are big enough to need full pages, make them a nested resource. Their pages live under the parent record:

- `/admin/courses/1/lessons/create`
- `/admin/courses/1/lessons/5` (view)
- `/admin/courses/1/lessons/5/edit`

Write a normal resource for the child, and point a relation manager at it with `related_resource`. Its form, table, infolist, header actions, hooks and permissions are used.

```python
class LessonResource(Resource):
    model = Lesson
    parent_relationship = "course"     # Lesson.course

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required(), RichEditor("body")])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title")]).header_actions([CreateAction()]).actions([EditAction()])


class LessonsRelationManager(RelationManager):
    relationship = "lessons"           # Course.lessons
    related_resource = LessonResource


class CourseResource(Resource):
    model = Course
    relations = [LessonsRelationManager]


LessonResource.parent_resource = CourseResource

panel.resources([CourseResource, LessonResource])
```

- **New lesson** and **Edit** in the course's lessons table open the nested pages. A new lesson is linked to the course for you.
- A lesson is only found under its own course: `/admin/courses/2/lessons/5` is "not found" when lesson 5 belongs to course 1.
- With `parent_resource` set, the lesson resource leaves the menu, its list page sends you to the courses, and old links like `/admin/lessons/5/edit` (global search, notifications) go to the nested page. `parent_relationship` names the lesson's link back to its course, which those links need.
- Register the nested resource with the panel too, so its own relation managers work on its pages.

## Scoping the related records

By default the table shows every record in the relationship. Add a `query()` class method to filter or change it. It can ask for `query` (the starting `select()`), `owner` and `ctx`, and must return a query.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def query(cls, query, owner):
        return query.where(Order.status != "cancelled")
```

## View popup

`ViewAction()` in a relation manager opens a read-only popup. Give the relation manager an `infolist()` to show formatted values there; without one, the form is shown disabled. See [Infolists](infolists).

```python
from tungsten.actions import ViewAction
from tungsten.infolists import TextEntry


class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def infolist(cls, infolist):
        return infolist.schema([
            TextEntry("number"),
            TextEntry("status").badge(),
            TextEntry("total").money("INR"),
            TextEntry("created_at").datetime(),
        ])

    @classmethod
    def table(cls, table):
        return table.columns([...]).actions([ViewAction(), EditAction()])
```

## Hooks

Relation managers support the same lifecycle hooks as resources: `mutate_form_data_before_create`, `before_create`, `after_create`, `mutate_form_data_before_save`, `before_save`, `after_save`, `before_delete`, `after_delete` and `after_restore`. They also get `owner`, the parent record.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def after_create(cls, record, owner, db):
        owner.last_order_at = record.created_at
```

See [Resources](resources#lifecycle-hooks) for when each hook runs.

## Permissions

By default:

- Users who can **view** the owner record can see the relation manager.
- Users who can **update** the owner record can create, edit, delete, attach, detach, associate and dissociate related records.

With a `related_resource`, that resource's permissions decide what users can do with its records (they still need to be able to view the owner).

Override `can()` to decide yourself. It receives `ctx`, the `ability` (such as `"create"`, `"update"`, `"delete"`, `"attach"`, `"detach"`, `"associate"`, `"dissociate"`), the related `record` (or `None`), and keyword arguments `owner` and `resource`.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def can(cls, ctx, ability, record=None, *, owner=None, resource=None):
        if ability in ("view", "view_any"):
            return True
        return ctx.user.is_admin
```

## Soft-deleted related records

If the related model has a `deleted_at` column, deleting a related record soft-deletes it, just like on a resource. Add `TrashedFilter()`, `RestoreAction()` and `ForceDeleteAction()` to the relation manager's table to see and restore them. See [Resources](resources#soft-deletes).
