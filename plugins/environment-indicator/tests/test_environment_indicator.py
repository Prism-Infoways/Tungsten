from __future__ import annotations

import pytest
from tungsten_environment_indicator import Environment, EnvironmentIndicatorPlugin, environment_of
from tungsten_environment_indicator.environment import (
    color_value,
    git_branch,
    host_of,
    is_local_host,
    normalise,
    text_color_for,
)


# ---------------------------------------------------------------- detection
@pytest.mark.parametrize("raw,expected", [
    ("production", "production"), (" PROD ", "production"), ("live", "production"), ("stage", "staging"),
    ("UAT", "staging"), ("dev", "development"), ("local", "local"), ("test", "testing"), ("qa", "testing"),
    ("Demo Site", "demo-site"), ("", ""), (None, ""), ("  ", ""), ("<script>", "script"),
])
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_env_var_order(monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    assert EnvironmentIndicatorPlugin().current().name == "staging"
    monkeypatch.setenv("APP_ENV", "prod")
    assert EnvironmentIndicatorPlugin().current().name == "production"
    monkeypatch.setenv("TUNGSTEN_ENV", "local")
    assert EnvironmentIndicatorPlugin().current().name == "local"


def test_blank_env_var_is_skipped(monkeypatch):
    monkeypatch.setenv("TUNGSTEN_ENV", "   ")
    monkeypatch.setenv("APP_ENV", "staging")
    assert EnvironmentIndicatorPlugin().current().name == "staging"


def test_explicit_beats_env_vars(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert EnvironmentIndicatorPlugin("local").current().name == "local"
    assert EnvironmentIndicatorPlugin(lambda: "Staging").current().name == "staging"


def test_broken_callback_falls_back(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")

    def boom():
        raise RuntimeError("no")

    assert EnvironmentIndicatorPlugin(boom).current().name == "staging"


def test_nothing_set_without_request_is_live():
    plugin = EnvironmentIndicatorPlugin()
    env = plugin.current()
    assert env.name == "production" and env.is_production and env.label == "Live"


@pytest.mark.parametrize("host,local", [
    ("localhost", True), ("localhost:8000", True), ("127.0.0.1:8000", True), ("127.0.1.1", True),
    ("[::1]:8000", True), ("::1", True), ("0.0.0.0", True), ("app.test", True), ("my-mac.local", True),
    ("admin.example.com", False), ("example.com:443", False), ("", False), (None, False),
    ("localhost.example.com", False), ("LOCALHOST.", True),
])
def test_is_local_host(host, local):
    assert is_local_host(host) is local


def test_host_of():
    assert host_of("https://admin.example.com/x") == "admin.example.com"
    assert host_of("localhost:8000") == "localhost"
    assert host_of("http://[::1") == ""
    assert host_of(None) == ""


# ---------------------------------------------------------------- colors and labels
def test_colors():
    assert color_value("red") == "#dc2626"
    assert color_value("DANGER") == "#dc2626"
    assert color_value("#0EA") == "#00eeaa"
    assert color_value("#0ea5e9") == "#0ea5e9"
    for bad in ("", "#12", "#zzzzzz", "red; background:url(x)", "url(javascript:1)", None, "rgb(1,2,3)"):
        with pytest.raises(ValueError):
            color_value(bad)


def test_bad_options_fail_at_start_up():
    with pytest.raises(ValueError):
        EnvironmentIndicatorPlugin(color="reddish")
    with pytest.raises(ValueError):
        EnvironmentIndicatorPlugin(colors={"qa": "nope"})
    with pytest.raises(ValueError):
        EnvironmentIndicatorPlugin("   ")
    with pytest.raises(ValueError):
        EnvironmentIndicatorPlugin(border_width="thick")


def test_text_color_contrast():
    assert text_color_for("#dc2626") == "#ffffff"
    assert text_color_for("#fde047") == "#111827"  # light yellow gets dark text
    assert text_color_for("#ffffff") == "#111827"
    assert text_color_for("#000000") == "#ffffff"


def test_defaults_and_overrides():
    assert EnvironmentIndicatorPlugin("staging").current().color == "#d97706"
    assert EnvironmentIndicatorPlugin("qa").current().label == "Testing"
    custom = EnvironmentIndicatorPlugin("demo", labels={"demo": "Demo"}, colors={"DEMO": "sky"}).current()
    assert (custom.label, custom.color) == ("Demo", "#0284c7")
    other = EnvironmentIndicatorPlugin("preview_2").current()
    assert other.label == "Preview 2" and other.color == "#4b5563"
    assert EnvironmentIndicatorPlugin("local", label="My laptop", color="#fde047").current().text_color == "#111827"


def test_border_width_is_clamped():
    assert EnvironmentIndicatorPlugin(border_width=99).border_width == 12
    assert EnvironmentIndicatorPlugin(border_width=-5).border_width == 0


# ---------------------------------------------------------------- git
def test_git_branch(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feature/login\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert git_branch(deep) == "feature/login"
    (tmp_path / ".git" / "HEAD").write_text("0123456789abcdef\n")
    assert git_branch(tmp_path) == "0123456"


def test_git_worktree_file(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "HEAD").write_text("ref: refs/heads/main\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../real\n")
    assert git_branch(wt) == "main"
    (wt / ".git").write_text("garbage")
    assert git_branch(wt) is None


def test_no_git(tmp_path):
    assert git_branch(tmp_path / "missing") is None
    empty = tmp_path / "x"
    (empty / ".git").mkdir(parents=True)  # .git folder without HEAD: keep looking up, never crash
    assert git_branch(empty) is None


# ---------------------------------------------------------------- in the panel
def test_badge_border_and_title_on_pages(make_client):
    client = make_client(EnvironmentIndicatorPlugin("staging"))
    html = client.get("/admin/").text
    assert 'data-environment="staging"' in html and "Staging" in html
    assert 'class="tw-env-border"' in html and "#d97706" in html
    assert '"[Staging] "' in html
    login = make_client(EnvironmentIndicatorPlugin("staging"), login=False).get("/admin/login").text
    assert "You are signing in to" in login and 'data-environment="staging"' in login


def test_localhost_request_is_local(make_client):
    client = make_client(EnvironmentIndicatorPlugin(), base_url="http://localhost:8000")
    assert 'data-environment="local"' in client.get("/admin/").text


def test_real_domain_is_live(make_client):
    client = make_client(EnvironmentIndicatorPlugin(), base_url="https://admin.example.com")
    html = client.get("/admin/").text
    assert 'data-environment="production"' in html and "Live" in html


def test_proxy_with_local_host_header_is_still_live(make_client):
    client = make_client(EnvironmentIndicatorPlugin(), base_url="http://127.0.0.1:8000")
    html = client.get("/admin/", headers={"X-Forwarded-For": "1.2.3.4"}).text
    assert 'data-environment="production"' in html
    html = client.get("/admin/", headers={"X-Forwarded-Host": "admin.example.com"}).text
    assert 'data-environment="production"' in html
    html = client.get("/admin/", headers={"X-Forwarded-Host": "localhost:3000"}).text
    assert 'data-environment="local"' in html


def test_env_var_wins_over_host(make_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    client = make_client(EnvironmentIndicatorPlugin(), base_url="http://localhost")
    assert 'data-environment="production"' in client.get("/admin/").text


def test_parts_can_be_turned_off(make_client):
    client = make_client(EnvironmentIndicatorPlugin("local", badge=False, border=False, title_prefix=False,
                                                    login=False))
    html = client.get("/admin/").text
    assert 'class="tw-env-badge"' not in html and 'class="tw-env-border"' not in html and "[Local]" not in html


def test_hide_in(make_client):
    client = make_client(EnvironmentIndicatorPlugin("prod", hide_in="production"))
    html = client.get("/admin/").text
    assert 'class="tw-env-badge"' not in html and 'class="tw-env-border"' not in html


def test_visible_callback_per_user(make_client):
    plugin = EnvironmentIndicatorPlugin("staging", visible=lambda user: bool(user and user.is_admin))
    admin = make_client(plugin)
    assert 'class="tw-env-badge"' in admin.get("/admin/").text
    staff = make_client(EnvironmentIndicatorPlugin("staging", visible=lambda user: bool(user and user.is_admin)),
                        login=False)
    assert staff.login("staff@example.com").status_code == 303
    assert 'class="tw-env-badge"' not in staff.get("/admin/").text


def test_broken_visible_callback_still_shows(make_client):
    def boom(user):
        raise RuntimeError("bad")

    html = make_client(EnvironmentIndicatorPlugin("production", visible=boom)).get("/admin/").text
    assert 'class="tw-env-badge"' in html


def test_label_is_escaped(make_client):
    plugin = EnvironmentIndicatorPlugin("local", label='<img src=x onerror=alert(1)>"')
    html = make_client(plugin).get("/admin/").text
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "\\u003cimg" in html  # title prefix script is escaped too


def test_debug_warning_on_live(make_client):
    html = make_client(EnvironmentIndicatorPlugin("production"), debug=True).get("/admin/").text
    assert "debug on" in html and "Turn it off on live" in html
    html = make_client(EnvironmentIndicatorPlugin("local"), debug=True).get("/admin/").text
    assert "debug on" not in html


def test_git_branch_in_badge(make_client, monkeypatch, tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / ".git" / "HEAD").write_text("ref: refs/heads/release-1\n")
    monkeypatch.chdir(tmp_path / "repo")
    html = make_client(EnvironmentIndicatorPlugin("staging", git_branch=True)).get("/admin/").text
    assert "Staging<span class=\"tw-env-extra\"> · release-1</span>" in html and "Branch: release-1" in html


def test_title_prefix_only_once_with_htmx(make_client):
    client = make_client(EnvironmentIndicatorPlugin("local"))
    html = client.get("/admin/").text
    assert html.count('var p="[Local] "') == 1
    assert "indexOf(p)!==0" in html


def test_environment_of_helper(make_client):
    client = make_client(EnvironmentIndicatorPlugin("staging"))
    env = environment_of(client.panel)
    assert isinstance(env, Environment) and env.name == "staging" and not env.is_production
    assert environment_of(object()) is None


def test_mcp_instructions():
    assert "real data" in EnvironmentIndicatorPlugin("live").mcp_instructions()
    assert "not live" in EnvironmentIndicatorPlugin("local").mcp_instructions()


def test_page_still_works_if_badge_breaks(make_client, monkeypatch):
    plugin = EnvironmentIndicatorPlugin("local")
    client = make_client(plugin)
    monkeypatch.setattr(plugin, "current", lambda ctx=None: (_ for _ in ()).throw(RuntimeError("x")))
    r = client.get("/admin/")
    assert r.status_code == 200 and 'class="tw-env-badge"' not in r.text


def test_small_screen_style_without_title_prefix(make_client):
    html = make_client(EnvironmentIndicatorPlugin("local", title_prefix=False)).get("/admin/").text
    assert ".tw-env-badge .tw-env-extra{display:none}" in html and "var p=" not in html
