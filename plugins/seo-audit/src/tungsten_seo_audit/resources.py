"""The "SEO audits" screens: the list of audits, one audit's report, and the stats on top."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from tungsten import Notification, RelationManager, Resource, Stat, StatsOverviewWidget
from tungsten.actions import Action, DeleteAction, DeleteBulkAction, ViewAction
from tungsten.forms import Grid, Section, TextInput, Toggle
from tungsten.infolists import KeyValueEntry, TextEntry
from tungsten.tables import SelectFilter, TextColumn

from .checks import CATEGORIES, CHECKS, SEVERITIES
from .models import SeoAudit

SEVERITY_COLORS = {"error": "danger", "warning": "warning", "notice": "info"}
STATUS_COLORS = {"running": "info", "done": "success", "failed": "danger"}


def score_color(score: Any) -> str:
    if score is None:
        return "gray"
    return "success" if score >= 90 else "warning" if score >= 50 else "danger"


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("seo-audit")


def audit_form() -> list:
    return [
        TextInput("url").label("Site address").url().required().placeholder("https://www.example.com")
        .default(lambda ctx: _plugin(ctx).default_url(ctx))
        .helper_text("The audit starts here and follows the links and the sitemap on the same site."),
        Grid(2).schema([
            TextInput("max_pages").label("Pages to check").numeric().integer().min_value(1).max_value(500)
            .default(lambda ctx: _plugin(ctx).max_pages),
            Toggle("check_external").label("Check links to other sites").default(True)
            .helper_text("Finds broken outgoing links. Makes the audit a little slower."),
        ]),
    ]


def start(ctx: Any, db: Any, url: str, max_pages: int, check_external: bool = True) -> SeoAudit:
    audit = _plugin(ctx).start_audit(db, url, max_pages, check_external,
                                     user_id=ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None)
    if audit.status == "running":
        Notification("Audit started").body("Pages are being checked. The report fills in as it goes.").info().send(ctx)
    elif audit.status == "failed":
        Notification("Audit failed").body(audit.error or "").danger().send(ctx)
    else:
        Notification("Audit done").body(f"Score {audit.score}/100, {audit.errors} errors, "
                                        f"{audit.warnings} warnings.").success().send(ctx)
    ctx.redirect(ctx.url("seo-audits", audit.id))
    return audit


def new_audit_action() -> Action:
    return (
        Action("audit").label("New audit").icon("search-check").color("primary")
        .modal_heading("Audit a site").modal_width("lg")
        .modal_description("Checks titles, descriptions, headings, images, links, speed, robots.txt, sitemap, "
                           "social tags, structured data and AI search readiness.")
        .form(audit_form()).modal_submit_action_label("Start audit")
        .action(lambda data, ctx, db: start(ctx, db, data["url"], int(data.get("max_pages") or 25),
                                            bool(data.get("check_external", True))))
    )


def rerun_action() -> Action:
    return (
        Action("rerun").label("Run again").icon("refresh-cw").color("gray")
        .visible(lambda record: record is not None and record.status != "running")
        .requires_confirmation().modal_heading("Run this audit again?")
        .modal_description("A new audit of the same site starts. This one stays in the history.")
        .action(lambda record, ctx, db: start(ctx, db, record.url, record.max_pages))
    )


class SeoStats(StatsOverviewWidget):
    columns = 4
    lazy = False

    @classmethod
    def stats(cls, db, ctx):
        last = db.scalars(select(SeoAudit).where(SeoAudit.status == "done")
                          .order_by(SeoAudit.started_at.desc(), SeoAudit.id.desc()).limit(8)).all()
        if not last:
            return [Stat("SEO score", "—").icon("gauge").color("gray").describe("Run your first audit")]
        a = last[0]
        trend = [x.score or 0 for x in reversed(last)]
        diff = (a.score or 0) - (last[1].score or 0) if len(last) > 1 else 0
        score = Stat("SEO score", f"{a.score}/100").icon("gauge").color(score_color(a.score)).chart(trend) \
            .describe(a.url).url(ctx.url("seo-audits", a.id))
        if diff:
            score.trend(f"{abs(diff)} points", "up" if diff > 0 else "down")
        return [
            score,
            Stat("Errors", str(a.errors)).icon("circle-x").color("danger" if a.errors else "success")
            .describe("Fix these first"),
            Stat("Warnings", str(a.warnings)).icon("triangle-alert").color("warning" if a.warnings else "success"),
            Stat("Pages checked", str(a.pages_count)).icon("files").color("info")
            .describe(f"{a.notices} notices"),
        ]


class IssuesRelationManager(RelationManager):
    relationship = "issues"
    title = "Issues"
    label = "issue"
    icon = "list-checks"

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("severity").badge().colors({c: s for s, c in SEVERITY_COLORS.items()})
                .format_state_using(lambda state: SEVERITIES.get(state, state)).sortable(),
                TextColumn("message").label("Issue").wrap().searchable().weight("medium")
                .description(lambda record: record.tip),
                TextColumn("page_url").label("Page").wrap().limit(80).placeholder("Whole site").searchable()
                .url(lambda record: record.page_url, open_in_new_tab=True),
                TextColumn("category").badge().color("gray"),
            ])
            .filters([
                SelectFilter("severity").options(SEVERITIES).multiple(),
                SelectFilter("category").options({c: c for c in CATEGORIES}).multiple(),
                SelectFilter("check").label("Check").options(
                    {k: k.replace("_", " ").capitalize() for k in sorted(CHECKS)}),
            ])
            .default_sort("id", "asc")
            .empty_state("No issues", "Nothing to fix here.", "circle-check")
        )


class PagesRelationManager(RelationManager):
    relationship = "pages"
    title = "Pages"
    label = "page"
    icon = "files"

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("url").label("Page").wrap().limit(90).searchable().weight("medium")
                .description(lambda record: record.title).url(lambda record: record.url, open_in_new_tab=True),
                TextColumn("score").badge().color(lambda state: score_color(state)).sortable(),
                TextColumn("status_code").label("Status").badge()
                .color(lambda state: "success" if state == 200 else "danger" if not state or state >= 400
                       else "warning").placeholder("Failed"),
                TextColumn("issues_count").label("Issues").sortable(),
                TextColumn("words").sortable().toggleable(),
                TextColumn("load_ms").label("Load").suffix(" ms").sortable(),
                TextColumn("size_kb").label("Size").suffix(" KB").sortable().toggleable(),
            ])
            .default_sort("score", "asc")
        )


class SeoAuditResource(Resource):
    model = SeoAudit
    slug = "seo-audits"
    label = "SEO audit"
    icon = "search-check"
    navigation_group = "SEO"
    navigation_sort = 80
    description = "Check your site for SEO problems, with a score and a tip for each fix."
    record_title_attribute = "url"
    pages = ("index", "view")
    relations = [IssuesRelationManager, PagesRelationManager]
    widgets = [SeoStats]

    @classmethod
    def can(cls, ctx, ability, record=None):
        if ability in ("create", "update", "edit"):
            return False
        return super().can(ctx, ability, record)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page == "view":
            return [rerun_action(), DeleteAction()]
        return [new_audit_action()]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("url").label("Site").weight("medium").searchable()
                .description(lambda record: record.error),
                TextColumn("score").badge().color(lambda state: score_color(state))
                .format_state_using(lambda state: f"{state}/100" if state is not None else "—").sortable(),
                TextColumn("status").badge().colors({c: s for s, c in STATUS_COLORS.items()})
                .format_state_using(lambda state: state.capitalize()),
                TextColumn("pages_count").label("Pages"),
                TextColumn("errors").color(lambda state: "danger" if state else None),
                TextColumn("warnings").color(lambda state: "warning" if state else None),
                TextColumn("started_at").label("When").since().sortable(),
            ])
            .filters([SelectFilter("status").options({s: s.capitalize() for s in STATUS_COLORS})])
            .actions([ViewAction(), rerun_action().icon_button(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .empty_state("No audits yet", "Press New audit to check your site.", "search-check")
            .empty_state_actions([new_audit_action()])
            .default_sort("started_at", "desc")
            .poll("5s")
        )

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Section("Report").column_span(2).columns(3).schema([
                TextEntry("url").label("Site").weight("semibold").column_span("full")
                .url(lambda record: record.url, open_in_new_tab=True),
                TextEntry("score").badge().size("lg").color(lambda state: score_color(state))
                .format_state_using(lambda state: f"{state}/100" if state is not None else "Checking..."),
                TextEntry("status").badge().colors({c: s for s, c in STATUS_COLORS.items()})
                .format_state_using(lambda state: state.capitalize()),
                TextEntry("pages_count").label("Pages checked"),
                TextEntry("errors").color("danger"),
                TextEntry("warnings").color("warning"),
                TextEntry("notices").color("info"),
                TextEntry("error").label("Note").color("danger").column_span("full")
                .visible(lambda record: bool(record and record.error)),
            ]),
            Section("Score by area").column_span(1).schema([
                KeyValueEntry("categories").hidden_label().key_label("Area").value_label("Score")
                .column_span("full"),
                TextEntry("started_at").label("Started").datetime(),
                TextEntry("finished_at").label("Finished").datetime(),
            ]),
        ])
