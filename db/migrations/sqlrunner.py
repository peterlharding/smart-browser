"""Run the `.sql` files a psql manifest names.

Shared by every revision, so the rule "the DDL lives in ``db/schema``" has one
implementation rather than one per migration. See ``versions/0001_initial_schema.py``
for why the schema is SQL files at all.

Imported by revision modules; ``env.py`` puts this directory on ``sys.path``.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

# psql meta-commands. `\ir` and `\i` name a file to run; `\echo` is progress output that
# means nothing here. Everything else would be a meta-command we do not understand, and
# is rejected rather than silently skipped -- see strip_meta_commands.
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


def strip_meta_commands(sql: str, source: Path) -> str:
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
                f"sqlrunner.py to handle it."
            )
        kept.append(line)
    return "\n".join(kept)


def run_script(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{path} is named by the manifest but does not exist")
    sql = strip_meta_commands(path.read_text(), path)
    if sql.strip():
        op.execute(sql)


def run_manifest(manifest: Path) -> None:
    for path in included_files(manifest):
        run_script(path)
