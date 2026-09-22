# 0018 - The browser ships as a signed, notarized Smart-Browser.app

- **Date:** 2026-09-22
- **Status:** Accepted
- **Builds on:** [ADR 0015](0015-electron-shell.md) (the shell, `build.mjs`), [ADR 0016](0016-local-history-backend-on-action.md) (`history.db` and its migrations)
- **Sketch:** [`m5-packaging.md`](../m5-packaging.md)

## Context

The browser runs only from the repo, as the generic `Electron` app, through `make browser-dev`.
That has costs beyond convenience:

- **The token's Keychain entry is shared.**
  `safeStorage` keys it by the running app's name, and every unpackaged Electron app is "Electron".
- **The outbound firewall asks again with each Electron upgrade**, because it knows programs by their binary.
- **Auto-update needs a packaged, signed app to replace.**

Three facts make packaging simpler than usual:

- **The app is `apps/browser/out/` and `package.json`, about 1 MB, with no runtime dependencies.**
  `build.mjs` bundles the main process and the preloads whole, and `node:sqlite` ships inside Electron.
  So nothing from `node_modules` goes into the app, and no native module needs rebuilding.
- **A Developer ID Application certificate is already in this Mac's Keychain** (team `T5RDMAD9Q4`), and `notarytool` is installed.
  Checked 2026-09-22.
- **The repository is public**, so Electron's free update service can serve it later.

## Decision

### Tooling: Electron's own pieces, from a script

**`apps/browser/package.mjs`, beside `build.mjs`**, runs four steps, each a package Electron itself maintains or a tool macOS ships:

1. **`@electron/packager`** makes `Smart-Browser.app` from `out/` and `package.json`, with the app's code in an `asar` archive.
2. **`@electron/osx-sign`** signs every binary in the bundle, the helper apps included.
3. **`@electron/notarize`** submits the app to Apple with `notarytool` and staples the ticket to it.
4. **`hdiutil`** makes the DMG and **`ditto`** makes the zip.

Each step is ordinary and visible, and the script is about a hundred lines.
It is the same choice ADR 0015 made in writing `build.mjs` instead of adopting `electron-vite`.

### Development and daily use get separate profiles

- **`Smart-Browser`** for the packaged app (`app.isPackaged`).
- **`Smart-Browser Dev`** when run from the repo.
- **`SMART_BROWSER_USER_DATA`** still overrides both, as the tests use it.

This comes first, and on its own, because `make browser-dev` already uses the profile a package would.
Without it, experiments land in real history, and a development build with a new `history.db` migration moves the profile to a version the installed app refuses.
Separate names also give the two separate Keychain entries.

### Identity

- **Bundle id `com.performiq.smart-browser`.**
  Once an app ships, its bundle id is its identity for the Keychain, the firewall and updates, so it is chosen once.
- **Name `Smart-Browser`**, as the menu and the profile already say.
- **Version**: the release version, which `scripts/version.py` already writes into `apps/browser/package.json`.
- **`arm64` only.**
  A universal build doubles the download for a machine that does not exist yet.
- **A placeholder icon**: a simple mark in the UI's accent colour, as a 1024-pixel master made into an `.icns`.
  A designed icon replaces it later without changing anything else.

### Signing and notarization

- **Signed with the Developer ID Application identity, with the hardened runtime**, and only the entitlement Electron needs: JIT for V8.
  None for camera, microphone or location, which the browser denies to pages anyway (ADR 0015).
- **Notarized with an App Store Connect API key**, stored once in the Keychain with `xcrun notarytool store-credentials`.
  It belongs to the team, not to a personal Apple ID password, and can be revoked alone.
- **Stapled**, so the app opens without asking Apple first.
- **Signed on this Mac at release time, never in CI.**
  The private key stays in this Keychain; in CI secrets, a leak would sign someone else's software as yours.
  CI builds an unsigned package instead, to prove packaging still works on every commit.

### Targets and releases

- **`make browser-package`**: an unsigned `.app` in `apps/browser/dist/` (gitignored), to try packaging locally.
- **`make browser-release`**: build, sign, notarize, staple, and make the DMG and the zip.
- **RELEASING.md** gains a step that attaches both to the GitHub release: the DMG for installing, and the zip for updates.

### Auto-update follows, on `update-electron-app`

