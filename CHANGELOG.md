# What's new in Tungsten

All notable changes to Tungsten (`tungsten-admin`) and its official plugins. Newest first.

## Unreleased

- **Security fix (issue #103): signing out ends the session everywhere.** Each sign-in is now kept on the server (table `tungsten_sessions`); signing out deletes it, so a saved copy of the cookie stops working. New `Auth(session_max_age=...)` (seconds, 14 days by default) and `Auth(sessions=...)` to use another store or `False` to turn it off. Sessions from before `idle_timeout` was turned on now idle out too. **Run `panel.create_tables(engine)` once**; users sign in again once.
- **Security fix (issue #85):** a disabled action (`.disabled(...)`) no longer runs when its form is posted.
- **Security fix (issue #86):** a `FileUpload` field only takes back stored paths the panel signed for this user (or the record's saved file), so nobody can post another user's file path.
- **Security fix (issue #87):** a searchable `Select(...).relationship(..., modify_query=...)` now checks submitted ids against the same modified query.
- **Security fix (issue #95):** new `panel.on_file_access(key, fn)` decides who may open a stored file at `/storage`.
- **Security fix (issue #107):** a hidden field gives no options, takes no uploads and no rich editor attachments.
- **Fix (issue #109):** signing in after a session ended on an open page goes back to that page, not to a bare widget.

## 2026-10-28 · tungsten-admin 0.1.13: two security fixes

- **`tungsten-admin` 0.1.13** is on PyPI: `pip install -U tungsten-admin`. No database changes. Plugins work as before.
- **Security fix: hidden `javascript:` links.** The HTML cleaner (used by the rich editor, HTML table columns, `Text` components and blog posts) now also blocks links like `java&#9;script:...` that hide a tab or new line inside `javascript:`. Browsers drop those characters and would run the link. Nothing to change in your code.
- **Security fix (issue #122)**: emailed sign-in codes can no longer be guessed without limit by sending a saved session cookie again. The wrong guesses (5 per code), the one-minute resend wait and used codes are now also counted on the server, in the same store as the login throttle (`Auth(throttle=...)`). After 5 wrong guesses the code stops working; ask for a new one after a minute. Nothing to change in your code.

## 2026-10-26 · tungsten-admin 0.1.12: modern design and new components

- **`tungsten-admin` 0.1.12** is on PyPI: `pip install -U tungsten-admin`. No database changes.
- **`tungsten-calendar` 0.1.1, `tungsten-kanban` 0.1.1 and `tungsten-saved-views` 0.1.1** are on PyPI with the new design: `pip install -U tungsten-calendar tungsten-kanban tungsten-saved-views`. They need `tungsten-admin` 0.1.12.


- **New look for the whole panel**, inspired by modern dashboard designs: a light gray page, white cards with big soft corners, a floating dark sidebar where the current page is a white pill, a top bar of round white buttons, pill-shaped buttons and badges, black pill tabs and small uppercase table headers. Dark mode and right-to-left languages included. Nothing to change in your code. See [UI components](/docs/ui-components).
- **10 new dashboard widgets**: `HeroStatWidget` (one big number with buttons), `GaugeWidget` (target gauge or ring), `ColumnsWidget` (rounded columns with one highlighted), `BannerWidget`, `ActivityWidget` (timeline), `LeaderboardWidget`, `FunnelWidget`, `ScheduleWidget` (week strip and events), `TeamWidget` and `QuickActionsWidget`, plus `ChecklistWidget`. List widgets share one `Item` class. See [Modern widgets](/docs/modern-widgets).
- **Filled stats cards**: `Stat(...).highlight()` fills a card with the brand color, `.highlight("dark")` makes it near black.
- **UI kit for your own templates**: new macros `pill_tabs`, `segmented`, `switch`, `chip`, `trend_pill`, `progress_ring`, `gauge`, `meter`, `columns`, `banner`, `list_row`, `timeline_item`, `avatar_group`, `week_strip`, `alert`, `kpi`, `skeleton`, `divider`, `dot` and `kbd`, and CSS classes like `tw-card-dark`, `tw-card-brand`, `tw-glass`, `tw-well` and `tw-pill-nav`. A gallery page shows them all: `content_template = "tungsten/components/gallery.html"`.
- **Demo app**: the shop dashboard now uses the new widgets, and has a **UI kit** page under Settings.
- **Every Filament component is now in Tungsten**: the last missing ones landed. Forms: `MarkdownEditor` (toolbar, shortcuts, live preview, `html_column()`), `CodeEditor` (line numbers, Tab indenting, `json()` mode) and `MorphToSelect` (a type and a record select for polymorphic relations). Layouts and blocks: `FusedGroup` (fields joined in one control), `Icon`, `Image` and `UnorderedList`. Tables: `Split`, `Stack`, `Panel` and `Grid` layout columns draw each row as a card, with `.grow(False)` and `.visible_from()` on inner columns. A small Markdown converter is in `tungsten.support.markdown`. See [Form fields](/docs/form-fields), [Form layouts](/docs/form-layouts) and [Table columns](/docs/table-columns).
- **Plugins in the new design**: every plugin page follows the new look. Saved view tabs, calendar view buttons, kanban lanes and cards, toggle buttons, relation manager tabs, wizard steps, ticket replies, dashboards toolbars and file fields are pill shaped and rounded like the rest.

## 2026-10-17 · tungsten-admin 0.1.11: advanced filters

- **`tungsten-admin` 0.1.11** is on PyPI: `pip install -U tungsten-admin`. No database changes.

- **Advanced filters**: pick an operator and type a value per column, like *Price is between 1000 and 5000* or *Created is this month*. `table.advanced_filters()` adds one for every column, typed from the database column; `AdvancedFilter.text/number/date/boolean/select/relationship(...)` adds them one by one. See [Advanced filters](/docs/advanced-filters).
- **More date operators** in advanced filters and the query builder: today, yesterday, tomorrow, this/last/next week, month and year, in the last N days/weeks/months/years, in the next N days/weeks/months, in the past, in the future, is not on, is not between. Numbers get "is not between". "In the last N days" no longer matches future dates.
- **Query builder from the columns**: `QueryBuilder().auto_constraints()` builds the constraints from the table columns, and `constraint_for(Model, "path")` gives the guess for one.
- **Fix**: an active "is between" rule in the query builder no longer breaks the table.

## 2026-10-15 · tungsten-mcp 0.1.3 and tungsten-security-audit 0.1.1

- **`tungsten-mcp` 0.1.3** is on PyPI: `pip install -U tungsten-mcp`. It adds MCP resources and prompts (`McpPlugin(documents=..., prompts=...)`), and a `TypeError` inside a tool is now reported as a server error instead of "wrong arguments". See [MCP](/docs/mcp).
- **`tungsten-security-audit` 0.1.1** is on PyPI: `pip install -U tungsten-security-audit`. "Unlock" on the login log works with the new login limit store in `tungsten-admin` 0.1.10.

## 2026-10-14 · tungsten-admin 0.1.10: background workers, scope every query, MCP resources

- **`tungsten-admin` 0.1.10** is on PyPI: `pip install -U tungsten-admin`. **After upgrading, run `panel.create_tables(engine)` once**: it adds the new job columns (retries, heartbeats) to the existing jobs table.

- **Jobs in their own worker process**: `Panel(jobs="worker")` plus `tungsten jobs:work --workers 4`. Jobs get retries with backoff (`max_attempts=3, backoff=[10, 60]`), heartbeats, and jobs from a stopped server are picked up again. See [Actions](/docs/actions).
- **Scope every query to the tenant**: `Tenancy(..., scope_session=True)` filters every ORM query on the panel's sessions, like a Laravel global scope, with `panel.tenancy.unscoped()` to step outside it. See [Multi-tenancy](/docs/multi-tenancy).
- **Login limit for several processes**: failed sign-ins can be counted in a shared store such as Redis (`Auth(throttle=...)`), and idle counts are dropped so memory stays small. See [Authentication](/docs/authentication).
- **MCP resources and prompts**: `tungsten-mcp` can give the AI documents to read and ready-made prompts, and the docs show how to add your own tools. It is in `tungsten-mcp` 0.1.3. See [MCP](/docs/mcp).
- **Filament migration**: `tungsten-filament` now converts relations defined in traits, keeps MySQL text sizes, and reports global scopes so you can turn on `scope_session`. See [Filament migration](/docs/filament-migration).

## 2026-10-14 · tungsten-admin 0.1.9 on PyPI

- **`tungsten-admin` 0.1.9** is on PyPI: `pip install -U tungsten-admin`. It has all the Filament-style work below: navigation and teams, forms, tables, actions and exports, login and security, notifications and the activity log, custom themes, infolists and relation managers.
- **After upgrading, run `panel.create_tables(engine)` once.** It adds the new tables for login and security and for per-team roles. Your data is not touched.
- **New: `tungsten-filament`** moves a Laravel Filament admin to Tungsten (models, resources, forms, tables, filters, actions and relation managers) on the same database and logins. **`tungsten-filament` 0.1.0** is on PyPI too: `pip install tungsten-filament`.

## 2026-10-14 · Navigation and teams like Filament

_In `tungsten-admin` 0.1.9._

- **Tenant in the URL**: `Tenancy(..., url=True, slug_attribute="slug")` gives links like `/admin/acme/products`, so two tabs can show two teams.
- **Team sign-up and settings pages**: users register new teams and edit the current one. Users without a team go to sign-up first.
- **Billing hooks**: plug in Stripe or any provider with `BillingProvider`, and lock unpaid teams with `require_subscription=True`.
- **Roles per team**: `RolesField().per_tenant()` makes a user Admin in one team and Viewer in another.
- **Clusters**: group resources and pages behind one menu item with their own sub-menu.
- **Record sub-menu**: `record_sub_navigation = ("view", "edit")` adds tabs or a side menu on a record's pages.
- **Menu along the top**: `Panel(top_navigation=True)`.
- Run `panel.create_tables(engine)` once after upgrading; it adds the table for per-team roles.

## 2026-10-14 · Forms: everything Filament has

_In `tungsten-admin` 0.1.9._

- **Actions inside forms**: buttons next to a field's hint, before or after an input, in an `Actions` row or in a callout. They can fill fields, or open their own modal form, which also works in a form that is already in a modal.
- **Select**: a + button to create a new option in a modal (saved and selected), and a pencil to edit the selected one.
- **New fields**: `ModalTableSelect` (pick records from a searchable, paged table), `Slider` (one or two handles) and `ViewField` for your own templates. The docs now show how to write a custom field.
- **Text inputs**: input masks (`mask("99999-99999")`) and money masks with Indian digit grouping.
- **Date and time pickers**: `timezone("Asia/Kolkata")` shows times in the user's zone and saves them in UTC.
- **Layouts**: `Flex` (alias `Split`) and the content blocks `Text`, `Html` and `Callout`. Tabs can keep the open tab in the URL (`?tab=pricing`) or in the browser.
- **Rich editor**: choose the toolbar buttons (now with underline, H2 and H3), attach files and images, `@mentions`, and custom blocks with their own form. `render_rich_content()` shows the result on your site.

## 2026-10-14 · Safer sign-in

_In `tungsten-admin` 0.1.9._

- **Two-factor codes by email.** `Auth(two_factor_email=True)`: users can get their sign-in code by email instead of (or as well as) an authenticator app.
- **Verified email change.** A new email on the profile page only takes effect after its owner opens the link sent to it. The old address gets a notice with a link to stop the change.
- **Idle timeout.** `Auth(idle_timeout=30)` signs people out after 30 minutes without activity. Background polling doesn't count.
- **API tokens, like Laravel Sanctum.** `Auth(api_tokens=True)`: users make tokens with abilities and an expiry on an API tokens page; protect your routes with `Depends(panel.api_user("orders:read"))`.
- **Security headers** on every panel page: HSTS (over HTTPS), X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy and a Content Security Policy. Change them with `Panel(security_headers=..., content_security_policy=...)`, or add `SecurityHeadersMiddleware` to your whole site.

## 2026-10-14 · Tables catch up with Filament

_In `tungsten-admin` 0.1.9._

- **Filters in a pop-up or a dropdown**: `filters(..., layout="modal")` or `layout="dropdown"`, next to the side panel and the toolbar.
- **Apply button for filters**: `deferred_filters()` runs the filters only when the user presses Apply. On by default in the modal and dropdown layouts.
- **Remember the table**: `persist_filters_in_session()`, `persist_search_in_session()`, `persist_sort_in_session()` (or `persist_in_session()` for all three) bring the table back as the user left it.
- **Fast pagination for huge tables**: `paginated(mode="simple")` (Previous / Next, no count) and `mode="cursor"` (stays fast on page 5,000).
- **Cards**: `stacked_on_mobile()` turns rows into cards on phones; `content_grid({"md": 2, "xl": 3})` shows records as a grid of cards.
- **Column groups**: `ColumnGroup("Pricing", [...])` puts one heading over several columns.
- **Range total**: `Range()` shows the lowest and highest value in the footer.
- Fixed: Decimal totals without a format now show thousands separators.

## 2026-10-14 · Notifications and activity log

_In `tungsten-admin` 0.1.9._

- **Email notifications**: `Notification(...).send_to_mail(users, ctx)` emails a notification through the panel's mailer, with an HTML version and full links.
- **Live notifications**: open tabs keep a WebSocket, so `broadcast(users, ctx)` pops a toast at once and `send_to_database` updates the bell count at once. Works with several workers through a custom broadcaster (Redis example in the docs).
- **Activity log** now also records deletes, restores, force deletes, every action run, exports, sign-ins, sign-outs, failed sign-ins and password resets. Create and edit popups are logged too. New docs page: Activity log.
- Fixed: the unread count on the notification bell never showed.

## 2026-10-14 · Actions and exports

_In `tungsten-admin` 0.1.9._

- **Modals in modals**: an action's modal can open another action's modal, and modal footers can hold extra buttons. Headers and footers can stay in view while the content scrolls.
- **Chained actions**: `.then(...)` runs a second action after the first, or picks the next one from the result.
- **A wizard in a modal**: an action's form can be a step-by-step wizard.
- **Before and after hooks** on every action, and **rate limits** so an action can't run too often.
- **File downloads**: ready-made actions that send a file or stream a big one.
- **Big bulk actions**: run the selected records in chunks, or in the background after the response.
- **Background exports**: a big export runs in the background and sends a "Your export is ready" notification with a Download button.
- **Export history**: every export is listed with its table, format, rows and status, with a download link.

## 2026-10-14 · Infolists and relation managers

_In `tungsten-admin` 0.1.9._

- **New entries**: `CodeEntry` (coloured JSON, Python, SQL and more) and `ViewEntry` (your own template).
- **Entry actions**: buttons on any entry, as a hint, before or after the value.
- **Extra fields when attaching**: `AttachAction` can fill extra columns on the link table, such as a member's role in a team.
- **Associate and dissociate** for one-to-many relationships.
- **Polymorphic relationships** (`morph_many`, `morph_to_many`) and **has many through** (a team's tasks through its projects).
- **Related records on their own page**, and **nested resources** with their own create, edit and view pages.

## 2026-10-14 · Your own theme

_In `tungsten-admin` 0.1.9._

- **Custom themes**: `tungsten make:theme` and `tungsten theme:build` make your own Tailwind build on top of Tungsten's, so every Tailwind class works in your templates and code, and you can change Tungsten's own styles. Your server does not need Node.js.

## 2026-10-14 · Move from Filament to Tungsten

- **New tool: Filament migration** (`tungsten-filament`). Point it at a Laravel Filament project and it writes a Tungsten admin: models from your migrations, relations, PHP enums, resources, forms, tables, filters, actions, infolists and relation managers, for Filament 3 and 4. The new admin runs on the same database and people sign in with the same passwords. What it cannot convert is marked in the code and listed in a report. On PyPI as `tungsten-filament` 0.1.0: `pip install tungsten-filament`.

## 2026-10-13 · Ten new plugins on PyPI

- **tungsten-admin 0.1.8** is on PyPI: `pip install -U tungsten-admin`. It adds the hooks that Impersonate, Media library and Saved views need.
- Now on PyPI, version 0.1.0 each: `tungsten-quick-create`, `tungsten-kanban`, `tungsten-dashboards`, `tungsten-calendar`, `tungsten-tags`, `tungsten-saved-views`, `tungsten-media-library`, `tungsten-pwa`, `tungsten-impersonate` and `tungsten-backups`.
- `tungsten-environment-indicator` 0.1.0 followed on 2026-10-14, so all eleven plugins from 2026-10-11 are on PyPI.
- **Website**: every plugin page now shows the plugins it works with and links to its blog post, and each plugin's docs page links back to it.

## 2026-10-11 · Eleven new plugins

- **New plugin: Quick Create** (`tungsten-quick-create`). A + New button in the top bar to create any record from any page.
- **New plugin: Kanban boards** (`tungsten-kanban`). Show any resource as a drag-and-drop board, with columns by status. Ready boards for leads, tickets and leave.
- **New plugin: Custom Dashboards** (`tungsten-dashboards`). Users build their own dashboards by drag and drop, with widgets from every plugin.
- **New plugin: Calendar** (`tungsten-calendar`). Month, week, day and list views, all-day and repeating events, drag and drop, and a private link for Google Calendar, Outlook or iPhone. Shows leave, holidays and birthdays (HR), lead follow-ups, ticket due times, unpaid invoices and blog posts when those plugins are installed.
- **New plugin: Tags** (`tungsten-tags`). Put colored tags on any record and filter by them.
- **New plugin: Saved table views** (`tungsten-saved-views`). Users save their own filters as one-click views like My Leads or Pending.
- **New plugin: Media library** (`tungsten-media-library`). Every image and file in one place. Upload once, reuse anywhere.
- **New plugin: Install as an app** (`tungsten-pwa`). Your team installs the panel like an app on Android, iPhone, Windows and Mac, with app icons, shortcuts, faster loading and an offline page. Pages and data are never cached.
- **New plugin: Impersonate** (`tungsten-impersonate`). Admins log in as any user to see what they see, safely and with a log.
- **New plugin: Backups** (`tungsten-backups`). Back up your database and files from the panel, and download the zip.
- **New plugin: Environment indicator** (`tungsten-environment-indicator`). A Local, Staging or Live badge, so nobody works on live by mistake.

## 2026-10-11 · HR and Finance on PyPI

- **`tungsten-hr` 0.1.0** is on PyPI: `pip install tungsten-hr`. Employees, attendance with check-in and biometric machines, leave with approval, and holidays.
- **`tungsten-finance` 0.2.0** is on PyPI: `pip install tungsten-finance`. Double-entry books with GST, invoices, payments, expenses and reports. Needs `tungsten-admin` 0.1.7.

## 2026-10-10 · HR, Finance and a faster core

- **New plugin: HR** (`tungsten-hr`). Employees, departments, attendance with check-in, leave with approval, and holidays. Works with biometric machines by push, pull, API or CSV.
- **New plugin: Finance and accounts** (`tungsten-finance` 0.2.0). Double-entry books like Tally, Busy and Zoho Books: invoices, payments, expenses, GST and reports.
- **tungsten-admin 0.1.6**: a faster core, with fewer database queries per page and cheaper table rendering.
- **tungsten-admin 0.1.7** on PyPI: fixes validation rules inside Repeater fields.
- **Website**: a page for every plugin, this What's new page, clean addresses without `.html`, and SEO, GEO and AEO across the site.

## 2026-10-09 · Help desk, blog and audits

- **New plugin: Help desk** (`tungsten-tickets`). Tickets with replies, internal notes, saved replies, SLA due times, emails and a customer support page.
- **New plugin: Blog** (`tungsten-blog`). A blog built for SEO, GEO and AEO, with a live score in the editor, schema.org data, sitemap, RSS and llms.txt.
- **New plugin: SEO audit** (`tungsten-seo-audit`). Audits your website and gives a score out of 100 with a fix tip for every issue, including AI search checks.
- **New plugin: Security audit** (`tungsten-security-audit`). A security score for your panel, a login log and lockout after wrong passwords.
- **tungsten-admin 0.1.5**: links inside the rich text editor no longer break the editor.
- Plugin updates: `tungsten-leads` 0.1.2, `tungsten-mcp` 0.1.2, `tungsten-meta-leads` 0.1.1 and `tungsten-whatsapp` 0.1.1.

## 2026-10-08 · AI access with MCP

- **New plugin: AI access** (`tungsten-mcp`). An MCP server inside your panel, so Claude and other AI assistants can read and change your data with the same roles and rules.
- Connect with OAuth login: add the address in Claude, log in and press Allow. No token to copy.
- Add your own MCP tools in Python.
- **tungsten-admin 0.1.4**: plugins can mount their own routes with `Plugin.mount`.
- `tungsten-leads` 0.1.1: send an `external_id` and the same lead is never added twice.

## 2026-10-04 · Plugins arrive

- Plugins now ship as their own pip packages.
- **New plugin: Leads** (`tungsten-leads`). A simple CRM with stages, a timeline, follow-ups and lead fields you add without code.
- **New plugin: Facebook and Instagram leads** (`tungsten-meta-leads`). Meta lead ads land in your panel the moment someone fills the form.
- **New plugin: WhatsApp** (`tungsten-whatsapp`). Click-to-chat links, the official Cloud API or WhatsApp Web.
- Step by step setup guides for Facebook leads and WhatsApp, inside the panel.
- **tungsten-admin 0.1.3**: plugin templates, static files and translations; `Panel.of(db)`.
- Fixes: menus cut off inside tables, the filter panel on phones, and the phone sidebar in right-to-left languages.

## 2026-10-03 · First release on PyPI

- **tungsten-admin 0.1.0 to 0.1.2** on PyPI: `pip install tungsten-admin`.
- A new design, the website at tungsten.prisminfoways.com, a demo video and screenshots.

## 2026-10-01 · Tungsten begins

- A Filament-style admin panel for FastAPI: resources, forms, tables, actions, widgets, logins and roles from Python classes.
- Infolists, list tabs, inline editing, two-factor login, async SQLAlchemy engines, a query builder filter, email verification and translations.
