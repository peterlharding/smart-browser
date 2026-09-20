"""M0 safety: sequences and the missing indexes.

Additive only. Nothing is dropped, renamed or retyped, and no constraint is added that
existing data would violate, so the v1 FastAPI app keeps working with this applied.

The DDL lives in ``migrations/sql/0001_m0_safety.sql`` rather than inline here. That keeps
it reviewable as SQL, keeps ``psql -f`` working in an emergency, and leaves exactly one
copy of the statements.

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0001_m0_safety.sql"

# Statements after this marker cannot run inside a transaction (CREATE INDEX CONCURRENTLY).
AUTOCOMMIT_MARKER = "###AUTOCOMMIT###"


def _split_sql() -> tuple[str, str]:
    text = SQL_FILE.read_text()
    if AUTOCOMMIT_MARKER not in text:
        return text, ""
    head, _, tail = text.partition(AUTOCOMMIT_MARKER)
    return head, tail


def upgrade() -> None:
    transactional, concurrent = _split_sql()

    op.execute(transactional)

    if concurrent.strip():
        # CREATE INDEX CONCURRENTLY cannot run in a transaction; Alembic opens a
        # transaction for the migration, so this block steps outside it.
        with op.get_context().autocommit_block():
            op.execute(concurrent)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index in (
            "bookmark_url_idx",
            "bookmark_tag_tag_fk_idx",
            "bookmark_tag_bookmark_fk_idx",
            "bookmark_used_idx",
        ):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index}")

    for table in ("bookmark", "tag", "bookmark_tag"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS bookmark_id_seq, tag_id_seq, bookmark_tag_id_seq")
