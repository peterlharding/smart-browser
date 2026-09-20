"""Settings.

Everything that M1/M2 might change lives here as a value, not a constant in code --
in particular the embedding dimension, which is still an open question (doc/plan.md).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    db_host: str = "127.0.0.1"
    db_port: int = 5436
    db_name: str = "bookmarks"
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

    # Embeddings (M2)
    embedding_backend: str = "local"
    embedding_model: str = "bge-small-en-v1.5"
    embedding_dim: int = 384
    ollama_base_url: str = "http://127.0.0.1:11434"

    @property
    def database_url(self) -> str:
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
