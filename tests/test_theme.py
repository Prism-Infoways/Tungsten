"""Custom themes: ``tungsten make:theme``, ``tungsten theme:build`` and ``Panel(theme_stylesheet=...)``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import tungsten
from tungsten.cli import theme_content

from .conftest import run_cli

ROOT = Path(__file__).resolve().parent.parent


def test_shipped_theme_files_match_the_frontend_sources():
    # build.mjs copies these into the package; a stale copy would give themes old styles
    theme = Path(tungsten.__file__).parent / "theme"
    assert (theme / "preset.js").read_text() == (ROOT / "frontend" / "preset.js").read_text()
    assert (theme / "tungsten.css").read_text() == (ROOT / "frontend" / "input.css").read_text()
    assert 'require("' not in (theme / "preset.js").read_text()  # no node_modules inside the Python package


def test_make_theme_writes_the_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run_cli("make:theme") == 0
    theme = tmp_path / "admin" / "theme"
    assert sorted(p.name for p in theme.iterdir()) == [".gitignore", "package.json", "tailwind.config.js", "theme.css"]
    assert not (theme / "__init__.py").exists()
    package = json.loads((theme / "package.json").read_text())
    assert "tailwindcss" in package["devDependencies"]
    assert package["scripts"]["build"] == "tungsten theme:build --dir ."
    assert "TUNGSTEN_THEME_DIR" in (theme / "tailwind.config.js").read_text()
    assert 'theme_stylesheet="admin/theme/dist/theme.css"' in capsys.readouterr().out

    (theme / "theme.css").write_text("/* mine */")
    assert run_cli("make:theme") == 1  # never overwrites without --force
    assert (theme / "theme.css").read_text() == "/* mine */"
    assert run_cli("make:theme", "--force") == 0
    assert (theme / "theme.css").read_text() != "/* mine */"


def test_theme_build_needs_a_theme(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run_cli("theme:build") == 1
    assert "tungsten make:theme" in capsys.readouterr().out


def test_theme_build_runs_tailwind(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_cli("make:theme", "--dir", "styles")
    (tmp_path / "styles" / "node_modules" / "tailwindcss").mkdir(parents=True)  # already installed
    calls = []
    monkeypatch.setattr("tungsten.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tungsten.cli.subprocess.run", lambda cmd, **kw: calls.append((cmd, kw)))
    assert run_cli("theme:build", "--dir", "styles") == 0

    (cmd, kw), = calls
    assert cmd == ["/usr/bin/npx", "tailwindcss", "-c", "tailwind.config.js", "-i", ".tungsten-input.css",
                   "-o", "dist/theme.css", "--minify"]
    assert kw["cwd"] == Path("styles")
    shipped = Path(tungsten.__file__).parent / "theme"
    assert kw["env"]["TUNGSTEN_THEME_DIR"] == shipped.resolve().as_posix()
    assert json.loads(kw["env"]["TUNGSTEN_THEME_CONTENT"]) == theme_content()
    entry = (tmp_path / "styles" / ".tungsten-input.css").read_text()
    assert f'@import "{(shipped / "tungsten.css").resolve().as_posix()}";' in entry
    assert entry.strip().endswith('@import "./theme.css";')

    calls.clear()
    run_cli("theme:build", "--dir", "styles", "--watch")
    assert calls[0][0][-1] == "--watch"


def test_theme_build_installs_npm_packages_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_cli("make:theme")
    calls = []
    monkeypatch.setattr("tungsten.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tungsten.cli.subprocess.run", lambda cmd, **kw: calls.append(cmd))
    run_cli("theme:build")
    assert calls[0][:2] == ["/usr/bin/npm", "install"]
    assert calls[1][1] == "tailwindcss"


def test_theme_build_reports_missing_node_and_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run_cli("make:theme")
    monkeypatch.setattr("tungsten.cli.shutil.which", lambda name: None)
    assert run_cli("theme:build") == 1
    assert "Node.js" in capsys.readouterr().out

    (tmp_path / "admin" / "theme" / "node_modules" / "tailwindcss").mkdir(parents=True)
    monkeypatch.setattr("tungsten.cli.shutil.which", lambda name: f"/usr/bin/{name}")

    def fail(cmd, **kw):
        raise subprocess.CalledProcessError(3, cmd)

    monkeypatch.setattr("tungsten.cli.subprocess.run", fail)
    assert run_cli("theme:build") == 3
    assert "Theme build failed" in capsys.readouterr().out


def test_theme_content_covers_tungsten():
    globs = theme_content()
    assert globs[0] == f"{Path(tungsten.__file__).parent.resolve().as_posix()}/**/*.{{html,py,js}}"
    assert len(globs) == len(set(globs))


def test_panel_uses_built_in_css_by_default(admin, panel):
    html = admin.get("/admin/").text
    assert panel.asset("tungsten.css") in html
    assert admin.get("/admin/theme.css").status_code == 404


def test_panel_serves_a_theme_file(admin, panel, tmp_path):
    css = tmp_path / "theme.css"
    css.write_text(".bg-lime-300{background:#bef264}")
    panel.theme_stylesheet = str(css)
    html = admin.get("/admin/").text
    assert "tungsten.css" not in html
    url = panel.stylesheet()
    assert url.startswith("/admin/theme.css?v=") and url in html
    r = admin.get(url)
    assert r.status_code == 200 and r.text == css.read_text()
    assert r.headers["content-type"].startswith("text/css")
    assert "immutable" in r.headers["cache-control"]

    css.write_text(".bg-lime-400{background:#a3e635}!")  # a rebuild gets a new version
    assert panel.stylesheet() != url


def test_panel_theme_url_and_missing_file(panel, tmp_path):
    panel.theme_stylesheet = "https://cdn.example.com/theme.css"
    assert panel.stylesheet() == "https://cdn.example.com/theme.css"
    panel.theme_stylesheet = "/static/theme.css"  # not a file here: a URL on the same site
    assert panel.stylesheet() == "/static/theme.css"
    panel.theme_stylesheet = tmp_path / "not-built-yet.css"
    assert panel.stylesheet() == panel.asset("tungsten.css")  # the panel keeps working
