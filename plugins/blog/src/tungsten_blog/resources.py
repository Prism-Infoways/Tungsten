"""Admin screens of the blog plugin: Posts (with the SEO / GEO / AEO score), Categories, Tags and Authors."""

from __future__ import annotations

import datetime as dt
from html import escape
from typing import Any

from markupsafe import Markup
from sqlalchemy import func, select

from tungsten import Resource
from tungsten.actions import Action, ActionGroup, DeleteAction, DeleteBulkAction, EditAction, ViewAction
from tungsten.forms import (
    DateTimePicker,
    FileUpload,
    Group,
    Placeholder,
    Repeater,
    RichEditor,
    Section,
    Select,
    Tab,
    Tabs,
    Textarea,
    TextInput,
    Toggle,
)
from tungsten.tables import ListTab, SelectFilter, TextColumn, ToggleColumn

from .models import BlogAuthor, BlogCategory, BlogPost, BlogTag
from .score import analyze, analyze_post

STATUSES = {"draft": "Draft", "published": "Published"}
GRADE_COLORS = {"good": "#16a34a", "fair": "#d97706", "poor": "#dc2626"}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("blog") if ctx is not None else None


def blog_path(ctx: Any) -> str:
    plugin = _plugin(ctx)
    return plugin.path if plugin is not None else "/blog"


def post_link(ctx: Any, record: Any) -> str:
    """Where the post is on the site; drafts and scheduled posts get a private preview link."""
    from .public import preview_token

    url = f"{blog_path(ctx)}/{record.slug}"
    if not record.is_live:
        url += f"?preview={preview_token(ctx.panel.secret_key, record.id)}"
    return url


def _grade_color(score: int) -> str:
    return GRADE_COLORS["good" if score >= 80 else "fair" if score >= 50 else "poor"]


def score_panel(get: Any, ctx: Any = None) -> Markup:
    """The live score box in the post editor. It updates when a field loses focus."""
    names = ("title", "slug", "excerpt", "content", "cover_image", "cover_alt", "meta_title", "meta_description",
             "focus_keyword", "noindex", "summary", "key_points", "sources", "faqs", "howto_title", "howto_steps",
             "author_id")
    data = {name: get(name) for name in names}
    if isinstance(data["cover_image"], list):
        data["cover_image"] = data["cover_image"][0] if data["cover_image"] else None
    report = analyze(data)
    out = ['<div style="display:grid;gap:14px">']
    for section in report.sections:
        color = _grade_color(section.score)
        out.append(
            '<details style="border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:10px 12px">'
            '<summary style="cursor:pointer;display:flex;align-items:center;gap:10px;list-style:none">'
            f'<strong style="min-width:42px">{escape(section.title)}</strong>'
            '<span style="flex:1;height:8px;border-radius:99px;background:rgba(127,127,127,.2);overflow:hidden">'
            f'<span style="display:block;height:100%;width:{section.score}%;background:{color}"></span></span>'
            f'<span style="font-weight:600;color:{color};min-width:34px;text-align:right">{section.score}</span>'
            '</summary><ul style="margin:10px 0 0;padding:0;list-style:none;display:grid;gap:6px;font-size:13px">')
        for check in sorted(section.checks, key=lambda c: c.ok):
            mark = "✓" if check.ok else "✗"
            mark_color = GRADE_COLORS["good"] if check.ok else GRADE_COLORS["poor"]
            tip = (f'<div style="opacity:.75;margin-top:2px">{escape(check.tip)}</div>'
                   if not check.ok and check.tip else "")
            out.append(f'<li style="display:flex;gap:8px"><span style="color:{mark_color};font-weight:700">{mark}'
                       f'</span><div>{escape(check.label)}{tip}</div></li>')
        out.append("</ul></details>")
    out.append('<p style="margin:0;font-size:12px;opacity:.7">Click a score to see tips. '
               'Scores update when you leave a field.</p></div>')
    return Markup("".join(out))


def _live(field: Any) -> Any:
    return field.live(on_blur=True)


