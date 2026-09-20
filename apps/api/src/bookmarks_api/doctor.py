"""Answer 'which database am I actually talking to?'.

Written after a migration reported success against 'page_history' while psql, pointed at
what looked like the same database, found no tables. Two things make that possible and
neither is visible from either side alone: the settings can resolve to a different host or
port than you think, and several Postgres instances can each hold a database of the same
name owned by a role of the same name.

So this prints where the settings point, and then asks the server it reaches to identify
itself -- port and data directory, which no two running instances share.

    uv run python -m bookmarks_api.doctor
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from .config import ENV_FILES, ConfigurationError, get_settings
from .schema_guard import REQUIRED_SCHEMA_REVISION

EXPECTED_TABLES = [
    "app_user", "user_identity", "bookmark", "user_bookmark",
    "tag", "tag_alias", "bookmark_tag", "alembic_version",
]


def main() -> int:
    print("env files, in order (later wins):")
    for path in ENV_FILES:
        print(f"  {path}  {'found' if path.exists() else 'absent'}")

    # Real environment variables beat both files, so a DB_* exported by a shell profile,
    # a direnv .envrc or a venv activate script silently wins and nothing in the files
    # explains where the connection went. Worth naming before anything else.
    shadowing = {
        name: ("set" if name.endswith("PASSWORD") else os.environ[name])
        for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
        if name in os.environ
    }
    if shadowing:
        print("\nset in the environment, overriding both files:")
        for name, value in shadowing.items():
            print(f"  {name}={value}")
    else:
        print("\nno DB_* set in the environment; the files decide")

    print(f"\npackage loaded from: {Path(__file__).resolve().parent}")
    if "site-packages" in str(Path(__file__).resolve()):
        print("  ^ installed as a copy, not editable -- the .env paths above are derived")
        print("    from this location and will not be your repo")

    try:
        settings = get_settings()
        url = settings.database_url
    except ConfigurationError as exc:
        print(f"\n{exc}")
        return 1

    print("\nsettings resolve to:")
    print(f"  host     {settings.db_host}")
    print(f"  port     {settings.db_port}")
    print(f"  database {settings.db_name}")
    print(f"  user     {settings.db_user}")
    print(f"  password {'set' if settings.db_password else 'EMPTY'}")

    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            ident = conn.execute(
                text(
                    "SELECT current_database(), current_user, version(), "
                    "       inet_server_addr()::text, inet_server_port(), "
                    "       current_setting('data_directory', true), "
                    "       current_schema(), current_setting('search_path')"
                )
            ).one()

            print("\nthe server actually reached says:")
            print(f"  database        {ident[0]}")
            print(f"  user            {ident[1]}")
            print(f"  server          {ident[2].split(',')[0]}")
            print(f"  listening on    {ident[3]}:{ident[4]}")
            # The one fingerprint no two running instances can share.
            print(f"  data_directory  {ident[5] or '(not readable by this role)'}")
            print(f"  current_schema  {ident[6]}")
            print(f"  search_path     {ident[7]}")

            rows = conn.execute(
                text(
                    "SELECT schemaname, tablename, tableowner FROM pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                    "ORDER BY schemaname, tablename"
                )
            ).all()

            print(f"\ntables visible to this connection: {len(rows)}")
            for schema, table, owner in rows:
                mark = " " if table in EXPECTED_TABLES else "?"
                print(f"  {mark} {schema}.{table}  (owner {owner})")

            found = {t for _, t, _ in rows}
            missing = [t for t in EXPECTED_TABLES if t not in found]
            if missing:
                print(f"\n  MISSING: {', '.join(missing)}")

            if "alembic_version" in found:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                ok = "matches" if rev == REQUIRED_SCHEMA_REVISION else "DOES NOT MATCH"
                print(f"\nalembic_version: {rev}  ({ok} the {REQUIRED_SCHEMA_REVISION} "
                      f"this code requires)")
            else:
                print("\nalembic_version: absent — nothing has migrated this database")
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic; report anything
        print(f"\ncould not connect: {type(exc).__name__}: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
