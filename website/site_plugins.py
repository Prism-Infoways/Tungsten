"""The official plugins, as shown on /plugins/ and /plugins/<slug>.html.

Each entry: slug, name, package, docs (doc slug), icon (SVG path), tagline (one line),
summary (the direct answer to "what is it", quoted by AI search), features, setup code,
needs (other packages), and faqs (shown on the page and as FAQPage schema).
"""

PLUGINS = [
    {
        "slug": "leads",
        "name": "Leads",
        "package": "tungsten-leads",
        "docs": "leads",
        "category": "Sales",
        "icon": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M19 8v6M16 11h6"/>',
        "tagline": "A simple CRM inside your FastAPI admin panel.",
        "summary": "tungsten-leads adds a leads list to your Tungsten panel, with stages from New to Won, owners, "
                   "deal values, follow-up dates and a timeline of calls and notes. Admins add their own lead form "
                   "fields from the panel without code, and your website can post leads to it with one API call.",
        "features": [
            ("Stages and owners", "New, Contacted, Qualified, Proposal sent, Won and Lost, or your own list."),
            ("Timeline", "Notes, calls, emails and messages on every lead."),
            ("Your own fields", "Text, number, date, dropdown, checkboxes and yes/no fields, added from the panel."),
            ("Follow-ups", "Tabs for My leads, Follow-up due, New and Won, with filters and export."),
            ("Bulk actions", "Assign, mark won, mark lost or delete many leads at once."),
            ("Website form API", "POST leads from any site. The same lead is never added twice."),
        ],
        "setup": 'from tungsten_leads import LeadsPlugin\n\npanel.plugin(LeadsPlugin())\npanel.create_tables(engine)',
        "needs": [],
        "faqs": [
            ("Can I add my own fields to a lead?",
             "Yes. Open Lead fields in the panel and add text, number, date, dropdown, checkbox or yes/no fields. "
             "They show on the lead form right away, with no code and no migration."),
            ("How do website form leads get into the panel?",
             "Set a capture_token, then POST JSON to <panel>/api/leads with the X-Leads-Token header. Send an "
             "external_id and a form that posts twice still makes one lead."),
            ("Can I change the lead stages?",
             "Yes. Pass your own statuses to LeadsPlugin, each with a label and a color."),
        ],
    },
    {
        "slug": "facebook-instagram-leads",
        "name": "Facebook & Instagram leads",
        "package": "tungsten-meta-leads",
        "docs": "facebook-leads",
        "category": "Sales",
        "icon": '<path d="M15 3h-2a4 4 0 0 0-4 4v3H7v4h2v7h4v-7h3l1-4h-4V7a1 1 0 0 1 1-1h2Z"/>',
        "tagline": "Meta lead ads land in your panel the moment someone fills the form.",
        "summary": "tungsten-meta-leads connects your Facebook and Instagram lead forms to Tungsten. Press Connect "
                   "Facebook once and every new lead from your Meta lead ads arrives in tungsten-leads within "
                   "seconds, with each answer saved in the right lead field.",
        "features": [
            ("One-click setup", "Connect Facebook sets up your Pages, lead forms and the webhook for you."),
            ("Every answer kept", "Name, email, phone and your own questions go to lead fields, created for you."),
            ("Per-form rules", "Switch a form on or off, pick the starting stage and who gets the leads."),
            ("Sync", "Reads recent leads from Meta, for leads sent while your site was down."),
            ("Lead log", "Every lead Meta sent and what happened to it, with Try again."),
            ("Setup guide", "A step by step guide in the panel with your own addresses filled in."),
        ],
        "setup": ('from tungsten_leads import LeadsPlugin\nfrom tungsten_meta_leads import MetaLeadsPlugin\n\n'
                  'panel = Panel(..., app_url="https://admin.example.com")\npanel.plugin(LeadsPlugin())\n'
                  'panel.plugin(MetaLeadsPlugin())\npanel.create_tables(engine)'),
        "needs": ["tungsten-leads"],
        "faqs": [
            ("Do I need Meta App Review?",
             "Not for your own Pages. App Review is only needed when other businesses connect their Pages to your app."),
            ("Why are no leads arriving?",
             "The Meta app must be live (Publish, Go live). Meta sends no leads, not even test leads, to an app in "
             "development. Your panel must also be reachable over https."),
            ("Will the same lead be added twice?",
             "No. Each lead keeps Meta's lead id, so the webhook and Sync never add it twice."),
        ],
    },
    {
        "slug": "whatsapp",
        "name": "WhatsApp",
        "package": "tungsten-whatsapp",
        "docs": "whatsapp",
        "category": "Sales",
        "icon": '<path d="M3 21l1.6-4.8A8.5 8.5 0 1 1 8 19.5Z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.5-2-1-1 1a4 4 0 0 1-2-2l1-1-1-2Z"/>',
        "tagline": "Chat with your leads on WhatsApp, right from the panel.",
        "summary": "tungsten-whatsapp lets your team message leads on WhatsApp from the Tungsten panel. Use simple "
                   "click-to-chat links, the official WhatsApp Cloud API, or your own number through WhatsApp Web. "
                   "Every message sent and received shows on the lead's timeline.",
        "features": [
            ("Three ways to send", "Links only, the official Cloud API, or WhatsApp Web with a linked phone."),
            ("Chats in the panel", "Every message on the lead timeline and in WhatsApp chats."),
            ("Templates", "Sync approved templates and send them outside the 24 hour window."),
            ("Welcome message", "Greet new leads, for example only leads from Facebook."),
            ("New chats become leads", "A first message from a new number can create a lead by itself."),
            ("Ticks", "Delivered and read status with the Cloud API."),
        ],
        "setup": ('from tungsten_leads import LeadsPlugin\nfrom tungsten_whatsapp import WhatsAppPlugin\n\n'
                  'panel.plugin(LeadsPlugin())\npanel.plugin(WhatsAppPlugin())\npanel.create_tables(engine)'),
        "needs": ["tungsten-leads"],
        "faqs": [
            ("Which WhatsApp option should I pick?",
             "Start with links only, which needs no setup. Pick the Cloud API for the official, reliable route with "
             "templates. Pick WhatsApp Web to send from your own existing number through a WAHA gateway."),
            ("Can I send a message to someone who has not written to me?",
             "With the Cloud API, only with an approved template. Free text works within 24 hours of the person's last message."),
            ("Does it need tungsten-leads?",
             "Yes. Messages are linked to leads, so install tungsten-leads too."),
        ],
    },
    {
        "slug": "mcp",
        "name": "AI access (MCP)",
        "package": "tungsten-mcp",
        "docs": "mcp",
        "category": "AI",
        "icon": '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 10h4v4h-4z"/>',
        "tagline": "Let Claude and other AI assistants work with your panel's data.",
        "summary": "tungsten-mcp puts a Model Context Protocol (MCP) server inside your Tungsten panel at /admin/mcp. "
                   "Claude, Claude Code, Cursor and other MCP apps can then list, search, read and, if you allow it, "
                   "change records, with the same roles and validation as the panel.",
        "features": [
            ("Tools for every resource", "List, describe, search, read, create, update and delete records."),
            ("OAuth login", "Add the URL as a connector in Claude, log in and press Allow. No token to copy."),
            ("Read-only by default", "Tokens can only read until you switch on Allow changes."),
            ("Same rules as the panel", "Roles, policies, tenancy, validation and hooks all apply."),
            ("AI access screen", "See and revoke connected apps and tokens, with a connect guide."),
            ("Custom tools", "Add your own MCP tools in Python."),
        ],
        "setup": ('from tungsten_mcp import McpPlugin\n\npanel = Panel(..., app_url="https://admin.example.com")\n'
                  'panel.plugin(McpPlugin())\npanel.create_tables(engine)'),
        "needs": [],
        "faqs": [
            ("How do I connect Claude to my Tungsten panel?",
             "In Claude, open Settings, Connectors, Add custom connector and paste https://your-site/admin/mcp. "
             "Press Connect, log in to your panel and press Allow."),
            ("Can the AI change or delete my data?",
             "Only if you allow it. Tokens are read-only by default, and every change goes through the resource's "
             "form with its validation, hooks and activity log."),
            ("Are passwords or secrets ever sent to the AI?",
             "No. Password hashes, tokens, secrets and API keys are never sent."),
        ],
    },
    {
        "slug": "tickets",
        "name": "Help desk (tickets)",
        "package": "tungsten-tickets",
        "docs": "tickets",
        "category": "Support",
        "icon": '<path d="M3 8a2 2 0 0 0 2-2V5h14v1a2 2 0 0 0 0 4v4a2 2 0 0 0 0 4v1H5v-1a2 2 0 0 0-2-2Z"/><path d="M9 9h6M9 13h4"/>',
        "tagline": "A help desk with replies, notes, SLA and a customer support page.",
        "summary": "tungsten-tickets turns your Tungsten panel into a help desk. Customers raise tickets from a support "
                   "page, by API or through your team, and agents answer them in the panel with saved replies, internal "
                   "notes and SLA due times.",
        "features": [
            ("Conversations", "Replies, customer messages, internal notes and a change log on every ticket."),
            ("Saved replies", "Canned answers, attachments and \"then set status\" in the reply box."),
            ("SLA", "Hours to resolve per priority. Late tickets show in red and in Overdue."),
            ("Support page", "Customers raise and follow tickets from a private link, no login needed."),
            ("Emails and bell", "Emails to the customer, and notifications for agents."),
            ("API and hooks", "POST tickets by API, and hooks for WhatsApp, Slack and more."),
        ],
        "setup": ('from tungsten_tickets import TicketsPlugin\n\n'
                  'panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))\n'
                  'panel.plugin(TicketsPlugin())\npanel.create_tables(engine)'),
        "needs": [],
        "faqs": [
            ("Do customers need an account to raise a ticket?",
             "No. They use the support page at <panel>/support and follow their ticket from a private link."),
            ("How does the SLA work?",
             "Each priority has hours to resolve: urgent 4, high 8, normal 24 and low 72 by default. You can change them."),
            ("Can other apps create tickets?",
             "Yes. Set an api_token and POST tickets to <panel>/api/tickets."),
        ],
    },
    {
        "slug": "blog",
        "name": "Blog (SEO, GEO, AEO)",
        "package": "tungsten-blog",
        "docs": "blog",
        "category": "Marketing",
        "icon": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16Z"/><path d="M13.5 6.5l4 4"/>',
        "tagline": "A blog built to rank on Google and get quoted by AI search.",
        "summary": "tungsten-blog adds a blog to your Tungsten panel with a live SEO, GEO and AEO score in the editor. "
                   "It publishes public pages with schema.org data, FAQs, a sitemap, RSS, robots.txt and llms.txt, "
                   "so posts rank on Google, get quoted by ChatGPT and Perplexity, and answer questions directly.",
        "features": [
            ("Live score", "SEO, GEO and AEO checks next to the editor, with a tip for each one."),
            ("Public blog", "Post list, posts, categories, tags, authors, search and pages."),
            ("Schema.org", "BlogPosting, BreadcrumbList, FAQPage, HowTo, Organization and Person."),
            ("AI search ready", "Summaries, key points, sources, llms.txt and a Markdown copy of each post."),
            ("Sitemap and RSS", "sitemap.xml, feed.xml and robots.txt that welcomes AI crawlers."),
            ("Drafts and schedule", "Draft, publish or schedule, with a private preview link."),
        ],
        "setup": ('from tungsten_blog import BlogPlugin\n\n'
                  'panel.plugin(BlogPlugin(site_name="Acme", site_url="https://acme.com"))\n'
                  'panel.create_tables(engine)'),
        "needs": [],
        "faqs": [
            ("What do SEO, GEO and AEO mean?",
             "SEO is ranking on search engines like Google. GEO (generative engine optimization) is getting quoted by "
             "AI search like ChatGPT, Perplexity and Google AI Overviews. AEO (answer engine optimization) is giving "
             "direct answers for answer boxes and voice assistants."),
            ("Does the blog make a sitemap and llms.txt?",
             "Yes. It serves /blog/sitemap.xml and /blog/feed.xml, and with site_files=True also /sitemap.xml, "
             "/robots.txt and /llms.txt at the site root."),
            ("Why don't my cover images show on the site?",
             "Use LocalStorage(public=True) in your Panel, so visitors can load uploaded images."),
        ],
    },
    {
        "slug": "seo-audit",
        "name": "SEO audit",
        "package": "tungsten-seo-audit",
        "docs": "seo-audit",
        "category": "Marketing",
        "icon": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/><path d="m8 11 2 2 4-4"/>',
        "tagline": "Audit your website's SEO and get a score with fix tips.",
        "summary": "tungsten-seo-audit checks your website's pages from the Tungsten panel and gives a score from 0 "
                   "to 100, a list of issues and a simple tip to fix each one. It covers content, technical SEO, "
                   "links, social tags, speed and AI search, and keeps every audit so you can see the score go up.",
        "features": [
            ("Score out of 100", "A score for each area: content, technical, links, social, speed and AI search."),
            ("About 45 checks", "Titles, headings, canonical, robots.txt, sitemap, redirects, broken links and more."),
            ("AI search checks", "AI crawlers in robots.txt, llms.txt and FAQ structured data."),
            ("Fix tips", "A plain tip for every issue, page by page."),
            ("History", "Every audit is saved, with a score trend on the dashboard."),
            ("Blog pages included", "Other plugins, like the blog, add their pages to every audit."),
        ],
        "setup": ('from tungsten_seo_audit import SeoAuditPlugin\n\n'
                  'panel.plugin(SeoAuditPlugin(site_url="https://www.example.com"))\npanel.create_tables(engine)'),
        "needs": [],
        "faqs": [
            ("How many pages does an audit check?",
             "25 by default. Change it per audit in the form, or with max_pages."),
            ("Does it check for AI search (GEO and AEO)?",
             "Yes. It checks that AI crawlers are not blocked in robots.txt, that llms.txt exists and that FAQ structured data is present."),
            ("Can I audit a site that is not built with Tungsten?",
             "Yes. Type any address you own. The audit crawls it like a search engine would."),
        ],
    },
    {
        "slug": "security-audit",
        "name": "Security audit",
        "package": "tungsten-security-audit",
        "docs": "security-audit",
        "category": "Security",
        "icon": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
        "tagline": "A security health check for your panel, plus a login log with lockout.",
        "summary": "tungsten-security-audit checks your Tungsten panel's settings, accounts, logins, website headers "
                   "and packages, and gives a score out of 100 with a plain tip for each problem. It also logs every "
                   "login and locks out repeated wrong passwords.",
        "features": [
            ("Score and grade", "A score out of 100 and a grade, with a tip to fix each problem."),
            ("Settings and accounts", "Secret key, debug mode, two-factor login, roles, weak admin passwords."),
            ("Website headers", "HTTPS, HSTS, CSP, cookie flags, http to https redirect, certificate expiry."),
            ("Packages", "Python version support and known holes from osv.dev."),
            ("Login log", "Every login try with email, IP, browser and result."),
            ("Lockout", "5 wrong passwords lock that login for 15 minutes, by default."),
        ],
        "setup": ('from tungsten_security_audit import SecurityAuditPlugin\n\n'
                  'panel = Panel(..., app_url="https://admin.example.com")\n'
                  'panel.plugin(SecurityAuditPlugin())\npanel.create_tables(engine)'),
        "needs": [],
        "faqs": [
            ("Does it scan other websites?",
             "No. It only checks your own app and your own address. It never scans or attacks other sites."),
            ("How does the login lockout work?",
             "After 5 wrong passwords for one email from one IP, that login is locked for 15 minutes. Unlock it early "
             "from the Login log screen, or change the numbers in the options."),
            ("Can I see how my score changes?",
             "Yes. Every audit is saved, and Audit history shows the score over time."),
        ],
    },
]

PLUGIN_FAQS = [
    ("What are Tungsten plugins?",
     "Tungsten plugins are separate pip packages that add whole features to a Tungsten admin panel, such as leads, "
     "a help desk, a blog or an MCP server for AI. Install one with pip and turn it on with panel.plugin(...)."),
    ("Are the plugins free?",
     "Yes. All official plugins are open source under the MIT license, like Tungsten itself."),
    ("How do I install a plugin?",
     "Run pip install with the plugin's package name, add panel.plugin(ThePlugin()) to your panel, and call "
     "panel.create_tables(engine) so its tables are created."),
    ("Can I build my own plugin?",
     "Yes. A plugin is a Python class that adds resources, pages, widgets, routes and hooks. See Plugins and hooks in the docs."),
]
