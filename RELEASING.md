# Releasing Smart-Browser

This document describes the release process for Smart-Browser.
Follow these steps for every release so that the version number, changelog, release notes, and git tag stay in sync.

## Versioning

The project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html): `MAJOR.MINOR.PATCH`.

- MAJOR: incompatible or sweeping changes.
- MINOR: new, backward-compatible features.
- PATCH: backward-compatible bug fixes only.

**One release version for the whole repo — as a label, not a guarantee.** See [ADR 0005](doc/decisions/0005-versioning-and-compatibility.md). Three things are versioned three different ways here, and conflating them is the mistake that ADR replaced:

| Thing | Versioned by | Changes |
| --- | --- | --- |
| Release | semver in `package.json` | Every release |
| API contract | `API_CONTRACT_VERSION` (the `v1` in `/api/v1`) | Only on a breaking change |
| Database schema | Alembic revisions (`0001`, `0002`, …) | Per migration; ordinal, never semver |

The release version does **not** enforce compatibility — two checks do, and both run regardless of what the version says:

- The API refuses to start when the database is not at `REQUIRED_SCHEMA_REVISION`.
- The browser asserts `contract` from `/api/v1/health` at startup (from M5).

**When to split the release version:** the first time a browser build runs against an API deployment it did not ship with. Until then one version is simpler and costs nothing; after then it asserts something untrue.

Until `1.0.0` the API contract is not stable. `/api/v1` is a path, not a promise.

## Where versions live

This is a polyglot monorepo, so the version string lives in several files that have no
reason to agree with each other:

- `version` in `package.json` — **canonical**, because that is what `npm version` writes.
- `version` in `apps/api/pyproject.toml`.
- `__version__` in `apps/api/src/bookmarks_api/__init__.py` — what `/api/v1/health` reports.
- `version` in `apps/browser/package.json`.
- `package-lock.json`, whose root and workspace entries each record a version.
- `CHANGELOG.md` at the repo root, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
- `release_notes/v<version>.md`, one user-facing file per release.
- The git tag `v<version>` (annotated).

Do not edit the first four by hand. `scripts/version.py` writes them together and
`make version-check` fails the build on drift — it runs as part of `make check`, so a
release cannot be cut with an API that reports the wrong version.

## Release steps

1. **Pick the version number** based on the nature of the changes (see Versioning above).

2. **Bump the version** everywhere at once, without letting npm commit or tag, so the release commit carries everything together:

   ```sh
   make version-set VERSION=<version>
   git diff   # expect only version fields to change
   ```

   That wraps `npm version <version> --no-git-tag-version` and `scripts/version.py set`, which also moves every entry in `package-lock.json`, then relocks `apps/api/uv.lock` and regenerates `packages/shared-types/openapi.json`, both of which record the version.
   Expect their version lines in the diff too; `make check` fails if either is left behind.

