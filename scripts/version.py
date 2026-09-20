#!/usr/bin/env python3
"""Keep one version number across a polyglot monorepo.

The version lives in three files that have no reason to agree with each other:

    package.json                                 "version": "..."
    apps/api/pyproject.toml                      version = "..."
    apps/api/src/bookmarks_api/__init__.py       __version__ = "..."

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
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class Site:
    """One place a version string lives."""

    path: Path
    pattern: re.Pattern[str]
    template: str

    def read(self) -> str | None:
        if not self.path.exists():
            return None
        match = self.pattern.search(self.path.read_text())
        return match.group(1) if match else None

    def write(self, version: str) -> bool:
        if not self.path.exists():
            return False
        text = self.path.read_text()
        updated, count = self.pattern.subn(
            lambda _: self.template.format(version=version), text, count=1
        )
        if count == 0:
            raise SystemExit(f"no version field found in {self.rel}")
        if updated != text:
            self.path.write_text(updated)
            return True
        return False

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(ROOT))


CANONICAL = Site(
    ROOT / "package.json",
    re.compile(r'"version":\s*"([^"]+)"'),
    '"version": "{version}"',
)

FOLLOWERS = [
    Site(
        ROOT / "apps/api/pyproject.toml",
        re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
        'version = "{version}"',
    ),
    Site(
        ROOT / "apps/api/src/bookmarks_api/__init__.py",
        re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE),
        '__version__ = "{version}"',
    ),
    # apps/browser/package.json joins this list at M5.
    Site(
        ROOT / "apps/browser/package.json",
        re.compile(r'"version":\s*"([^"]+)"'),
        '"version": "{version}"',
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
        if found != expected:
            problems.append(f"  {site.rel}: {found}  (expected {expected})")

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
