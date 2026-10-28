"""Media library: upload, capture from other plugins, dedupe, picker, pick, usage and safe delete."""

from __future__ import annotations

import io
import json
import re
import struct
import zlib

from sqlalchemy import select
from tungsten_blog.models import BlogPost
from tungsten_blog.resources import PostResource
from tungsten_media_library import MediaItem, image_size
from tungsten_media_library.service import clean_folder, human_size, kind_of


def png(width: int = 3, height: int = 2, seed: int = 0) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + bytes([seed % 256]) * (width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def items(panel) -> list[MediaItem]:
    with panel.db() as db:
        return db.scalars(select(MediaItem).order_by(MediaItem.id)).all()


def upload(admin, host: dict, field: str, name: str, content: bytes, mime: str, extra: dict | None = None):
    """Send a file through a form refresh, like the browser does when a file is picked."""
    data = {"_tw_form_id": "tw-test-form", **host, **(extra or {})}
    return admin.post("/admin/_tw/form", data, files={f"{field}.__upload": (name, content, mime)})


LIBRARY_UPLOAD = {"_tw_kind": "action", "_tw_host": "resource:media", "_tw_scope": "page", "_tw_name": "upload"}


def post_form(admin) -> dict:
    return {"_tw_kind": "host", "_tw_host": f"resource:{PostResource.get_slug()}", "_tw_op": "create"}


def signed_values(html: str, field: str) -> list[str]:
    """What the hidden inputs carry and the browser posts back: "path|signature" (see FileUpload.sign)."""
    return re.findall(rf'name="{re.escape(field)}" value="([^"]+)"', html)


def stored_paths(html: str, field: str) -> list[str]:
    return [v.split("|")[0] for v in signed_values(html, field)]


def test_pages_load(admin):
    assert admin.get("/admin/media").status_code == 200
    page = admin.get("/admin/media").text
    assert "Media library" in page and "No files yet" in page and "Upload files" in page


def test_library_upload_records_details_and_folder(admin, panel):
    r = upload(admin, LIBRARY_UPLOAD, "files", "Team photo.png", png(3, 2), "image/png")
    path, signed = stored_paths(r.text, "files")[0], signed_values(r.text, "files")[0]
    assert path.startswith("media/") and path.endswith(".png")
    (item,) = items(panel)
    assert (item.name, item.kind, item.mime, item.width, item.height) == ("Team photo.png", "image", "image/png", 3, 2)
    assert item.size > 0 and len(item.checksum) == 64 and item.uploaded_by == "1"
    r = admin.post("/admin/_tw/action", {**{k: v for k, v in LIBRARY_UPLOAD.items() if k != "_tw_kind"},
                                         "files": signed, "folder": " Team / Photos "})
    assert r.status_code in (200, 204), r.text
    assert items(panel)[0].folder == "team/photos"
    page = admin.get("/admin/media").text
    assert "Team photo.png" in page and "3 × 2" in page
    view = admin.get(f"/admin/media/{item.id}").text
    assert "Not used anywhere" in view and "![](https://" in view


def test_empty_library_upload_is_refused(admin, panel):
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:media", "_tw_scope": "page", "_tw_name": "upload"})
    assert "required" in r.text.lower()
    assert items(panel) == []


def test_wrong_and_big_files_are_refused(admin, panel):
    r = upload(admin, LIBRARY_UPLOAD, "files", "evil.html", b"<script>alert(1)</script>", "text/html")
    assert "not allowed" in r.text
    r = upload(admin, LIBRARY_UPLOAD, "files", "big.pdf", b"%PDF" + b"0" * 60 * 1024, "application/pdf")
    assert "greater than 50 kilobytes" in r.text
    assert items(panel) == []


def test_same_file_twice_is_stored_once(admin, panel, tmp_path):
    first = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "a.png", png(seed=7), "image/png").text, "files")[0]
    second = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "copy of a.png", png(seed=7), "image/png").text,
                          "files")
    assert second == [first]  # the copy we already had, shown once
    assert len(items(panel)) == 1
    assert len(list((tmp_path / "storage" / "media").rglob("*.png"))) == 1


