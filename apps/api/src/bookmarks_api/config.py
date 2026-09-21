"""Settings.

Everything that M1/M2 might change lives here as a value, not a constant in code --
in particular the embedding dimension, which is still an open question (doc/plan.md).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute paths, not relative ones. `env_file=".env"` resolves against the *current
# working directory*, so `alembic -c db/alembic.ini` run from the repo root would
# find nothing and fall back to every default -- silently, because a missing .env is not
# an error.
APP_ROOT = Path(__file__).resolve().parents[2]  # apps/api
REPO_ROOT = APP_ROOT.parents[1]  # the monorepo root

# The alembic tree lives at the repo root, not under apps/api: the schema is the whole
# project's, not this service's. Named here so that moving it again is one edit.
ALEMBIC_INI = REPO_ROOT / "db" / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

# Both are read, repo root first. A root .env holds what the whole project shares; an
# apps/api one overrides it for this service. Real environment variables beat both.
ENV_FILES = (REPO_ROOT / ".env", APP_ROOT / ".env")


class ConfigurationError(RuntimeError):
    """Settings are missing something there is no safe default for."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database.
    #
    # The defaults deliberately point at a stock local Postgres and a database named for
    # this project. An earlier default of port 5436 / "bookmarks" was the predecessor's
    # Docker instance and its database, which meant a default `make migrate` would have
    # run DDL against a system this project has no business touching.
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "page_history"
    db_user: str = ""
    db_password: str = ""

    # Bearer tokens, comma-separated, each optionally naming the user it belongs to:
    #
    #     API_TOKENS=plh:s3cret,alice:t0ken     -> two users
    #     API_TOKENS=s3cret                     -> one user, named by single_user_id
    #
    # Empty means every request is refused -- deliberately not "everything is open".
    # An unconfigured deployment should be inert, not public.
    api_tokens: str = ""

    # The display_name of the app_user row a bare API token maps to, created on first
    # use. M1 replaces this with OAuth identities resolving through user_identity.
    single_user_id: str = "plh"

    # Refuse to start when the database is not at the Alembic revision this code
    # requires. Turning it off is a deliberate act, not a default.
    schema_check: bool = True

    # Origins allowed to call the API from a browser, comma-separated. Extension pages
    # are matched by pattern instead (see cors_origin_regex) because an extension's
    # origin is its id, which differs between an unpacked load and a published one.
    cors_origins: str = ""

    # chrome-extension://<32 letters a-p>. Matching the shape rather than listing ids
    # keeps an unpacked reload -- which gets a new id -- from silently breaking the
    # extension, without opening the API to the web.
    cors_origin_regex: str = r"^(chrome|moz)-extension://[a-z0-9-]+$"

    # Embeddings (M2)
    embedding_backend: str = "local"
    embedding_model: str = "bge-small-en-v1.5"
    embedding_dim: int = 384
    ollama_base_url: str = "http://127.0.0.1:11434"

    @property
    def database_url(self) -> str:
        """The connection URL, refusing to build one that connects as somebody unintended.

        An empty user is not a harmless default. libpq treats it as unset and falls back
        to the operating-system user, so the process connects as whoever ran it -- and
        since Postgres assigns table ownership to the role that runs CREATE TABLE, a
        migration run this way leaves every table owned by the wrong role. It succeeds,
        which is what makes it worth an exception here.
        """
        if not self.db_user:
            searched = "\n".join(
                f"  {path}{'' if path.exists() else '   (not present)'}"
                for path in ENV_FILES
            )
            raise ConfigurationError(
                "DB_USER is not set, so a connection would be made as the operating-system "
                "user rather than a role you chose.\n"
                "Set DB_USER and DB_PASSWORD in one of:\n"
                f"{searched}\n"
                "The second overrides the first; copy apps/api/.env.example for a template."
            )
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def token_map(self) -> dict[str, str]:
        """Token -> the display name of the `app_user` it acts as.

        A stand-in for real sign-in until M1: an OAuth identity will resolve through
        `user_identity` to the same table. Tokens are the only credential a browser
        extension can carry without an interactive login, so they outlive that change.
        """
        mapping: dict[str, str] = {}
        for entry in self.api_tokens.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, sep, token = entry.partition(":")
            if sep and token.strip():
                mapping[token.strip()] = name.strip() or self.single_user_id
            else:
                mapping[entry] = self.single_user_id
        return mapping

    @property
    def token_set(self) -> frozenset[str]:
        return frozenset(self.token_map)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
