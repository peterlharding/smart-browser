"""Settings that refuse to guess.

`database_url` is the one place a wrong-but-plausible default does real damage, because
connecting as the wrong role leaves tables owned by it -- and the migration *succeeds*,
so nothing tells you until you look.
"""

import pytest

from bookmarks_api.config import (
    APP_ROOT,
    ENV_FILES,
    REPO_ROOT,
    ConfigurationError,
    Settings,
)


def test_database_url_refuses_an_empty_user():
    settings = Settings(db_user="")
    with pytest.raises(ConfigurationError) as excinfo:
        _ = settings.database_url

    message = str(excinfo.value)
    assert "DB_USER" in message
    assert "operating-system user" in message
    for path in ENV_FILES:
        assert str(path) in message, "name every file that was searched"


def test_database_url_is_built_from_every_part():
    url = Settings(
        db_user="api", db_password="secret",
        db_host="db.example", db_port=6000, db_name="page_history",
    ).database_url
    assert url == "postgresql+psycopg://api:secret@db.example:6000/page_history"


def test_env_files_are_absolute_not_relative_to_the_working_directory():
    """`env_file=".env"` resolves against cwd, so running alembic from the repo root
    would find nothing and fall back to every default -- silently."""
    assert APP_ROOT.name == "api"
    assert (APP_ROOT / "pyproject.toml").exists()
    assert (REPO_ROOT / "Makefile").exists()
    assert all(path.is_absolute() for path in Settings.model_config["env_file"])


def test_both_env_files_are_read_with_the_app_overriding_the_root():
    """A root .env is the project-wide one; apps/api/.env overrides it for this service.

    pydantic-settings gives later files priority, so the order is load-bearing.
    """
    assert Settings.model_config["env_file"] == (REPO_ROOT / ".env", APP_ROOT / ".env")


def test_layering_actually_works(tmp_path, monkeypatch):
    root_env = tmp_path / "root.env"
    app_env = tmp_path / "app.env"
    root_env.write_text("DB_USER=from_root\nDB_NAME=shared\n")
    app_env.write_text("DB_USER=from_app\n")

    class Layered(Settings):
        model_config = Settings.model_config | {"env_file": (root_env, app_env)}

    # Real environment variables beat both, so clear the ones under test.
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    settings = Layered()
    assert settings.db_user == "from_app", "the app file must win"
    assert settings.db_name == "shared", "root values survive where not overridden"


def test_tokens_parse_into_users():
    settings = Settings(api_tokens="plh:abc, alice:def , bare", single_user_id="plh")
    assert settings.token_map == {"abc": "plh", "def": "alice", "bare": "plh"}
