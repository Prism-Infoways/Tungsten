---
title: Impersonate (log in as a user)
description: Let support admins log in as any user of your FastAPI admin panel to see exactly what they see, with safety rules, a time limit, a "Back to my account" bar and a full log.
---

The `tungsten-impersonate` plugin lets an admin **log in as another user** and see the panel exactly as that user sees it: the same menu, records, permissions and tenant. It is made for support: "the customer says the invoice button is missing" becomes a one-click check.

It is safe by default: only allowed admins can use it, nobody can become a super admin or get more access than they already have, a bar on every page brings the admin back, the session ends by itself after 60 minutes, and every use is written to a log.

## Install

```bash
pip install tungsten-impersonate
```

```python
from tungsten_impersonate import ImpersonatePlugin

panel = Panel(..., auth=Auth(User))
panel.plugin(ImpersonatePlugin())
panel.create_tables(engine)   # creates the impersonation log table
```

That's all. You get:

- A **Log in as** button on every row of your users list and on each user's page.
- A **Log in as a user** button on the **Security → Impersonation log** screen, to pick any user by name or email.
- An orange **bar on top of every page** while you are someone else, with **Back to my account** and the minutes left.
- The **Impersonation log**: who logged in as whom, when, why, for how long, from which IP and browser.

The buttons on your users list and on other plugins' screens need `panel.record_action()`, which comes with the tungsten-admin release after 0.1.7. On 0.1.7, add the button to your users table yourself (see [Your own button](#your-own-button)); the log screen's button works on every version.

## Who can log in as others

| Panel | Who can use "Log in as" |
| --- | --- |
| Without roles | Every panel user (they can already do everything). The security audit warns about this. |
| With [roles](roles-and-permissions) | Super admins, and roles with the **Log in as other users** permission (`impersonate.start`). |
| `can_impersonate=` | Your own rule: `ImpersonatePlugin(can_impersonate=lambda user: user.is_support)`. |

## Who can be impersonated

The button is hidden, and the action refused with a clear message, when the user:

- is yourself, is not active, or can't open the panel (`Auth(can_access=...)` says no);
- is a **super admin**;
- has a permission **you don't have** (so "log in as" is never a way to get more access). Turn this off with `no_more_access=False`;
- must use two-step login but has not set it up, or has not verified their email (the panel would send you to *their* setup page);
- fails your own rule: `can_be_impersonated=lambda user, target: not target.is_owner`.

You also can't start a second "log in as" from inside someone else's account: go back first.

## While logged in as someone

Everything you see and do is as that user: the menu, the records, tenant and permissions. Anything you save is saved as them, so the **Impersonation log** keeps who really did it and when.

The session ends when you:

- press **Back to my account** in the bar (you return to the page you started from);
- reach the time limit (`max_minutes`, 60 by default). Your next click takes you back to your own account with a note;
- log out (you are signed out completely).

If your own account was deleted or blocked meanwhile, "Back to my account" signs you out instead.

## Options

```python
ImpersonatePlugin(
    can_impersonate=None,          # fn(user, ctx) -> bool: who may log in as others
    can_be_impersonated=None,      # fn(user, target, ctx) -> bool: an extra rule per user
    no_more_access=True,           # never become a user with permissions you don't have
    max_minutes=60,                # 0: no time limit
    require_reason=False,          # ask "Why?" before logging in (always saved when given)
    redirect_to=None,              # page to open as the user: "/admin/orders" or fn(user, ctx)
    users=True,                    # button on your user model's resource
    link_plugins=True,             # buttons in HR and the help desk, and a security audit check
    banner=True,                   # the bar on top of every page
    log_resource=True,             # the Impersonation log screen
    trust_proxy=False,             # read the IP from X-Forwarded-For (only behind your own proxy)
    on_start=None,                 # fn(db, log, user, target, ctx)
    on_end=None,                   # fn(db, state, reason, ctx); reason: left, expired, logged_out, ended
    navigation_group="Security",
    label="Log in as",
)
```

## Your own button

Add the action anywhere a table or page takes actions. `plugin.action()` takes an optional function that finds the panel user behind a record:

```python
imp = ImpersonatePlugin()
panel.plugin(imp)

class UserResource(Resource):
    model = User

    @classmethod
    def table(cls, table):
        return table.columns([...]).actions([imp.action(), EditAction()])

class CustomerResource(Resource):
    model = Customer

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [imp.action(lambda db, record: record.user, label="Log in as customer"), *super().header_actions(ctx, page, record)]
```

Or link a whole resource in one line (needs `panel.record_action`):

```python
imp.link(Customer, lambda db, customer: customer.user)
```

## Works with other plugins

Each link only turns on when the other plugin is installed. The impersonate plugin works fine alone.

- **[HR](hr)**: employees that have a panel login get a **Log in as** button, to check what they see on check-in and leave pages.
- **[Help desk](tickets)**: a ticket's page gets **Log in as customer** when a panel user has the requester's email.
- **[Security audit](security-audit)**: adds three checks: who can log in as others, the time limit, and the log.

## From code

```python
from tungsten_impersonate import impersonator_id, is_impersonating

def my_action(ctx):
    if is_impersonating(ctx):
        real_admin = impersonator_id(ctx)   # the id of the admin behind this request
```

`refusal(plugin, ctx, user)` returns why `ctx.user` may not log in as `user` (or `None`), and `start(plugin, ctx, user, reason)` / `end(plugin, ctx)` do the switch from your own routes.

## FAQ

**Does the user know?** No message is sent to them. The log shows every use, and you can send your own note with `on_start`.

**Can the admin change the user's password while logged in as them?** They can do what the user can do on their own profile page. Use the log to see who did it, or `can_be_impersonated` to protect some users.

**Does it work with async databases and multi-tenancy?** Yes. The admin's own team is restored when they go back.
