"""Initial schema.

The DDL is not here. It lives in ``db/schema/create/*.sql``, one file per object, with
``create_tables.sql`` as this revision's ordered manifest -- the convention used across
these projects. This revision reads that manifest and executes each file it names, so the
schema is reviewable as SQL, ``psql -f`` still works, and there is one ordering rather
than two that can drift apart. The runner itself is in ``../sqlrunner.py``, shared with
later revisions.

``bookmark_content`` and ``crawl_job`` are deliberately absent: they arrive in 0002 with
the crawler that fills them.

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

from pathlib import Path

from sqlrunner import run_manifest, run_script

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
CREATE_MANIFEST = SCHEMA_DIR / "create" / "create_tables.sql"
DROP_SCRIPT = SCHEMA_DIR / "drop" / "drop_tables.sql"


def upgrade() -> None:
    run_manifest(CREATE_MANIFEST)


def downgrade() -> None:
    run_script(DROP_SCRIPT)