def test_blog_cover_joins_library_and_tickets_stay_private(admin, panel):
    r = upload(admin, post_form(admin), "cover_image", "cover.png", png(8, 4), "image/png", {"title": "Hello"})
    cover = stored_paths(r.text, "cover_image")[0]
    assert cover.startswith("blog/")
    (item,) = items(panel)
    assert item.path == cover and item.folder == "blog" and item.width == 8
    reply = {"_tw_kind": "action", "_tw_host": "resource:tickets", "_tw_scope": "table", "_tw_name": "create"}
    upload(admin, reply, "attachments", "invoice.pdf", b"%PDF-1.4 secret", "application/pdf")
    assert [i.path for i in items(panel)] == [cover]  # ticket files are not added to the library


def test_picker_button_list_search_and_filter(admin, panel):
    upload(admin, LIBRARY_UPLOAD, "files", "logo.png", png(seed=1), "image/png")
    upload(admin, LIBRARY_UPLOAD, "files", "price list.pdf", b"%PDF-1.4 prices", "application/pdf")
    form = admin.get(f"/admin/{PostResource.get_slug()}/create").text
    assert "Choose from library" in form
    url = re.search(r'hx-get="(/admin/media-library/picker\?[^"]+)"', form).group(1).replace("&amp;", "&")
    assert "accept=image" in url
    listing = admin.get(url, headers={"HX-Request": "true"}).text
    assert "logo.png" in listing and "price list.pdf" not in listing  # a cover takes images only
    everything = re.sub(r"accept=[^&]+&?", "", url)
    listing = admin.get(everything + "&mq=price").text
    assert "price list.pdf" in listing and "logo.png" not in listing
    assert "No files found" in admin.get(everything + "&mq=nothing-like-this").text


def test_picker_needs_login_and_good_links(admin, client, app):
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    assert anon.get("/admin/media-library/picker?field=x&form=f&refresh=/admin/_tw/form",
                    follow_redirects=False).status_code in (302, 303, 401)
    bad = admin.get('/admin/media-library/picker?field=x&form=f&refresh=https://evil.com/"x')
    assert bad.status_code == 400
    bad = admin.get("/admin/media-library/picker?field=x%22onclick&form=f&refresh=/admin/_tw/form")
    assert bad.status_code == 400


def test_picker_pages(admin, panel):
    for n in range(30):
        upload(admin, LIBRARY_UPLOAD, "files", f"file{n}.png", png(seed=n + 10), "image/png")
    url = "/admin/media-library/picker?field=cover_image&form=tw-record-form&refresh=/admin/_tw/form"
    first = admin.get(url).text
    assert first.count("file.pick:") == 24 and "Load more" in first
    more = re.search(r'hx-get="([^"]+page=2[^"]*)"', first).group(1).replace("&amp;", "&")
    second = admin.get(more).text
    assert second.count("file.pick:") == 6 and "Load more" not in second


def test_pick_from_library_fills_the_field(admin, panel):
    logo = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "logo.png", png(), "image/png").text, "files")[0]
    pdf = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "doc.pdf", b"%PDF-1.4 x", "application/pdf").text,
                       "files")[0]
    host = post_form(admin)
    r = admin.post("/admin/_tw/form", {**host, "title": "Hi", "_tw_ui_action": f"file.pick:cover_image:{logo}"})
    assert stored_paths(r.text, "cover_image") == [logo]
    picked = signed_values(r.text, "cover_image")[0]
    r = admin.post("/admin/_tw/form", {**host, "_tw_ui_action": f"file.pick:cover_image:{pdf}"})
    assert stored_paths(r.text, "cover_image") == [] and "must be a file of type" in r.text  # covers take images only
    r = admin.post("/admin/_tw/form", {**host, "_tw_ui_action": "file.pick:cover_image:imports/secret.csv"})
    assert stored_paths(r.text, "cover_image") == [] and "can&#39;t be used here" in r.text
    r = admin.post(f"/admin/{PostResource.get_slug()}/create", {"title": "With a library cover", "cover_image": picked,
                                                                 "status": "draft"})
    assert r.status_code in (200, 204, 303), r.text
    with panel.db() as db:
        assert db.scalars(select(BlogPost.cover_image)).one() == logo