class PostResource(Resource):
    model = BlogPost
    icon = "newspaper"
    navigation_group = "Blog"
    navigation_sort = 1
    navigation_label = "Posts"
    description = "Write posts that rank on Google and get quoted by AI search."
    global_search_attributes = ["title", "excerpt"]

    @classmethod
    def get_record_title(cls, record: Any) -> str:
        return record.title

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Group([
                Section("Post").icon("pen-line").columns(1).schema([
                    _live(TextInput("title").required().max_length(200).placeholder("How to ...")),
                    _live(TextInput("slug").label("URL slug").max_length(200)
                          .helper_text("Leave empty to make it from the title. Short, with the keyword.")),
                    _live(Textarea("excerpt").rows(2)
                          .helper_text("One or two lines shown on the blog list and in feeds.")),
                    _live(RichEditor("content").column_span("full")),
                ]),
                Tabs().key("blog-optimize").tabs([
                    Tab("SEO").icon("search").columns(2).schema([
                        _live(TextInput("meta_title").label("SEO title").max_length(160)
                              .helper_text("Shown in Google. 30 to 60 characters. Empty: the post title.")),
                        _live(TextInput("focus_keyword").max_length(120)
                              .helper_text("The search phrase this post should rank for.")),
                        _live(Textarea("meta_description").max_length(320).rows(2).column_span("full")
                              .helper_text("Shown under the title in Google. 120 to 160 characters.")),
                        TextInput("canonical_url").label("Canonical URL").url().max_length(500)
                        .helper_text("Only if this post first appeared on another page."),
                        FileUpload("og_image").label("Social share image").image().directory("blog")
                        .helper_text("For Facebook, LinkedIn, X and WhatsApp. 1200 x 630. Empty: the cover."),
                        _live(Toggle("noindex").label("Hide from search engines")),
                    ]),
                    Tab("GEO").icon("sparkles").columns(1).schema([
                        _live(Textarea("summary").label("Summary (TL;DR)").rows(3).helper_text(
                            "2 to 3 sentences that answer the post's main question. "
                            "AI search (ChatGPT, Perplexity, Google AI) quotes this.")),
                        _live(Repeater("key_points").schema([TextInput("text").label("Point").required()])
                              .default_items(0).add_action_label("Add key point")),
                        _live(Repeater("sources").columns(2).schema([
                            TextInput("title").max_length(200),
                            TextInput("url").label("URL").url().required(),
                        ]).default_items(0).add_action_label("Add source")),
                    ]),
                    Tab("AEO").icon("message-circle-question").columns(1).schema([
                        _live(Repeater("faqs").label("FAQs").schema([
                            TextInput("question").required().max_length(300),
                            Textarea("answer").rows(3).required()
                            .helper_text("Answer in the first sentence. About 40 to 60 words."),
                        ]).default_items(0).collapsible().add_action_label("Add question")
                            .item_label(lambda state: (state or {}).get("question") or None)),
                        _live(TextInput("howto_title").label("How-to title").max_length(200)
                              .helper_text("For step-by-step posts, e.g. \"How to install Tungsten\".")),
                        _live(Repeater("howto_steps").label("How-to steps").schema([
                            TextInput("name").label("Step title").max_length(200),
                            Textarea("text").label("What to do").rows(2).required(),
                        ]).default_items(0).add_action_label("Add step")),
                    ]),
                ]),
            ]).columns(1).column_span(2),
            Group([
                Section("Publish").icon("send").columns(1).schema([
                    Select("status").options(STATUSES).default("draft").required(),
                    DateTimePicker("published_at").label("Publish date")
                    .helper_text("A future date schedules the post. Empty: now, when published."),
                    _live(Select("author_id").label("Author").relationship("author", "name").searchable().preload()),
                    Select("category_id").label("Category").relationship("category", "name").searchable().preload(),
                    Select("tags").multiple().relationship("tags", "name").searchable().preload(),
                    Toggle("featured"),
                ]),
                Section("Cover image").icon("image").columns(1).schema([
                    _live(FileUpload("cover_image").label("Image").image().directory("blog")),
                    _live(TextInput("cover_alt").label("Alt text").max_length(255)
                          .helper_text("Describe the image for screen readers and search.")),
                ]),
                Section("Score").icon("gauge").columns(1).schema([
                    Placeholder("score").hidden_label().content(score_panel),
                ]),
            ]).columns(1).column_span(1),
        ])

    @classmethod
    def table(cls, table):
        def score_of(record: Any) -> int:
            return analyze_post(record).score

        return (
            table.columns([
                TextColumn("title").weight("medium").searchable().sortable().wrap().limit(90)
                .description(lambda record: f"/{record.slug}"),
                TextColumn("status").badge().sortable()
                .state(lambda record: "scheduled" if record.is_scheduled else record.status)
                .format_state_using(lambda state: {**STATUSES, "scheduled": "Scheduled"}.get(state, state))
                .color(lambda state: {"published": "success", "scheduled": "info"}.get(state, "gray")),
                TextColumn("score").label("SEO/GEO/AEO").badge().state(score_of)
                .color(lambda state: "success" if state >= 80 else "warning" if state >= 50 else "danger"),
                TextColumn("category.name").label("Category").toggleable(),
                TextColumn("author.name").label("Author").toggleable(hidden_by_default=True),
                ToggleColumn("featured").toggleable(hidden_by_default=True),
                TextColumn("published_at").label("Published").datetime().sortable(),
            ])
            .filters([
                SelectFilter("status").options(STATUSES),
                SelectFilter("category_id").label("Category").relationship("category", "name"),
                SelectFilter("author_id").label("Author").relationship("author", "name"),
            ])
            .tabs([
                ListTab("all").label("All posts").badge(),
                ListTab("published").label("Published").query(
                    lambda query, model: query.where(model.status == "published",
                                                     (model.published_at.is_(None))
                                                     | (model.published_at <= dt.datetime.now()))),
                ListTab("scheduled").label("Scheduled").badge(color="info").query(
                    lambda query, model: query.where(model.status == "published",
                                                     model.published_at > dt.datetime.now())),
                ListTab("drafts").label("Drafts").badge(color="gray").query(
                    lambda query, model: query.where(model.status == "draft")),
            ])
            .actions([
                Action("open").label("Open on site").icon("external-link").icon_button()
                .url(lambda record, ctx: post_link(ctx, record), open_in_new_tab=True),
                EditAction(),
                ActionGroup([ViewAction(), DeleteAction()]),
            ])
            .bulk_actions([
                DeleteBulkAction(),
            ])
            .default_sort("created_at", "desc")
        )

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if record is not None and page in ("view", "edit"):
            label = "Open on site" if record.is_live else "Preview"
            actions = [Action("open").label(label).icon("external-link").color("gray")
                       .url(post_link(ctx, record), open_in_new_tab=True).button()] + actions
        return actions


