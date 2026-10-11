# tungsten-environment-indicator

A **Local / Staging / Live** badge for [Tungsten](https://tungsten.prisminfoways.com/) admin panels, so nobody
changes live data by mistake.

## What you get

- A colored **badge** in the top bar: green Local, blue Development, amber Staging, red Live.
- A thin **colored line** on top of every page, sign-in page too.
- The **browser tab title** starts with `[Live]`, `[Staging]`... so you can tell tabs apart.
- "You are signing in to **Live**" on the **sign-in page**.
- Optional **git branch** in the badge (read from `.git/HEAD`, no command runs).
- A **debug on** warning when a live app runs with `FastAPI(debug=True)`.
- Show it only to some users (for example admins), or hide it on live for a customer panel.
- AI assistants using the [MCP plugin](https://tungsten.prisminfoways.com/plugins/mcp) are told when the panel is live.

## Install

```bash
pip install tungsten-environment-indicator
```

```python
from tungsten_environment_indicator import EnvironmentIndicatorPlugin

panel.plugin(EnvironmentIndicatorPlugin())
```

Then set the environment where your app runs:

```bash
APP_ENV=staging uvicorn app:app
```

It reads `TUNGSTEN_ENV`, `APP_ENV`, `ENVIRONMENT`, `ENV`, `FASTAPI_ENV` or `PYTHON_ENV` (first one set wins).
`prod` and `live` mean production, `stage` and `uat` mean staging, `dev` means development.

With none of them set, a panel opened on `localhost` or `127.0.0.1` shows **Local**, and anything else shows
**Live**. Behind a proxy (nginx, Apache) it only says Local when the forwarded host is local too. So a forgotten
setting never hides the Live warning.

## Options

```python
EnvironmentIndicatorPlugin(
    environment="staging",                  # or a function; None = detect
    labels={"production": "Production"},    # text per environment
    colors={"staging": "orange", "qa": "#0ea5e9"},
    visible=lambda user: user.is_admin,     # or True / False
    hide_in=("production",),                # show nothing on live
    git_branch=True,
    badge=True, border=True, title_prefix=True, login=True,
    border_width=3,
)
```

Colors are names (`red`, `amber`, `green`, `blue`, `violet`, `danger`, `warning`, `success`...) or hex like
`#0ea5e9`. A wrong color stops the app at start-up, so you see the typo at once.

## For other plugins

```python
from tungsten_environment_indicator import environment_of

env = environment_of(panel, ctx)      # None when this plugin is not installed
if env and env.is_production:
    ...
plugin = panel.get_plugin("environment-indicator")
plugin.badge(ctx, size="lg")          # the same badge, as HTML
```

`Environment` has `name`, `label`, `color`, `text_color`, `branch`, `debug` and `is_production`.

Docs: https://tungsten.prisminfoways.com/docs/environment-indicator
