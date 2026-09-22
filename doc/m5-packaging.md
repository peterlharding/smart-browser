# M5 — packaging and signing

> Sketch, not a decision.
> What it takes to turn `make browser-dev` into a `Smart-Browser.app` you install and live in, the choices still open, and a recommendation, so the ADR (0018) can be written from a settled list.
> Its recommendations were accepted on 2026-09-22 and drafted as [ADR 0018](decisions/0018-packaging-and-signing.md), with an App Store Connect API key for notarization.

## Why now

The browser runs only from the repo, as the generic `Electron` app.
That costs more than convenience:

- **The token's Keychain entry is shared.**
  `safeStorage` keeps its key under the running app's name, and unpackaged, every Electron app on the Mac is "Electron".
- **The firewall asks again with each Electron upgrade.**
  The outbound firewall knows programs by their binary, and an unsigned Electron is a new program every time it changes.
- **Auto-update needs something to update**: a packaged, signed app.
- **Daily use belongs in `/Applications`**, not in a terminal running `make`.

## What there is to package

Less than usual, which makes every option simpler.

- **The app is `apps/browser/out/` and `package.json`, about 1 MB.**
  `build.mjs` bundles the main process and the preloads whole (esbuild), and Vite builds the UI.
  **The app has no runtime dependencies**: every `node_modules` package is a build or test tool, and `node:sqlite` ships inside Electron.
  So the packaged app needs no `node_modules` at all, and no native module needs rebuilding.
- **Electron 44.4.3** supplies the rest: the framework and its helper apps.
- **Paths are relative to `__dirname`** (`out/main/..`), so the UI, the preloads and the `smart://` handler move with the app, inside an `asar` archive or not.
  Whether `net.fetch` of a `file://` URL inside `app.asar` serves the UI is the first thing to prove (see Testing it).

## Checked on this Mac, 2026-09-22

- **Signing identities**: `Developer ID Application: Peter Harding (T5RDMAD9Q4)`, which signs apps for distribution outside the App Store; also Apple Development and Apple Distribution.
- **`notarytool`** is installed with Xcode.
  No stored notarization credentials yet: `xcrun notarytool store-credentials` is a one-time step, with an app-specific password or an App Store Connect API key.
- **The repository is public** on GitHub, which matters for auto-update (below).
- **Current releases**:

  | Tool | Version | What it is |
  | --- | --- | --- |
  | `electron-builder` | 26.15.3 | All-in-one: package, sign, notarize, DMG and zip, with `electron-updater` 6.8.9 |
  | `@electron-forge/cli` | 7.11.2 | Electron's official all-in-one, built on the pieces below |
  | `@electron/packager` | 20.3.0 | Electron's own: turns the app into a `.app` |
  | `@electron/osx-sign` | 2.7.0 | Electron's own: codesigns every binary in the bundle, helpers included |
  | `@electron/notarize` | 3.1.1 | Electron's own: submits to Apple with `notarytool` and staples the ticket |
  | `update-electron-app` | 3.3.0 | Electron's own: Squirrel.Mac updates from `update.electronjs.org`, for public GitHub repos |

- **The installed profile** (`~/Library/Application Support/Smart-Browser`) holds settings and a session from before 0.5.0, and no `history.db` yet.

## The tooling

### Option A — electron-builder

One configuration block does packaging, signing, notarization, a DMG and a zip, and its `electron-updater` does auto-update from GitHub Releases.