Auto-update is its own step, after this one.
It will use **`update-electron-app` and `update.electronjs.org`**: Electron's free service for public GitHub repositories, which serves Squirrel.Mac updates from the zip on each release.
That is why releases carry the zip from the start.

### Testing

- **The end-to-end suite also runs against the packaged app.**
  Playwright launches any Electron executable, so the same tests drive `dist/Smart-Browser.app`.
  That proves the `asar` paths, the `smart://` handler and the preloads work packaged, which nothing in the suite sees today.
- **The release checks the signature**: `codesign --verify --deep --strict`, `spctl --assess` for Gatekeeper's verdict, and `stapler validate`.
- **CI packages unsigned on a macOS runner** and runs the suite against that package.

## Options not taken

- **electron-builder.**
  The least code to write, and a large dependency tree and a bundled binary for a 1 MB app.
  It also has its own update format beside Electron's.
- **Electron Forge.**
  Official, and built on the same pieces this uses.
  Its build plugins want to own the build, which is ADR 0015's objection to `electron-vite`.
  Without them, it is a configuration layer over the pieces used here directly.
- **Ad-hoc signing** (`codesign -s -`).
  It runs on this Mac, and gives the app a new identity with every build, which is the problem packaging is meant to solve.
- **Signing in CI.**
  Possible with the certificate in GitHub secrets, and a leaked secret would sign someone else's software.
- **An app-specific password for notarization.**
  It works, and is tied to a personal Apple ID; the API key is the team's and revocable on its own.
- **A universal (`arm64` and `x86_64`) build.**
  Twice the size, for an Intel Mac nobody uses.
- **One profile for development and the packaged app.**
  It is what exists today, and it lets a development build lock the installed app out of its own history.

## Consequences

- The browser installs from a DMG into `/Applications`, opens without a Gatekeeper warning, and keeps one identity across updates for the Keychain and the firewall.
- **The first launch of the packaged app asks for the API token once.**
  Its Keychain entry is its own, by design.
  `SettingsStore.token()` already returns null for a token it cannot decrypt, and the save button then sends you to Settings.
- `make browser-dev` moves to a `Smart-Browser Dev` profile.
  The history and settings in today's `Smart-Browser` profile stay there for the packaged app to use.
- A release needs this Mac, with its Keychain, to sign and notarize.
- CI gains a macOS job.

## Implementation notes

Where building it refined the decision above.

- **`make browser-package` signs ad hoc, not "unsigned".**
  Apple silicon runs no unsigned code, so a local package gets an ad-hoc signature (`codesign -s -`) to launch at all.
  It is still not a Developer ID build, and says so.
- **`@electron/notarize` notarizes the DMG as well as the app**, and staples both.
  The app is stapled before it goes into the DMG and the zip, so both carry a stapled app, and the DMG is signed and stapled in its own right.
- **Packaging is fast**: about three seconds once Electron's release zip is cached, because the app is `out/` and `package.json`, and nothing from `node_modules`.
- **Tests use a mock Keychain for the packaged app too.**
  Playwright's loader gives a build run from `out/` Chromium's mock Keychain, but not a packaged app.
  A packaged app then used the real Keychain, and macOS asked whether each new build's signature may read "Smart-Browser Safe Storage".
  That is correct behaviour for a new identity, and it left the run waiting on a dialog.
  The fixture now passes `--use-mock-keychain` to a packaged app on macOS, so tests never touch your Keychain.
- **CI starts the package but does not run the full suite against it.**
  The suite needs Postgres, and GitHub's macOS runners have no service containers.
  CI's macOS job packages the app and runs a smoke test that needs no API.
  The test covers the UI and preloads served from inside `app.asar`, the history page, Settings, `app.isPackaged`, and quitting cleanly.
  The full suite runs against the package locally with `make test-browser-e2e-packaged`, and passed there, against both the ad-hoc package and a Developer ID-signed one.
- **Developer ID signing was checked on this Mac before any release**: hardened runtime, only the JIT entitlement, timestamped, and `spctl` accepts it as Developer ID.
  Notarization waits on the one-time credentials RELEASING.md describes.
- **The icon is drawn from `assets/icon.svg`** by `assets/make-icon.cjs`, which renders it in Electron at every size macOS asks for and packs them with `iconutil`.
  The `.icns` is committed, so packaging needs neither step.
