---
title: Media library
description: Keep every image and file of your panel in one place. Upload once, add alt text, see where a file is used, and pick it again from any file field.
---

The `tungsten-media-library` plugin keeps every image and file of your panel in one place. Upload a file once, give it alt text, and reuse it anywhere: a blog cover, a ticket reply or an employee's documents. It works like Curator for Filament.

## Install

```bash
pip install tungsten-media-library
```

```python
from tungsten import LocalStorage
from tungsten_media_library import MediaLibraryPlugin

panel = Panel(..., storage=LocalStorage("storage", public=True))   # public=True: images show on your website
panel.plugin(MediaLibraryPlugin())
panel.create_tables(engine)
```

This adds **Media library** under a **Content** menu, and a **Choose from library** button under every file field of the panel. It needs `tungsten-admin` 0.1.8 or newer.

Use `public=True` on the storage only when the files are meant for a public site (blog images, product photos). Without it, files open only for signed-in users.

## The library screen

- **Upload files** adds many files at once (up to 20, 20 MB each by default). Pick a folder to keep them tidy.
- **Tabs**: All, Images, Documents, Videos, Audio, Other.
- **Search** by file name, title or alt text. **Filters**: folder, missing files, has alt text.
- **Open a file** to see a big preview, its link and a ready **Markdown** line to paste into a post, and **Used in**: every blog post, ticket or employee that uses it.
- **Edit** the name, title, **alt text**, caption, folder and tags.
- **Bulk actions**: move to a folder, delete.
- **Check files** finds entries whose file was deleted from the disk. They show in red and can't be picked.

## Choose from library

Every file field in the panel gets a **Choose from library** button. It opens a grid of your files with search. Click a file and the field takes it. No second copy is uploaded.

- An image field (like a blog cover) shows only images. A field that takes `.pdf` shows only PDFs.
- Files that are missing from storage are not shown.
- It keeps working when the form around it refreshes.
- The button only shows to users who may see the library (`media.view_any` with roles on).

## Everything in one place

Files uploaded through any file field of the panel join the library on their own, with their real name, type, size and pixel size. A blog cover uploaded on a post shows up in the library under the **blog** folder.

Some folders stay private and are **not** added: `tickets` (customer attachments), `hr` (employee documents) and `imports`. You can still attach a library file to a ticket or an employee.

```python
MediaLibraryPlugin(private_directories=("imports", "tickets", "hr", "invoices"))
```

## Same file twice

When someone uploads a file the library already has (same content), the panel keeps the copy it has and deletes the new one. Turn this off with `dedupe=False`.

## Safe delete

A file that a blog post, ticket reply or employee still uses can't be deleted. The library tells you where it is used, so you can remove it there first. Bulk delete skips files in use and names them. Deleting a file also removes it from storage.

Turn this off with `protect_used=False`.

## Works with other plugins

| Plugin | What you get |
| --- | --- |
| Blog | Covers, social images and author photos from the library. Posts that use a file show in **Used in**. Copy the Markdown line into a post. |
| Help desk | Attach library files (manuals, price lists) to replies and notes. Ticket attachments stay out of the library. |
| HR | Attach library files (policies, letters) to employees. Employee documents stay out of the library. |
| Tags | Library tags become shared, colored tags with a tag filter. |
| Quick create | An **Upload files** entry in the **+ New** menu. |
| PWA | A **Media library** shortcut on the installed app's icon. |

None of these is needed. The library works on its own.

## Options

```python
MediaLibraryPlugin(
    capture_uploads=True,      # add files uploaded anywhere in the panel
    picker=True,               # "Choose from library" on every file field
    dedupe=True,               # same file twice: keep one copy
    private_directories=("imports", "tickets", "hr"),
    directory="media",         # where the library's own uploads go
    max_size=20480,            # kilobytes per file
    max_files=20,              # files per upload
    accepted_file_types=None,  # e.g. ["image/*", ".pdf"]
    protect_used=True,         # don't delete files in use
    navigation_group="Content",
    per_page=24,               # files per page in the picker
)
```

## Hooks for your code

```python
media = panel.get_plugin("media")

media.on_media_added("tags", lambda db, item: ...)       # a file joined the library
media.on_media_deleted("cdn", lambda db, item: ...)      # a file was deleted

# your own table holds file paths: count it in "Used in" and safe delete
media.track("products", Product, "image", "gallery", label="Product")

# or answer yourself
media.add_usage_finder("pages", lambda db, item: [{"label": "Page", "title": "Home", "url": "/admin/pages/1"}])

media.url(path)               # link to a file
media.alt_for(db, path)       # its alt text, for your public pages
media.add_file(db, path, name="Logo.png", folder="brand")   # add a file you stored yourself
```

`track` reads a text column as one path, and a JSON or long text column as "mentions the path".

## Core hooks it uses

The plugin is built on small panel hooks that any plugin can use:

- `panel.on_upload(key, fn)` runs after a form upload is stored. Return another path to use it instead.
- `panel.on_file_pick(key, fn)` lets file fields take an already stored file (`file.pick` UI action).
- `panel.on_file_names(key, fn)` shows real file names in file fields instead of the stored id.
- The `forms.file-upload.after` render hook adds HTML under every file field.
