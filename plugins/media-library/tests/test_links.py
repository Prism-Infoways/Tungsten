"""The library with the Tags, Quick create and PWA plugins (each optional)."""

from __future__ import annotations

import pytest
from conftest import Base, PanelClient, User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tungsten_media_library import MediaLibraryPlugin, MediaResource

from tungsten import Auth, LocalStorage, Panel, hash_password

tags_mod = pytest.importorskip("tungsten_tags")
quick_mod = pytest.importorskip("tungsten_quick_create")
pwa_mod = pytest.importorskip("tungsten_pwa")


@pytest.fixture()
def linked(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'linked.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha", email="admin@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User),
                  storage=LocalStorage(tmp_path / "storage"))
    panel.plugin(MediaLibraryPlugin())
    panel.plugin(tags_mod.TagsPlugin())
    panel.plugin(quick_mod.QuickCreatePlugin())
    panel.plugin(pwa_mod.PWAPlugin())
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    assert client.login().status_code == 303
    return panel, client


def test_tags_quick_create_and_app_shortcut(linked):
    panel, client = linked
    assert panel.get_plugin("tags").target_for(MediaResource) is not None
    assert "media" in panel.get_plugin("quick-create").links
    shortcuts = panel.get_plugin("pwa").get_shortcuts()
    assert any(s["name"] == "Media library" for s in shortcuts)
    page = client.get("/admin/media")
    assert page.status_code == 200 and "Upload files" in page.text