def test_used_file_is_not_deleted(admin, panel, tmp_path):
    logo = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "logo.png", png(), "image/png").text, "files")[0]
    spare = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "spare.png", png(seed=3), "image/png").text,
                         "files")[0]
    with panel.db() as db:
        db.add(BlogPost(title="Launch", slug="launch", cover_image=logo))
        db.commit()
    logo_item, spare_item = items(panel)
    view = admin.get(f"/admin/media/{logo_item.id}").text
    assert "Blog post" in view and "Launch" in view
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:media", "_tw_scope": "row", "_tw_name": "delete",
                                         "_tw_record": str(logo_item.id)})
    assert "This file is in use" in json.dumps(json.loads(r.headers["HX-Trigger"]))
    assert (tmp_path / "storage" / logo).exists() and len(items(panel)) == 2
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:media", "_tw_scope": "bulk", "_tw_name": "delete",
                                         "records": [str(logo_item.id), str(spare_item.id)]})
    note = json.dumps(json.loads(r.headers["HX-Trigger"]))
    assert "Not deleted: logo.png" in note and "1 file(s) deleted" in note
    assert [i.path for i in items(panel)] == [logo]
    assert not (tmp_path / "storage" / spare).exists()


def test_ticket_and_employee_files_count_as_used(admin, panel):
    from tungsten_hr.models import Employee
    from tungsten_tickets.models import Ticket, TicketReply

    manual = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "manual.pdf", b"%PDF-1.4 m", "application/pdf").text,
                          "files")[0]
    with panel.db() as db:
        ticket = Ticket(subject="Printer broken", number="TCK-1")
        db.add(ticket)
        db.flush()
        db.add(TicketReply(ticket_id=ticket.id, body="See the manual", attachments=[manual]))
        db.add(Employee(first_name="Ravi", documents=["hr/documents/x.pdf", manual]))
        db.commit()
    (item,) = items(panel)
    with panel.db() as db:
        used = panel.get_plugin("media").usages(db, item)
    assert sorted(u["label"] for u in used) == ["Employee", "Ticket"]
    view = admin.get(f"/admin/media/{item.id}").text
    assert "TCK-1 Printer broken" in view and "Ravi" in view


def test_unused_file_is_deleted_with_its_file(admin, panel, tmp_path):
    path = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "old.png", png(), "image/png").text, "files")[0]
    (item,) = items(panel)
    admin.post("/admin/_tw/action", {"_tw_host": "resource:media", "_tw_scope": "row", "_tw_name": "delete",
                                     "_tw_record": str(item.id)})
    assert items(panel) == [] and not (tmp_path / "storage" / path).exists()


def test_missing_files_are_found(admin, panel, tmp_path):
    path = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "gone.png", png(), "image/png").text, "files")[0]
    (tmp_path / "storage" / path).unlink()
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:media", "_tw_scope": "page",
                                         "_tw_name": "check_files"})
    assert r.status_code == 204
    assert "1 missing" in admin.get("/admin/media").text  # the toast shows after the page refresh
    (item,) = items(panel)
    assert item.missing
    assert "missing from storage" in admin.get(f"/admin/media/{item.id}").text
    picker = admin.get("/admin/media-library/picker?field=f&form=x&refresh=/admin/_tw/form").text
    assert "gone.png" not in picker  # missing files can't be picked
    # an upload of the same content is not swapped for the missing copy
    again = stored_paths(upload(admin, LIBRARY_UPLOAD, "files", "gone.png", png(), "image/png").text, "files")[0]
    assert again != path and (tmp_path / "storage" / again).exists()


def test_edit_alt_text_and_folder(admin, panel):
    upload(admin, LIBRARY_UPLOAD, "files", "team.png", png(), "image/png")
    (item,) = items(panel)
    assert "Alt text" in admin.get(f"/admin/media/{item.id}/edit").text
    r = admin.post(f"/admin/media/{item.id}/edit", {"name": "team.png", "alt": "Our team at the office",
                                                     "folder": "People/../Team"})
    assert r.status_code == 200, r.text
    (item,) = items(panel)
    assert item.alt == "Our team at the office" and item.folder == "people/team"
    assert panel.get_plugin("media").alt_for(panel.db(), item.path) == "Our team at the office"


