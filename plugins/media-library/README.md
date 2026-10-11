# tungsten-media-library

Media library plugin for [Tungsten](https://tungsten.prisminfoways.com/): every image and file of your panel in one place. Upload once, add alt text, see where a file is used, and pick it again from any file field. Like Curator for Filament.

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

Needs `tungsten-admin` 0.1.8 or newer.

## What you get

- **Media library** screen: upload many files at once, folders, search, tabs by type (images, documents, videos, audio), alt text, captions and tags.
- **Choose from library** under every file field of the panel: a grid with search. Image fields show only images.
- **Everything in one place**: files uploaded anywhere in the panel (like a blog cover) join the library with their real name, type, size and pixel size. Ticket attachments, HR documents and imports stay private.
- **Same file twice** is stored once.
- **Used in**: see every blog post, ticket or employee that uses a file. Files in use can't be deleted by mistake.
- **Copy link** and a ready **Markdown** line for blog posts.
- **Check files** finds entries whose file is gone from the disk.

## Works with other plugins

- **Blog** (`tungsten-blog`): covers, social images and author photos from the library; posts show in "Used in".
- **Help desk** (`tungsten-tickets`): attach library files to replies and notes.
- **HR** (`tungsten-hr`): attach library files to employees.
- **Tags** (`tungsten-tags`): shared, colored tags and a tag filter.
- **Quick create** (`tungsten-quick-create`): "Upload files" in the + New menu.
- **PWA** (`tungsten-pwa`): a "Media library" shortcut on the app icon.

None of them is needed.

## Options

```python
MediaLibraryPlugin(
    capture_uploads=True,      # add files uploaded anywhere in the panel
    picker=True,               # "Choose from library" on every file field
    dedupe=True,               # same file twice: keep one copy
    private_directories=("imports", "tickets", "hr"),
    max_size=20480,            # kilobytes per file
    max_files=20,              # files per upload
    accepted_file_types=None,  # e.g. ["image/*", ".pdf"]
    protect_used=True,         # don't delete files in use
)
```

## Hooks

```python
media = panel.get_plugin("media")
media.on_media_added("key", lambda db, item: ...)
media.on_media_deleted("key", lambda db, item: ...)
media.track("products", Product, "image", "gallery", label="Product")   # count your own file columns
media.add_usage_finder("key", lambda db, item: [{"label": "Page", "title": "Home", "url": "/admin/pages/1"}])
```

Full guide: https://tungsten.prisminfoways.com/docs/media-library

## Try it

```bash
pip install -e . -e plugins/media-library -e plugins/blog -e plugins/tickets uvicorn
cd plugins/media-library && uvicorn example:app --reload
```

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.

MIT license.
