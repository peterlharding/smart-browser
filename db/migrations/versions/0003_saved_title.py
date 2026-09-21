"""The title as seen at save time.

``user_bookmark.saved_title`` holds the title the client saw when it saved, so that
``title_override`` means only a title a person chose. Existing overrides move into the new
column, because every one of them was written by a client. See
``doc/decisions/0010-title-seen-at-save.md``.

The DDL is in ``db/schema/create/``, named by ``create_saved_title.sql``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21
"""

from __future__ import annotations

from pathlib import Path

from sqlrunner import run_manifest, run_script

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
CREATE_MANIFEST = SCHEMA_DIR / "create" / "create_saved_title.sql"
DROP_SCRIPT = SCHEMA_DIR / "drop" / "drop_saved_title.sql"


def upgrade() -> None:
    run_manifest(CREATE_MANIFEST)


def downgrade() -> None:
    run_script(DROP_SCRIPT)
