# tungsten-impersonate

"Log in as" plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI. An admin logs in as any user to see exactly what they see. Made for support, and safe by default.

## What you get

- A **Log in as** button on your users list and user pages, and a **Log in as a user** picker.
- An orange **bar on every page** while you are someone else, with **Back to my account** and the minutes left.
- **Time limit**: you go back to your own account after 60 minutes.
- **Impersonation log**: who logged in as whom, when, why, for how long, from which IP and browser.
- **Safety rules**: only allowed admins; never as yourself, a super admin, an inactive user or a user with more access than you; no "log in as" from inside another account.
- Links with other plugins when installed: **HR** employees with a login, **help desk** ticket customers, and three **security audit** checks.

## Install

```bash
pip install tungsten-impersonate
```

```python
from tungsten_impersonate import ImpersonatePlugin

panel.plugin(ImpersonatePlugin())
panel.create_tables(engine)   # creates the impersonation log table
```

With [roles](https://tungsten.prisminfoways.com/docs/roles-and-permissions), give the **Log in as other users** permission only to your support admins. Without roles every panel user may use it.

### Options

```python
ImpersonatePlugin(
    can_impersonate=None,       # fn(user, ctx) -> bool
    can_be_impersonated=None,   # fn(user, target, ctx) -> bool
    no_more_access=True,        # never become a user with permissions you don't have
    max_minutes=60,             # 0: no limit
    require_reason=False,       # ask "Why?" first
    redirect_to=None,           # page to open as the user
    users=True, link_plugins=True, banner=True, log_resource=True,
    on_start=None, on_end=None,
)
```

The buttons on your users list and other plugins' screens use `panel.record_action()` from the tungsten-admin release after 0.1.7. On 0.1.7 add `plugin.action()` to your users table yourself; the log screen's picker works everywhere.

Docs: https://tungsten.prisminfoways.com/docs/impersonate

## Try it

```bash
pip install -e . -e plugins/impersonate uvicorn
uvicorn plugins.impersonate.example:app --reload     # from the repo root
```

Sign in as admin@example.com / password, open **Users** and press **Log in as** on a row.

## Tests

```bash
pip install -e ".[dev]" -e plugins/impersonate -e plugins/hr -e plugins/tickets -e plugins/security-audit
pytest plugins/impersonate/tests
```