It is the most used and the least code to write.
Against it: a large dependency tree for a 1 MB app, and its own opinions (a bundled `app-builder` binary, its own `node_modules` handling, its own update format beside Electron's).
It would take our `out/` as given, so it does not fight `build.mjs`.

### Option B — Electron Forge

Electron's official toolchain, and the pieces it uses are the ones in option C.
Its build plugins (Vite, webpack) want to own the build, the same objection that ruled out `electron-vite` in ADR 0015.
Used without them, Forge is a configuration layer over `@electron/packager` and the makers, which option C uses directly.

### Option C — Electron's own pieces, from a script

`scripts` or `apps/browser/package.mjs`, beside `build.mjs`, about a hundred lines:

1. `@electron/packager` makes `Smart-Browser.app` from `out/` and `package.json`, into an `asar`, with the icon, the bundle id and the version.
2. `@electron/osx-sign` signs it with the Developer ID identity, hardened runtime on, with the entitlements Electron needs (JIT for V8).
3. `@electron/notarize` sends it to Apple and staples the ticket.
4. `hdiutil` makes the DMG; `ditto` makes the zip Squirrel.Mac updates from.

Four small packages, all Electron's own, each doing one step we can see.
It matches how this repo already works: `build.mjs` instead of `electron-vite`, for the same reason.
It is more code to own than option A, and every step is ordinary.

## Development and daily use need separate profiles

Today `make browser-dev` and a packaged app would both use `~/Library/Application Support/Smart-Browser`.
That breaks two ways:

- **Experiments land in real history and settings.**
- **A development build can lock the installed app out.**
  A build with a new `history.db` migration moves the profile to a version the installed app refuses, on purpose ("newer than this browser knows").

So the profile follows the build: `Smart-Browser` when packaged (`app.isPackaged`), `Smart-Browser Dev` when run from the repo.
`SMART_BROWSER_USER_DATA` still overrides both, as the tests use it.
A development build also gets its own Keychain entry this way, so its token never touches the installed app's.

## Identity

- **Bundle id**: `com.performiq.smart-browser`, from the domain of the Developer ID account's owner.
  Once an app ships under a bundle id, the id is its identity for the Keychain, the firewall and updates, so it is chosen once.
- **Name**: `Smart-Browser`, as the menu and profile already say.
- **Icon**: none exists.
  macOS needs a 1024-pixel master, made into an `.icns`.
  It is a design task of its own, and a placeholder mark would do until then.
- **Version**: the release version, which `scripts/version.py` already writes into `apps/browser/package.json`.
- **Architecture**: `arm64` only, for this Mac.
  A universal build doubles the download and needs a second Electron download at package time, for a machine that does not exist yet.

## Signing and notarization

- **Signed with Developer ID and notarized**, so Gatekeeper opens it without a warning, and the firewall and Keychain know it by a stable identity across updates.
  Ad-hoc signing (`codesign -s -`) would run on this Mac, but it gives the app a new identity with every build, which is exactly the problem packaging is meant to solve.
- **Hardened runtime**, with only the entitlements Electron needs: JIT for V8.
  No camera, microphone or location entitlements: the browser denies those to pages anyway (ADR 0015).
- **Signed on this Mac, at release time, not in CI.**
  The Developer ID private key stays in this Keychain.
  Putting it in GitHub secrets is possible, and it makes a leaked secret into someone else's signed malware.
  CI can build an unsigned package to prove packaging still works.

## The token after the move

The installed app will not read the token a development build stored: a different app name means a different Keychain entry, by design.
So the first launch of the packaged app asks for the token once in Settings, as it did on the first launch of 0.4.0.
`SettingsStore.token()` already returns null for a token it cannot decrypt, and the save button then sends you to Settings.

## Where it goes

- **`make browser-package`** builds an unsigned `.app` into `apps/browser/dist/` (gitignored), for trying packaging locally.
- **`make browser-release`** builds, signs, notarizes and staples, and makes the DMG and the zip.
- **RELEASING.md step 10** attaches both to the GitHub release: the DMG for installing, and the zip for updates.

## Auto-update, which follows

Not part of this step, but chosen with it, because the choice decides what a release has to publish.

- **`update-electron-app` and `update.electronjs.org`**: Electron's own free update service for public GitHub repositories, which this one is.
  It serves Squirrel.Mac updates from the zip on each GitHub release, and needs no server of ours.
- **`electron-updater`**, if option A is chosen: the same idea in electron-builder's own format.

With option C, `update-electron-app` fits, and the release only needs to carry the signed zip.

## Testing it

- **The end-to-end suite runs against the packaged app as well as `out/`.**
  Playwright launches any Electron executable, so the same tests drive `dist/Smart-Browser.app`.
  That proves the `asar` paths, the `smart://` handler and the preloads work packaged, which nothing in the suite can see today.
- **The packaged app's signature is checked**: `codesign --verify --deep --strict`, `spctl --assess` (Gatekeeper's verdict), and `stapler validate`.
- **CI packages unsigned on macOS** and runs the checks that need no signature, so a packaging break shows up on the commit that caused it, not at release time.

## Questions for you

1. **Tooling**: A (electron-builder), or C (Electron's own pieces from a script).
   The recommendation is C.
2. **Bundle id**: `com.performiq.smart-browser`, or another.
3. **Notarization credentials**: an app-specific password for your Apple ID, or an App Store Connect API key, stored once with `notarytool store-credentials`.
4. **The icon**: a placeholder now and a designed one later, or designed first.

## Recommendation

1. Option C: `@electron/packager`, `@electron/osx-sign`, `@electron/notarize`, `hdiutil`, from a script beside `build.mjs`.
2. Separate profiles: `Smart-Browser` packaged, `Smart-Browser Dev` from the repo.
3. Bundle id `com.performiq.smart-browser`; `arm64` only.
4. Developer ID signing, hardened runtime, notarized and stapled, on this Mac at release time; CI packages unsigned.
5. Releases carry a DMG and a zip, so `update-electron-app` can follow as the auto-update step.
6. A placeholder icon until a designed one exists.

## If that is chosen, the order of work

1. The ADR (0018), from this sketch and your answers.
2. Separate development and packaged profiles, first and on their own, since today's `make browser-dev` already shares the profile a package would use.
3. `make browser-package`: an unsigned `.app`, and the end-to-end suite run against it.
4. Signing, notarization and stapling: `make browser-release`, with the signature checks.
5. The DMG and zip, and RELEASING.md's step for attaching them.
6. CI: package unsigned on a macOS runner.
7. Then auto-update, as its own step.
