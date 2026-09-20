"""The migration tree resolves the database URL without importing the application.

`db/migrations/dburl.py` exists so that `alembic upgrade head` needs only alembic,
sqlalchemy and psycopg -- the schema belongs to the project, not to the API service, and
requiring the service's package to migrate it inverts that.

The cost is that the URL is now built in two places. These tests are what pays it down:
identical inputs must produce identical URLs, and the second-to-last one fails if either
side changes its precedence or its defaults.
"""

import importlib.util

import pytest

from bookmarks_api.config import REPO_ROOT, ConfigurationError, Settings

DBURL_PY = REPO_ROOT / "db" / "migrations" / "dburl.py"


def load_dburl():
    """Import the module by path -- it is not on sys.path outside alembic."""
    spec = importlib.util.spec_from_file_location("dburl", DBURL_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dburl(monkeypatch, tmp_path):
    """dburl with its .env lookup pointed at a directory under our control."""
    module = load_dburl()
    monkeypatch.setattr(module, "ENV_FILES", (tmp_path / "root.env", tmp_path / "app.env"))
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return module


def test_it_imports_without_the_application(dburl):
    """The whole point: nothing outside the standard library.

    Checked against the import statements rather than the text, so a docstring that
    mentions bookmarks_api does not trip a rule about depending on it.
    """
    import ast
    import sys

    imported = set()
    for node in ast.walk(ast.parse(DBURL_PY.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    third_party = imported - set(sys.stdlib_module_names)
    assert not third_party, (
        f"dburl.py must import only the standard library -- the db environment has "
        f"alembic, sqlalchemy and psycopg and nothing else. Found: {sorted(third_party)}"
    )


def test_matches_the_application_settings(dburl, tmp_path):
    """Two builders, one URL. This is the drift guard."""
    (tmp_path / "root.env").write_text(
        "DB_HOST=db.example\nDB_PORT=6000\nDB_NAME=page_history\n"
        "DB_USER=api\nDB_PASSWORD=s3cret\n"
    )
    from_db = dburl.resolve_database_url()
    from_app = Settings(
        db_host="db.example", db_port=6000, db_name="page_history",
        db_user="api", db_password="s3cret",
    ).database_url
    assert from_db == from_app


def test_defaults_match_the_application_defaults(dburl):
    """Including the defaults, which are the easiest thing to change on one side only."""
    assert dburl.DEFAULTS["DB_HOST"] == Settings.model_fields["db_host"].default
    assert dburl.DEFAULTS["DB_PORT"] == str(Settings.model_fields["db_port"].default)
    assert dburl.DEFAULTS["DB_NAME"] == Settings.model_fields["db_name"].default


def test_the_app_env_file_overrides_the_root_one(dburl, tmp_path):
    (tmp_path / "root.env").write_text("DB_USER=from_root\nDB_NAME=shared\n")
    (tmp_path / "app.env").write_text("DB_USER=from_app\n")
    url = dburl.resolve_database_url()
    assert "from_app" in url
    assert "/shared" in url, "root values survive where not overridden"


def test_real_environment_variables_beat_the_files(dburl, tmp_path, monkeypatch):
    (tmp_path / "root.env").write_text("DB_USER=from_file\n")
    monkeypatch.setenv("DB_USER", "from_environment")
    assert "from_environment" in dburl.resolve_database_url()


def test_database_url_wins_outright(dburl, tmp_path, monkeypatch):
    (tmp_path / "root.env").write_text("DB_USER=api\nDB_NAME=page_history\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://someone@elsewhere/other")
    assert dburl.resolve_database_url() == "postgresql+psycopg://someone@elsewhere/other"


def test_the_x_argument_beats_everything(dburl, tmp_path, monkeypatch):
    """`alembic -x db_url=...` for a scratch database or a recovery."""
    (tmp_path / "root.env").write_text("DB_USER=api\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env@host/db")
    assert dburl.resolve_database_url("postgresql+psycopg://x@y/z") == "postgresql+psycopg://x@y/z"


def test_a_missing_user_is_refused_the_same_way(dburl, tmp_path):
    """Same rule as the app: an empty user connects as the OS user and misassigns owners."""
    (tmp_path / "root.env").write_text("DB_NAME=page_history\n")
    with pytest.raises(dburl.ConfigurationError) as excinfo:
        dburl.resolve_database_url()

    message = str(excinfo.value)
    assert "DB_USER" in message
    assert "operating-system user" in message
    assert "db_url=" in message, "offer the override as a way out"

    settings = Settings(db_user="")
    with pytest.raises(ConfigurationError):
        _ = settings.database_url


def test_the_dotenv_parser_handles_what_people_write(dburl, tmp_path):
    (tmp_path / "root.env").write_text(
        "# a comment\n"
        "\n"
        "export DB_USER=api\n"
        'DB_PASSWORD="quoted secret"\n'
        "DB_NAME=page_history   # trailing comment\n"
        "MALFORMED_NO_EQUALS\n"
    )
    values = dburl.read_env_file(tmp_path / "root.env")
    assert values["DB_USER"] == "api"
    assert values["DB_PASSWORD"] == "quoted secret"
    assert values["DB_NAME"] == "page_history"
    assert "MALFORMED_NO_EQUALS" not in values


def test_unrelated_keys_are_ignored(dburl, tmp_path):
    """A shared root .env holds more than database settings."""
    (tmp_path / "root.env").write_text("HOST=0.0.0.0\nAPP_PORT=8000\nDB_USER=api\n")
    resolved = dburl.settings()
    assert "HOST" not in resolved
    assert resolved["DB_USER"] == "api"
