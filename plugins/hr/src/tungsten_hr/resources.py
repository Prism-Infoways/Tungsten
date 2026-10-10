"""Admin screens of the HR plugin: Employees, Departments, Attendance, Leave requests, Leave types, Holidays."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select

from tungsten import RelationManager, Resource
from tungsten.actions import (
    Action,
    ActionGroup,
    BulkAction,
    DeleteAction,
    DeleteBulkAction,
    EditAction,
    ViewAction,
)
from tungsten.forms import (
    DatePicker,
    FileUpload,
    Group,
    KeyValue,
    Placeholder,
    Section,
    Select,
    Textarea,
    TextInput,
    TimePicker,
    Toggle,
)
from tungsten.importexport import ExportAction, ExportBulkAction, ImportAction, ImportColumn, Importer
from tungsten.infolists import TextEntry
from tungsten.support.colors import COLOR_NAMES
from tungsten.tables import DateFilter, ListTab, SelectFilter, TernaryFilter, TextColumn, ToggleColumn

from .biometric import apply_punch, find_employee, link_punches, parse_time, pull_device
from .models import Attendance, BiometricDevice, Department, Employee, Holiday, LeaveRequest, LeaveType, Punch
from .service import (
    ATTENDANCE_STATUSES,
    EMPLOYEE_STATUSES,
    EMPLOYMENT_TYPES,
    LEAVE_STATUSES,
    LeaveError,
    check_in,
    check_leave,
    check_out,
    count_days,
    decide_leave,
    employee_for_user,
    fill_attendance,
    give_code,
    leave_requested,
    mark_attendance,
    today_row,
)
from .views import balance_html, month_html
from .widgets import HRStats

COLORS = {c: c.title() for c in COLOR_NAMES if c != "primary"} | {"primary": "Brand"}
GENDERS = {"female": "Female", "male": "Male", "other": "Other"}
SOURCES = {"panel": "Panel", "self": "Check-in button", "leave": "Leave", "import": "Import", "api": "API",
           "device": "Biometric machine"}
PUNCH_SOURCES = {"push": "Machine sent", "pull": "Fetched", "api": "API", "import": "File"}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("hr") if ctx is not None else None


def _labels(table: dict) -> dict[str, str]:
    return {key: label for key, (label, _) in table.items()}


def _color(table: dict):
    return lambda state: table.get(str(state), ("", "gray"))[1]


def _label(table: dict):
    return lambda state: table.get(str(state), (state, ""))[0]


def _me(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx is not None and ctx.user is not None else None


def my_employee(ctx: Any) -> Employee | None:
    """The employee record of the person using the panel (None when they have none)."""
    if ctx is None or ctx.user is None:
        return None
    cache = ctx.__dict__.setdefault("_hr_me", {})
    if "employee" not in cache:
        cache["employee"] = employee_for_user(ctx.db, _me(ctx))
    return cache["employee"]


def user_options(ctx: Any) -> dict[str, str]:
    """Panel users, for "Logs in as"."""
    auth = ctx.panel.auth
    if auth.user_model is None:
        return {}
    users = ctx.db.scalars(select(auth.user_model).limit(500)).all()
    return {auth.user_id(u): auth.display_name(u) for u in users}


def user_name(ctx: Any, user_id: str | None) -> str | None:
    if not user_id or ctx is None:
        return None
    cache = ctx.__dict__.setdefault("_hr_user_names", {})
    if user_id not in cache:
        user = ctx.panel.auth.find_by_id(ctx.db, user_id)
        cache[user_id] = ctx.panel.auth.display_name(user) if user is not None else None
    return cache[user_id]


def employee_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(Employee).where(Employee.status != "left")
                          .order_by(Employee.first_name, Employee.last_name).limit(2000)).all()
    return {str(e.id): f"{e.name} ({e.code})" if e.code else e.name for e in rows}


def _all_employee_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(Employee).order_by(Employee.first_name, Employee.last_name).limit(2000)).all()
    return {str(e.id): e.name for e in rows}


def leave_type_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(LeaveType).where(LeaveType.is_active.is_(True))
                          .order_by(LeaveType.sort, LeaveType.name)).all()
    return {str(t.id): t.name for t in rows}


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _hhmm(state: Any) -> Any:
    return state.strftime("%H:%M") if isinstance(state, dt.time) else state


def _days(state: Any) -> Any:
    return f"{state:g}" if isinstance(state, (int, float)) else state


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ====================================================================== employees
class AttendanceRelationManager(RelationManager):
    relationship = "attendance"
    icon = "calendar-check"

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("date").date().sortable(),
                TextColumn("status").badge().format_state_using(_label(ATTENDANCE_STATUSES))
                .color(_color(ATTENDANCE_STATUSES)),
                TextColumn("check_in").label("In").placeholder("—").format_state_using(_hhmm),
                TextColumn("check_out").label("Out").placeholder("—").format_state_using(_hhmm),
                TextColumn("hours").placeholder("—"),
                TextColumn("note").placeholder("—").limit(40),
            ])
            .default_sort("date", "desc")
        )


class LeaveRelationManager(RelationManager):
    relationship = "leave_requests"
    title = "Leave"
    icon = "plane"

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("leave_type.name").label("Type").badge()
                .color(lambda record: record.leave_type.color if record.leave_type else "gray"),
                TextColumn("start_date").label("From").date().sortable(),
                TextColumn("end_date").label("To").date(),
                TextColumn("days").format_state_using(_days),
                TextColumn("status").badge().format_state_using(_label(LEAVE_STATUSES)).color(_color(LEAVE_STATUSES)),
                TextColumn("reason").placeholder("—").limit(40),
            ])
            .default_sort("start_date", "desc")
        )


def mark_attendance_bulk_action() -> BulkAction:
    def run(records, data, db, ctx):
        day = _date(data.get("date")) or dt.date.today()
        for employee in records:
            mark_attendance(db, employee, day, data["status"], note=data.get("note") or None)
        db.commit()

    return (
        BulkAction("mark_attendance").label("Mark attendance").icon("calendar-check").color("success")
        .form([
            DatePicker("date").default(lambda: dt.date.today()).required(),
            Select("status").options(_labels(ATTENDANCE_STATUSES)).default("present").required().native(),
            TextInput("note").max_length(255),
        ])
        .action(run)
        .success_notification_title("Attendance saved")
    )


class EmployeeResource(Resource):
    model = Employee
    slug = "employees"
    icon = "users"
    navigation_group = "HR"
    navigation_sort = 1
    description = "Your team: job, department, manager, contact details and documents."
    global_search_attributes = ["code", "first_name", "last_name", "email", "phone"]
    record_title_attribute = "name"
    relations = [AttendanceRelationManager, LeaveRelationManager]
    widgets = [HRStats]

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Group([
                Section("Person").icon("user").schema([
                    TextInput("first_name").required().max_length(100),
                    TextInput("last_name").max_length(100),
                    TextInput("email").email().max_length(255).prefix_icon("mail"),
                    TextInput("phone").tel().max_length(40).prefix_icon("phone"),
                    DatePicker("birth_date").label("Date of birth"),
                    Select("gender").options(GENDERS).native(),
                    TextInput("emergency_contact").max_length(200).column_span("full")
                    .placeholder("Name, relation, phone"),
                    Textarea("address").rows(2).column_span("full"),
                ]),
                Section("Job").icon("briefcase").schema([
                    TextInput("job_title").max_length(100).placeholder("Sales executive"),
                    Select("department_id").label("Department").relationship("department", "name").preload(),
                    Select("manager_id").label("Manager").options(employee_options).searchable()
                    .helper_text("Approves this person's leave. Empty: the head of the department."),
                    Select("employment_type").label("Type").options(EMPLOYMENT_TYPES).default("full_time").required(),
                    DatePicker("joined_on").label("Joined on").default(lambda: dt.date.today()),
                    DatePicker("left_on").label("Left on"),
                    TextInput("salary").label("Monthly salary").numeric().min_value(0),
                ]),
                Section("More").icon("folder").collapsible().schema([
                    KeyValue("details").label("Other details").key_label("Name").value_label("Value")
                    .column_span("full").helper_text("Bank account, PAN, Aadhaar, blood group..."),
                    FileUpload("documents").multiple().directory("hr/documents").max_size(10240).max_files(10)
                    .column_span("full"),
                    Textarea("notes").rows(3).column_span("full"),
                ]),
            ]).columns(1).column_span(2),
            Section("Status").icon("badge-check").column_span(1).columns(1).schema([
                FileUpload("photo").avatar().directory("hr/photos"),
                TextInput("code").label("Employee code").max_length(30).unique()
                .helper_text("Empty: made for you, like EMP-0007."),
                Select("status").options(_labels(EMPLOYEE_STATUSES)).default("active").required(),
                Select("user_id").label("Logs in as").options(user_options).searchable()
                .helper_text("The panel user who checks in and asks for leave as this person."),
                TextInput("biometric_id").label("Machine ID").max_length(50).unique()
                .helper_text("Their user ID / PIN on the biometric machine. Punches become attendance."),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Group([
                Section("Leave left this year").icon("plane").columns(1).schema([
                    Placeholder("balance").hidden_label().content(lambda record, ctx: balance_html(ctx.db, record)),
                ]),
                Section("Attendance this month").icon("calendar-check").columns(1).schema([
                    Placeholder("month").hidden_label().content(lambda record, ctx: month_html(ctx.db, record)),
                ]),
            ]).columns(1).column_span(2),
            Group([
                Section("Job").icon("briefcase").columns(1).schema([
                    TextEntry("code").label("Code").copyable().inline_label(),
                    TextEntry("status").badge().inline_label().format_state_using(_label(EMPLOYEE_STATUSES))
                    .color(_color(EMPLOYEE_STATUSES)),
                    TextEntry("job_title").label("Job").placeholder("—").inline_label(),
                    TextEntry("department.name").label("Department").placeholder("—").inline_label(),
                    TextEntry("manager.name").label("Manager").placeholder("—").inline_label(),
                    TextEntry("employment_type").label("Type").inline_label()
                    .format_state_using(lambda state: EMPLOYMENT_TYPES.get(state, state)),
                    TextEntry("joined_on").label("Joined").date().placeholder("—").inline_label(),
                ]),
                Section("Contact").icon("user").columns(1).schema([
                    TextEntry("email").copyable().placeholder("—").inline_label(),
                    TextEntry("phone").copyable().placeholder("—").inline_label(),
                    TextEntry("birth_date").label("Birthday").date().placeholder("—").inline_label(),
                    TextEntry("emergency_contact").label("Emergency").placeholder("—").inline_label(),
                ]),
            ]).columns(1).column_span(1),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page == "view":
            return [ActionGroup([EditAction(), DeleteAction()]).button()]
        return super().header_actions(ctx, page, record)

    @classmethod
    def after_create(cls, record, db, ctx):
        give_code(db, record)
        link_punches(db, record)
        plugin = _plugin(ctx)
        if plugin is not None:
            for fn in list(plugin.employee_listeners.values()):
                fn(db, record)

    @classmethod
    def after_save(cls, record, db):
        link_punches(db, record)  # punches that came in before the machine ID was set

    @classmethod
    def table(cls, table):
        def status_tab(key):
            return lambda query, model: query.where(model.status == key)

        return (
            table.columns([
                TextColumn("code").label("Code").searchable().sortable().copyable(),
                TextColumn("first_name").label("Name").weight("medium").sortable()
                .searchable(columns=["first_name", "last_name"])
                .state(lambda record: record.name).description(lambda record: record.job_title),
                TextColumn("department.name").label("Department").placeholder("—").badge()
                .color(lambda record: record.department.color if record.department else "gray"),
                TextColumn("manager.name").label("Manager").placeholder("—").toggleable(),
                TextColumn("status").badge().sortable().format_state_using(_label(EMPLOYEE_STATUSES))
                .color(_color(EMPLOYEE_STATUSES)),
                TextColumn("employment_type").label("Type").toggleable()
                .format_state_using(lambda state: EMPLOYMENT_TYPES.get(state, state)),
                TextColumn("email").searchable().toggleable(hidden_by_default=True),
                TextColumn("phone").searchable().toggleable(hidden_by_default=True),
                TextColumn("joined_on").label("Joined").date().sortable().toggleable(),
            ])
            .filters([
                SelectFilter("department_id").label("Department").relationship("department", "name"),
                SelectFilter("employment_type").label("Type").options(EMPLOYMENT_TYPES),
                DateFilter("joined_on").label("Joined on"),
            ])
            .tabs([
                ListTab("current").label("Current").query(lambda query, model: query.where(model.status != "left")),
                ListTab("probation").label("On probation").badge(color="info").query(status_tab("probation")),
                ListTab("notice").label("On notice").badge(color="warning").query(status_tab("notice")),
                ListTab("left").label("Left").query(status_tab("left")),
                ListTab("all").label("All"),
            ])
            .actions([ActionGroup([ViewAction(), EditAction(), DeleteAction()])])
            .bulk_actions([mark_attendance_bulk_action(), ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: EmployeeResource.get_url(ctx, "view", record))
            .default_sort("first_name", "asc")
        )


class DepartmentResource(Resource):
    model = Department
    slug = "departments"
    icon = "building-2"
    navigation_group = "HR"
    navigation_sort = 2
    description = "Teams like Sales or Accounts, with a head who approves leave."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Sales"),
            TextInput("code").max_length(20).placeholder("SAL"),
            Select("head_id").label("Head").options(employee_options).searchable(),
            Select("color").options(COLORS).default("gray").required(),
            TextInput("description").max_length(255).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "gray").searchable()
                .description(lambda record: record.description),
                TextColumn("code").placeholder("—"),
                TextColumn("head.name").label("Head").placeholder("—"),
                TextColumn("people").label("People")
                .state(lambda record: sum(1 for e in record.employees if e.status != "left")),
            ])
            .actions([EditAction(), DeleteAction()])
            .default_sort("name", "asc")
        )


# ====================================================================== attendance
def _day_taken(value, get, record, db):
    employee_id, day = _int(get("employee_id")), _date(value)
    if not employee_id or day is None:
        return True
    row = db.scalars(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.date == day)).first()
    if row is not None and (record is None or row.id != record.id):
        return "This person already has attendance for that day. Edit it instead."
    return True


def check_in_action() -> Action:
    def run(data, db, ctx):
        check_in(db, my_employee(ctx), remote=bool(data.get("remote")))
        db.commit()

    def visible(ctx):
        me = my_employee(ctx)
        if me is None:
            return False
        row = today_row(ctx.db, me)
        return row is None or row.check_in is None

    return (
        Action("check_in").label("Check in").icon("log-in").color("success")
        .visible(visible)
        .form([Toggle("remote").label("Working from home today")])
        .modal_submit_action_label("Check in")
        .action(run)
        .success_notification_title("Checked in. Have a good day!")
    )


def check_out_action() -> Action:
    def run(db, ctx):
        check_out(db, my_employee(ctx))
        db.commit()

    def visible(ctx):
        me = my_employee(ctx)
        if me is None:
            return False
        row = today_row(ctx.db, me)
        return row is not None and row.check_in is not None and row.check_out is None

    return (
        Action("check_out").label("Check out").icon("log-out").color("gray")
        .visible(visible)
        .requires_confirmation()
        .modal_description("End your day now?")
        .action(run)
        .success_notification_title("Checked out")
    )


class AttendanceResource(Resource):
    model = Attendance
    slug = "attendance"
    icon = "calendar-check"
    navigation_group = "HR"
    navigation_sort = 3
    label = "Attendance"
    plural_label = "Attendance"
    description = "Who came in, when, and for how long. People check in with one button."

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Select("employee_id").label("Employee").options(employee_options).searchable().required(),
            DatePicker("date").default(lambda: dt.date.today()).required().rule(_day_taken),
            Select("status").options(_labels(ATTENDANCE_STATUSES)).default("present").required(),
            Group([
                TimePicker("check_in").label("In"),
                TimePicker("check_out").label("Out"),
            ]).columns(2),
            TextInput("note").max_length(255).column_span("full"),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page in ("list", "index"):
            return [check_in_action().button(), check_out_action().button(), *actions]
        return actions

    @classmethod
    def after_create(cls, record, db):
        fill_attendance(db, record)

    @classmethod
    def after_save(cls, record, db):
        fill_attendance(db, record)

    @classmethod
    def table(cls, table):
        today = dt.date.today
        return (
            table.columns([
                TextColumn("date").date().sortable(),
                TextColumn("employee.first_name").label("Employee").weight("medium")
                .state(lambda record: record.employee.name if record.employee else None)
                .description(lambda record: record.employee.code if record.employee else None),
                TextColumn("status").badge().sortable().format_state_using(_label(ATTENDANCE_STATUSES))
                .color(_color(ATTENDANCE_STATUSES)),
                TextColumn("check_in").label("In").placeholder("—").format_state_using(_hhmm)
                .color(lambda record: "danger" if record.is_late else None),
                TextColumn("check_out").label("Out").placeholder("—").format_state_using(_hhmm),
                TextColumn("hours").placeholder("—").sortable(),
                TextColumn("note").placeholder("—").limit(40).toggleable(),
                TextColumn("source").badge().color("gray").toggleable(hidden_by_default=True)
                .format_state_using(lambda state: SOURCES.get(state, state)),
            ])
            .filters([
                SelectFilter("employee_id").label("Employee").options(_all_employee_options),
                SelectFilter("status").options(_labels(ATTENDANCE_STATUSES)).multiple(),
                TernaryFilter("is_late").label("Late"),
                DateFilter("date"),
            ])
            .tabs([
                ListTab("today").label("Today").query(lambda query, model: query.where(model.date == today())),
                ListTab("week").label("This week").query(lambda query, model: query.where(
                    model.date >= today() - dt.timedelta(days=today().weekday()))),
                ListTab("late").label("Late").query(lambda query, model: query.where(model.is_late.is_(True))),
                ListTab("absent").label("Absent").query(lambda query, model: query.where(model.status == "absent")),
                ListTab("all").label("All"),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .default_sort("date", "desc")
        )


# ====================================================================== leave
def _leave_rule(value, get, record, db):
    """Run the leave checks (dates, weekends, clashes, days left) while the form is checked."""
    start, end = _date(get("start_date")), _date(value)
    employee_id = _int(get("employee_id"))
    if start is None or end is None or not employee_id:
        return True
    probe = LeaveRequest(employee_id=employee_id, leave_type_id=_int(get("leave_type_id")), start_date=start,
                         end_date=end, half_day=bool(get("half_day")), status="pending")
    probe.id = record.id if record is not None else None
    try:
        with db.no_autoflush:
            check_leave(db, probe)
    except LeaveError as exc:
        return str(exc)
    finally:
        if probe in db:
            db.expunge(probe)
    return True


def _days_preview(get, db) -> str:
    start = _date(get("start_date"))
    end = _date(get("end_date")) or start
    if start is None or end is None or end < start:
        return "—"
    return f"{count_days(db, start, end, bool(get('half_day'))):g} working day(s)"


def decide_action(status: str) -> Action:
    label, color = {"approved": ("Approve", "success"), "rejected": ("Reject", "danger"),
                    "cancelled": ("Cancel", "gray")}[status]
    icon = {"approved": "check", "rejected": "x", "cancelled": "ban"}[status]

    def run(record, data, db, ctx):
        try:
            decide_leave(db, record, status, user_id=_me(ctx), note=data.get("note"), ctx=ctx)
        except LeaveError as exc:
            from tungsten import Notification

            Notification("Can't approve").body(str(exc)).danger().send(ctx)
            db.rollback()
            return
        db.commit()

    def visible(record, ctx):
        if record is None:
            return False
        if status == "cancelled":
            return record.status in ("pending", "approved")
        mine = my_employee(ctx)
        return record.status == "pending" and (mine is None or mine.id != record.employee_id)

    action = (
        Action(status[:-1] if status != "cancelled" else "cancel").label(label).icon(icon).color(color)
        .visible(visible)
        .action(run)
        .success_notification_title({"approved": "Leave approved", "rejected": "Leave rejected",
                                     "cancelled": "Leave cancelled"}[status])
    )
    if status == "rejected":
        action = action.form([Textarea("note").label("Why").rows(3).max_length(255)])
    else:
        action = action.requires_confirmation()
    return action


class LeaveRequestResource(Resource):
    model = LeaveRequest
    slug = "leave-requests"
    icon = "plane"
    navigation_group = "HR"
    navigation_sort = 4
    label = "Leave request"
    description = "Ask for leave, and approve or reject it. Approved days show in attendance."

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(LeaveRequest)
                         .where(LeaveRequest.status == "pending")) or None

    navigation_badge_color = "warning"

    @classmethod
    def form(cls, form):
        def default_employee(ctx):
            me = my_employee(ctx)
            return str(me.id) if me is not None else None

        return form.columns(2).schema([
            Select("employee_id").label("Employee").options(employee_options).searchable().required()
            .default(default_employee),
            Select("leave_type_id").label("Leave type").options(leave_type_options).required(),
            DatePicker("start_date").label("From").default(lambda: dt.date.today()).required().live(),
            DatePicker("end_date").label("To").required().default(lambda: dt.date.today())
            .min_date(lambda get: get("start_date")).rule(_leave_rule).live(),
            Toggle("half_day").label("Half day").helper_text("Only the first day, half.").live(),
            Placeholder("count").label("Days").content(_days_preview),
            Textarea("reason").rows(3).max_length(2000).column_span("full"),
        ])

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(2).schema([
            Section("Leave").icon("plane").columns(1).schema([
                TextEntry("employee.name").label("Employee").inline_label(),
                TextEntry("leave_type.name").label("Type").badge().inline_label()
                .color(lambda record: record.leave_type.color if record.leave_type else "gray"),
                TextEntry("start_date").label("From").date().inline_label(),
                TextEntry("end_date").label("To").date().inline_label(),
                TextEntry("days").inline_label().format_state_using(_days),
                TextEntry("reason").placeholder("—"),
            ]),
            Section("Decision").icon("check").columns(1).schema([
                TextEntry("status").badge().inline_label().format_state_using(_label(LEAVE_STATUSES))
                .color(_color(LEAVE_STATUSES)),
                TextEntry("reviewed_by").label("By").placeholder("—").inline_label()
                .state(lambda record, ctx: user_name(ctx, record.reviewed_by)),
                TextEntry("reviewed_at").label("On").datetime().placeholder("—").inline_label(),
                TextEntry("review_note").label("Note").placeholder("—"),
                Placeholder("balance").label("Leave left").content(
                    lambda record, ctx: balance_html(ctx.db, record.employee, record.start_date.year)),
            ]),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page == "view":
            return [decide_action("approved").button(), decide_action("rejected").button(),
                    decide_action("cancelled").button(),
                    ActionGroup([EditAction().visible(lambda record: record.status == "pending"),
                                 DeleteAction()]).button()]
        return super().header_actions(ctx, page, record)

    @classmethod
    def after_create(cls, record, db, ctx):
        record.status = "pending"
        record.days = count_days(db, record.start_date, record.end_date, record.half_day)
        if record.half_day:
            record.end_date = record.start_date
        db.flush()
        leave_requested(db, record, ctx)

    @classmethod
    def after_save(cls, record, db):
        if record.half_day:
            record.end_date = record.start_date
        record.days = count_days(db, record.start_date, record.end_date, record.half_day)

    @classmethod
    def table(cls, table):
        def bulk(status):
            def run(records, db, ctx):
                for r in records:
                    if r.status == "pending":
                        try:
                            decide_leave(db, r, status, user_id=_me(ctx), ctx=ctx)
                        except LeaveError:
                            continue
                db.commit()
            return run

        def mine(query, model, ctx):
            me = my_employee(ctx)
            return query.where(model.employee_id == me.id) if me is not None else query.where(False)

        return (
            table.columns([
                TextColumn("employee.first_name").label("Employee").weight("medium")
                .state(lambda record: record.employee.name if record.employee else None)
                .description(lambda record: record.employee.department.name
                             if record.employee and record.employee.department else None),
                TextColumn("leave_type.name").label("Type").badge()
                .color(lambda record: record.leave_type.color if record.leave_type else "gray"),
                TextColumn("start_date").label("From").date().sortable(),
                TextColumn("end_date").label("To").date().sortable(),
                TextColumn("days").format_state_using(_days).sortable(),
                TextColumn("status").badge().sortable().format_state_using(_label(LEAVE_STATUSES))
                .color(_color(LEAVE_STATUSES)),
                TextColumn("reason").limit(50).placeholder("—").toggleable(hidden_by_default=True),
                TextColumn("created_at").label("Asked").since().sortable().toggleable(),
            ])
            .filters([
                SelectFilter("employee_id").label("Employee").options(_all_employee_options),
                SelectFilter("leave_type_id").label("Type").relationship("leave_type", "name"),
                SelectFilter("status").options(_labels(LEAVE_STATUSES)).multiple(),
                DateFilter("start_date").label("From"),
            ])
            .tabs([
                ListTab("pending").label("To approve").badge(color="warning")
                .query(lambda query, model: query.where(model.status == "pending")),
                ListTab("upcoming").label("Upcoming").query(lambda query, model: query.where(
                    model.status == "approved", model.end_date >= dt.date.today())),
                ListTab("mine").label("My leave").query(mine),
                ListTab("all").label("All"),
            ])
            .actions([
                decide_action("approved").icon_button(),
                decide_action("rejected").icon_button(),
                ActionGroup([ViewAction(), EditAction().visible(lambda record: record.status == "pending"),
                             decide_action("cancelled"), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("approve_all").label("Approve").icon("check").color("success")
                .action(bulk("approved")).success_notification_title("Leave approved"),
                BulkAction("reject_all").label("Reject").icon("x").color("danger")
                .action(bulk("rejected")).success_notification_title("Leave rejected"),
                ExportBulkAction(),
                DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: LeaveRequestResource.get_url(ctx, "view", record))
            .default_sort("created_at", "desc")
        )


class LeaveTypeResource(Resource):
    model = LeaveType
    slug = "leave-types"
    icon = "tags"
    navigation_group = "HR"
    navigation_sort = 50
    label = "Leave type"
    description = "Casual, Sick, Earned... and how many days a year each person gets."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Casual leave"),
            TextInput("days_per_year").label("Days a year").numeric().min_value(0)
            .helper_text("Empty: no limit."),
            Select("color").options(COLORS).default("info").required(),
            TextInput("sort").label("Order").integer().default(0),
            Toggle("is_paid").label("Paid").default(True),
            Toggle("allow_negative").label("Allow more than the days left"),
            Toggle("is_active").label("In use").default(True),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "gray"),
                TextColumn("days_per_year").label("Days a year").placeholder("No limit"),
                ToggleColumn("is_paid").label("Paid"),
                ToggleColumn("is_active").label("In use"),
                TextColumn("sort").label("Order").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .reorderable("sort")
            .default_sort("sort", "asc")
        )


class HolidayResource(Resource):
    model = Holiday
    slug = "holidays"
    icon = "party-popper"
    navigation_group = "HR"
    navigation_sort = 51
    description = "Days off for everyone. They don't count as leave days."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Diwali"),
            DatePicker("date").required().unique(),
            Toggle("is_optional").label("Optional holiday")
            .helper_text("People may still work. Leave on this day counts."),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("date").date().sortable().description(lambda record: f"{record.date:%A}"),
                TextColumn("name").weight("medium").searchable(),
                ToggleColumn("is_optional").label("Optional"),
            ])
            .tabs([
                ListTab("upcoming").label("Upcoming")
                .query(lambda query, model: query.where(model.date >= dt.date.today())),
                ListTab("all").label("All"),
            ])
            .actions([EditAction(), DeleteAction()])
            .default_sort("date", "asc")
        )


# ====================================================================== biometric
def pull_action() -> Action:
    def run(record, db, ctx):
        from tungsten import Notification

        try:
            new, read = pull_device(db, record)
        except Exception as exc:  # noqa: BLE001 - machine off, wrong IP, pyzk missing...
            db.rollback()
            Notification("Could not fetch punches").body(str(exc)[:300]).danger().send(ctx)
            return
        db.commit()
        Notification("Punches fetched").body(f"{new} new of {read} on the machine.").success().send(ctx)

    return (
        Action("pull").label("Fetch punches").icon("download").color("primary")
        .visible(lambda record: record is not None and bool(record.ip_address) and record.is_active)
        .action(run)
    )


class BiometricDeviceResource(Resource):
    model = BiometricDevice
    slug = "biometric-devices"
    icon = "fingerprint"
    navigation_group = "HR"
    navigation_sort = 60
    label = "Biometric machine"
    description = ("Fingerprint and face machines. They send punches to /iclock/cdata on your site, "
                   "or the panel fetches them over the office network.")
    simple = True

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(BiometricDevice)
                         .where(BiometricDevice.is_active.is_(False))) or None

    navigation_badge_color = "warning"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Head office gate"),
            TextInput("serial_number").label("Serial number (SN)").max_length(64).unique()
            .helper_text("Needed when the machine sends punches (ADMS / Cloud server)."),
            TextInput("ip_address").label("IP address").max_length(64).placeholder("192.168.1.201")
            .helper_text("Only to fetch punches over the office network."),
            TextInput("port").integer().default(4370),
            TextInput("password").label("Comm key").integer().default(0),
            Toggle("is_active").label("Take punches from this machine").default(True),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable()
                .description(lambda record: record.serial_number),
                TextColumn("ip_address").label("IP").placeholder("—"),
                ToggleColumn("is_active").label("On"),
                TextColumn("last_seen_at").label("Last seen").since().placeholder("Never"),
                TextColumn("last_punch_at").label("Last punch").since().placeholder("—"),
            ])
            .actions([pull_action().icon_button(), EditAction(), DeleteAction()])
            .default_sort("name", "asc")
        )


class PunchImporter(Importer):
    """CSV / Excel of punches: who (machine ID or employee code) and when."""

    model = Punch
    columns = [
        ImportColumn("person").label("Employee").required().guess(
            ["employee code", "code", "machine id", "user id", "userid", "pin", "emp code", "enroll no", "id"])
        .example("EMP-0002"),
        ImportColumn("punched_at").label("Time").required().guess(
            ["punch time", "datetime", "date time", "timestamp", "log time", "punch"])
        .cast_state_using(lambda state: parse_time(state)).example("2026-11-02 09:12:00"),
    ]

    @classmethod
    def resolve_record(cls, ctx, data):
        return db_punch(ctx.db, data) or Punch()

    @classmethod
    def fill_record(cls, ctx, record, data):
        if record.id is not None:
            return  # the same punch again: nothing to do
        record.person = str(data["person"]).strip()[:50]
        record.punched_at = data["punched_at"]
        record.source = "import"
        employee = find_employee(ctx.db, record.person)
        record.employee_id = employee.id if employee is not None else None

    @classmethod
    def before_save(cls, ctx, record, data):
        if record.id is None and record.employee_id is not None:
            apply_punch(ctx.db, record.employee_id, record.punched_at)


def db_punch(db, data):
    person = str(data.get("person") or "").strip()[:50]
    at = data.get("punched_at")
    if not person or at is None:
        return None
    return db.scalars(select(Punch).where(Punch.person == person, Punch.punched_at == at)).first()


class PunchResource(Resource):
    """Every punch from machines, the API and files. Attendance is made from these."""

    model = Punch
    slug = "punches"
    icon = "scan-line"
    navigation_group = "HR"
    navigation_sort = 61
    description = "Raw punches from biometric machines, the API and files. The first and last of a day make attendance."
    pages = ("index",)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [ImportAction(PunchImporter).label("Upload punches")
                .modal_heading("Upload punches")
                .modal_description("A CSV or Excel file from any machine: one row per punch, "
                                   "with the machine ID or employee code, and the time.")]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("punched_at").label("Time").datetime().sortable(),
                TextColumn("employee.first_name").label("Employee").placeholder("Not matched")
                .state(lambda record: record.employee.name if record.employee else None)
                .description(lambda record: f"ID {record.person}"),
                TextColumn("device.name").label("Machine").placeholder("—"),
                TextColumn("source").badge().color("gray")
                .format_state_using(lambda state: PUNCH_SOURCES.get(state, state)),
            ])
            .filters([
                SelectFilter("employee_id").label("Employee").options(_all_employee_options),
                SelectFilter("source").options(PUNCH_SOURCES),
                DateFilter("punched_at").label("Day"),
            ])
            .tabs([
                ListTab("all").label("All"),
                ListTab("unmatched").label("Not matched").badge(color="warning")
                .query(lambda query, model: query.where(model.employee_id.is_(None))),
            ])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("punched_at", "desc")
        )


RESOURCES = [EmployeeResource, DepartmentResource, AttendanceResource, LeaveRequestResource, LeaveTypeResource,
             HolidayResource, BiometricDeviceResource, PunchResource]

__all__ = [
    "RESOURCES",
    "AttendanceResource",
    "BiometricDeviceResource",
    "DepartmentResource",
    "EmployeeResource",
    "HolidayResource",
    "LeaveRequestResource",
    "LeaveTypeResource",
    "PunchResource",
    "check_in_action",
    "check_out_action",
    "decide_action",
    "my_employee",
]
