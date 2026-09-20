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
        conn_cm = engine.connect()
    except Exception as exc:  # noqa: BLE001 - diagnostic; report anything
        print(f"\ncould not connect: {type(exc).__name__}: {exc}")
        return 1

    with conn_cm as conn:
        print("\nthe server actually reached says:")
        for label, sql in [
            ("database", "SELECT current_database()"),
            ("database oid", "SELECT oid FROM pg_database WHERE datname = current_database()"),
            ("user", "SELECT current_user"),
            ("server", "SELECT split_part(version(), ',', 1)"),
            ("listening on", "SELECT inet_server_addr()::text || ':' || inet_server_port()"),
            # Privilege-free, and no two running instances share it -- the fingerprint
            # data_directory was meant to be, without needing pg_read_all_settings.
            ("started at", "SELECT pg_postmaster_start_time()"),
            ("data_directory", "SELECT setting FROM pg_settings WHERE name = 'data_directory'"),
            ("current_schema", "SELECT current_schema()"),
            ("search_path", "SELECT current_setting('search_path')"),
        ]:
            # Every probe stands alone. A diagnostic that aborts on the first thing this
            # role may not read is useless exactly when it is needed.
            try:
                result = conn.execute(text(sql)).scalar()
                shown = "(not available)" if result is None else str(result)
                print(f"  {label:<15} {shown}")
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                reason = type(exc).__name__
                if "InsufficientPrivilege" in str(exc) or "permission denied" in str(exc):
                    reason = "permission denied for this role"
                print(f"  {label:<15} (unavailable: {reason})")

        try:
            names = conn.execute(
                text("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1")
            ).scalars().all()
            print(f"\ndatabases on this server: {', '.join(names)}")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            print(f"\ndatabases on this server: (unavailable: {type(exc).__name__})")

        try:
            types = conn.execute(
                text(
                    "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
                    "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = 'public' GROUP BY t.typname ORDER BY t.typname"
                )
            ).all()
            # A type outlives a hand-written table drop, and a database holding one with
            # no tables is exactly the state a half-applied migration leaves behind.
            print(f"\nenum types in this database: {len(types)}")
            for name, labels in types:
                print(f"    {name}  ({', '.join(labels)})")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            print(f"\nenum types: (unavailable: {type(exc).__name__})")

        try:
            rows = conn.execute(
                text(
                    "SELECT schemaname, tablename, tableowner FROM pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                    "ORDER BY schemaname, tablename"
                )
            ).all()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            print(f"\ncould not list tables: {type(exc).__name__}: {exc}")
            return 1

        print(f"\ntables in this database: {len(rows)}")
        for schema, table, owner in rows:
            mark = " " if table in EXPECTED_TABLES else "?"
            print(f"  {mark} {schema}.{table}  (owner {owner})")

        found = {table for _, table, _ in rows}
        missing = [table for table in EXPECTED_TABLES if table not in found]
        if missing:
            print(f"\n  MISSING: {', '.join(missing)}")

        if "alembic_version" in found:
            try:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                verdict = "matches" if rev == REQUIRED_SCHEMA_REVISION else "DOES NOT MATCH"
                print(
                    f"\nalembic_version: {rev}  ({verdict} the "
                    f"{REQUIRED_SCHEMA_REVISION} this code requires)"
                )
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                print(f"\nalembic_version: unreadable ({type(exc).__name__})")
        else:
            print("\nalembic_version: absent -- nothing has migrated this database")
            print("  A migration that logged 'Running upgrade' but left no alembic_version")
            print("  did not commit. Re-run it and read everything it prints.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
