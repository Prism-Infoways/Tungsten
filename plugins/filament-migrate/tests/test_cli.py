"""``tungsten-filament scan`` and ``convert``."""

from __future__ import annotations

import shutil

from conftest import FIXTURES
from tungsten_filament.cli import main


def test_scan_writes_nothing(tmp_path, capsys):
    root = tmp_path / "app"
    shutil.copytree(FIXTURES / "shop3", root)
    assert main(["scan", str(root)]) == 0
    out = capsys.readouterr().out
    assert "Filament 3 project: 7 models, 4 resources" in out
    assert "createOptionForm() uses a value that was not converted" in out
    assert not (tmp_path / "tungsten_admin").exists()


def test_convert_and_refuse_to_overwrite(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "app"
    shutil.copytree(FIXTURES / "shop3", root)
    assert main(["convert", str(root)]) == 0
    assert (tmp_path / "tungsten_admin" / "app.py").exists()
    assert "Wrote 9 files" in capsys.readouterr().out
    assert main(["convert", str(root)]) == 1
    assert "pass --force" in capsys.readouterr().err
    assert main(["convert", str(root), "--force"]) == 0


def test_not_a_laravel_project(tmp_path, capsys):
    assert main(["scan", str(tmp_path)]) == 2
    assert "does not look like a Laravel project" in capsys.readouterr().err
