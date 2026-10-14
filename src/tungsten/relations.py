"""Linking records through relationships, for relation managers.

:class:`RelationLink` knows how to list, link and unlink the records of one relationship
(or a dotted path of them), including the cases SQLAlchemy can't do with a plain
``collection.append``:

* extra columns on the link table of a many-to-many (``AttachAction().form([...])``),
* polymorphic links, where a type column must be filled too (see :func:`morph_many`),
* "has many through" paths (``"teams.projects"``), which are read-only.

Polymorphic relationships, Laravel style::

    from tungsten.relations import morph_many, morph_to_many

    class Post(Base):
        comments = morph_many("Comment", "commentable")             # comments.commentable_id/_type
        tags = morph_to_many("Tag", "taggable", table="taggables")  # taggables.taggable_id/_type/tag_id

    class Video(Base):
        comments = morph_many("Comment", "commentable")

The type stored is the owner's table name (``"posts"``), or pass ``type="post"``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BindParameter, and_, delete, insert, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import declared_attr, relationship, with_parent
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression


def morph_many(target: str, name: str, *, type: str | None = None, id_column: str | None = None,
               type_column: str | None = None, owner_key: str = "id", **kwargs: Any) -> Any:
    """A polymorphic one-to-many: ``target`` rows point back with ``<name>_id`` and ``<name>_type``.

    Several models can own the same kind of row (comments on posts and on videos). The
    relationship is read-only for SQLAlchemy (``viewonly``); relation managers still create,
    associate and dissociate records on it, filling both columns.
    """
    id_col = id_column or f"{name}_id"
    type_col = type_column or f"{name}_type"

    def make(cls: Any) -> Any:
        value = type or cls.__tablename__
        join = (f"and_({cls.__name__}.{owner_key} == foreign({target}.{id_col}), "
                f"{target}.{type_col} == {value!r})")
        return relationship(target, primaryjoin=join, viewonly=True, **kwargs)

    return declared_attr(make)


def morph_to_many(target: str, name: str, *, table: str, type: str | None = None, id_column: str | None = None,
                  type_column: str | None = None, target_column: str | None = None, owner_key: str = "id",
                  target_key: str = "id", **kwargs: Any) -> Any:
    """A polymorphic many-to-many through ``table`` (``<name>_id``, ``<name>_type``, ``<target>_id``).

    Attach and detach in a relation manager write the type column too.
    """
    id_col = id_column or f"{name}_id"
    type_col = type_column or f"{name}_type"

    def make(cls: Any) -> Any:
        value = type or cls.__tablename__
        tcol = target_column or f"{target.lower()}_id"
        primary = f"and_({cls.__name__}.{owner_key} == foreign({table}.c.{id_col}), {table}.c.{type_col} == {value!r})"
        secondary = f"{target}.{target_key} == foreign({table}.c.{tcol})"
        return relationship(target, secondary=table, primaryjoin=primary, secondaryjoin=secondary,
                            viewonly=True, **kwargs)

    return declared_attr(make)


def _literals(clause: Any) -> list[tuple[Any, Any]]:
    """``column == 'value'`` conditions in a join (the type column of a polymorphic link)."""
    out = []
    if clause is None:
        return out
    for el in visitors.iterate(clause):
        if not isinstance(el, BinaryExpression) or el.operator is not operators.eq:
            continue
        left, right = el.left, el.right
        if isinstance(left, BindParameter):
            left, right = right, left
        if isinstance(right, BindParameter) and getattr(left, "table", None) is not None:
            out.append((left, right.effective_value))
    return out


def _same(a: Any, b: Any) -> bool:
    return a.name == b.name and getattr(a.table, "name", None) == getattr(b.table, "name", None)


def _prop_key(mapper: Any, column: Any) -> str:
    for prop in mapper.column_attrs:
        if any(_same(c, column) for c in prop.columns):
            return prop.key
    raise KeyError(column)


class RelationLink:
    """One relationship (``"tags"``) or a path (``"teams.projects"``) starting at ``owner_model``."""

    def __init__(self, owner_model: Any, path: str, linkable: bool | None = None) -> None:
        self.owner_model = owner_model
        self.path = path
        mapper = sa_inspect(owner_model)
        self.rels = []
        for part in path.split("."):
            rel = mapper.relationships[part]
            self.rels.append(rel)
            mapper = rel.mapper
        self.rel = self.rels[0]
        self.through = len(self.rels) > 1
        self.model = mapper.class_
        self.many_to_many = not self.through and self.rel.secondary is not None
        literals = _literals(self.rel.primaryjoin) + _literals(self.rel.secondaryjoin)
        self.literals = literals
        if linkable is None:
            # a read-only relationship can still be linked when it is a polymorphic one (a type column)
            linkable = not self.through and (not self.rel.viewonly or bool(literals))
        self.linkable = linkable

    # ------------------------------------------------------------------ query
    def query(self, owner: Any):
        if not self.through:
            return select(self.model).where(with_parent(owner, getattr(type(owner), self.rel.key)))
        first = self.rels[0].mapper.class_
        target_pk = sa_inspect(self.model).primary_key[0]
        keys = select(target_pk).select_from(first)
        prev = first
        for rel in self.rels[1:]:
            keys = keys.join(getattr(prev, rel.key))
            prev = rel.mapper.class_
        keys = keys.where(with_parent(owner, getattr(type(owner), self.rels[0].key)))
        return select(self.model).where(target_pk.in_(keys))

    def count(self, db: Any, owner: Any) -> int:
        from sqlalchemy import func

        return int(db.scalar(select(func.count()).select_from(self.query(owner).subquery())) or 0)

    # ------------------------------------------------------------------ helpers
    def _owner_values(self, owner: Any) -> dict[Any, Any]:
        """Link-table (or child) column -> value that points at ``owner``."""
        mapper = sa_inspect(type(owner))
        return {remote: getattr(owner, _prop_key(mapper, local)) for local, remote in self.rel.synchronize_pairs}

    def _target_values(self, record: Any) -> dict[Any, Any]:
        mapper = sa_inspect(type(record))
        return {sec: getattr(record, _prop_key(mapper, col)) for col, sec in self.rel.secondary_synchronize_pairs}

    def _secondary_literals(self) -> dict[Any, Any]:
        sec = self.rel.secondary
        return {col: value for col, value in self.literals if getattr(col.table, "name", None) == sec.name}

    def _key_columns(self) -> set[str]:
        cols = {c.name for _, c in self.rel.synchronize_pairs}
        cols |= {c.name for _, c in self.rel.secondary_synchronize_pairs}
        cols |= {c.name for c in self._secondary_literals()}
        return cols

    def pivot_columns(self) -> list[str]:
        """Extra columns on the link table (``role``, ``joined_at``...)."""
        if not self.many_to_many:
            return []
        keys = self._key_columns()
        return [c.name for c in self.rel.secondary.columns if c.name not in keys]

    def _expire(self, db: Any, owner: Any) -> None:
        try:
            db.expire(owner, [self.rel.key])
        except Exception:  # noqa: BLE001 - not in this session
            pass

    def _append(self, db: Any, owner: Any, records: list) -> None:
        with db.no_autoflush:  # a new record is not complete until it is in the collection
            collection = getattr(owner, self.rel.key)
            for r in records:
                if r not in collection:
                    collection.append(r)

    def _manual(self) -> bool:
        return self.rel.viewonly or bool(self.literals)

    # ------------------------------------------------------------------ link / unlink
    def link(self, db: Any, owner: Any, records: list, pivot: dict | None = None) -> None:
        if not self.linkable:
            raise PermissionError("This relationship is read-only")
        if not records:
            return
        if self.many_to_many:
            pivot = {k: v for k, v in (pivot or {}).items() if k in self.pivot_columns()}
            if not pivot and not self._manual():
                self._append(db, owner, records)
                return
            db.flush()  # new records need their keys
            sec = self.rel.secondary
            base = {**{c.name: v for c, v in self._owner_values(owner).items()},
                    **{c.name: v for c, v in self._secondary_literals().items()}}
            for r in records:
                values = {**base, **{c.name: v for c, v in self._target_values(r).items()}}
                exists = db.execute(select(sec).where(and_(*[sec.c[k] == v for k, v in values.items()]))).first()
                if exists is None:
                    db.execute(insert(sec).values(**values, **pivot))
            self._expire(db, owner)
            return
        # one-to-many: point the child at the owner
        if not self._manual():
            self._append(db, owner, records)
            return
        values = self._owner_values(owner)
        target = sa_inspect(self.model)
        for r in records:
            for col, value in values.items():
                setattr(r, _prop_key(target, col), value)
            for col, value in self.literals:
                if getattr(col.table, "name", None) == target.local_table.name:
                    setattr(r, _prop_key(target, col), value)
        db.flush()
        self._expire(db, owner)

    def can_unlink_one_to_many(self) -> bool:
        """Dissociating sets the child's link column to empty, so that column must allow NULL."""
        if self.many_to_many or self.through:
            return False
        return all(remote.nullable for _, remote in self.rel.synchronize_pairs)

    def unlink(self, db: Any, owner: Any, records: list) -> None:
        if not self.linkable:
            raise PermissionError("This relationship is read-only")
        if not records:
            return
        if self.many_to_many:
            if not self._manual():
                collection = getattr(owner, self.rel.key)
                for r in records:
                    if r in collection:
                        collection.remove(r)
                return
            sec = self.rel.secondary
            base = {**{c.name: v for c, v in self._owner_values(owner).items()},
                    **{c.name: v for c, v in self._secondary_literals().items()}}
            for r in records:
                values = {**base, **{c.name: v for c, v in self._target_values(r).items()}}
                db.execute(delete(sec).where(and_(*[sec.c[k] == v for k, v in values.items()])))
            self._expire(db, owner)
            return
        if not self.can_unlink_one_to_many():
            raise ValueError("These records must belong to an owner, so they can't be dissociated")
        target = sa_inspect(self.model)
        for r in records:
            for col in self._owner_values(owner):
                setattr(r, _prop_key(target, col), None)
            for col, _ in self.literals:
                if getattr(col.table, "name", None) == target.local_table.name and col.nullable:
                    setattr(r, _prop_key(target, col), None)
        db.flush()
        self._expire(db, owner)

    # ------------------------------------------------------------------ pivot data
    def load_pivots(self, db: Any, owner: Any, records: list) -> None:
        """Set ``record.pivot`` (extra link-table columns) on each related record."""
        from .forms.fields import DataRecord

        extra = self.pivot_columns()
        if not extra or not records:
            return
        sec = self.rel.secondary
        conds = [sec.c[c.name] == v for c, v in self._owner_values(owner).items()]
        conds += [sec.c[c.name] == v for c, v in self._secondary_literals().items()]
        pairs = self.rel.secondary_synchronize_pairs
        if len(pairs) != 1:
            return
        col, sec_col = pairs[0]
        key = _prop_key(sa_inspect(self.model), col)
        by_key = {getattr(r, key): r for r in records}
        rows = db.execute(select(sec).where(and_(*conds), sec.c[sec_col.name].in_(list(by_key)))).mappings().all()
        found = {row[sec_col.name]: row for row in rows}
        for value, record in by_key.items():
            row = found.get(value)
            data = {c: (row[c] if row is not None else None) for c in extra}
            try:
                record.pivot = DataRecord(data)
            except AttributeError:  # a real attribute called "pivot"
                pass


__all__ = ["RelationLink", "morph_many", "morph_to_many"]
