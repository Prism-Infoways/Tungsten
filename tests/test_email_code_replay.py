"""Email codes cannot be guessed or re-sent without limit by replaying a saved session cookie (issue #122)."""

from __future__ import annotations

import copy
import re
from types import SimpleNamespace

from sqlalchemy import select

from tests.conftest import db_session
from tungsten.auth import two_factor as tfa


def _setup(panel):
    from examples.shop.models import User

    panel.auth.two_factor_email = True
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == "admin@example.com")).first()
    return user, SimpleNamespace(panel=panel, session={})


def _code(panel) -> str:
    return re.search(r"\b(\d{6})\b", panel.test_mails[-1]["body"]).group(1)


def _wrong(code: str) -> str:
    return str((int(code) + 1) % 10 ** 6).zfill(6)


def test_replayed_cookie_does_not_reset_wrong_guesses(panel):
    user, ctx = _setup(panel)
    assert tfa.send_email_code(ctx, user)
    code, saved = _code(panel), copy.deepcopy(ctx.session)
    for _ in range(tfa.EMAIL_CODE_TRIES):
        ctx.session = copy.deepcopy(saved)
        assert not tfa.check_email_code(ctx, user, _wrong(code))
    ctx.session = copy.deepcopy(saved)
    assert not tfa.check_email_code(ctx, user, code)  # out of tries, even the right code is refused


def test_a_right_code_clears_the_count_and_is_used_once(panel):
    user, ctx = _setup(panel)
    tfa.send_email_code(ctx, user)
    code, saved = _code(panel), copy.deepcopy(ctx.session)
    assert not tfa.check_email_code(ctx, user, _wrong(code))
    assert not tfa.check_email_code(ctx, user, "abc")  # not digits counts as a try too
    assert tfa.check_email_code(ctx, user, code)
    assert panel.auth.throttle.failures(tfa._tries_key("login", panel.auth.user_id(user)), 600) == 0
    ctx.session = copy.deepcopy(saved)
    assert not tfa.check_email_code(ctx, user, code)  # the used code can't be replayed


def test_resend_wait_holds_without_the_cookie(panel):
    user, ctx = _setup(panel)
    assert tfa.send_email_code(ctx, user)
    sent = len(panel.test_mails)
    for _ in range(3):
        fresh = SimpleNamespace(panel=panel, session={})
        assert not tfa.send_email_code(fresh, user)
    assert len(panel.test_mails) == sent
    # other purposes keep their own wait
    assert tfa.send_email_code(SimpleNamespace(panel=panel, session={}), user, "setup")


def test_resend_after_a_minute(panel, monkeypatch):
    user, ctx = _setup(panel)
    now = [1000.0]
    monkeypatch.setattr("tungsten.auth.throttle.time.monotonic", lambda: now[0])
    monkeypatch.setattr("tungsten.auth.two_factor.time.time", lambda: now[0])
    assert tfa.send_email_code(ctx, user)
    now[0] += tfa.EMAIL_RESEND_SECONDS + 1
    assert tfa.send_email_code(SimpleNamespace(panel=panel, session={}), user)
