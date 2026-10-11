---
title: Environment indicator
description: Show a Local, Staging or Live badge, a colored line and a tab title prefix in your Tungsten admin panel, so nobody changes live data by mistake.
---

The `tungsten-environment-indicator` plugin shows which copy of your app you are using. A local copy shows a green **Local** badge, staging shows amber **Staging**, and live shows red **Live**. You see it in the top bar, on the sign-in page, as a thin line on top of every page and in the browser tab title, like `[Live] Orders · Acme`.

It stops the classic mistake: deleting or editing real data because you thought you were on your laptop.

## Install

```bash
pip install tungsten-environment-indicator
```

```python
from tungsten_environment_indicator import EnvironmentIndicatorPlugin

panel.plugin(EnvironmentIndicatorPlugin())
```

It needs `tungsten-admin` 0.1.4 or newer. No tables, no settings screen.

## Tell it the environment

Set one environment variable where the app runs:

```bash
APP_ENV=staging uvicorn app:app
```

It reads these, and the first one that is set wins: `TUNGSTEN_ENV`, `APP_ENV`, `ENVIRONMENT`, `ENV`, `FASTAPI_ENV`, `PYTHON_ENV`. Case and spaces don't matter.

| You write | It shows |
| --- | --- |
| `production`, `prod`, `live` | **Live** (red) |
| `staging`, `stage`, `uat`, `preprod` | **Staging** (amber) |
| `development`, `dev` | **Development** (blue) |
| `local` | **Local** (green) |
| `testing`, `test`, `qa`, `ci` | **Testing** (violet) |
| anything else, like `demo` | **Demo** (gray) |

You can also pass it in code: `EnvironmentIndicatorPlugin("staging")`, or a function: `EnvironmentIndicatorPlugin(lambda: settings.env)`.

### When nothing is set

The plugin guesses, and it always guesses on the safe side:

- Opened on `localhost`, `127.0.0.1`, `::1`, or a name ending in `.local`, `.test` or `.localhost`: **Local**.
- Anything else: **Live**.

Behind a proxy like nginx or Apache, your app often sees `127.0.0.1` even on the live server. So when the request came through a proxy, it only says Local if the forwarded host is local too. A forgotten setting can make your laptop say Live, but it never makes the live server say Local.

## Options

```python
EnvironmentIndicatorPlugin(
    environment=None,                        # name, function, or None to detect
    label=None,                              # text for the current environment
    color=None,                              # color for the current environment
    labels={"production": "Production"},     # text per environment
    colors={"staging": "orange", "qa": "#0ea5e9"},
    visible=True,                            # True, False, or fn(user, ctx) -> bool
    hide_in=(),                              # environments that show nothing
    badge=True,                              # badge in the top bar
    border=True,                             # colored line on top of every page
    title_prefix=True,                       # "[Live] " in the browser tab
    login=True,                              # "You are signing in to Live" on the sign-in page
    git_branch=False,                        # add the git branch to the badge
    border_width=3,                          # line height in pixels, 0 to 12
)
```

**Colors** are names (`red`, `orange`, `amber`, `yellow`, `green`, `emerald`, `teal`, `cyan`, `sky`, `blue`, `indigo`, `violet`, `purple`, `pink`, `rose`, `gray`, `slate`) or Tungsten's names (`danger`, `warning`, `success`, `info`, `primary`), or a hex color like `#0ea5e9`. The text turns dark on light colors, so it stays readable. A wrong color stops the app at start-up, so a typo can't slip into live.

### Only for some users

```python
EnvironmentIndicatorPlugin(visible=lambda user: user is not None and user.is_admin)
```

The function gets `user` and `ctx` (ask only for what you need). On the sign-in page `user` is `None`. If the function raises an error, the badge still shows: showing it by mistake is better than hiding a Live warning by mistake.

### Hide it on live

For a panel your customers use, you may not want them to see a red Live badge:

```python
EnvironmentIndicatorPlugin(hide_in=("production",))
```

Your team still sees Staging and Local everywhere else.

### Git branch

`git_branch=True` adds the branch, like **Staging · release-2**. It reads `.git/HEAD` from the app's folder (worktrees too). No `git` command runs. It shows the short commit when the checkout is not on a branch, and nothing when there is no repository. The branch is read once when the app starts.

On phones the badge shows only the environment name, so the top bar keeps its buttons.

## Debug mode warning

When the environment is Live and your app was created with `FastAPI(debug=True)`, the badge adds **debug on**. Debug mode shows error details to visitors, so turn it off on live. The [Security audit](security-audit) plugin checks this too.

## Works with other plugins

- **MCP**: with the [MCP plugin](mcp), AI assistants are told which environment they are working in. On Live they are told that changes affect real data, and to confirm before changing anything.
- **Quick Create**: with the [Quick Create](quick-create) plugin on Live, its form says "You are on Live. This record goes into real data."
- **Your own plugins** can show the same badge, for example in a banner:

```python
from tungsten_environment_indicator import environment_of

env = environment_of(panel, ctx)       # None when the plugin is not installed
if env and env.is_production:
    ...

plugin = panel.get_plugin("environment-indicator")
html = plugin.badge(ctx, size="lg")    # "sm" for the top bar size
prefix = plugin.title_prefix(ctx)      # "[Live] "
```

`Environment` has `name`, `label`, `color`, `text_color`, `branch`, `debug` and `is_production`.

## Questions

**Does it slow pages down?** No. The environment and branch are read once at start-up. Each page adds a few hundred bytes of HTML.

**Does it change my data or add tables?** No. It only adds HTML to pages.

**I changed `APP_ENV` but the badge didn't change.** Restart the app. Or call `plugin.refresh()`.