def _post_count(model: Any, column: Any) -> Any:
    return lambda record, ctx: ctx.db.scalar(select(func.count()).select_from(BlogPost).where(column == record.id))


class CategoryResource(Resource):
    model = BlogCategory
    icon = "folder"
    navigation_group = "Blog"
    navigation_sort = 2
    navigation_label = "Categories"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Section("Category").columns(2).schema([
                TextInput("name").required().max_length(120),
                TextInput("slug").label("URL slug").max_length(140).helper_text("Empty: made from the name."),
                Textarea("description").rows(3).column_span("full")
                .helper_text("Shown at the top of the category page. Helps it rank."),
                TextInput("meta_title").label("SEO title").max_length(160),
                TextInput("sort").numeric().integer().default(0),
                Textarea("meta_description").max_length(320).rows(2).column_span("full"),
            ]).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable().description(lambda record: f"/{record.slug}"),
                TextColumn("posts").label("Posts").state(_post_count(BlogCategory, BlogPost.category_id)),
                TextColumn("sort").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .default_sort("sort", "asc")
        )


class TagResource(Resource):
    model = BlogTag
    icon = "tag"
    navigation_group = "Blog"
    navigation_sort = 3
    navigation_label = "Tags"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(80),
            TextInput("slug").label("URL slug").max_length(100).helper_text("Empty: made from the name."),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable().description(lambda record: f"/{record.slug}"),
                TextColumn("created_at").label("Added").since().sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("name", "asc")
        )


class AuthorResource(Resource):
    model = BlogAuthor
    icon = "user-pen"
    navigation_group = "Blog"
    navigation_sort = 4
    navigation_label = "Authors"

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("Author").columns(2).column_span(2).schema([
                TextInput("name").required().max_length(120),
                TextInput("slug").label("URL slug").max_length(140).helper_text("Empty: made from the name."),
                TextInput("job_title").max_length(120).placeholder("Senior Python Developer"),
                TextInput("email").email().max_length(255),
                Textarea("bio").rows(4).column_span("full")
                .helper_text("Who they are and why they know the topic. Search and AI engines look for this."),
                TextInput("website").url().max_length(500).column_span("full"),
                Repeater("profiles").label("Profile links").schema([
                    TextInput("url").label("URL").url().required().placeholder("https://www.linkedin.com/in/..."),
                ]).default_items(0).add_action_label("Add profile").column_span("full"),
            ]),
            Section("Photo").column_span(1).schema([
                FileUpload("avatar").image().avatar().directory("blog"),
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable().description(lambda record: record.job_title),
                TextColumn("posts").label("Posts").state(_post_count(BlogAuthor, BlogPost.author_id)),
            ])
            .actions([EditAction(), DeleteAction()])
            .default_sort("name", "asc")
        )
