"""Tests for the version synchroniser.

Tested because this script is the only thing preventing a release tagged v0.3.0 from
shipping an API that reports 0.1.0, and a silent failure here is invisible until someone
reads a bug report against the wrong version.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "version.py"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "apps/api/src/bookmarks_api").mkdir(parents=True)

    (tmp_path / "scripts/version.py").write_text(SCRIPT.read_text())
    (tmp_path / "package.json").write_text(json.dumps({"name": "x", "version": "0.1.0"}))
    (tmp_path / "apps/api/pyproject.toml").write_text(
        '[project]\nname = "bookmarks-api"\nversion = "0.1.0"\n'
    )
    (tmp_path / "apps/api/src/bookmarks_api/__init__.py").write_text(
        '"""Doc."""\n\n__version__ = "0.1.0"\n'
    )
    return tmp_path


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "scripts/version.py"), *args],
        capture_output=True,
        text=True,
    )


def test_check_passes_when_versions_agree(repo):
    assert run(repo, "check").returncode == 0


def test_check_fails_on_drift(repo):
    (repo / "apps/api/pyproject.toml").write_text(
        '[project]\nname = "bookmarks-api"\nversion = "0.2.0"\n'
    )
    result = run(repo, "check")
    assert result.returncode == 1
    assert "pyproject.toml" in result.stderr
    assert "0.2.0" in result.stderr


def test_check_names_every_drifted_file(repo):
    (repo / "apps/api/pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    (repo / "apps/api/src/bookmarks_api/__init__.py").write_text('__version__ = "0.3.0"\n')
    result = run(repo, "check")
    assert "pyproject.toml" in result.stderr
    assert "__init__.py" in result.stderr


def test_set_updates_every_file(repo):
    assert run(repo, "set", "1.2.3").returncode == 0

    assert json.loads((repo / "package.json").read_text())["version"] == "1.2.3"
    assert 'version = "1.2.3"' in (repo / "apps/api/pyproject.toml").read_text()
    assert '__version__ = "1.2.3"' in (
        repo / "apps/api/src/bookmarks_api/__init__.py"
    ).read_text()
    assert run(repo, "check").returncode == 0


def test_set_rejects_a_non_semver_version(repo):
    assert run(repo, "set", "v1.2").returncode != 0
    assert json.loads((repo / "package.json").read_text())["version"] == "0.1.0"


def test_set_accepts_a_prerelease(repo):
    assert run(repo, "set", "1.0.0-rc.1").returncode == 0
    assert run(repo, "check").returncode == 0


def test_missing_follower_is_not_drift(repo):
    """apps/browser/package.json does not exist until M5; that must not fail the build."""
    assert not (repo / "apps/browser").exists()
    assert run(repo, "check").returncode == 0


def test_check_rejects_a_malformed_canonical_version(repo):
    (repo / "package.json").write_text(json.dumps({"name": "x", "version": "not-a-version"}))
    assert run(repo, "check").returncode == 1


def test_set_only_touches_the_version_field(repo):
    before = (repo / "apps/api/pyproject.toml").read_text()
    run(repo, "set", "2.0.0")
    after = (repo / "apps/api/pyproject.toml").read_text()
    assert before.replace('version = "0.1.0"', 'version = "2.0.0"') == after
