"""Content and the crawl queue.

``bookmark_content`` holds what the crawler extracted, keyed by URL so the cost is paid
once per page rather than once per person who saved it. ``crawl_job`` is the queue:
written in the same transaction as the bookmark, drained by a separate worker. See
``doc/decisions/0009-crawl-queue-in-postgres.md``.

The DDL is in ``db/schema/create/``, named by ``create_content.sql``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlrunner import run_manifest, run_script

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
CREATE_MANIFEST = SCHEMA_DIR / "create" / "create_content.sql"
DROP_SCRIPT = SCHEMA_DIR / "drop" / "drop_content.sql"
BOOTSTRAP = SCHEMA_DIR / "bootstrap.sql"


def pgvector_message(available: str | None, database: str) -> str:
    """What to tell someone whose database has no `vector` extension.

    *database* is named in the remedy because the extension is per database: the test
    database needs its own bootstrap, and "run make db-bootstrap" against the default one
    would leave a failing `make test-pg` exactly where it was.

    A separate function because the two branches are the whole value of the check and
    neither is reachable from a test without a superuser to take the extension away
    again. This much is testable; the queries in require_pgvector are a few lines.
    """
    if available:
        return (
            f"pgvector {available} is available in this server but not installed in "
            f"database {database!r}, and the migration role cannot install it: pgvector "
            "is not a trusted extension, so CREATE EXTENSION requires a superuser.\n"
            "Run it once, as postgres:\n"
            f"    make db-bootstrap DB={database}\n"
            f"which applies {BOOTSTRAP}."
        )
    return (
        "pgvector is not available in this PostgreSQL server, so the embedding columns "
        "cannot be created. Use an image that ships it (pgvector/pgvector:pg18) or "
        "install the extension package for this server, then run "
        f"`make db-bootstrap DB={database}`."
    )


def require_pgvector() -> None:
    """Stop with the fix in hand, rather than on `type "vector" does not exist`.

    pgvector is not a trusted extension, so `CREATE EXTENSION vector` needs a superuser --
    which the role running migrations deliberately is not. This is the one piece of schema
    a migration cannot apply itself, so the least it can do is say so precisely. The same
    reasoning as the schema guard: a missing precondition should name its own remedy.

    Raising here leaves nothing behind: alembic runs the whole upgrade in one transaction,
    so a database that was at base stays at base -- no tables, no alembic_version row --
    rather than stopping half-migrated. Verified by hand against a database without the
    extension; it needs a superuser to arrange, which is why no test does it.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    installed = bind.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if installed:
        return

    available = bind.execute(
        sa.text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
    ).scalar()
    database = bind.execute(sa.text("SELECT current_database()")).scalar_one()
    raise RuntimeError(pgvector_message(available, database))


def upgrade() -> None:
    require_pgvector()
    run_manifest(CREATE_MANIFEST)


def downgrade() -> None:
    run_script(DROP_SCRIPT)
