"""Tag logic that works with any SQLAlchemy model.

Every function takes ``db``: an ORM ``Session`` or a Core ``Connection`` (the tags plugin
also calls them from inside a flush). Records are found by table name and primary key,
so no foreign key to your tables is needed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from sqlalchemy import String, and_, cast, delete, exists, false, func, insert, select
from sqlalchemy import inspect as sa_inspect

from .models import Tag, Tagging

#: longest tag name; longer names are cut
MAX_LENGTH = 50
#: badge colors a tag can have (all exist in the panel's stylesheet)
COLORS = {
    "gray": "Gray", "primary": "Brand", "info": "Blue", "success": "Green", "warning": "Amber",
    "danger": "Red", "purple": "Purple", "indigo": "Indigo", "teal": "Teal", "pink": "Pink",
}

_tags = Tag.__table__
_taggings = Tagging.__table__
_SPACES = re.compile(r"\s+")
# stay under SQLite's limit of bound parameters in one query
_CHUNK = 500


# ---------------------------------------------------------------------- names
def clean_name(name: Any) -> str | None:
    """Tidy one tag name: no control characters, single spaces, at most 50 characters."""
    if name is None:
        return None
    text = "".join(ch for ch in str(name) if unicodedata.category(ch)[0] != "C" or ch in " \t\n")
    text = _SPACES.sub(" ", text).strip()[:MAX_LENGTH].strip()
    return text or None


def tag_key(name: str) -> str:
    """The name in lower case: "VIP", "vip" and "Vip" are the same tag."""
    return name.casefold()[:MAX_LENGTH]


def clean_names(names: Any) -> list[str]:
    """Tidy a list of names (or one comma separated string): drop blanks and repeats, keep order."""
    if names is None:
        return []
    if isinstance(names, str):
        names = names.split(",")
    out: dict[str, str] = {}
    for raw in names:
        name = clean_name(raw)
        if name is not None:
            out.setdefault(tag_key(name), name)
    return list(out.values())


# ---------------------------------------------------------------------- records
def model_type(model: Any) -> str:
    """The name taggings use for a model: its (base) table name."""
    mapper = sa_inspect(model)
    return mapper.base_mapper.local_table.name


def primary_key(model: Any) -> Any:
    keys = sa_inspect(model).primary_key
    if len(keys) != 1:
        raise ValueError(f"Tags need a model with one primary key column; {model.__name__} has {len(keys)}.")
    return keys[0]


def record_ref(record: Any) -> tuple[str, str | None]:
    """``(taggable_type, taggable_id)`` of a record. The id is None while the record is not saved."""
    model = type(record)
    pk = primary_key(model)
    value = getattr(record, sa_inspect(model).get_property_by_column(pk).key, None)
    return model_type(model), (None if value is None else str(value))


def tagged(model: Any, tag_ids: Iterable[int], match: str = "any") -> Any:
    """A WHERE condition: records of ``model`` with any (or ``match="all"``) of these tags."""
    ids = [int(i) for i in tag_ids]
    pk = cast(getattr(model, sa_inspect(model).get_property_by_column(primary_key(model)).key), String)
    kind = model_type(model)

    def has(condition: Any) -> Any:
        return exists().where(Tagging.taggable_type == kind, Tagging.taggable_id == pk, condition)

    if not ids:
        return false()
    if match == "all":
        return and_(*(has(Tagging.tag_id == i) for i in ids))
    return has(Tagging.tag_id.in_(ids))


# ---------------------------------------------------------------------- tags
def find_tags(db: Any, names: Iterable[str], type: str = "") -> dict[str, Any]:
    """Existing tags of ``type`` for these names, by key."""
    keys = list(dict.fromkeys(tag_key(n) for n in names))
    found: dict[str, Any] = {}
    for start in range(0, len(keys), _CHUNK):
        rows = db.execute(select(_tags.c.id, _tags.c.name, _tags.c.key, _tags.c.color)
                          .where(_tags.c.type == type, _tags.c.key.in_(keys[start:start + _CHUNK])))
        for row in rows:
            found[row.key] = row
    return found


def ensure_tags(db: Any, names: Any, type: str = "", create: bool = True, color: str = "gray") -> list[Any]:
    """The tags for ``names``, in that order, made when missing (unless ``create=False``).

    Rows have ``id``, ``name``, ``key`` and ``color``. Names keep the spelling of the existing tag.
    """
    names = clean_names(names)
    if not names:
        return []
    found = find_tags(db, names, type)
    missing = [n for n in names if tag_key(n) not in found]
    if missing and create:
        db.execute(insert(_tags), [{"name": n, "key": tag_key(n), "type": type, "color": color, "sort": 0}
                                   for n in missing])
        found.update(find_tags(db, missing, type))
    return [found[tag_key(n)] for n in names if tag_key(n) in found]


def tag_names(db: Any, type: str = "") -> list[str]:
    """Every tag name of ``type``, for suggestions."""
    return list(db.execute(select(_tags.c.name).where(_tags.c.type == type)
                           .order_by(_tags.c.sort, func.lower(_tags.c.name))).scalars())


def tag_options(db: Any, type: str = "") -> dict[int, str]:
    rows = db.execute(select(_tags.c.id, _tags.c.name).where(_tags.c.type == type)
                      .order_by(_tags.c.sort, func.lower(_tags.c.name)))
    return {row.id: row.name for row in rows}


def tag_colors(db: Any, type: str = "") -> dict[str, str]:
    """Color of every tag of ``type``, by key."""
    rows = db.execute(select(_tags.c.key, _tags.c.color).where(_tags.c.type == type))
    return {row.key: row.color or "gray" for row in rows}


# ---------------------------------------------------------------------- taggings
def record_tags(db: Any, kind: str, ids: Iterable[str], type: str | None = "") -> dict[str, list[Any]]:
    """Tags of many records at once: ``{record id: [rows with name/color/id]}``, sorted by name."""
    ids = list(dict.fromkeys(str(i) for i in ids if i is not None))
    out: dict[str, list[Any]] = {i: [] for i in ids}
    for start in range(0, len(ids), _CHUNK):
        query = (select(_taggings.c.taggable_id, _tags.c.id, _tags.c.name, _tags.c.key, _tags.c.color)
                 .join(_tags, _tags.c.id == _taggings.c.tag_id)
                 .where(_taggings.c.taggable_type == kind, _taggings.c.taggable_id.in_(ids[start:start + _CHUNK]))
                 .order_by(_tags.c.sort, func.lower(_tags.c.name)))
        if type is not None:
            query = query.where(_tags.c.type == type)
        for row in db.execute(query):
            out[row.taggable_id].append(row)
    return out


def set_record_tags(db: Any, kind: str, record_id: str, tag_ids: Iterable[int], type: str | None = "") -> None:
    """Make exactly these tags (of ``type``) sit on the record. Tags of other types stay."""
    wanted = list(dict.fromkeys(int(i) for i in tag_ids))
    current_query = select(_taggings.c.tag_id).where(
        _taggings.c.taggable_type == kind, _taggings.c.taggable_id == record_id)
    if type is not None:
        current_query = current_query.join(_tags, _tags.c.id == _taggings.c.tag_id).where(_tags.c.type == type)
    current = set(db.execute(current_query).scalars())
    gone = current - set(wanted)
    if gone:
        db.execute(delete(_taggings).where(_taggings.c.taggable_type == kind, _taggings.c.taggable_id == record_id,
                                           _taggings.c.tag_id.in_(gone)))
    new = [i for i in wanted if i not in current]
    if new:
        db.execute(insert(_taggings), [{"tag_id": i, "taggable_type": kind, "taggable_id": record_id} for i in new])


def add_record_tags(db: Any, kind: str, record_id: str, tag_ids: Iterable[int]) -> None:
    wanted = list(dict.fromkeys(int(i) for i in tag_ids))
    if not wanted:
        return
    current = set(db.execute(select(_taggings.c.tag_id).where(
        _taggings.c.taggable_type == kind, _taggings.c.taggable_id == record_id,
        _taggings.c.tag_id.in_(wanted))).scalars())
    new = [i for i in wanted if i not in current]
    if new:
        db.execute(insert(_taggings), [{"tag_id": i, "taggable_type": kind, "taggable_id": record_id} for i in new])


def remove_record_tags(db: Any, kind: str, record_id: str, tag_ids: Iterable[int]) -> None:
    ids = [int(i) for i in tag_ids]
    if ids:
        db.execute(delete(_taggings).where(_taggings.c.taggable_type == kind, _taggings.c.taggable_id == record_id,
                                           _taggings.c.tag_id.in_(ids)))


def forget_record(db: Any, kind: str, record_id: str) -> None:
    """Drop every tag of a deleted record, so a new record that reuses its id starts clean."""
    db.execute(delete(_taggings).where(_taggings.c.taggable_type == kind, _taggings.c.taggable_id == record_id))


def usage(db: Any, tag_ids: Iterable[int] | None = None) -> dict[int, int]:
    """How many records carry each tag."""
    query = select(_taggings.c.tag_id, func.count()).group_by(_taggings.c.tag_id)
    if tag_ids is not None:
        query = query.where(_taggings.c.tag_id.in_(list(tag_ids)))
    return {row[0]: int(row[1]) for row in db.execute(query)}


def tagged_ids(db: Any, tag_id: int, kind: str | None = None) -> list[str]:
    query = select(_taggings.c.taggable_id).where(_taggings.c.tag_id == tag_id)
    if kind is not None:
        query = query.where(_taggings.c.taggable_type == kind)
    return list(db.execute(query).scalars())


def type_counts(db: Any, tag_id: int) -> dict[str, int]:
    """How many records of each table carry the tag."""
    rows = db.execute(select(_taggings.c.taggable_type, func.count()).where(_taggings.c.tag_id == tag_id)
                      .group_by(_taggings.c.taggable_type))
    return {row[0]: int(row[1]) for row in rows}


def move_taggings(db: Any, source_id: int, target_id: int) -> None:
    """Put the target tag on every record that has the source tag, then drop the source's taggings."""
    rows = db.execute(select(_taggings.c.taggable_type, _taggings.c.taggable_id)
                      .where(_taggings.c.tag_id == source_id)).all()
    by_kind: dict[str, list[str]] = {}
    for kind, record_id in rows:
        by_kind.setdefault(kind, []).append(record_id)
    for kind, ids in by_kind.items():
        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start:start + _CHUNK]
            have = set(db.execute(select(_taggings.c.taggable_id).where(
                _taggings.c.tag_id == target_id, _taggings.c.taggable_type == kind,
                _taggings.c.taggable_id.in_(chunk))).scalars())
            new = [i for i in chunk if i not in have]
            if new:
                db.execute(insert(_taggings), [{"tag_id": target_id, "taggable_type": kind, "taggable_id": i}
                                               for i in new])
    db.execute(delete(_taggings).where(_taggings.c.tag_id == source_id))


def forget_tag(db: Any, tag_id: int) -> None:
    """Take a tag off every record (before the tag itself is deleted)."""
    db.execute(delete(_taggings).where(_taggings.c.tag_id == tag_id))


def drop_orphans(db: Any, model: Any) -> int:
    """Remove taggings of ``model`` records that no longer exist. Returns how many."""
    pk = getattr(model, sa_inspect(model).get_property_by_column(primary_key(model)).key)
    alive = select(cast(pk, String))
    result = db.execute(delete(_taggings).where(_taggings.c.taggable_type == model_type(model),
                                                _taggings.c.taggable_id.not_in(alive)))
    return int(result.rowcount or 0)