3. **Cut the changelog.** In `CHANGELOG.md`:
   - Move the items under `## [Unreleased]` into a new `## [<version>] - YYYY-MM-DD` section (today's date).
   - Leave a fresh, empty `## [Unreleased]` at the top.
   - Add a `See [release_notes/v<version>.md](release_notes/v<version>.md) for details.` line under the new heading.
   - Update the link references at the bottom of the file: point `[Unreleased]` at `compare/v<version>...HEAD` and add a `[<version>]` tag link.

4. **Write the release notes** at `release_notes/v<version>.md`.
   See `release_notes/README.md` for the structure: a short intro, Highlights, any Fixed section, and Under the hood.

5. **Run every check** and confirm there are no warnings and no failures:

   ```sh
   make check   # version sync, lockfiles, OpenAPI contract, markdown lint, ruff, mypy, tests
   ```

   `make check` runs everything through `uv`, which syncs the environment from `uv.lock` first — so a stale lockfile shows up here rather than in CI.

   The default test run needs no database: the API suite runs against SQLite in memory.
   Before a release, also run the Postgres suite against a scratch database, because it
   covers the id allocation and migration behaviour SQLite cannot:

   ```sh
   make test-pg
   ```

   It runs against `<DB_NAME>_test`, built from `.env`, and refuses any URL pointing at the configured database — that suite creates and drops tables.

   Do not cut a release on a failing or flaky suite.
   Fix the test or the code first, even when the failure looks unrelated to what the release contains.

   Warnings count as failures: `pytest` is configured with `filterwarnings = ["error", ...]`, with the handful of third-party deprecations we do not control listed explicitly. If a new warning appears, deal with it rather than adding it to that list out of habit.

6. **Check the migrations.** If the release contains a new revision in `db/migrations/versions/`:

   - Confirm `REQUIRED_SCHEMA_REVISION` in `src/bookmarks_api/schema_guard.py` was bumped to match. `make test` fails if it was not.
   - Say in the release notes that a migration must be applied, and name the revision.
   - Apply it to the deployment target before or with the deploy:

     ```sh
     make migrate-status   # what the database is at, and what the code wants
     make migrate          # bring it to head
     ```

   The API will refuse to start against a database that is behind, so a forgotten migration is a failed boot rather than a corrupted request. That is the intent — do not work around it by setting `SCHEMA_CHECK=false`.

   **If `urlnorm.py` changed**, including a new tracking parameter, existing rows hold keys the new rules would not produce, and nothing refuses to start over it: a re-save of the same page quietly misses its row and creates a second one.
   Rekey them with the deploy, and resolve any collision it reports by hand (ADR 0011):

   ```sh
   make rehash-urls              # what would change
   make rehash-urls CONFIRM=yes  # change it
   ```

7. **Commit** the version bump, changelog, and release notes together:

   ```sh
   git add -A
   git commit -m "Release <version>"
   ```

8. **Push the commit, not the tag**, and wait for CI to pass on it:

   ```sh
   git push origin main
   gh run watch --exit-status \
     "$(gh run list --commit "$(git rev-parse HEAD)" -L 1 --json databaseId --jq '.[0].databaseId')"
   ```

   A tag is a claim that this commit is the release, and a pushed tag should never move.
   So it goes on only after CI has passed on exactly that commit.
   0.2.0 shows why: it was tagged and pushed together, CI then failed on the release commit, and 0.2.1 had to be cut to carry a one-line fix.

   If CI fails here, the release commit is on `main` but nothing claims it.
   Fix forward in a new commit, cut the changelog and notes again if the fix belongs in the release, and repeat this step on the new commit.

9. **Tag** the commit CI passed, with an annotated tag, and push the tag:

   ```sh
   git tag -a v<version> -m "Smart-Browser <version>" <commit>
   git push origin v<version>
   ```

   Name the commit rather than tagging `HEAD`, so a commit made meanwhile cannot end up tagged by accident.
   If a tag ever does go out on a bad commit, leave it where it is and release the next patch version, as 0.2.1 did; moving a published tag rewrites what anyone who fetched it already has.

10. **Build the browser for the release**, on this Mac, from the tagged commit ([ADR 0018](doc/decisions/0018-packaging-and-signing.md)):

    ```sh
    git checkout v<version>
    make browser-release
    git checkout main
    ```

    It packages `Smart-Browser.app`, signs it with the Developer ID certificate, notarizes and staples it, and makes the two files a release carries in `apps/browser/dist/`:
    `Smart-Browser-<version>-arm64.dmg` to install from, and `Smart-Browser-<version>-darwin-arm64.zip`, which updates come from.
    Notarizing takes a few minutes each for the app and the DMG.
    It needs the one-time setup under **Signing and notarization** below, and stops before doing anything slow if either part is missing.

11. **Publish the GitHub release** from the tag, with the release notes as the body and the DMG and zip attached:

    ```sh
    gh release create v<version> --title "Smart-Browser <version>" \
      --notes-file release_notes/v<version>.md --verify-tag \
      apps/browser/dist/Smart-Browser-<version>-arm64.dmg \
      apps/browser/dist/Smart-Browser-<version>-darwin-arm64.zip
    ```

    `--verify-tag` refuses to publish if the tag is not on GitHub, rather than creating one on whatever `main` is by then.

    Treat creating a release as a one-shot.
    If the repository has immutable releases enabled, a release cannot be amended, and deleting it leaves the tag name reserved, so it cannot be recreated.
    Get the notes right first.

    If the previous version was tagged but never published, readers of this release have not seen its notes.
    Publish the two files together, this release's first, with relative links made absolute: 0.2.1's release body carries 0.2.0's notes this way.

## Signing and notarization

A release is signed and notarized on this Mac, never in CI, so the signing key never leaves its Keychain (ADR 0018).
Two things must be there, once:

- **The Developer ID Application certificate**, `Developer ID Application: Peter Harding (T5RDMAD9Q4)`.
  `security find-identity -v -p codesigning` lists it.
  Another certificate can be named with `SMART_BROWSER_SIGNING_IDENTITY`.
- **Notarization credentials, as an App Store Connect API key**, stored in the Keychain under the name `smart-browser-notary`:
  1. In App Store Connect, under Users and Access, Integrations, Team Keys, create a key with the Developer role, and download its `AuthKey_<id>.p8`, which can be downloaded once.
  2. Store it, with the key id and the issuer id shown on that page:

     ```sh
     xcrun notarytool store-credentials smart-browser-notary \
       --key AuthKey_<id>.p8 --key-id <id> --issuer <issuer-uuid>
     ```

  3. Delete the `.p8` file, or keep it somewhere safe: the Keychain now holds what notarizing needs.

  Another stored name can be used with `SMART_BROWSER_NOTARY_PROFILE`.

`make browser-package` builds the same app signed ad hoc, for trying it on this Mac, and `make test-browser-e2e-packaged` runs the whole end-to-end suite against it.

## Commit conventions

Use a short prefix on commit messages so history is easy to scan.

- `Release <version>` for the single commit that cuts a release (step 7 above).
- `feat: <summary>` for a new feature, `fix: <summary>` for a bug fix.
- `refactor: <summary>` for restructuring that does not change behaviour.
- `docs: <summary>` for documentation and process changes that are not part of a release.
- `test: <summary>` for test-only changes.
- `build: <summary>` for build tooling, dependencies, and configuration.
- `db: <summary>` for a migration in `db/migrations/`, so schema changes are greppable in history.

Documentation or process changes (this file, README, the `doc/` tree) are committed on their own with a `docs:` message rather than being folded into a release commit.

Architecture decisions go in `doc/decisions/` as numbered ADRs, committed with `docs:`. An ADR is added when a decision is settled, not when it is proposed — open questions live in `doc/plan.md` until then.

## Notes

- `CHANGELOG.md` is maintained by hand; there is no generator.
  Add to `## [Unreleased]` as part of each change, not only at release time.
- Tags are annotated (`git tag -a`) so they carry a message and tagger, and can be verified and listed with release metadata.
- Keep one commit per release (`Release <version>`) so each tag anchors to a distinct, accurate point in history.
- Build output (`dist/`, `out/`, `.venv/`) is gitignored. Nothing it produces is committed.
- Database migrations are **not** part of the version scheme. A release does not have a "schema version"; it has a required Alembic revision, recorded in `schema_guard.py` and checked at startup.
- `apps/api/uv.lock` **is** committed, and CI installs from it with `--frozen`. Changing a dependency means committing the regenerated lockfile in the same change.
- `packages/shared-types/openapi.json` **is** committed: it is generated, but it is also the contract the browser client is built from, so a diff against it in review is the signal that an API change is breaking. Regenerate it with `make api-openapi` whenever routes or schemas change.
