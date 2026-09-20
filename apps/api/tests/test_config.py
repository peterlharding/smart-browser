"""Settings that refuse to guess.

`database_url` is the one place a wrong-but-plausible default does real damage, because
connecting as the wrong role leaves tables owned by it -- and the migration *succeeds*,
so nothing tells you until you look.
"""

import pytest

from bookmarks_api.config import APP_ROOT, ConfigurationError, Settings


def test_database_url_refuses_an_empty_user():
    settings = Settings(db_user="")
    with pytest.raises(ConfigurationError) as excinfo:
        _ = settings.database_url

    message = str(excinfo.value)
    assert "DB_USER" in message
    assert "operating-system user" in message
    assert str(APP_ROOT / ".env") in message, "say which file to edit"


def test_database_url_is_built_from_every_part():
    url = Settings(
        db_user="api", db_password="secret",
        db_host="db.example", db_port=6000, db_name="page_history",
    ).database_url
    assert url == "postgresql+psycopg://api:secret@db.example:6000/page_history"


def test_env_file_is_anchored_to_the_app_not_the_working_directory():
    """`env_file=".env"` resolves against cwd, so running alembic from the repo root
    would find nothing and fall back to every default."""
    assert APP_ROOT.name == "api"
    assert (APP_ROOT / "pyproject.toml").exists()
    assert Settings.model_config["env_file"] == APP_ROOT / ".env"


def test_tokens_parse_into_users():
    settings = Settings(api_tokens="plh:abc, alice:def , bare", single_user_id="plh")
    assert settings.token_map == {"abc": "plh", "def": "alice", "bare": "plh"}
