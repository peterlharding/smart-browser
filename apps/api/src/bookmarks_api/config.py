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

    # Auth. Comma-separated bearer tokens accepted on writes.
    # Empty means writes are refused outright -- deliberately not "writes are open",
    # which is how /xyzzy ended up public.
    api_tokens: str = ""

    # M0 only: the pre-migration schema has no ownership columns, so every request acts
    # as this identity. M1 replaces it with token -> app_user (ADR 0001, ADR 0003).
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
    def token_set(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.api_tokens.split(",") if t.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