def test_hooks_for_other_plugins(panel):
    plugin = panel.get_plugin("media")
    seen = []
    plugin.on_media_added("test", lambda item: seen.append(("added", item.name)))
    plugin.on_media_deleted("test", lambda item: seen.append(("deleted", item.name)))
    plugin.add_usage_finder("test", lambda item: [{"label": "Page", "title": "Home", "url": "/home"}])
    path = panel.storage.save(io.BytesIO(png()), "x.png", "media")
    with panel.db() as db:
        item = plugin.add_file(db, path, name="x.png")
        assert plugin.add_file(db, path) is item  # adding twice keeps one row
        assert plugin.usages(db, item)[0]["title"] == "Home"
        plugin.delete(db, item)
        db.commit()
    assert seen == [("added", "x.png"), ("deleted", "x.png")]
    assert panel.storage.path(path).exists()  # still used (by the finder), so the file stays


def test_a_broken_listener_never_loses_the_upload(admin, panel):
    plugin = panel.get_plugin("media")
    plugin.on_media_added("broken", lambda item: 1 / 0)
    r = upload(admin, LIBRARY_UPLOAD, "files", "ok.png", png(), "image/png")
    assert stored_paths(r.text, "files") and len(items(panel)) == 1


def test_image_sizes_and_helpers():
    assert image_size(io.BytesIO(png(5, 7))) == (5, 7)
    assert image_size(io.BytesIO(b"GIF89a" + struct.pack("<HH", 10, 20) + b"\x00" * 30)) == (10, 20)
    jpeg = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 600, 800) + b"\x00" * 12)
    assert image_size(io.BytesIO(jpeg)) == (800, 600)
    vp8x = b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x00" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    assert image_size(io.BytesIO(vp8x)) == (100, 50)
    bmp = b"BM" + b"\x00" * 16 + struct.pack("<ii", 4, -3) + b"\x00" * 10
    assert image_size(io.BytesIO(bmp)) == (4, 3)
    assert image_size(io.BytesIO(b"\xff\xd8\xff")) is None
    assert image_size(io.BytesIO(b"not an image at all, just text....")) is None
    assert image_size(io.BytesIO(b"")) is None
    assert kind_of("application/pdf", "a.pdf") == "document" and kind_of("video/mp4") == "video"
    assert kind_of("application/zip", "a.zip") == "other"
    assert human_size(0) == "0 B" and human_size(2048) == "2 KB" and human_size(1536 * 1024) == "1.5 MB"
    assert clean_folder(" Blog / ../ Covers// ") == "blog/covers" and clean_folder(None) == ""



def test_picker_shows_in_action_modals(admin, panel):
    from tungsten_tickets.models import Ticket

    with panel.db() as db:
        db.add(Ticket(subject="Help", number="TCK-9"))
        db.commit()
    modal = admin.client.get("/admin/_tw/action?_tw_host=resource:tickets&_tw_scope=page&_tw_name=reply&_tw_record=1",
                             headers={"HX-Request": "true"}).text
    assert "Choose from library" in modal and "form=tw-action-form" in modal
    library = admin.client.get("/admin/_tw/action?_tw_host=resource:media&_tw_scope=page&_tw_name=upload",
                               headers={"HX-Request": "true"}).text
    assert "Upload files" in library and "Choose from library" not in library


def test_file_fields_show_the_real_name(admin, panel):
    r = upload(admin, LIBRARY_UPLOAD, "files", "Price list 2026.pdf", b"%PDF-1.4 p", "application/pdf")
    assert "Price list 2026.pdf" in r.text


def test_capture_off_still_records_library_uploads(admin, panel):
    panel.get_plugin("media").capture_uploads = False
    upload(admin, post_form(admin), "cover_image", "cover.png", png(seed=4), "image/png", {"title": "Hi"})
    assert items(panel) == []  # a blog cover is not collected
    upload(admin, LIBRARY_UPLOAD, "files", "Logo.png", png(seed=5), "image/png")
    assert [i.name for i in items(panel)] == ["Logo.png"]
