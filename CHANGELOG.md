# What's new in Tungsten

All notable changes to Tungsten (`tungsten-admin`) and its official plugins. Newest first.

## 2026-10-14 · Safer sign-in

- **Two-factor codes by email.** `Auth(two_factor_email=True)`: users can get their sign-in code by email instead of (or as well as) an authenticator app.
- **Verified email change.** A new email on the profile page only takes effect after its owner opens the link sent to it. The old address gets a notice with a link to stop the change.
- **Idle timeout.** `Auth(idle_timeout=30)` signs people out after 30 minutes without activity. Background polling doesn't count.
- **API tokens, like Laravel Sanctum.** `Auth(api_tokens=True)`: users make tokens with abilities and an expiry on an API tokens page; protect your routes with `Depends(panel.api_user("orders:read"))`.
- **Security headers** on every panel page: HSTS (over HTTPS), X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy and a Content Security Policy. Change them with `Panel(security_headers=..., content_security_policy=...)`, or add `SecurityHeadersMiddleware` to your whole site.

## 2026-10-14 · Tables catch up with Filament

- **Filters in a pop-up or a dropdown**: `filters(..., layout="modal")` or `layout="dropdown"`, next to the side panel and the toolbar.
- **Apply button for filters**: `deferred_filters()` runs the filters only when the user presses Apply. On by default in the modal and dropdown layouts.
- **Remember the table**: `persist_filters_in_session()`, `persist_search_in_session()`, `persist_sort_in_session()` (or `persist_in_session()` for all three) bring the table back as the user left it.
- **Fast pagination for huge tables**: `paginated(mode="simple")` (Previous / Next, no count) and `mode="cursor"` (stays fast on page 5,000).
- **Cards**: `stacked_on_mobile()` turns rows into cards on phones; `content_grid({"md": 2, "xl": 3})` shows records as a grid of cards.
- **Column groups**: `ColumnGroup("Pricing", [...])` puts one heading over several columns.
- **Range total**: `Range()` shows the lowest and highest value in the footer.
- Fixed: Decimal totals without a format now show thousands separators.

## 2026-10-14 · Notifications and activity log

- **Email notifications**: `Notification(...).send_to_mail(users, ctx)` emails a notification through the panel's mailer, with an HTML version and full links.
- **Live notifications**: open tabs keep a WebSocket, so `broadcast(users, ctx)` pops a toast at once and `send_to_database` updates the bell count at once. Works with several workers through a custom broadcaster (Redis example in the docs).
- **Activity log** now also records deletes, restores, force deletes, every action run, exports, sign-ins, sign-outs, failed sign-ins and password resets. Create and edit popups are logged too. New docs page: Activity log.
- Fixed: the unread count on the notification bell never showed.

## 2026-10-14 · Move from Filament to Tungsten

- **New tool: Filament migration** (`tungsten-filament`). Point it at a Laravel Filament project and it writes a Tungsten admin: models from your migrations, relations, PHP enums, resources, forms, tables, filters, actions, infolists and relation managers, for Filament 3 and 4. The new admin runs on the same database and people sign in with the same passwords. What it cannot convert is marked in the code and listed in a report. Not on PyPI yet.

## 2026-10-13 · Ten new plugins on PyPI

- **tungsten-admin 0.1.8** is on PyPI: `pip install -U tungsten-admin`. It adds the hooks that Impersonate, Media library and Saved views need.
- Now on PyPI, version 0.1.0 each: `tungsten-quick-create`, `tungsten-kanban`, `tungsten-dashboards`, `tungsten-calendar`, `tungsten-tags`, `tungsten-saved-views`, `tungsten-media-library`, `tungsten-pwa`, `tungsten-impersonate` and `tungsten-backups`.
- `tungsten-environment-indicator` follows next.
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
