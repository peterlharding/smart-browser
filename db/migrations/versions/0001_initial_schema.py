"""Initial schema.

The DDL is not here. It lives in ``db/schema/create/*.sql``, one file per object, with
``create_tables.sql`` as the ordered manifest -- the convention used across these
projects. This revision reads that manifest and executes each file it names, so the schema
is reviewable as SQL, ``psql -f`` still works, and there is one ordering rather than two
that can drift apart.

``bookmark_content`` and ``tag_centroid`` are deliberately absent. They are the only
tables needing pgvector and they arrive at M3 with the crawler that fills them.

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
CREATE_MANIFEST = SCHEMA_DIR / "create" / "create_tables.sql"
DROP_SCRIPT = SCHEMA_DIR / "drop" / "drop_tables.sql"

# psql meta-commands. `\ir` and `\i` name a file to run; `\echo` is progress output that
# means nothing here. Everything else would be a meta-command we do not understand, and
# is rejected rather than silently skipped -- see _strip_meta_commands.
INCLUDE = re.compile(r"^\s*\\ir?\s+(\S+)\s*;?\s*$")
IGNORABLE = re.compile(r"^\s*\\(echo|qecho|set|unset|timing|pset|x)\b")


def included_files(manifest: Path) -> list[Path]:
    """The files *manifest* names, in the order it names them."""
    paths = []
    for line in manifest.read_text().splitlines():
        match = INCLUDE.match(line)
        if match:
            # \ir is relative to the file doing the including, which is the whole reason
            # for preferring it over \i.
            paths.append((manifest.parent / match.group(1)).resolve())
    if not paths:
        raise RuntimeError(f"{manifest} names no files to run")
    return paths


def _strip_meta_commands(sql: str, source: Path) -> str:
    """Remove psql meta-commands, refusing any this runner does not implement.

    A meta-command silently dropped is DDL silently not run. If one of these files grows a
    `\\copy` or a `\\gexec`, this must stop rather than apply a partial schema.
    """
    kept = []
    for number, line in enumerate(sql.splitlines(), start=1):
        if INCLUDE.match(line) or IGNORABLE.match(line):
            continue
        if line.lstrip().startswith("\\"):
            raise RuntimeError(
                f"{source}:{number}: psql meta-command {line.strip()!r} is not supported "
                f"by the migration runner. Move it out of the file, or teach "
                f"{Path(__file__).name} to handle it."
            )
        kept.append(line)
    return "\n".join(kept)


def run_script(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{path} is named by the manifest but does not exist")
    sql = _strip_meta_commands(path.read_text(), path)
    if sql.strip():
        op.execute(sql)


def upgrade() -> None:
    for path in included_files(CREATE_MANIFEST):
        run_script(path)


def downgrade() -> None:
    run_script(DROP_SCRIPT)
