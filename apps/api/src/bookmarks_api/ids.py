"""Primary-key allocation.

The existing tables have no sequences -- `id` is a plain integer with a primary key and
no default -- so the v1 app allocates with `SELECT MAX(id)+1` in Python. That races: two
concurrent saves read the same max and one insert fails, or worse, silently wins.

migrations/0001_m0_safety.sql creates real sequences and attaches them as defaults. Until
that has been applied, `next_id` provides a safe fallback by taking a transaction-scoped
advisory lock, which serialises allocation without blocking reads.

Once 0001 is applied this module is dead code and the INSERTs can simply omit `id`.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

_LOCK_NAMESPACE = 0x424D  # "BM"


def sequences_installed(db: Session, table: str) -> bool:
    """Does *table* have a real sequence backing its id?

    Non-Postgres backends (the SQLite used by the fast test suite) are reported as
    installed: their integer primary keys autoincrement, so the advisory-lock fallback
    is neither needed nor available there.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return True
    return bool(
        db.execute(
            text("SELECT pg_get_serial_sequence(:t, 'id') IS NOT NULL"), {"t": table}
        ).scalar()
    )


def next_id(db: Session, table: str) -> int:
    """Allocate the next id for *table*, serialised by advisory lock.

    Must be called inside a transaction: the lock is released at commit or rollback.
    """
    if table not in {"bookmark", "tag", "bookmark_tag"}:
        raise ValueError(f"refusing to allocate id for unknown table {table!r}")

    if db.bind is not None and db.bind.dialect.name != "postgresql":
        current = db.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar_one()
        return int(current) + 1

    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:t))"),
        {"ns": _LOCK_NAMESPACE, "t": table},
    )
    current = db.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar_one()
    return int(current) + 1
