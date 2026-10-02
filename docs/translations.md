---
title: Translations
description: Show the panel in your users' languages with JSON language files, a language switcher and right-to-left support.
---

Every screen in Tungsten can be translated. Text is looked up by its English wording, so you write your labels in English as usual and add a JSON file per language. Tungsten ships with **Hindi** (`hi`) built in.

## Choosing languages

Set the default language and the languages users can pick from on the panel:

```python
from pathlib import Path

from tungsten import Panel

panel = Panel(
    ...,
    locale="en",                 # default language
    locales=["en", "hi"],        # languages users can choose
    lang_dirs=[Path("lang")],    # folders with your own <code>.json files
)
```

| Option | Default | What it does |
| --- | --- | --- |
| `locale` | `"en"` | The default language. It is always added to `locales`. |
| `locales` | `[locale]` | The languages users can pick. The language switcher appears when there is more than one. |
| `lang_dirs` | `()` | Folders with your language files. Files here override Tungsten's built-in text. |

Language codes are short codes like `hi`, `fr` or `ar`. Regional codes use an underscore, like `pt_BR`.

## Language files

A language file is a JSON object that maps English text to the translation. Name it after the language code and put it in one of your `lang_dirs`:

```json
{
  "Products": "उत्पाद",
  "Low stock only": "सिर्फ़ कम स्टॉक",
  "Order shipped": "ऑर्डर भेजा गया",
  "Welcome, :name": "स्वागत है, :name"
}
```

Saved as `lang/hi.json`.

How files are found and merged:

- Tungsten's own file is loaded first (`tungsten/lang/hi.json`), then yours on top. If both have the same key, yours wins. So you can also change Tungsten's own wording.
- For a regional code like `pt_BR`, `pt.json` is loaded first, then `pt_BR.json` on top.
- Text with no translation, or with an empty translation (`""`), is shown in English.

> [!NOTE]
> Language files are read once and cached. Restart the app after changing them.

## What is translated for you

You don't need to wrap most text yourself. Tungsten translates these when it draws the page:

- resource, page and navigation labels, and navigation groups,
- form field labels, placeholders, helper text, sections, tabs and wizard steps,
- table column labels, filters, list tabs, and options in selects, radios and filters,
- action labels, popup headings and buttons,
- widget headings, stat labels and chart dataset labels,
- toast notifications (`Notification(...).send(ctx)`) and the notification bell,
- validation messages and all of Tungsten's built-in text: login, profile, two-factor, emails and so on.

So this field is translated as long as your `hi.json` has `"Full name"`:

```python
TextInput("name").label("Full name")
```

Labels that Tungsten makes from a field name are translated too. `TextInput("unit_price")` gets the label "Unit price", which is looked up in your file.

## Translating text in Python

For text you build yourself, use `__()`:

```python
from tungsten import Notification, __


def ship(record, db, ctx):
    record.status = "shipped"
    db.commit()
    Notification(__("Order :number shipped", number=record.number)).success().send(ctx)
```

`__(text, **params)` returns the text in the current user's language. `_()` and `translate()` are the same function.

### Placeholders

Placeholders start with a colon: `:name`, `:count`, `:number`. They are filled in after translation, so the translated sentence can put them anywhere:

```json
{"Order :number shipped": "ऑर्डर :number भेज दिया गया"}
```

Keep placeholders in the English key and use `__()` with parameters, not an f-string. With an f-string the key would be different for every order and would never match.

### When to call `__()`

Call `__()` while a request is running: inside a closure, a hook, an action or a class method. At import time no user language is known yet, so text is returned in English.

```python
# Good: runs during the request
TextInput("sku").helper_text(lambda: __("Leave empty to generate one."))

# Also fine: Tungsten translates plain labels for you at render time
TextInput("sku").helper_text("Leave empty to generate one.")

# Not translated: runs once, when the module is imported
HELP = __("Leave empty to generate one.")
```

`Markup(...)` values are treated as finished HTML and are not translated.

## Translating text in templates

In your own Jinja templates (for example a custom page's `content_template`, or an overridden Tungsten template), `__()` and `_()` are available:

```html
<h2>{{ __('Sales report') }}</h2>
<p>{{ __('Welcome, :name', name=user.name) }}</p>
```

## Collecting text with the CLI

`tungsten lang:extract` scans your code and adds every piece of text it finds to a language file, ready to fill in:

```bash
tungsten lang:extract hi --path app
```

```text
  lang/hi.json: 48 new, 48 still to translate
```

It finds:

- text in `__()`, `_()` and `translate()` calls,
- labels, headings, descriptions, placeholders, helper text, option labels and other UI text in your Tungsten classes and calls,
- `__('...')` calls in `.html` templates.

New text is added with an empty value. Text you already translated is kept. The file is sorted alphabetically. Folders named `.venv`, `node_modules`, `__pycache__` and `tests` are skipped.

| Option | Default | What it does |
| --- | --- | --- |
| `LOCALE` (argument) | required | The language code, e.g. `hi`, `gu`, `fr` |
| `--path`, `-p` | `.` | Folder or file to scan. Repeat it to scan several. |
| `--out`, `-o` | `lang` | Folder for `<locale>.json` |
| `--builtin` | off | Also list Tungsten's own text, so you can override it |

Text that Tungsten already translates in its built-in file for that language is left out, unless you pass `--builtin`.

```bash
tungsten lang:extract fr --path app --path templates --out app/lang
```

Then point the panel at the folder:

```python
Panel(..., locales=["en", "fr"], lang_dirs=["app/lang"])
```

> [!TIP]
> Run the command again whenever you add screens. Only new text is added, and empty values fall back to English until you fill them in.

## The language switcher

When `locales` has more than one language, users can switch:

- in the **user menu** (top right), under **Language**,
- at the bottom of the **login** and other sign-in pages.

Languages are shown by their own name, for example "हिन्दी" or "Français". Tungsten knows the names of many common languages. For other codes, the code itself is shown.

The choice is saved in the user's session.

## How the language is picked

For each request, Tungsten uses the first of these that applies:

1. The language the user picked in the switcher.
2. The browser's preferred languages (the `Accept-Language` header), if one of them is in `locales`. A browser asking for `hi-IN` gets `hi`.
3. The panel's default `locale`.

The browser language is only used when `locales` has more than one entry.

## Right-to-left languages

For Arabic (`ar`), Hebrew (`he`), Persian (`fa`) and Urdu (`ur`), the page gets `dir="rtl"`, so the layout is mirrored: the sidebar moves to the right and text runs right to left. The `<html lang="...">` attribute is always set to the current language.

```python
Panel(..., locales=["en", "ar"], lang_dirs=["lang"])   # add lang/ar.json
```

## Finding missing translations

The panel's translator can record text that has no translation. Turn it on during development and print the list:

```python
panel.translator.missing = set()

# ... click through the panel in Hindi ...

print(sorted(panel.translator.missing))
```

## Adding a whole new language

1. Run `tungsten lang:extract gu --path app --builtin` to get all text, yours and Tungsten's.
2. Fill in `lang/gu.json`.
3. Add the code to `locales` and the folder to `lang_dirs`.

```python
Panel(..., locales=["en", "hi", "gu"], lang_dirs=["lang"])
```
