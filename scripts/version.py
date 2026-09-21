#!/usr/bin/env python3
"""Keep one version number across a polyglot monorepo.

The version lives in several files that have no reason to agree with each other:

    package.json                                 "version": "..."
    apps/api/pyproject.toml                      version = "..."
    apps/api/src/bookmarks_api/__init__.py       __version__ = "..."
    apps/extension, apps/browser                 their package.json, and the manifest
    package-lock.json                            the root's and each workspace's entry

`package.json` is canonical because that is what `npm version` writes. This script makes
the others follow, and `check` fails the build when they drift -- which is the only thing
that stops a release tagged v0.3.0 shipping an API that reports 0.1.0.

Usage:
    python3 scripts/version.py check          # exit 1 on any mismatch
    python3 scripts/version.py show           # print the canonical version
    python3 scripts/version.py set 0.2.0      # write it everywhere
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def numeric_only(version: str) -> str:
    """Strip any prerelease/build suffix, leaving MAJOR.MINOR.PATCH.

    Chrome extension manifests accept one to four dot-separated integers and nothing else,
    so `1.0.0-rc.1` is rejected outright. The manifest therefore tracks the numeric core
    of the release version rather than the full semver string.
    """
    return re.split(r"[-+]", version, maxsplit=1)[0]


@dataclass(frozen=True)
class Site:
    """One place a version string lives."""

    path: Path
    # Group 1 is the version. Only that span is rewritten, so a pattern can say which of
    # several "version" fields it means by matching what surrounds it.
    pattern: re.Pattern[str]
    # Applied before writing, and before comparing on `check`.
    transform: Callable[[str], str] = lambda v: v

    def read(self) -> str | None:
        if not self.path.exists():
            return None
        match = self.pattern.search(self.path.read_text())
        return match.group(1) if match else None

    def expected(self, version: str) -> str:
        return self.transform(version)

    def write(self, version: str) -> bool:
        if not self.path.exists():
            return False
        text = self.path.read_text()
        match = self.pattern.search(text)
        if match is None:
            raise SystemExit(f"no version field found in {self.rel}")
        updated = text[: match.start(1)] + self.transform(version) + text[match.end(1) :]
        if updated != text:
            self.path.write_text(updated)
            return True
        return False

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(ROOT))


CANONICAL = Site(ROOT / "package.json", re.compile(r'"version":\s*"([^"]+)"'))

FOLLOWERS = [
    Site(
        ROOT / "apps/api/pyproject.toml",
        re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
    ),
    Site(
        ROOT / "apps/api/src/bookmarks_api/__init__.py",
        re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE),
    ),
    Site(
        ROOT / "apps/extension/package.json",
        re.compile(r'"version":\s*"([^"]+)"'),
    ),
    # The manifest is what Chrome reads, and it will not accept a prerelease suffix.
    Site(
        ROOT / "apps/extension/src/manifest.json",
        re.compile(r'"version":\s*"([^"]+)"'),
        transform=numeric_only,
    ),
    Site(
        ROOT / "apps/browser/package.json",
        re.compile(r'"version":\s*"([^"]+)"'),
    ),
    # package-lock.json records the root's version twice and each workspace's once, and
    # `npm version` updates only the root's: a lockfile left behind makes `npm ci` install
    # from a file that disagrees with the packages it describes.
    Site(ROOT / "package-lock.json", re.compile(r'^  "version":\s*"([^"]+)"', re.MULTILINE)),
    *(
        Site(
            ROOT / "package-lock.json",
            re.compile(
                rf'"{re.escape(entry)}":\s*\{{\s*"name":\s*"[^"]*",\s*"version":\s*"([^"]+)"'
            ),
        )
        for entry in ("", "apps/browser", "apps/extension")
    ),
]


def canonical_version() -> str:
    version = CANONICAL.read()
    if version is None:
        raise SystemExit(f"cannot read a version from {CANONICAL.rel}")
    return version


def cmd_show() -> int:
    print(canonical_version())
    return 0


def cmd_check() -> int:
    expected = canonical_version()
    if not SEMVER.match(expected):
        print(f"FAIL  {CANONICAL.rel}: {expected!r} is not semver", file=sys.stderr)
        return 1

    problems: list[str] = []
    for site in FOLLOWERS:
        found = site.read()
        if found is None:
            continue  # the file does not exist yet; not a drift
        want = site.expected(expected)
        if found != want:
            problems.append(f"  {site.rel}: {found}  (expected {want})")

    if problems:
        print(f"Version drift against {CANONICAL.rel} ({expected}):", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print("\nRun: python3 scripts/version.py set " + expected, file=sys.stderr)
        return 1

    print(f"version {expected} consistent across all files")
    return 0


def cmd_set(version: str) -> int:
    if not SEMVER.match(version):
        raise SystemExit(f"{version!r} is not a semver version")

    changed = [site.rel for site in (CANONICAL, *FOLLOWERS) if site.write(version)]
    for rel in changed:
        print(f"updated {rel}")
    if not changed:
        print(f"already at {version}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"check", "set", "show"}:
        print(__doc__)
        return 2
    if argv[1] == "check":
        return cmd_check()
    if argv[1] == "show":
        return cmd_show()
    if len(argv) < 3:
        raise SystemExit("usage: version.py set <semver>")
    return cmd_set(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
