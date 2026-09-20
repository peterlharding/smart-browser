"""Resolve the database URL without importing the application.

`db/` is the project's schema, not the API service's, so running a migration must not
require the API package to be installed. This reads the same `.env` files the app reads,
with the same precedence and the same refusal to guess a user, using nothing but the
standard library.

That does mean the URL is now built in two places -- here and in
``bookmarks_api.config.Settings`` -- which is a real cost. It is paid down by
``test_dburl_matches_the_application_settings``, which builds both from identical inputs
and asserts they agree.

Precedence, lowest first:

    1. the defaults below
    2. <repo root>/.env
    3. <repo root>/apps/api/.env
    4. real environment variables
    5. DATABASE_URL, which wins outright
    6. `alembic -x db_url=...`, which wins over everything
"""

from __future__ import annotations

import os
from pathlib import Path

DB_DIR = Path(__file__).resolve().parents[1]  # db/
REPO_ROOT = DB_DIR.parent
ENV_FILES = (REPO_ROOT / ".env", REPO_ROOT / "apps" / "api" / ".env")

DEFAULTS = {
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_NAME": "page_history",
    "DB_USER": "",
    "DB_PASSWORD": "",
}


class ConfigurationError(RuntimeError):
    """Settings are missing something there is no safe default for."""


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file. Deliberately small: KEY=value, quotes stripped, # ignored."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def settings() -> dict[str, str]:
    resolved = dict(DEFAULTS)
    for path in ENV_FILES:
        resolved.update(
            {k: v for k, v in read_env_file(path).items() if k in DEFAULTS or k == "DATABASE_URL"}
        )
    # Real environment variables beat the files.
    for key in (*DEFAULTS, "DATABASE_URL"):
        if key in os.environ:
            resolved[key] = os.environ[key]
    return resolved


def resolve_database_url(x_argument: str | None = None) -> str:
    """The URL to migrate, and a usable error when there is not one."""
    if x_argument:
        return x_argument

    resolved = settings()
    if resolved.get("DATABASE_URL"):
        return resolved["DATABASE_URL"]

    if not resolved["DB_USER"]:
        searched = "\n".join(
            f"  {path}{'' if path.exists() else '   (not present)'}" for path in ENV_FILES
        )
        raise ConfigurationError(
            "DB_USER is not set, so a connection would be made as the operating-system "
            "user rather than a role you chose -- and Postgres gives table ownership to "
            "whoever runs CREATE TABLE.\n"
            "Set DB_USER and DB_PASSWORD in one of:\n"
            f"{searched}\n"
            "or pass a URL directly:  alembic -x db_url=postgresql+psycopg://... upgrade head"
        )

    return (
        f"postgresql+psycopg://{resolved['DB_USER']}:{resolved['DB_PASSWORD']}"
        f"@{resolved['DB_HOST']}:{resolved['DB_PORT']}/{resolved['DB_NAME']}"
    )
