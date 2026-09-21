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

    (tmp_path / "apps/extension/src").mkdir(parents=True)
    (tmp_path / "apps/extension/package.json").write_text(
        json.dumps({"name": "ext", "version": "0.1.0"})
    )
    (tmp_path / "apps/extension/src/manifest.json").write_text(
        json.dumps({"manifest_version": 3, "version": "0.1.0"})
    )
    (tmp_path / "package-lock.json").write_text(json.dumps(LOCKFILE, indent=2))
    return tmp_path


# Shaped as npm writes it: the root's version at the top and in its "" entry, and each
# workspace's in its own entry, with dependencies' versions around them to be left alone.
LOCKFILE = {
    "name": "x",
    "version": "0.1.0",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "x", "version": "0.1.0", "workspaces": ["apps/browser", "apps/extension"]},
        "apps/browser": {"name": "@x/browser", "version": "0.1.0", "devDependencies": {}},
        "apps/extension": {"name": "@x/extension", "version": "0.1.0"},
        "node_modules/esbuild": {"version": "0.28.2"},
    },
}


def lock_versions(repo: Path) -> dict[str, str]:
    lock = json.loads((repo / "package-lock.json").read_text())
    return {
        "top": lock["version"],
        **{name or "root": entry["version"] for name, entry in lock["packages"].items()},
    }


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


def test_manifest_gets_the_numeric_core_of_a_prerelease(repo):
    """Chrome rejects a manifest version with a prerelease suffix outright."""
    run(repo, "set", "1.0.0-rc.1")

    manifest = json.loads((repo / "apps/extension/src/manifest.json").read_text())
    assert manifest["version"] == "1.0.0"

    # The extension's package.json keeps the full semver; only the manifest is stripped.
    pkg = json.loads((repo / "apps/extension/package.json").read_text())
    assert pkg["version"] == "1.0.0-rc.1"

    assert run(repo, "check").returncode == 0


def test_manifest_drift_is_reported(repo):
    (repo / "apps/extension/src/manifest.json").write_text(
        json.dumps({"manifest_version": 3, "version": "0.9.9"})
    )
    result = run(repo, "check")
    assert result.returncode == 1
    assert "manifest.json" in result.stderr


def test_manifest_keeps_other_fields(repo):
    run(repo, "set", "2.0.0")
    manifest = json.loads((repo / "apps/extension/src/manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert manifest["version"] == "2.0.0"


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


def test_set_updates_the_lockfile_for_the_root_and_every_workspace(repo):
    run(repo, "set", "0.4.0")
    assert lock_versions(repo) == {
        "top": "0.4.0",
        "root": "0.4.0",
        "apps/browser": "0.4.0",
        "apps/extension": "0.4.0",
        "node_modules/esbuild": "0.28.2",  # a dependency's version is not ours to change
    }


def test_a_workspace_left_behind_in_the_lockfile_is_drift(repo):
    """`npm version` updates only the root's entries, which is how 0.4.0 found this."""
    run(repo, "set", "0.4.0")
    lock = json.loads((repo / "package-lock.json").read_text())
    lock["packages"]["apps/browser"]["version"] = "0.1.0"
    (repo / "package-lock.json").write_text(json.dumps(lock, indent=2))

    result = run(repo, "check")
    assert result.returncode == 1
    assert "package-lock.json: 0.1.0  (expected 0.4.0)" in result.stderr

